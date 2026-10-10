"""Real CLI, HTTP and MCP reads for committed ticket-action receipts."""

from __future__ import annotations

from contextlib import closing
from http.client import HTTPConnection
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
from urllib.parse import urlencode

from agentrelay.server import AppServer
from agentrelay.store import Store
from agentrelay.workspaces import Workspace


ROOT = Path(__file__).resolve().parents[1]


def keyed(store: Store, request_id: str, title: str, actor: str) -> dict:
    return store.action("apply_ticket_action", {
        "request_id": request_id, "action": "create_ticket",
        "data": {"title": title, "acceptance": ["Reviewed"]},
    }, actor=actor)


def logical_snapshot(store: Store):
    """Compare domain rows without export's intentionally fresh timestamp."""
    with store._connection() as connection:
        receipts = [tuple(row) for row in connection.execute(
            "SELECT request_id,actor,action,payload_sha256,payload_json,result_json,"
            "committed_at FROM action_requests ORDER BY request_id")]
    return {"state": store.state(), "action_requests": receipts}


class CLIActionReceiptLookupTests(unittest.TestCase):
    def test_exact_unicode_key_actor_scope_and_missing_database(self):
        with tempfile.TemporaryDirectory(prefix="agentrelay-receipt-lookup-cli-") as directory:
            root = Path(directory)
            database = root / "workspace.sqlite"
            store = Store(database)
            request_id = "ü/" + "x" * 126
            original = keyed(store, request_id, "CLI historical", "agent:cli-reader")
            before = logical_snapshot(store)

            def call(*extra):
                return subprocess.run([
                    sys.executable, "-m", "agentrelay", "action-receipt",
                    "--db", str(database), *extra,
                ], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=20, check=False)

            found = call("--actor", "agent:cli-reader", "--request-id", request_id)
            self.assertEqual(found.returncode, 0, found.stderr)
            result = json.loads(found.stdout)
            self.assertEqual(result, {"schema_version": 1, "receipt": {
                key: value for key, value in original.items() if key != "replayed"
            }})
            self.assertNotIn("state", result)
            self.assertNotIn("payload", result["receipt"])

            denied = call("--actor", "agent:other", "--request-id", request_id)
            self.assertEqual(denied.returncode, 1)
            self.assertIn("(404)", denied.stderr)
            self.assertNotIn("Traceback", denied.stderr)
            self.assertEqual(logical_snapshot(store), before)

            missing = root / "missing" / "workspace.sqlite"
            invalid = subprocess.run([
                sys.executable, "-m", "agentrelay", "action-receipt",
                "--db", str(missing), "--actor", "agent:cli-reader",
                "--request-id", " invalid ",
            ], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=20, check=False)
            self.assertEqual(invalid.returncode, 1)
            self.assertIn("(400)", invalid.stderr)
            self.assertFalse(missing.exists())
            self.assertFalse(missing.parent.exists())

            absent_database = root / "absent" / "workspace.sqlite"
            absent = subprocess.run([
                sys.executable, "-m", "agentrelay", "action-receipt",
                "--db", str(absent_database), "--actor", "agent:cli-reader",
                "--request-id", "valid-but-no-database",
            ], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=20, check=False)
            self.assertEqual(absent.returncode, 1)
            self.assertNotIn("Traceback", absent.stderr)
            self.assertFalse(absent_database.exists())
            self.assertFalse(absent_database.parent.exists())


class HTTPActionReceiptLookupTests(unittest.TestCase):
    def test_get_is_workspace_scoped_strict_and_recovers_postcommit_failure(self):
        with tempfile.TemporaryDirectory(prefix="agentrelay-receipt-lookup-http-") as directory:
            root = Path(directory)
            stores = {name: Store(root / f"{name}.sqlite") for name in ("alpha", "beta")}
            shared_key = "same/project+key/á"
            alpha = keyed(stores["alpha"], shared_key, "Alpha", "human")
            beta = keyed(stores["beta"], shared_key, "Beta", "human")
            keyed(stores["alpha"], "agent-only", "Agent private", "agent:worker")
            spaces = {name: Workspace(name, name.title(), store)
                      for name, store in stores.items()}
            server = AppServer(("127.0.0.1", 0), stores["alpha"], workspaces=spaces,
                               default_workspace_id="alpha")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            def request(path, workspace=None, *, method="GET", body=None):
                connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                headers = {}
                if workspace is not None:
                    headers["X-AgentRelay-Workspace"] = workspace
                if method == "POST":
                    headers.update({"X-AgentRelay-Client": "browser",
                                    "Content-Type": "application/json"})
                try:
                    connection.request(method, path,
                                       json.dumps(body) if body is not None else None, headers)
                    response = connection.getresponse()
                    return response.status, response.getheader("Cache-Control"), json.loads(response.read())
                finally:
                    connection.close()

            def receipt_path(value):
                return "/api/action-receipts?" + urlencode({"request_id": value})

            try:
                self.assertEqual(request(receipt_path(shared_key))[0], 400)
                for workspace, expected in (("alpha", alpha), ("beta", beta)):
                    status, cache, result = request(receipt_path(shared_key), workspace)
                    self.assertEqual(status, 200, result)
                    self.assertEqual(cache, "no-store")
                    self.assertEqual(result["workspace"]["id"], workspace)
                    self.assertEqual(result["receipt"], {
                        key: value for key, value in expected.items() if key != "replayed"
                    })
                    self.assertNotIn("state", result)
                    self.assertNotIn("payload", result["receipt"])
                self.assertEqual(request(receipt_path("agent-only"), "alpha")[0], 404)
                self.assertEqual(request(receipt_path(shared_key), "missing")[0], 404)

                invalid_paths = [
                    "/api/action-receipts",
                    "/api/action-receipts?request_id=a&request_id=b",
                    "/api/action-receipts?request_id=%ZZ",
                    "/api/action-receipts?request_id=%FF",
                    "/api/action-receipts?other=a",
                    "/api/action-receipts?request_id=a&other=b",
                ]
                for path in invalid_paths:
                    with self.subTest(path=path):
                        self.assertEqual(request(path, "alpha")[0], 400)

                payload = {"action": "apply_ticket_action", "data": {
                    "request_id": "lost-response", "action": "add_comment",
                    "data": {"id": alpha["result"]["id"], "body": "One comment"},
                }}
                with mock.patch.object(server, "snapshot", side_effect=ValueError("after commit")):
                    with mock.patch("agentrelay.server.logging.exception"):
                        self.assertEqual(request("/api/actions", "alpha", method="POST",
                                                 body=payload)[0], 500)
                events_before = stores["alpha"].export()["events"]
                status, _, recovered = request(receipt_path("lost-response"), "alpha")
                self.assertEqual(status, 200, recovered)
                self.assertEqual(recovered["receipt"]["result"]["id"], alpha["result"]["id"])
                self.assertNotIn("replayed", recovered["receipt"])
                self.assertEqual(stores["alpha"].export()["events"], events_before)

                corrupt = keyed(stores["alpha"], "corrupt", "Corrupt", "human")
                self.assertEqual(corrupt["request_id"], "corrupt")
                with closing(sqlite3.connect(stores["alpha"].path)) as connection:
                    connection.execute("UPDATE action_requests SET result_json=? WHERE request_id=?",
                                       ("not-json", "corrupt"))
                    connection.commit()
                self.assertEqual(request(receipt_path("corrupt"), "alpha")[0], 500)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(3)


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Install .[mcp] for SDK integration")
class MCPActionReceiptLookupTests(unittest.IsolatedAsyncioTestCase):
    async def test_readonly_schema_actor_binding_and_no_domain_mutation(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory(prefix="agentrelay-receipt-lookup-mcp-") as directory:
            database = Path(directory) / "workspace.sqlite"
            store = Store(database)
            original = keyed(store, "mcp/read+á", "MCP historical", "agent:reader")
            before = logical_snapshot(store)

            # Keep all assertions inside each live session; returned response data is detached.
            params = StdioServerParameters(command=sys.executable, args=[
                "-m", "agentrelay", "mcp", "--db", str(database),
                "--actor", "agent:reader",
            ], cwd=str(ROOT))
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                    self.assertTrue(tools["get_action_receipt"].annotations.readOnlyHint)
                    response = await session.call_tool(
                        "get_action_receipt", {"request_id": "mcp/read+á"})
                    self.assertFalse(response.isError, str(response))
                    result = (response.structuredContent if response.structuredContent is not None
                              else json.loads(response.content[0].text))
                    self.assertEqual(result["receipt"], {
                        key: value for key, value in original.items() if key != "replayed"
                    })
                    self.assertNotIn("state", result)
                    missing = await session.call_tool(
                        "get_action_receipt", {"request_id": "absent"})
                    self.assertTrue(missing.isError, str(missing))

            other_params = StdioServerParameters(command=sys.executable, args=[
                "-m", "agentrelay", "mcp", "--db", str(database),
                "--actor", "agent:other",
            ], cwd=str(ROOT))
            async with stdio_client(other_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    denied = await session.call_tool(
                        "get_action_receipt", {"request_id": "mcp/read+á"})
                    self.assertTrue(denied.isError, str(denied))

            self.assertEqual(logical_snapshot(Store(database)), before)


if __name__ == "__main__":
    unittest.main()
