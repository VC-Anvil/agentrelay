"""CLI source checks bind explicit local comparisons to historical ticket receipts."""

from contextlib import closing, redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from agentrelay import __main__ as cli
from agentrelay.snapshots import create_snapshot
from agentrelay.source_checks import check_sources
from agentrelay.store import Store


RECEIPT_KEYS = {
    "schema_version", "check_id", "request_id", "ticket_id", "ticket_revision",
    "actor", "method", "snapshot_id", "report_sha256", "summary", "checked_at",
    "recorded_at",
}


def prepare_source_check_fixture(database: Path, root: Path):
    store = Store(database)
    ticket = store.action("create_ticket", {
        "title": "Revisar fuentes ácidas",
        "acceptance": ["Distinguir observación histórica de estado actual"],
    })
    source = root / "captured-source"
    source.mkdir()
    (source / "entrada.txt").write_text("versión uno\n", encoding="utf-8")
    snapshot = root / "snapshot"
    manifest = create_snapshot(source, ["entrada.txt"], snapshot)
    current = root / "current"
    current.mkdir()
    (current / "entrada.txt").write_text("versión uno\n", encoding="utf-8")
    return store, ticket, snapshot, manifest["snapshot_id"], current


def persisted_rows(database: Path):
    with closing(sqlite3.connect(database)) as connection:
        return {
            table: connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
            for table in ("profiles", "tickets", "dependencies", "events", "metadata", "source_checks")
        }


class CliSourceChecksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-cli-source-checks-")
        self.root = Path(self.temp.name)
        self.database = self.root / "workspace.sqlite"
        (self.store, self.ticket, self.snapshot, self.snapshot_id,
         self.current) = prepare_source_check_fixture(self.database, self.root)

    def tearDown(self):
        self.temp.cleanup()

    def command(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "agentrelay", *map(str, args)],
            capture_output=True, text=True, encoding="utf-8", timeout=20,
        )

    def check(self, request_id, *, revision=None, snapshot_id=None, snapshot=None, root=None):
        return self.command(
            "check-sources", "--db", self.database, "--ticket", self.ticket["id"],
            "--expected-revision", self.ticket["revision"] if revision is None else revision,
            "--snapshot", self.snapshot if snapshot is None else snapshot,
            "--expected-snapshot-id", self.snapshot_id if snapshot_id is None else snapshot_id,
            "--root", self.current if root is None else root,
            "--request-id", request_id, "--actor", "agent:source-reader",
        )

    def test_records_advisory_findings_with_exit_zero_and_reads_pages_and_detail(self):
        ticket_before = self.store.context(self.ticket["id"])["ticket"]
        first = self.check("source-check-uno")
        self.assertEqual(first.returncode, 0, first.stderr)
        receipt_one = json.loads(first.stdout)
        self.assertEqual(set(receipt_one), RECEIPT_KEYS)
        self.assertEqual(receipt_one["summary"], {
            "total": 1, "unchanged": 1, "modified": 0, "missing": 0, "uncheckable": 0,
        })
        self.assertNotIn("report", receipt_one)
        self.assertNotIn(str(self.current), first.stdout)

        (self.current / "entrada.txt").write_text("versión dos\n", encoding="utf-8")
        second = self.check("source-check-dos")
        self.assertEqual(second.returncode, 0, second.stderr)
        receipt_two = json.loads(second.stdout)
        self.assertEqual(receipt_two["summary"]["modified"], 1)
        self.assertEqual(self.store.context(self.ticket["id"])["ticket"], ticket_before)

        listed = self.command("source-checks", "--db", self.database,
                              "--ticket", self.ticket["id"], "--limit", 1)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        page = json.loads(listed.stdout)
        self.assertEqual(page["checks"], [receipt_two])
        self.assertEqual(page["total"], 2)
        self.assertEqual(page["count"], 1)
        self.assertEqual(page["limit"], 1)
        self.assertEqual(page["next_before_id"], receipt_two["check_id"])
        self.assertNotIn("report", page["checks"][0])

        older = self.command("source-checks", "--db", self.database,
                             "--ticket", self.ticket["id"], "--limit", 1,
                             "--before-id", page["next_before_id"])
        self.assertEqual(older.returncode, 0, older.stderr)
        self.assertEqual(json.loads(older.stdout)["checks"], [receipt_one])

        detail = self.command("source-check", "--db", self.database,
                              "--check-id", receipt_two["check_id"])
        self.assertEqual(detail.returncode, 0, detail.stderr)
        detailed = json.loads(detail.stdout)
        self.assertEqual({key: detailed[key] for key in RECEIPT_KEYS}, receipt_two)
        self.assertEqual(detailed["report"]["snapshot_id"], self.snapshot_id)
        self.assertEqual(detailed["report"]["summary"]["modified"], 1)
        self.assertEqual(detailed["report"]["files"][0]["path"], "entrada.txt")

        context = self.command("context", "--db", self.database, "--ticket", self.ticket["id"])
        self.assertEqual(context.returncode, 0, context.stderr)
        current = json.loads(context.stdout)
        self.assertEqual([item["check_id"] for item in current["source_checks"]],
                         [receipt_two["check_id"], receipt_one["check_id"]])
        self.assertTrue(all(item["ticket_revision_matches_now"]
                            for item in current["source_checks"]))
        self.assertNotIn("report", current["source_checks"][0])

    def test_exact_replay_survives_missing_paths_and_changed_ticket(self):
        first = self.check("durable-replay")
        self.assertEqual(first.returncode, 0, first.stderr)
        receipt = json.loads(first.stdout)
        updated = self.store.action("update_ticket", {
            "id": self.ticket["id"], "expected_revision": self.ticket["revision"],
            "title": "El ticket cambió después",
        })
        self.assertEqual(updated["revision"], self.ticket["revision"] + 1)
        shutil.rmtree(self.snapshot)
        shutil.rmtree(self.current)
        before = persisted_rows(self.database)

        replay = self.check("durable-replay")

        self.assertEqual(replay.returncode, 0, replay.stderr)
        self.assertEqual(json.loads(replay.stdout), receipt)
        self.assertEqual(persisted_rows(self.database), before)

    def test_failures_are_concise_and_do_not_record_or_create_databases(self):
        before = persisted_rows(self.database)
        mismatch = self.check("wrong-snapshot", snapshot_id="sha256:" + "0" * 64,
                              root=self.root / "root-must-not-be-inspected")
        self.assertEqual(mismatch.returncode, 1)
        self.assertIn("snapshot", mismatch.stderr.lower())
        self.assertNotIn("traceback", mismatch.stderr.lower())
        self.assertEqual(persisted_rows(self.database), before)

        stale = self.check("stale-ticket", revision=self.ticket["revision"] + 1,
                           snapshot=self.root / "snapshot-must-not-be-read",
                           root=self.root / "root-must-not-be-read")
        self.assertEqual(stale.returncode, 1)
        self.assertIn("revision", stale.stderr.lower())
        self.assertEqual(persisted_rows(self.database), before)

        invalid_reads = (
            ("source-checks", "--db", self.database, "--ticket", self.ticket["id"], "--limit", 0),
            ("source-checks", "--db", self.database, "--ticket", self.ticket["id"],
             "--before-id", 0),
            ("source-checks", "--db", self.database, "--ticket", "missing"),
            ("source-check", "--db", self.database, "--check-id", 0),
            ("source-check", "--db", self.database, "--check-id", 999999),
        )
        for arguments in invalid_reads:
            with self.subTest(arguments=arguments):
                result = self.command(*arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("traceback", result.stderr.lower())
        self.assertEqual(persisted_rows(self.database), before)

        for command, arguments in (
            ("check-sources", ("--ticket", self.ticket["id"], "--expected-revision", 1,
                               "--snapshot", self.snapshot, "--expected-snapshot-id", self.snapshot_id,
                               "--root", self.current, "--request-id", "missing-db", "--actor", "human")),
            ("source-checks", ("--ticket", self.ticket["id"])),
            ("source-check", ("--check-id", 1)),
        ):
            with self.subTest(command=command):
                result = self.command(command, *arguments)
                self.assertEqual(result.returncode, 2)
                self.assertIn("--db", result.stderr)

        missing = self.root / "missing" / "workspace.sqlite"
        result = self.command("source-checks", "--db", missing,
                              "--ticket", self.ticket["id"])
        self.assertEqual(result.returncode, 1)
        self.assertFalse(missing.parent.exists())

    def test_sqlite_service_failure_is_controlled_without_success_json(self):
        output, errors = StringIO(), StringIO()
        with patch.object(sys, "argv", [
                "agentrelay", "source-check", "--db", str(self.database), "--check-id", "1",
        ]), patch("agentrelay.source_checks.get_source_check",
                  side_effect=sqlite3.OperationalError("simulated read failure")), \
                redirect_stdout(output), redirect_stderr(errors):
            with self.assertRaises(SystemExit) as stopped:
                cli.main()

        self.assertEqual(stopped.exception.code, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("simulated read failure", errors.getvalue())
        self.assertNotIn("traceback", errors.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
