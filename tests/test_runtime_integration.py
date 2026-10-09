"""Real HTTP/process boundaries with explicit non-LLM fixture workers."""

import json
from http.client import HTTPConnection
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from agentrelay.__main__ import ready_work
from agentrelay.adapters import codex, ollama, persist_result
from agentrelay.execution import ExecutionManager
from agentrelay.server import AppServer
from agentrelay.store import Store


class RuntimeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-http-runtime-")
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "test.sqlite")
        script = self.root / "fixture.py"
        script.write_text('import json,sys\np=json.load(sys.stdin)\nprint(json.dumps({"outcome":"submit","summary":"Fixture only, no LLM", "evidence":[{"kind":"test","label":"Protocol fixture","uri":"fixture://result"}]}))', encoding="utf-8")
        self.config = self.root / "workers.json"
        self.worker = {"id": "fixture", "name": "Fixture, not an LLM", "command": [sys.executable, str(script)],
                       "cwd": str(self.root), "model": "fixture-no-llm", "effort": "none",
                       "profile_ids": [], "timeout_seconds": 10}
        self.config.write_text(json.dumps({"workers": [self.worker]}), encoding="utf-8")
        self.manager = ExecutionManager(self.store, self.config)
        self.server = AppServer(("127.0.0.1", 0), self.store, execution=self.manager)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)
        self.temp.cleanup()

    def request(self, method, path, data=None):
        conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        conn.request(method, path, json.dumps(data) if data else None,
                     {"Content-Type": "application/json", "X-AgentRelay-Client": "browser"})
        response = conn.getresponse()
        value = response.status, json.loads(response.read())
        conn.close()
        return value

    def action(self, action, data):
        return self.request("POST", "/api/actions", {"action": action, "data": data})

    def test_launch_to_independent_review_export_and_online_backup(self):
        status, created = self.action("create_ticket", {"title": "Protocol check", "acceptance": ["Report delivered"]})
        self.assertEqual(status, 200)
        ticket = created["result"]
        status, response = self.action("start_run", {"ticket_id": ticket["id"], "worker_id": "fixture", "expected_revision": ticket["revision"]})
        self.assertEqual(status, 200, response)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = self.request("GET", "/api/state")[1]
            if state["execution"]["runs"][0]["status"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(state["execution"]["runs"][0]["status"], "submitted", state)
        self.assertNotIn("command", state["execution"]["workers"][0])
        ticket = state["tickets"][0]
        self.assertEqual(ticket["status"], "review")
        status, response = self.action("complete_ticket", {"id": ticket["id"], "expected_revision": ticket["revision"],
            "verification": "Independently checked fixture response", "accepted_criteria": ticket["acceptance"]})
        self.assertEqual(status, 200, response)
        exported = self.request("GET", "/api/export")[1]
        self.assertEqual(exported["runs"][0]["status"], "submitted")
        self.assertEqual(exported["tickets"][0]["status"], "done")
        backup = self.store.backup(self.root / "backup.sqlite")
        restored = Store(backup).export()
        for field in ("tickets", "profiles", "events", "runs", "demo"):
            self.assertEqual(restored[field], exported[field])
        with self.assertRaises(FileExistsError):
            self.store.backup(backup)
        self.assertEqual(Store(backup).export()["tickets"], exported["tickets"])

    def test_runtime_errors_are_validation_errors(self):
        self.assertEqual(self.action("start_run", {})[0], 400)
        self.assertEqual(self.action("cancel_run", {"run_id": 123})[0], 400)
        self.assertEqual(self.action("cancel_run", {"run_id": "missing"})[0], 404)
        self.assertEqual(self.action("start_run", {"ticket_id": "missing", "worker_id": "fixture", "expected_revision": True})[0], 400)

    def test_scheduler_honors_priority_dependencies_profile_and_acceptance(self):
        a = self.store.action("create_ticket", {"title": "Normal", "acceptance": ["one"], "profile_id": "sol"})
        b = self.store.action("create_ticket", {"title": "Urgent blocked", "priority": "urgent", "depends_on": [a["id"]], "acceptance": ["two"], "profile_id": "sol"})
        c = self.store.action("create_ticket", {"title": "High ready", "priority": "high", "acceptance": ["three"], "profile_id": "sol"})
        self.store.action("create_ticket", {"title": "No criteria", "priority": "urgent", "profile_id": "sol"})
        worker = {**self.worker, "profile_ids": ["sol"]}
        self.assertEqual([t["id"] for t in ready_work(self.store, worker)], [c["id"], a["id"]])

    def test_demo_marker_survives_reopening_without_flag(self):
        self.store.seed_demo()
        self.assertTrue(self.request("GET", "/api/state")[1]["demo"])
        self.assertTrue(Store(self.store.path).export()["demo"])


class AdapterBoundaryTests(unittest.TestCase):
    def test_codex_uses_explicit_model_effort_sandbox_and_json_schema(self):
        packet = {"worker": {"model": "gpt-6-sol", "effort": "high"}, "context": {"ticket": {"id": "AR-1"}}}
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            def fake_run(args, **kwargs):
                self.assertEqual(args[args.index("--model") + 1], "gpt-6-sol")
                self.assertEqual(args[args.index("--sandbox") + 1], "read-only")
                self.assertIn('model_reasoning_effort="high"', args)
                self.assertIn("--ignore-user-config", args)
                self.assertFalse(kwargs["shell"])
                Path(args[args.index("--output-last-message") + 1]).write_text(json.dumps({"outcome": "blocked", "summary": "Fixture"}))
                return type("Process", (), {"returncode": 0})()
            with patch("agentrelay.adapters.subprocess.run", side_effect=fake_run):
                self.assertEqual(codex(packet, directory, "codex", "read-only")["outcome"], "blocked")

    def test_report_evidence_points_to_saved_exact_content(self):
        packet = {"worker": {"model": "fixture", "effort": "none"}, "context": {"ticket": {"id": "AR-1"}}}
        with tempfile.TemporaryDirectory() as temp:
            result = persist_result({"outcome": "submit", "summary": "Written result", "artifact_markdown": "# Exact report\ná", "evidence": []}, Path(temp), packet, "fixture")
            self.assertEqual(Path(result["evidence"][0]["uri"]).read_text(encoding="utf-8"), "# Exact report\ná")
            with self.assertRaises(ValueError):
                persist_result({"outcome": "submit", "artifact_markdown": ""}, Path(temp), packet, "fixture")

    def test_local_adapter_rejects_cloud_and_unsupported_effort_before_request(self):
        for model, effort in (("model-cloud", "none"), ("local", "high")):
            with self.assertRaises(ValueError):
                ollama({"worker": {"model": model, "effort": effort}}, 11434, 1)


if __name__ == "__main__":
    unittest.main()
