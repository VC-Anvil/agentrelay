"""Actual CLI, HTTP and MCP boundaries reject stale review context."""

import importlib.util
import json
from http.client import HTTPConnection
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from agentrelay.server import AppServer
from agentrelay.store import Store


ROOT = Path(__file__).resolve().parents[1]


def submit(store, title, **fields):
    ticket = store.action("create_ticket", {"title": title, "acceptance": ["Checked"], **fields})
    ticket = store.action("claim_ticket", {"id": ticket["id"],
        "expected_revision": ticket["revision"], "assignee": "author"}, "agent:author")
    return store.action("submit_ticket", {"id": ticket["id"],
        "expected_revision": ticket["revision"], "summary": "Fixture delivery",
        "evidence": [{"kind": "test", "label": "Fixture", "uri": "fixture://review"}]}, "agent:author")


def acceptance(context):
    ticket = context["ticket"]
    return {"id": ticket["id"], "expected_revision": ticket["revision"],
            "expected_acceptance_context_token": context["acceptance_context"]["token"],
            "verification": "Fixture context inspected", "accepted_criteria": ticket["acceptance"]}


def add_completed_child(store, parent):
    child = submit(store, "Later child", parent_id=parent["id"])
    store.action("complete_ticket", acceptance(store.context(child["id"])), "agent:reviewer")


class AcceptanceContextProtocols(unittest.TestCase):
    def test_cli_requires_token_and_preserves_state_on_stale_context(self):
        with tempfile.TemporaryDirectory(prefix="agentrelay-context-cli-") as directory:
            root = Path(directory)
            store = Store(root / "workspace.sqlite")
            parent = submit(store, "Parent")
            original = acceptance(store.context(parent["id"]))
            add_completed_child(store, parent)
            before = store.state()

            def call(data):
                path = root / "request.json"
                path.write_text(json.dumps({"action": "complete_ticket", "data": data}), encoding="utf-8")
                return subprocess.run([sys.executable, "-m", "agentrelay", "action",
                    "--db", store.path, "--actor", "agent:reviewer", "--input", str(path)],
                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=20)

            for data, diagnostic in (
                ({key: value for key, value in original.items() if key != "expected_acceptance_context_token"},
                 "expected_acceptance_context_token"),
                (original, "acceptance context changed"),
            ):
                failed = call(data)
                self.assertEqual(failed.returncode, 1, failed.stderr)
                self.assertEqual(failed.stdout.strip(), "")
                self.assertIn(diagnostic, failed.stderr)
                self.assertNotIn("Traceback", failed.stderr)
                self.assertEqual(store.state(), before)
            current = acceptance(store.context(parent["id"]))
            result = call(current)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "done")

    def test_http_context_and_completion_share_required_precondition(self):
        with tempfile.TemporaryDirectory(prefix="agentrelay-context-http-") as directory:
            store = Store(Path(directory) / "workspace.sqlite")
            parent = submit(store, "Parent")
            server = AppServer(("127.0.0.1", 0), store)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def request(method, path, payload=None):
                    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
                    try:
                        connection.request(method, path, json.dumps(payload) if payload else None,
                            {"Content-Type": "application/json", "X-AgentRelay-Client": "browser"})
                        response = connection.getresponse()
                        return response.status, json.loads(response.read())
                    finally:
                        connection.close()

                path = f"/api/tickets/{parent['id']}/context"
                status, context = request("GET", path)
                self.assertEqual(status, 200)
                original = acceptance(context)
                add_completed_child(store, parent)
                before = store.state()
                for data, expected_status in (
                    ({**original, "expected_acceptance_context_token": "invalid"}, 400),
                    (original, 409),
                ):
                    status, result = request("POST", "/api/actions", {"action": "complete_ticket", "data": data})
                    self.assertEqual(status, expected_status, result)
                    self.assertIn("error", result)
                    self.assertEqual(store.state(), before)
                status, context = request("GET", path)
                self.assertEqual(status, 200)
                status, result = request("POST", "/api/actions", {
                    "action": "complete_ticket", "data": acceptance(context)})
                self.assertEqual(status, 200, result)
                self.assertEqual(result["result"]["status"], "done")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(3)


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Install .[mcp] for SDK integration")
class AcceptanceContextMCP(unittest.IsolatedAsyncioTestCase):
    async def test_required_schema_stale_context_and_explicit_rereview(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory(prefix="agentrelay-context-mcp-") as directory:
            store = Store(Path(directory) / "workspace.sqlite")
            parent = submit(store, "Parent")
            parameters = StdioServerParameters(command=sys.executable,
                args=["-m", "agentrelay", "mcp", "--db", store.path, "--actor", "agent:reviewer"], cwd=str(ROOT))
            async with stdio_client(parameters) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    schema = next(t for t in (await client.list_tools()).tools if t.name == "review_ticket").inputSchema
                    self.assertIn("expected_acceptance_context_token", schema["required"])

                    async def context():
                        response = await client.call_tool("get_ticket_context", {"ticket_id": parent["id"]})
                        self.assertFalse(response.isError, str(response))
                        return response.structuredContent or json.loads(response.content[0].text)

                    def arguments(value):
                        data = acceptance(value)
                        data["ticket_id"] = data.pop("id")
                        return data

                    original = arguments(await context())
                    add_completed_child(store, parent)
                    before = store.state()
                    failed = await client.call_tool("review_ticket", original)
                    self.assertTrue(failed.isError, str(failed))
                    self.assertIn("409", str(failed.content))
                    self.assertIn("acceptance context changed", str(failed.content))
                    self.assertEqual(store.state(), before)
                    missing = {k: v for k, v in original.items() if k != "expected_acceptance_context_token"}
                    failed = await client.call_tool("review_ticket", missing)
                    self.assertTrue(failed.isError, str(failed))
                    self.assertEqual(store.state(), before)
                    result = await client.call_tool("review_ticket", arguments(await context()))
                    self.assertFalse(result.isError, str(result))
                    self.assertEqual(store.context(parent["id"])["ticket"]["status"], "done")


if __name__ == "__main__":
    unittest.main()
