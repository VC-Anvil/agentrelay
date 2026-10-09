"""Malformed stored proposal depth remains an explicit read error, without mutation."""

import json
from pathlib import Path
import tempfile
import unittest

from agentrelay.run_results import get_run_result
from agentrelay.store import DomainError, Store


class RunResultDepthTests(unittest.TestCase):
    def test_deep_result_is_domain_error_and_other_run_remains_readable(self):
        with tempfile.TemporaryDirectory(prefix="agentrelay-result-depth-") as directory:
            store = Store(Path(directory) / "tickets.sqlite")
            ticket = store.action("create_ticket", {
                "title": "Inspect saved result", "acceptance": ["Review proposal"]})
            before = store.context(ticket["id"])
            deep_json = '{"evidence":' + '[' * 5000 + '0' + ']' * 5000 + '}'
            at_limit_json = '{"evidence":' + '[' * 63 + '0' + ']' * 63 + '}'
            over_limit_json = '{"evidence":' + '[' * 64 + '0' + ']' * 64 + '}'
            brackets_in_string = json.dumps({"evidence": "[" * 5000})
            valid_result = {"outcome": "submit", "summary": "Otra propuesta", "evidence": []}
            valid_json = json.dumps(valid_result, ensure_ascii=False)

            with store._write() as db:
                db.execute("""CREATE TABLE execution_runs (
                    id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL REFERENCES tickets(id),
                    worker_id TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL,
                    finished_at TEXT, summary TEXT NOT NULL, error TEXT NOT NULL,
                    model TEXT NOT NULL, effort TEXT NOT NULL, claim_revision INTEGER NOT NULL,
                    actor TEXT NOT NULL, result_json TEXT
                )""")
                db.executemany("""INSERT INTO execution_runs
                    (id,ticket_id,worker_id,status,started_at,finished_at,summary,error,
                     model,effort,claim_revision,actor,result_json)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", [
                    ("run-depth", ticket["id"], "fixture", "failed", "2026-01-01T00:00:00Z",
                     None, "", "", "unknown", "unknown", 1, "agent:fixture", deep_json),
                    ("run-limit", ticket["id"], "fixture", "failed", "2026-01-01T00:00:02Z",
                     None, "", "", "unknown", "unknown", 1, "agent:fixture", at_limit_json),
                    ("run-over-limit", ticket["id"], "fixture", "failed", "2026-01-01T00:00:03Z",
                     None, "", "", "unknown", "unknown", 1, "agent:fixture", over_limit_json),
                    ("run-brackets", ticket["id"], "fixture", "failed", "2026-01-01T00:00:04Z",
                     None, "", "", "unknown", "unknown", 1, "agent:fixture", brackets_in_string),
                    ("run-valid", ticket["id"], "fixture", "submitted", "2026-01-01T00:00:01Z",
                     None, "", "", "unknown", "unknown", 1, "agent:fixture", valid_json),
                ])

            for run_id in ("run-depth", "run-over-limit"):
                with self.subTest(run_id=run_id), self.assertRaises(DomainError) as caught:
                    get_run_result(store, run_id)
                self.assertEqual(caught.exception.status, 500)
                self.assertEqual(str(caught.exception), "stored worker result is invalid")
            self.assertEqual(get_run_result(store, "run-limit")["result"], json.loads(at_limit_json))
            self.assertEqual(get_run_result(store, "run-brackets")["result"],
                             json.loads(brackets_in_string))
            self.assertEqual(get_run_result(store, "run-valid")["result"], valid_result)
            self.assertEqual(store.context(ticket["id"]), before)
            with store._connection() as db:
                rows = db.execute("SELECT id,result_json FROM execution_runs ORDER BY id").fetchall()
            self.assertEqual([(row["id"], row["result_json"]) for row in rows],
                             [("run-brackets", brackets_in_string), ("run-depth", deep_json),
                              ("run-limit", at_limit_json), ("run-over-limit", over_limit_json),
                              ("run-valid", valid_json)])


if __name__ == "__main__":
    unittest.main()
