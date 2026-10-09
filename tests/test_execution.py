"""Execution tests use tiny local Python fixtures, never an LLM provider."""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from agentrelay.execution import ExecutionManager
from agentrelay.store import DomainError, Store


FIXTURE = r'''
import json, sys, time
request = json.load(sys.stdin)
assert request["protocol"] == "agentrelay.worker.v1"
assert request["context"]["ticket"]["id"].startswith("AR-")
assert request["worker"]["model"] == "fixture-model"
mode = sys.argv[1]
if mode in ("slow", "stale"):
    time.sleep(4 if mode == "slow" else 0.6)
if mode == "invalid":
    print("not json")
elif mode == "nonzero":
    print("falló la prueba local", file=sys.stderr)
    sys.exit(7)
elif mode == "oversize":
    print("x" * 1100000)
elif mode == "help":
    print(json.dumps({"outcome":"help","summary":"Need design input","evidence":[],
        "title":"Clarify format","description":"Specify the input schema","profile_id":None,"children":None}))
elif mode == "split":
    print(json.dumps({"outcome":"split","summary":"Decomposed safely","evidence":[],
        "title":None,"description":None,"profile_id":None,
        "children":[{"title":"Part A","acceptance":["A checked"]},
                    {"title":"Part B","acceptance":["B checked"]}]}))
elif mode == "blocked":
    print(json.dumps({"outcome":"blocked","summary":"Awaiting external input","evidence":[],
        "title":None,"description":None,"profile_id":None,"children":None}))
else:
    print(json.dumps({"outcome":"submit","summary":"Salida revisable en español",
        "evidence":[{"kind":"file","label":"Fixture output","uri":"local://fixture"}],
        "title":None,"description":None,"profile_id":None,"children":None}, ensure_ascii=False))
'''


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="agentrelay-execution-")
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "test.sqlite"
        self.store = Store(self.db)
        self.script = self.dir / "worker.py"
        self.script.write_text(FIXTURE, encoding="utf-8")
        self.managers = []

    def tearDown(self):
        for manager in reversed(self.managers):
            manager.close()
        self.tmp.cleanup()

    def config(self, mode="submit", **changes):
        worker = {"id": "fixture", "name": "Fixture worker", "command": [sys.executable, str(self.script), mode],
                  "cwd": ".", "model": "fixture-model", "effort": "medium",
                  "profile_ids": [], "timeout_seconds": 2}
        worker.update(changes)
        path = self.dir / "workers.json"
        path.write_text(json.dumps({"workers": [worker]}), encoding="utf-8")
        return path

    def manager(self, config_path):
        manager = ExecutionManager(self.store, config_path)
        self.managers.append(manager)
        return manager

    def ticket(self, **fields):
        return self.store.action("create_ticket", {"title": "Fixture ticket", "acceptance": ["Output reviewed"], **fields})

    def finish(self, manager, run_id, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            run = next(x for x in manager.snapshot()["runs"] if x["id"] == run_id)
            if run["status"] != "running":
                return run
            time.sleep(0.05)
        self.fail("run did not finish")

    def log_file(self, run_id, name):
        path = self.dir / "runs" / run_id / name
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not path.exists():
            time.sleep(0.05)
        self.assertTrue(path.exists())
        return path

    def test_disabled_snapshot_and_config_validation(self):
        disabled = self.manager(None)
        self.assertFalse(disabled.snapshot()["enabled"])
        self.assertEqual(disabled.snapshot()["workers"], [])
        ticket = self.ticket()
        with self.assertRaises(DomainError):
            disabled.start(ticket["id"], "fixture", ticket["revision"])
        with self.assertRaises(DomainError):
            self.manager(self.config(profile_ids=["missing"]))
        self.assertEqual(self.store.context(ticket["id"])["ticket"]["revision"], 1)

    def test_submit_records_run_without_auto_review(self):
        manager = self.manager(self.config())
        ticket = self.ticket()
        run = manager.start(ticket["id"], "fixture", ticket["revision"])
        self.assertEqual(run["status"], "running")
        result = self.finish(manager, run["id"])
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(result["model"], "fixture-model")
        self.assertEqual(result["summary"], "Salida revisable en español")
        self.assertEqual(self.store.context(ticket["id"])["ticket"]["status"], "review")
        self.assertNotIn("command", manager.snapshot()["workers"][0])
        self.assertNotIn("cwd", manager.snapshot()["workers"][0])
        self.assertIn("español", self.log_file(run["id"], "stdout.json").read_text(encoding="utf-8"))
        self.assertEqual(self.store.export()["runs"][0]["id"], run["id"])

    def test_help_and_split_preserve_parent_and_create_children(self):
        for mode, expected in (("help", "help_requested"), ("split", "split")):
            with self.subTest(mode=mode):
                manager = self.manager(self.config(mode))
                parent = self.ticket(priority="high", profile_id="sol")
                result = self.finish(manager, manager.start(parent["id"], "fixture", 1)["id"])
                self.assertEqual(result["status"], expected)
                context = self.store.context(parent["id"])
                self.assertEqual(context["ticket"]["status"], "blocked")
                self.assertEqual(context["ticket"]["checkpoint"], result["summary"])
                self.assertEqual(len(context["children"]), 1 if mode == "help" else 2)
                manager.close()
                self.managers.remove(manager)

    def test_blocked_failure_timeout_and_invalid_output(self):
        for mode, status in (("blocked", "blocked"), ("invalid", "failed"),
                             ("nonzero", "failed"), ("oversize", "failed"), ("slow", "failed")):
            with self.subTest(mode=mode):
                manager = self.manager(self.config(mode, timeout_seconds=1))
                ticket = self.ticket()
                result = self.finish(manager, manager.start(ticket["id"], "fixture", 1)["id"])
                self.assertEqual(result["status"], status)
                self.assertEqual(self.store.context(ticket["id"])["ticket"]["status"], "blocked")
                self.assertLessEqual(len(result["error"]), 240)
                self.assertLessEqual(self.log_file(result["id"], "stdout.json").stat().st_size, 1_048_576)
                if mode == "nonzero":
                    self.assertIn("falló", self.log_file(result["id"], "stderr.log").read_text(encoding="utf-8"))
                    self.assertNotIn("falló", json.dumps(manager.snapshot(), ensure_ascii=False))
                manager.close()
                self.managers.remove(manager)

    def test_cancel_and_active_contention(self):
        manager = self.manager(self.config("slow", timeout_seconds=10))
        a, b = self.ticket(), self.ticket()
        running = manager.start(a["id"], "fixture", 1)
        with self.assertRaises(DomainError) as caught:
            manager.start(b["id"], "fixture", 1)
        self.assertEqual(caught.exception.status, 409)
        with self.assertRaises(DomainError) as caught:
            self.manager(self.config("slow", timeout_seconds=10))
        self.assertEqual(caught.exception.status, 409)
        cancelled = manager.cancel(running["id"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(self.store.context(a["id"])["ticket"]["status"], "blocked")
        self.assertEqual(self.store.context(b["id"])["ticket"]["status"], "queued")

    def test_external_edit_causes_conflict_without_overwrite(self):
        manager = self.manager(self.config("stale", timeout_seconds=3))
        ticket = self.ticket()
        running = manager.start(ticket["id"], "fixture", 1)
        self.store.action("update_ticket", {"id": ticket["id"], "expected_revision": 2,
                                            "description": "Human edit during worker run"})
        result = self.finish(manager, running["id"])
        self.assertEqual(result["status"], "conflict")
        current = self.store.context(ticket["id"])["ticket"]
        self.assertEqual(current["description"], "Human edit during worker run")
        self.assertEqual(current["status"], "in_progress")

    def test_restart_interrupts_stale_run_and_blocks_owned_ticket(self):
        first = self.manager(None)
        ticket = self.ticket()
        actor = "agent:run-stale"
        claimed = self.store.action("claim_ticket", {"id": ticket["id"], "expected_revision": 1,
                                                      "assignee": actor, "actual_model": "fixture-model",
                                                      "actual_effort": "medium"}, actor)
        with self.store._write() as db:
            db.execute("""INSERT INTO execution_runs
                (id,ticket_id,worker_id,status,started_at,finished_at,summary,error,model,effort,
                 claim_revision,actor,owner_instance,owner_pid)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("run-stale", ticket["id"], "fixture", "running", "2026-01-01T00:00:00Z", None, "", "",
                 "fixture-model", "medium", claimed["revision"], actor, "dead-manager", os.getpid()))
        recovered = self.manager(self.config())
        run = recovered.snapshot()["runs"][0]
        self.assertEqual(run["status"], "interrupted")
        self.assertEqual(self.store.context(ticket["id"])["ticket"]["status"], "blocked")

    def test_start_rejects_empty_acceptance_and_profile_mismatch(self):
        manager = self.manager(self.config(profile_ids=["sol"]))
        empty = self.store.action("create_ticket", {"title": "No criteria"})
        with self.assertRaises(DomainError):
            manager.start(empty["id"], "fixture", 1)
        unprofiled = self.ticket()
        with self.assertRaises(DomainError):
            manager.start(unprofiled["id"], "fixture", 1)
        self.assertEqual(self.store.state()["stats"]["ready"], 2)


if __name__ == "__main__":
    unittest.main()
