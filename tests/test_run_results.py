"""Real local fixture subprocesses exercise persisted proposals; no model provider is used."""

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest

from agentrelay.execution import ExecutionManager
from agentrelay.run_results import get_run_result
from agentrelay.store import DomainError, Store


FIXTURE = r'''
import json, pathlib, sys, time
request = json.load(sys.stdin)
assert request["protocol"] == "agentrelay.worker.v1"
mode, marker, gate = sys.argv[1:]
if mode in {"conflict", "cancel"}:
    pathlib.Path(marker).write_text("ready", encoding="utf-8")
    while not pathlib.Path(gate).exists():
        time.sleep(0.02)
if mode == "oversize":
    print("x" * 1_100_000)
else:
    print("PRIVATE STDERR ONLY", file=sys.stderr)
    if mode == "reject":
        result = {"outcome": "help", "summary": "Proposal needs review", "evidence": [],
                  "title": "Need specialist", "description": "Inspect the format",
                  "profile_id": "missing-profile", "children": None}
    else:
        label = "ñ" * 390_000 if mode == "latin" else "Fixture output"
        result = {"outcome": "submit", "summary": "  Salida revisable en español  ",
                  "evidence": [{"kind": "file", "label": label, "uri": "local://fixture"}],
                  "title": None, "description": None, "profile_id": None, "children": None}
        if mode == "deep":
            nested = 0
            for _ in range(65):
                nested = [nested]
            result["children"] = nested
    print(json.dumps(result, ensure_ascii=False))
'''


class RunResultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-run-results-")
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "tickets.sqlite")
        self.script = self.root / "worker.py"
        self.script.write_text(FIXTURE, encoding="utf-8")
        self.marker = self.root / "started.txt"
        self.gate = self.root / "continue.txt"
        self.managers = []

    def tearDown(self):
        for manager in reversed(self.managers):
            manager.close()
        self.temp.cleanup()

    def ticket(self):
        return self.store.action("create_ticket", {"title": "Fixture task",
            "acceptance": ["Output checked"]})

    def manager(self, mode):
        config = self.root / "workers.json"
        config.write_text(json.dumps({"workers": [{"id": "fixture", "name": "Fixture",
            "command": [sys.executable, str(self.script), mode, str(self.marker), str(self.gate)],
            "cwd": str(self.root), "model": "fixture-model", "effort": "medium",
            "profile_ids": [], "timeout_seconds": 5}]}), encoding="utf-8")
        manager = ExecutionManager(self.store, config)
        self.managers.append(manager)
        return manager

    def wait_for(self, condition, label, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = condition()
            if value:
                return value
            time.sleep(0.02)
        self.fail(f"timed out waiting for {label}")

    def finished(self, manager, run_id):
        return self.wait_for(lambda: next((run for run in manager.snapshot()["runs"]
            if run["id"] == run_id and run["status"] != "running"), None), "run finish")

    def test_conflict_keeps_proposal_and_concurrent_ticket_edit(self):
        ticket = self.ticket()
        manager = self.manager("conflict")
        run_id = manager.start(ticket["id"], "fixture", ticket["revision"])["id"]
        self.wait_for(self.marker.exists, "worker start")
        edited = self.store.action("update_ticket", {"id": ticket["id"],
            "expected_revision": 2, "description": "Keep this concurrent edit"})
        self.gate.write_text("continue", encoding="utf-8")
        finished = self.finished(manager, run_id)

        self.assertEqual(finished["status"], "conflict")
        self.assertEqual(finished["summary"], "")
        captured = get_run_result(self.store, run_id)
        self.assertEqual(captured["schema_version"], 1)
        self.assertEqual(captured["run"]["claim_revision"], 2)
        self.assertEqual(captured["run"]["actor"], "agent:" + run_id)
        self.assertEqual(captured["result"]["summary"], "Salida revisable en español")
        self.assertEqual(captured["result"]["evidence"][0]["label"], "Fixture output")
        self.assertEqual(captured["current_ticket"], {"id": ticket["id"],
            "revision": edited["revision"], "status": "in_progress", "assignee": "agent:" + run_id})
        current = self.store.context(ticket["id"])["ticket"]
        self.assertEqual(current["description"], "Keep this concurrent edit")
        self.assertEqual(current["evidence"], [])
        self.assertNotIn("result_json", manager.snapshot()["runs"][0])
        self.assertNotIn("result_json", self.store.export()["runs"][0])
        self.assertNotIn("PRIVATE STDERR ONLY", json.dumps(captured))
        self.assertNotIn("Salida revisable en español", json.dumps(manager.snapshot(), ensure_ascii=False))

    def test_submitted_proposal_survives_backup_without_bulk_exposure(self):
        ticket = self.ticket()
        manager = self.manager("submit")
        run_id = manager.start(ticket["id"], "fixture", 1)["id"]
        self.assertEqual(self.finished(manager, run_id)["status"], "submitted")
        captured = get_run_result(self.store, run_id)
        self.assertEqual(captured["result"]["outcome"], "submit")
        self.assertEqual(captured["result"]["summary"], "Salida revisable en español")
        self.assertEqual(captured["current_ticket"]["status"], "review")
        self.assertEqual(captured["current_ticket"]["revision"], 3)
        self.assertEqual(captured["run"]["summary"], captured["result"]["summary"])
        self.assertNotIn("result_json", manager.snapshot()["runs"][0])
        self.assertNotIn("result_json", self.store.export()["runs"][0])
        self.assertNotIn("result", self.store.context(ticket["id"])["ticket"])
        backup = self.root / "backup.sqlite"
        self.store.backup(backup)
        restored = get_run_result(Store(backup), run_id)
        self.assertEqual(restored["result"], captured["result"])
        self.assertEqual(restored["current_ticket"], captured["current_ticket"])

    def test_utf8_output_below_one_megabyte_survives_ascii_normalization(self):
        ticket = self.ticket()
        manager = self.manager("latin")
        run_id = manager.start(ticket["id"], "fixture", 1)["id"]
        self.assertEqual(self.finished(manager, run_id)["status"], "submitted")
        result = get_run_result(self.store, run_id)["result"]
        self.assertEqual(len(result["evidence"][0]["label"]), 390_000)
        self.assertEqual(result["summary"], "Salida revisable en español")
        log = self.root / "runs" / run_id / "stdout.json"
        self.wait_for(log.exists, "bounded local stdout log")
        raw = log.read_bytes()
        self.assertLessEqual(len(raw), 1_048_576)
        with self.store._connection() as db:
            stored = db.execute("SELECT length(CAST(result_json AS BLOB)) FROM execution_runs WHERE id=?",
                                (run_id,)).fetchone()[0]
        self.assertGreater(stored, 2_097_152)
        self.assertLessEqual(stored, 4_194_304)

    def test_store_rejection_rolls_back_partial_ticket_work_but_keeps_proposal(self):
        ticket = self.ticket()
        manager = self.manager("reject")
        run_id = manager.start(ticket["id"], "fixture", 1)["id"]
        finished = self.finished(manager, run_id)
        self.assertEqual(finished["status"], "failed")
        captured = get_run_result(self.store, run_id)
        self.assertEqual(captured["result"]["outcome"], "help")
        self.assertEqual(captured["result"]["profile_id"], "missing-profile")
        self.assertEqual(captured["current_ticket"]["status"], "blocked")
        context = self.store.context(ticket["id"])
        self.assertEqual(context["ticket"]["checkpoint"], "")
        self.assertEqual(context["children"], [])
        self.assertFalse(any(event["action"] in {"checkpoint", "request_help", "create_help"}
                             for event in context["events"]))

    def test_cancel_and_oversize_leave_no_captured_result(self):
        ticket = self.ticket()
        manager = self.manager("cancel")
        run_id = manager.start(ticket["id"], "fixture", 1)["id"]
        self.wait_for(self.marker.exists, "worker start")
        self.assertEqual(manager.cancel(run_id)["status"], "cancelled")
        self.assertIsNone(get_run_result(self.store, run_id)["result"])
        manager.close()
        self.managers.remove(manager)
        second = self.ticket()
        oversize_manager = self.manager("oversize")
        oversize_id = oversize_manager.start(second["id"], "fixture", 1)["id"]
        self.assertEqual(self.finished(oversize_manager, oversize_id)["status"], "failed")
        self.assertIsNone(get_run_result(self.store, oversize_id)["result"])

    def test_excessive_depth_is_rejected_before_capture_or_submission(self):
        ticket = self.ticket()
        manager = self.manager("deep")
        run_id = manager.start(ticket["id"], "fixture", 1)["id"]
        finished = self.finished(manager, run_id)
        self.assertEqual(finished["status"], "failed")
        self.assertIn("invalid JSON", finished["error"])
        self.assertIsNone(get_run_result(self.store, run_id)["result"])
        context = self.store.context(ticket["id"])
        self.assertEqual(context["ticket"]["status"], "blocked")
        self.assertEqual(context["ticket"]["evidence"], [])
        self.assertFalse(any(event["action"] == "submit_ticket" for event in context["events"]))

    def test_cancel_after_capture_does_not_apply_proposal(self):
        ticket = self.ticket()
        manager = self.manager("submit")
        captured = threading.Event()
        release = threading.Event()
        applied = threading.Event()
        original_apply = manager._apply_result

        def wait_before_apply(run_id, result):
            captured.set()
            if not release.wait(5):
                raise AssertionError("test did not release application")
            try:
                return original_apply(run_id, result)
            finally:
                applied.set()

        manager._apply_result = wait_before_apply
        run_id = manager.start(ticket["id"], "fixture", 1)["id"]
        try:
            self.assertTrue(captured.wait(5), "result was not captured")
            before_cancel = get_run_result(self.store, run_id)
            self.assertEqual(before_cancel["run"]["status"], "running")
            self.assertEqual(before_cancel["result"]["outcome"], "submit")
            self.assertEqual(manager.cancel(run_id)["status"], "cancelled")
        finally:
            release.set()
        self.assertTrue(applied.wait(5), "application callback did not return")
        self.assertEqual(self.finished(manager, run_id)["status"], "cancelled")
        self.assertEqual(get_run_result(self.store, run_id)["result"]["outcome"], "submit")
        current = self.store.context(ticket["id"])["ticket"]
        self.assertEqual(current["status"], "blocked")
        self.assertEqual(current["evidence"], [])

    def test_legacy_read_without_manager_and_migration(self):
        ticket = self.ticket()
        for value in (None, "", "  ", 7):
            with self.subTest(value=value), self.assertRaises(DomainError) as caught:
                get_run_result(self.store, value)
            self.assertEqual(caught.exception.status, 400)
        with self.assertRaises(DomainError) as caught:
            get_run_result(self.store, "missing")
        self.assertEqual(caught.exception.status, 404)
        with self.store._write() as db:
            db.execute("""CREATE TABLE execution_runs (
                id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL REFERENCES tickets(id),
                worker_id TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL,
                finished_at TEXT, summary TEXT NOT NULL, error TEXT NOT NULL,
                model TEXT NOT NULL, effort TEXT NOT NULL, claim_revision INTEGER NOT NULL,
                actor TEXT NOT NULL, owner_instance TEXT NOT NULL, owner_pid INTEGER NOT NULL
            )""")
            db.execute("""INSERT INTO execution_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("run-legacy", ticket["id"], "fixture", "failed", "2026-01-01T00:00:00Z",
                 "2026-01-01T00:00:01Z", "", "Legacy failure", "unknown", "unknown", 1,
                 "agent:legacy", "legacy", 0))
        legacy = get_run_result(self.store, "run-legacy")
        self.assertIsNone(legacy["result"])
        self.assertEqual(legacy["run"]["actor"], "agent:legacy")
        with self.store._connection() as db:
            self.assertNotIn("result_json", {row[1] for row in db.execute("PRAGMA table_info(execution_runs)")})
        disabled = ExecutionManager(self.store, None)
        self.managers.append(disabled)
        with self.store._connection() as db:
            self.assertIn("result_json", {row[1] for row in db.execute("PRAGMA table_info(execution_runs)")})
        self.assertIsNone(get_run_result(self.store, "run-legacy")["result"])
        for invalid in ("[]", '"text"', "NaN", "null"):
            with self.subTest(invalid=invalid):
                with self.store._write() as db:
                    db.execute("UPDATE execution_runs SET result_json=? WHERE id='run-legacy'", (invalid,))
                with self.assertRaises(DomainError) as caught:
                    get_run_result(self.store, "run-legacy")
                self.assertEqual(caught.exception.status, 500)


if __name__ == "__main__":
    unittest.main()
