"""The CLI reads one retained worker proposal without execution or mutation."""

from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from agentrelay.store import Store


RUN_SCHEMA = """CREATE TABLE execution_runs (
    id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL REFERENCES tickets(id),
    worker_id TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL,
    finished_at TEXT, summary TEXT NOT NULL, error TEXT NOT NULL,
    model TEXT NOT NULL, effort TEXT NOT NULL, claim_revision INTEGER NOT NULL,
    actor TEXT NOT NULL, owner_instance TEXT NOT NULL, owner_pid INTEGER NOT NULL,
    result_json TEXT
)"""


def prepare_database(path):
    store = Store(path)
    first = store.action("create_ticket", {"title": "Revisión del resultado",
                         "acceptance": ["Comprobar propuesta retenida"]})
    second = store.action("create_ticket", {"title": "Otro ticket",
                          "acceptance": ["Mantener aislamiento"]})
    proposal = {"outcome": "submit", "summary": "Propuesta útil en español: ágil",
                "evidence": [{"kind": "file", "label": "Salida ñ", "uri": "local://resultado"}],
                "title": None, "description": None, "profile_id": None, "children": None}
    other = {"outcome": "blocked", "summary": "Otro resultado", "evidence": [],
             "title": None, "description": None, "profile_id": None, "children": None}
    with store._write() as database:
        database.execute(RUN_SCHEMA)
        values = (
            ("run-á", first["id"], "worker-one", "conflict", "2026-10-10T00:00:00Z",
             "2026-10-10T00:00:01Z", "", "Revision conflict", "fixture-model", "high",
             first["revision"], "agent:run-á", "fixture", 1,
             json.dumps(proposal, ensure_ascii=False, separators=(",", ":"))),
            ("run-other", second["id"], "worker-two", "failed", "2026-10-10T00:01:00Z",
             "2026-10-10T00:01:01Z", "", "Not applied", "other-model", "low",
             second["revision"], "agent:run-other", "fixture", 2,
             json.dumps(other, ensure_ascii=False, separators=(",", ":"))),
            ("run-legacy", first["id"], "legacy", "failed", "2026-10-09T00:00:00Z",
             "2026-10-09T00:00:01Z", "", "Legacy output unavailable", "unknown", "unknown",
             first["revision"], "agent:legacy", "legacy", 0, None),
        )
        database.executemany("INSERT INTO execution_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", values)
    return store, proposal


def domain_rows(path):
    with closing(sqlite3.connect(path)) as database:
        result = {}
        for table in ("tickets", "profiles", "dependencies", "events", "metadata", "execution_runs"):
            result[table] = database.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
        return result


class CliRunResultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-cli-run-result-")
        self.root = Path(self.temp.name)
        self.database = self.root / "workspace.sqlite"
        self.store, self.proposal = prepare_database(self.database)

    def tearDown(self):
        self.temp.cleanup()

    def command(self, *args):
        return subprocess.run([sys.executable, "-m", "agentrelay", *map(str, args)],
                              capture_output=True, text=True, encoding="utf-8", timeout=20)

    def test_selected_unicode_result_and_legacy_null_leave_domain_unchanged(self):
        before = domain_rows(self.database)

        selected = self.command("run-result", "--db", self.database, "--run", "run-á")
        self.assertEqual(selected.returncode, 0, selected.stderr)
        self.assertIn("Propuesta útil en español: ágil", selected.stdout)
        result = json.loads(selected.stdout)
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["run"]["id"], "run-á")
        self.assertEqual(result["run"]["claim_revision"], 1)
        self.assertEqual(result["run"]["actor"], "agent:run-á")
        self.assertEqual(result["result"], self.proposal)
        self.assertEqual(result["current_ticket"], {
            "id": "AR-0001", "revision": 1, "status": "queued", "assignee": None})
        self.assertNotIn("owner_instance", result["run"])
        self.assertNotIn("result_json", result["run"])
        self.assertNotIn("Otro resultado", selected.stdout)

        legacy = self.command("run-result", "--db", self.database, "--run", "run-legacy")
        self.assertEqual(legacy.returncode, 0, legacy.stderr)
        self.assertIsNone(json.loads(legacy.stdout)["result"])
        self.assertEqual(domain_rows(self.database), before)

    def test_empty_unknown_and_missing_run_ids_fail_without_changes(self):
        before = domain_rows(self.database)
        for run_id in ("", "   ", "missing"):
            with self.subTest(run_id=run_id):
                result = self.command("run-result", "--db", self.database, "--run", run_id)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("Traceback", result.stderr)
        missing_option = self.command("run-result", "--db", self.database)
        self.assertNotEqual(missing_option.returncode, 0)
        self.assertEqual(domain_rows(self.database), before)

    def test_deep_stored_result_is_controlled_and_other_result_remains_readable(self):
        raw = '{"payload":' + '[' * 5000 + '0' + ']' * 5000 + '}'
        with self.store._write() as database:
            database.execute("UPDATE execution_runs SET result_json=? WHERE id='run-other'", (raw,))
        before = domain_rows(self.database)

        rejected = self.command("run-result", "--db", self.database, "--run", "run-other")
        self.assertEqual(rejected.returncode, 1)
        self.assertEqual(rejected.stdout, "")
        self.assertIn("stored worker result is invalid", rejected.stderr)
        self.assertNotIn("Traceback", rejected.stderr)
        selected = self.command("run-result", "--db", self.database, "--run", "run-á")
        self.assertEqual(selected.returncode, 0, selected.stderr)
        self.assertEqual(json.loads(selected.stdout)["result"], self.proposal)
        self.assertEqual(domain_rows(self.database), before)

    def test_missing_and_foreign_database_are_not_created_or_mutated(self):
        missing = self.root / "missing" / "typo.sqlite"
        result = self.command("run-result", "--db", missing, "--run", "run-á")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(missing.parent.exists())
        self.assertFalse(missing.exists())

        foreign = self.root / "foreign.sqlite"
        with closing(sqlite3.connect(foreign)) as database:
            database.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
            database.execute("INSERT INTO sentinel VALUES ('unchanged')")
            database.commit()
        original = foreign.read_bytes()
        digest = hashlib.sha256(original).digest()

        result = self.command("run-result", "--db", foreign, "--run", "run-á")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(hashlib.sha256(foreign.read_bytes()).digest(), digest)
        self.assertEqual(foreign.read_bytes(), original)
        with closing(sqlite3.connect(foreign)) as database:
            self.assertEqual(database.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [("sentinel",)])


if __name__ == "__main__":
    unittest.main()
