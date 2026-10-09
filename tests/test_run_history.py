"""Run discovery uses existing SQLite history without activating execution."""

from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import unittest

from agentrelay.run_history import list_runs
from agentrelay.run_results import PUBLIC_RUN_FIELDS
from agentrelay.store import DomainError, Store


CREATE_RUNS = """CREATE TABLE execution_runs (
    id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL REFERENCES tickets(id),
    worker_id TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL,
    finished_at TEXT, summary TEXT NOT NULL, error TEXT NOT NULL,
    model TEXT NOT NULL, effort TEXT NOT NULL, claim_revision INTEGER NOT NULL,
    actor TEXT NOT NULL, owner_instance TEXT NOT NULL, owner_pid INTEGER NOT NULL
    {result_column}
)"""


class RunHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-run-history-")
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "tickets.sqlite")
        self.first = self.store.action("create_ticket", {"title": "First", "acceptance": ["Reviewed"]})
        self.second = self.store.action("create_ticket", {"title": "Second", "acceptance": ["Reviewed"]})

    def tearDown(self):
        self.temp.cleanup()

    def create_table(self, *, with_result=True):
        result_column = ",result_json TEXT" if with_result else ""
        with self.store._write() as db:
            db.execute(CREATE_RUNS.format(result_column=result_column))

    def add_run(self, run_id, ticket_id, started_at, status="submitted", *, has_result=False, db=None):
        with self.store._write() if db is None else nullcontext(db) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(execution_runs)")}
            fields = (run_id, ticket_id, "fixture", status, started_at, started_at,
                      "", "", "fixture-model", "medium", 2, "agent:fixture", "fixture", 1)
            if "result_json" in columns:
                db.execute("INSERT INTO execution_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (*fields, json.dumps({"secret_proposal_body": "never list this"}) if has_result else None))
            else:
                db.execute("INSERT INTO execution_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", fields)

    def assert_error(self, expected_status, **kwargs):
        with self.assertRaises(DomainError) as caught:
            list_runs(self.store, **kwargs)
        self.assertEqual(caught.exception.status, expected_status)

    def test_keyset_pages_over_hundred_runs_with_timestamp_ties_and_new_run(self):
        self.create_table()
        expected = []
        with self.store._write() as db:
            for number in range(125):
                run_id = f"run-{number:03}"
                started_at = f"2026-01-01T00:{number // 5:02}:00Z"
                self.add_run(run_id, self.first["id"], started_at,
                             has_result=number % 2 == 0, db=db)
                expected.append((started_at, run_id))
        expected_ids = [run_id for _, run_id in sorted(expected, reverse=True)]

        first_page = list_runs(self.store, ticket_id=self.first["id"], limit=17)
        self.assertEqual(first_page["total"], 125)
        self.assertEqual(first_page["count"], 17)
        self.assertEqual(first_page["before_id"], None)
        self.assertEqual(first_page["runs"][0]["id"], expected_ids[0])
        self.assertEqual(first_page["next_before_id"], first_page["runs"][-1]["id"])
        self.assertEqual(set(first_page["runs"][0]), {*PUBLIC_RUN_FIELDS, "has_result"})
        self.assertIsInstance(first_page["runs"][0]["has_result"], bool)
        self.assertNotIn("never list this", json.dumps(first_page))

        self.add_run("run-newer", self.first["id"], "2099-01-01T00:00:00Z", has_result=True)
        gathered = [run["id"] for run in first_page["runs"]]
        cursor = first_page["next_before_id"]
        while cursor is not None:
            page = list_runs(self.store, ticket_id=self.first["id"], limit=17, before_id=cursor)
            self.assertEqual(page["total"], 126)
            self.assertEqual(page["before_id"], cursor)
            self.assertEqual(page["count"], len(page["runs"]))
            self.assertLessEqual(page["count"], 17)
            gathered.extend(run["id"] for run in page["runs"])
            cursor = page["next_before_id"]
        self.assertEqual(gathered, expected_ids)
        self.assertEqual(len(set(gathered)), 125)
        self.assertEqual(list_runs(self.store, ticket_id=self.first["id"], limit=17,
                                   before_id=expected_ids[-1])["runs"], [])

    def test_ticket_status_filters_and_cursor_survive_status_change(self):
        self.create_table()
        self.add_run("run-early", self.first["id"], "2026-01-01T00:00:00Z", has_result=True)
        self.add_run("run-middle", self.first["id"], "2026-01-01T00:01:00Z", status="failed")
        self.add_run("run-anchor", self.first["id"], "2026-01-01T00:02:00Z", has_result=True)
        self.add_run("run-other", self.second["id"], "2026-01-01T00:03:00Z", has_result=True)

        page = list_runs(self.store, ticket_id=self.first["id"], status="submitted", limit=1)
        self.assertEqual(page["total"], 2)
        self.assertEqual(page["runs"][0]["id"], "run-anchor")
        self.assertEqual(page["next_before_id"], "run-anchor")
        with self.store._write() as db:
            db.execute("UPDATE execution_runs SET status='failed' WHERE id='run-anchor'")
        older = list_runs(self.store, ticket_id=self.first["id"], status="submitted",
                          limit=1, before_id="run-anchor")
        self.assertEqual(older["total"], 1)
        self.assertEqual([run["id"] for run in older["runs"]], ["run-early"])
        self.assertIsNone(older["next_before_id"])
        self.assertEqual(list_runs(self.store, ticket_id=self.second["id"])["total"], 1)
        self.assertEqual(list_runs(self.store, status="failed")["total"], 2)
        self.assert_error(400, ticket_id=self.first["id"], before_id="run-other")

    def test_no_run_table_and_legacy_table_are_read_only(self):
        with self.store._connection() as db:
            before_tables = tuple(row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"))
        empty = list_runs(self.store, ticket_id=self.first["id"])
        self.assertEqual(empty, {"runs": [], "ticket_id": self.first["id"], "status": None,
                                 "total": 0, "count": 0, "limit": 20,
                                 "before_id": None, "next_before_id": None})
        self.assert_error(404, ticket_id="AR-9999")
        self.assert_error(404, before_id="run-missing")
        with self.store._connection() as db:
            after_tables = tuple(row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"))
        self.assertEqual(after_tables, before_tables)

        self.create_table(with_result=False)
        self.add_run("run-legacy", self.first["id"], "2026-01-01T00:00:00Z")
        legacy = list_runs(self.store)
        self.assertEqual(legacy["total"], 1)
        self.assertEqual(legacy["runs"][0]["has_result"], False)
        with self.store._connection() as db:
            self.assertNotIn("result_json", {row[1] for row in db.execute("PRAGMA table_info(execution_runs)")})

    def test_strict_validation_and_cursor_errors(self):
        self.create_table()
        self.add_run("run-one", self.first["id"], "2026-01-01T00:00:00Z")
        self.add_run("run-two", self.second["id"], "2026-01-01T00:01:00Z")
        for invalid in (True, False, 0, 101, 1.5, "20", None):
            with self.subTest(limit=invalid):
                self.assert_error(400, limit=invalid)
        for invalid in ("", " ", " AR-0001", "AR-0001 ", 5):
            with self.subTest(ticket_id=invalid):
                self.assert_error(400, ticket_id=invalid)
        for invalid in ("", " ", " run-one", "run-one ", 5):
            with self.subTest(before_id=invalid):
                self.assert_error(400, before_id=invalid)
        for invalid in ("", "submitted ", "unknown", 7):
            with self.subTest(status=invalid):
                self.assert_error(400, status=invalid)
        self.assert_error(404, ticket_id="AR-9999")
        self.assert_error(404, before_id="run-missing")
        self.assert_error(400, ticket_id=self.first["id"], before_id="run-two")


if __name__ == "__main__":
    unittest.main()
