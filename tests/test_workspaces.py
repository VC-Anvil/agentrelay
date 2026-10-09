"""Same ticket IDs must never cross a configured project boundary."""

from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest

from agentrelay.server import AppServer
from agentrelay.store import DomainError, Store
from agentrelay.workspaces import Workspace, load_workspaces


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-workspaces-")
        self.root = Path(self.temp.name)
        self.stores = {key: Store(self.root / f"{key}.sqlite") for key in ("alpha", "beta")}
        for key, store in self.stores.items():
            store.action("create_ticket", {"title": key, "acceptance": [f"Check {key}"]})
        self.registry = self.root / "workspaces.json"
        self.entries = [{"id": key, "name": key.upper(), "db": f"{key}.sqlite"} for key in self.stores]
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def save(self, entries=None, **extra):
        self.registry.write_text(json.dumps({"workspaces": self.entries if entries is None else entries,
                                            **extra}), encoding="utf-8")

    def test_registry_rejects_duplicate_missing_and_unrelated_databases(self):
        workspaces, default = load_workspaces(self.registry)
        self.assertEqual(default, "alpha")
        self.assertEqual(workspaces["beta"].public()["database"], str(self.root / "beta.sqlite"))
        for entries in ([self.entries[0], {**self.entries[1], "id": "alpha"}],
                        [self.entries[0], {**self.entries[1], "db": "./alpha.sqlite"}],
                        [{**self.entries[0], "db": "typo.sqlite"}],
                        [{**self.entries[0], "id": "../alpha"}],
                        [{**self.entries[0], "command": ["unexpected"]}]):
            self.save(entries)
            with self.assertRaises(DomainError):
                load_workspaces(self.registry)
        self.assertFalse((self.root / "typo.sqlite").exists())
        unrelated = self.root / "other.sqlite"
        connection = sqlite3.connect(unrelated)
        connection.execute("CREATE TABLE important (value TEXT)")
        connection.close()
        original = unrelated.read_bytes()
        self.save([{**self.entries[0], "db": "other.sqlite"}])
        with self.assertRaises(DomainError):
            load_workspaces(self.registry)
        self.assertEqual(unrelated.read_bytes(), original)

    def test_http_concurrent_projects_context_export_and_writes_are_isolated(self):
        workspaces, default = load_workspaces(self.registry)
        server = AppServer(("127.0.0.1", 0), self.stores[default], workspaces=workspaces,
                           default_workspace_id=default)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(method, path, workspace=None, data=None):
            conn = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
            headers = {"Content-Type": "application/json", "X-AgentRelay-Client": "browser"}
            if workspace is not None:
                headers["X-AgentRelay-Workspace"] = workspace
            conn.request(method, path, json.dumps(data) if data else None, headers)
            response = conn.getresponse()
            result = response.status, json.loads(response.read())
            conn.close()
            return result
        try:
            self.assertEqual(request("GET", "/api/workspaces")[1]["default_workspace_id"], "alpha")
            self.assertEqual(request("GET", "/api/state")[0], 400)
            self.assertEqual(request("GET", "/api/state", "missing")[0], 404)
            payload = {"action": "update_ticket", "data": {"id": "AR-0001", "expected_revision": 1,
                       "title": "Changed in alpha"}}
            self.assertEqual(request("POST", "/api/actions", data=payload)[0], 400)
            self.assertEqual(request("POST", "/api/actions", "../beta", payload)[0], 404)
            status, result = request("POST", "/api/actions", "alpha", payload)
            self.assertEqual(status, 200, result)
            self.assertEqual(result["state"]["workspace"]["id"], "alpha")
            self.assertEqual(self.stores["beta"].context("AR-0001")["ticket"]["title"], "beta")
            for path in ("/api/state", "/api/export", "/api/tickets/AR-0001/context"):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(request, "GET", path, name) for name in ("alpha", "beta")]
                    for name, future in zip(("alpha", "beta"), futures):
                        status, result = future.result()
                        self.assertEqual(status, 200, result)
                        self.assertEqual(result["workspace"]["id"], name)
                        title = result.get("ticket", result.get("tickets", [{}])[0])["title"]
                        self.assertEqual(title, "Changed in alpha" if name == "alpha" else "beta")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)

    def test_partial_execution_setup_failure_releases_previous_lock(self):
        valid = self.root / "workers.json"
        valid.write_text(json.dumps({"workers": [{"id": "fixture", "name": "Fixture", "command": [sys.executable],
            "cwd": str(self.root), "model": "fixture", "effort": "none", "profile_ids": [], "timeout_seconds": 5}]}))
        self.save([{**self.entries[0], "workers": str(valid)}, {**self.entries[1], "workers": "missing.json"}])
        with self.assertRaises(DomainError):
            load_workspaces(self.registry)
        self.save([{**self.entries[0], "workers": str(valid)}])
        workspaces, _ = load_workspaces(self.registry)
        workspaces["alpha"].execution.close()
