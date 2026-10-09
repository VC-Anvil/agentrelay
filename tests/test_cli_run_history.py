"""The CLI discovers bounded run summaries without exposing proposal bodies."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from agentrelay.store import Store
from tests.test_cli_run_results import domain_rows, prepare_database


class CliRunHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-cli-run-history-")
        self.root = Path(self.temp.name)
        self.database = self.root / "workspace.sqlite"
        self.store, _ = prepare_database(self.database)

    def tearDown(self):
        self.temp.cleanup()

    def command(self, *args):
        return subprocess.run([sys.executable, "-m", "agentrelay", *map(str, args)],
                              capture_output=True, text=True, encoding="utf-8", timeout=20)

    def read(self, *args):
        process = self.command("runs", "--db", self.database, *args)
        self.assertEqual(process.returncode, 0, process.stderr)
        return process, json.loads(process.stdout)

    def test_utf8_filters_and_cursor_pages_are_summaries_and_read_only(self):
        before = domain_rows(self.database)

        first_process, first = self.read("--limit", 2)
        self.assertEqual([run["id"] for run in first["runs"]], ["run-other", "run-á"])
        self.assertEqual(first["total"], 3)
        self.assertEqual(first["count"], 2)
        self.assertEqual(first["limit"], 2)
        self.assertEqual(first["next_before_id"], "run-á")
        self.assertIn("run-á", first_process.stdout)
        self.assertNotIn("result_json", first_process.stdout)
        self.assertNotIn("Propuesta útil", first_process.stdout)
        self.assertTrue(first["runs"][0]["has_result"])
        self.assertTrue(first["runs"][1]["has_result"])

        _, second = self.read("--limit", 2, "--before-id", first["next_before_id"])
        self.assertEqual([run["id"] for run in second["runs"]], ["run-legacy"])
        self.assertFalse(second["runs"][0]["has_result"])
        self.assertIsNone(second["next_before_id"])
        self.assertEqual(second["total"], 3)

        _, ticket = self.read("--ticket", "AR-0001")
        self.assertEqual([run["id"] for run in ticket["runs"]], ["run-á", "run-legacy"])
        self.assertEqual(ticket["ticket_id"], "AR-0001")
        self.assertEqual(ticket["total"], 2)

        _, status = self.read("--status", "conflict")
        self.assertEqual([run["id"] for run in status["runs"]], ["run-á"])
        self.assertEqual(status["status"], "conflict")
        self.assertEqual(domain_rows(self.database), before)

    def test_invalid_filters_limits_and_cursors_fail_without_mutation(self):
        before = domain_rows(self.database)
        cases = (
            ("--limit", 0), ("--limit", 101), ("--limit", "two"),
            ("--ticket", "missing"), ("--ticket", " AR-0001"),
            ("--status", "unknown"), ("--status", " conflict"),
            ("--before-id", "missing"),
            ("--ticket", "AR-0001", "--before-id", "run-other"),
        )
        for args in cases:
            with self.subTest(args=args):
                process = self.command("runs", "--db", self.database, *args)
                self.assertNotEqual(process.returncode, 0)
                self.assertNotIn("Traceback", process.stderr)
        self.assertEqual(domain_rows(self.database), before)

    def test_missing_database_is_not_created(self):
        missing = self.root / "missing" / "typo.sqlite"
        process = self.command("runs", "--db", missing, "--limit", 1)
        self.assertNotEqual(process.returncode, 0)
        self.assertNotIn("Traceback", process.stderr)
        self.assertFalse(missing.parent.exists())
        self.assertFalse(missing.exists())

    def test_legacy_database_without_runs_or_result_column_is_supported(self):
        without_runs = self.root / "without-runs.sqlite"
        Store(without_runs)
        empty = self.command("runs", "--db", without_runs)
        self.assertEqual(empty.returncode, 0, empty.stderr)
        self.assertEqual(json.loads(empty.stdout)["runs"], [])

        legacy = self.root / "legacy.sqlite"
        store = Store(legacy)
        ticket = store.action("create_ticket", {"title": "Legacy", "acceptance": ["Inspect"]})
        with store._write() as database:
            database.execute("""CREATE TABLE execution_runs (
                id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL REFERENCES tickets(id),
                worker_id TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL,
                finished_at TEXT, summary TEXT NOT NULL, error TEXT NOT NULL,
                model TEXT NOT NULL, effort TEXT NOT NULL, claim_revision INTEGER NOT NULL,
                actor TEXT NOT NULL, owner_instance TEXT NOT NULL, owner_pid INTEGER NOT NULL
            )""")
            database.execute("INSERT INTO execution_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                "legacy-run", ticket["id"], "old-worker", "failed", "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:01Z", "", "Legacy failure", "unknown", "unknown",
                ticket["revision"], "agent:legacy", "old-instance", 1))
        listed = self.command("runs", "--db", legacy)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        runs = json.loads(listed.stdout)["runs"]
        self.assertEqual([run["id"] for run in runs], ["legacy-run"])
        self.assertFalse(runs[0]["has_result"])


if __name__ == "__main__":
    unittest.main()
