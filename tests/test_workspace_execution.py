"""Exercise worker execution through two HTTP workspaces with colliding IDs."""

from http.client import HTTPConnection
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

from agentrelay.execution import ExecutionManager
from agentrelay.server import AppServer
from agentrelay.store import Store
from agentrelay.workspaces import Workspace


WORKER_SOURCE = """\
import json
from pathlib import Path
import sys
import time

packet = json.load(sys.stdin)
title = packet['context']['ticket']['title']
marker = title.split()[0]
Path('started.txt').write_text(marker, encoding='utf-8')
if marker == 'ALPHA':
    release = Path.cwd().parent / 'release-alpha'
    deadline = time.monotonic() + 6
    while not release.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
elif marker == 'CANCEL':
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        time.sleep(0.05)
report = Path.cwd() / ('report-' + marker.lower() + '.txt')
report.write_text(marker + ' report with evidence', encoding='utf-8')
json.dump({'outcome': 'submit', 'summary': marker + ' fixture report',
           'evidence': [{'kind': 'report', 'label': marker + ' evidence',
                         'uri': str(report)}]}, sys.stdout)
"""


class WorkspaceExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-workspace-execution-")
        self.root = Path(self.temp.name)
        self.server = None
        self.thread = None
        self.managers = []
        self.addCleanup(self._cleanup)
        worker_script = self.root / "fixture_worker.py"
        worker_script.write_text(WORKER_SOURCE, encoding="utf-8")
        workspaces = {}
        for identity in ("alpha", "beta"):
            directory = self.root / identity
            directory.mkdir()
            store = Store(directory / "workspace.sqlite")
            store.action("create_ticket", {"title": identity.upper() + " project",
                                           "acceptance": ["Produce a fixture report"]})
            config = directory / "workers.json"
            config.write_text(json.dumps({"workers": [{
                "id": "fixture", "name": "Fixture", "command": [sys.executable, str(worker_script)],
                "cwd": str(directory), "model": "fixture-model", "effort": "medium",
                "profile_ids": [], "timeout_seconds": 10,
            }]}), encoding="utf-8")
            manager = ExecutionManager(store, config)
            self.managers.append(manager)
            workspaces[identity] = Workspace(identity, identity.upper(), store, manager)
        self.workspaces = workspaces
        self.server = AppServer(("127.0.0.1", 0), workspaces["alpha"].store,
                                workspaces=workspaces, default_workspace_id="alpha")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def _cleanup(self):
        if self.thread is not None:
            self.server.shutdown()
        if self.server is not None:
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=3)
        for manager in self.managers:
            manager.close()
        self.temp.cleanup()

    def request(self, method, path, workspace, data=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {"X-AgentRelay-Workspace": workspace,
                   "X-AgentRelay-Client": "browser", "Content-Type": "application/json"}
        try:
            connection.request(method, path, json.dumps(data) if data is not None else None, headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def action(self, workspace, name, data):
        return self.request("POST", "/api/actions", workspace, {"action": name, "data": data})

    def wait_until(self, predicate, timeout=12):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(0.05)
        self.fail("Timed out waiting for fixture worker state")

    def run_status(self, workspace, run_id):
        status, body = self.request("GET", "/api/state", workspace)
        self.assertEqual(status, 200, body)
        matches = [run for run in body["execution"]["runs"] if run["id"] == run_id]
        self.assertEqual(len(matches), 1)
        return matches[0]["status"]

    def test_execution_cancel_and_history_are_isolated_by_workspace(self):
        for identity in ("alpha", "beta"):
            status, body = self.request("GET", "/api/tickets/AR-0001/context", identity)
            self.assertEqual(status, 200, body)
            self.assertEqual(body["ticket"]["title"], identity.upper() + " project")

        status, body = self.action("alpha", "start_run", {"ticket_id": "AR-0001",
                                                          "worker_id": "fixture", "expected_revision": 1})
        self.assertEqual(status, 200, body)
        alpha_run = body["result"]["id"]
        self.wait_until(lambda: (self.root / "alpha" / "started.txt").exists())
        self.assertEqual(self.run_status("alpha", alpha_run), "running")

        status, body = self.action("beta", "cancel_run", {"run_id": alpha_run})
        self.assertEqual(status, 404, body)
        self.assertEqual(self.run_status("alpha", alpha_run), "running")

        status, body = self.action("beta", "start_run", {"ticket_id": "AR-0001",
                                                         "worker_id": "fixture", "expected_revision": 1})
        self.assertEqual(status, 200, body)
        beta_run = body["result"]["id"]
        self.assertEqual(self.run_status("alpha", alpha_run), "running")
        (self.root / "release-alpha").write_text("continue", encoding="utf-8")
        self.wait_until(lambda: self.run_status("alpha", alpha_run) == "submitted")
        self.wait_until(lambda: self.run_status("beta", beta_run) == "submitted")

        for identity, run_id, other_run in (("alpha", alpha_run, beta_run),
                                            ("beta", beta_run, alpha_run)):
            status, state = self.request("GET", "/api/state", identity)
            self.assertEqual(status, 200, state)
            self.assertEqual(state["workspace"]["id"], identity)
            self.assertEqual([run["id"] for run in state["execution"]["runs"]], [run_id])
            ticket = next(item for item in state["tickets"] if item["id"] == "AR-0001")
            self.assertEqual(ticket["status"], "review")
            self.assertEqual(ticket["evidence"][0]["label"], identity.upper() + " evidence")
            report = self.root / identity / ("report-" + identity + ".txt")
            self.assertEqual(ticket["evidence"][0]["uri"], str(report))
            self.assertEqual(report.read_text(encoding="utf-8"), identity.upper() + " report with evidence")
            self.assertIn(identity.upper(), ticket["checkpoint"])
            status, exported = self.request("GET", "/api/export", identity)
            self.assertEqual(status, 200, exported)
            self.assertEqual([run["id"] for run in exported["runs"]], [run_id])
            self.assertNotIn(other_run, json.dumps(exported))

        status, created = self.action("beta", "create_ticket", {
            "title": "CANCEL project", "acceptance": ["Cancelled fixture remains blocked"]})
        self.assertEqual(status, 200, created)
        cancel_ticket = created["result"]["id"]
        status, started = self.action("beta", "start_run", {"ticket_id": cancel_ticket,
                                                            "worker_id": "fixture", "expected_revision": 1})
        self.assertEqual(status, 200, started)
        cancel_run = started["result"]["id"]
        self.wait_until(lambda: (self.root / "beta" / "started.txt").read_text(encoding="utf-8") == "CANCEL")
        status, cancelled = self.action("beta", "cancel_run", {"run_id": cancel_run})
        self.assertEqual(status, 200, cancelled)
        self.assertEqual(cancelled["result"]["status"], "cancelled")
        self.assertEqual(self.run_status("beta", cancel_run), "cancelled")
        self.assertEqual(self.run_status("alpha", alpha_run), "submitted")
        self.assertEqual(self.workspaces["beta"].store.context(cancel_ticket)["ticket"]["status"], "blocked")
        self.assertFalse((self.root / "beta" / "report-cancel.txt").exists())


if __name__ == "__main__":
    unittest.main()
