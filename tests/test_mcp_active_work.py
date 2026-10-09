"""Agent-facing recovery: extend active acceptance and route urgent help."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from agentrelay.store import Store


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Install .[mcp] for SDK integration")
class MCPActiveWorkTests(unittest.IsolatedAsyncioTestCase):
    async def test_extend_criteria_and_discover_urgent_help(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory(prefix="agentrelay-mcp-active-") as directory:
            database = Path(directory) / "tickets.sqlite"
            store = Store(database)
            parent = store.action("create_ticket", {
                "title": "Urgent recovery", "priority": "urgent",
                "acceptance": ["Recovered"], "profile_id": "sol"})
            other = store.action("create_ticket", {
                "title": "Other pending work", "priority": "high",
                "acceptance": ["Checked"], "profile_id": "luna"})
            params = StdioServerParameters(command=sys.executable, args=[
                "-m", "agentrelay", "mcp", "--db", str(database),
                "--actor", "agent:recovery-worker"],
                cwd=str(Path(__file__).resolve().parents[1]))
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()

                    async def call(name, args):
                        result = await client.call_tool(name, args)
                        self.assertFalse(result.isError, str(result))
                        return (result.structuredContent if result.structuredContent is not None
                                else json.loads(result.content[0].text))

                    claimed = await call("claim_ticket", {
                        "ticket_id": parent["id"], "expected_revision": parent["revision"],
                        "actual_model": "fixture-model", "actual_effort": "high"})
                    extended = await call("update_ticket", {
                        "ticket_id": parent["id"], "expected_revision": claimed["revision"],
                        "changes": {"acceptance": ["Recovered", "Regression checked"],
                                    "description": "A second check was discovered during work"}})
                    self.assertEqual(extended["acceptance"], ["Recovered", "Regression checked"])
                    context = await call("get_ticket_context", {"ticket_id": parent["id"]})
                    change = next(event for event in context["events"]
                                  if event["action"] == "update_ticket")
                    self.assertEqual(change["details"]["before"]["acceptance"], ["Recovered"])
                    self.assertEqual(change["details"]["after"]["acceptance"],
                                     ["Recovered", "Regression checked"])
                    rejected = await client.call_tool("update_ticket", {
                        "ticket_id": parent["id"], "expected_revision": extended["revision"],
                        "changes": {"acceptance": ["Recovered"]}})
                    self.assertTrue(rejected.isError)
                    after = await call("get_ticket_context", {"ticket_id": parent["id"]})
                    self.assertEqual(after["ticket"]["revision"], extended["revision"])

                    help_result = await call("request_help", {
                        "ticket_id": parent["id"], "expected_revision": extended["revision"],
                        "title": "Extract diagnostic records", "description": "Need the failed check details",
                        "profile_id": "luna"})
                    child = help_result["child"]
                    self.assertEqual(help_result["parent"]["status"], "blocked")
                    self.assertEqual(child["priority"], "urgent")
                    self.assertEqual(child["profile_id"], "luna")
                    rejected = await client.call_tool("update_ticket", {
                        "ticket_id": parent["id"],
                        "expected_revision": help_result["parent"]["revision"],
                        "changes": {"acceptance": ["Recovered"]}})
                    self.assertTrue(rejected.isError)
                    blocked = await call("get_ticket_context", {"ticket_id": parent["id"]})
                    self.assertEqual(blocked["ticket"]["revision"],
                                     help_result["parent"]["revision"])
                    ready = await call("list_tickets", {"ready_only": True, "profile_id": "luna"})
                    self.assertEqual([ticket["id"] for ticket in ready["tickets"]],
                                     [child["id"], other["id"]])
                    self.assertEqual(store.context(parent["id"])["ticket"]["acceptance"],
                                     ["Recovered", "Regression checked"])


if __name__ == "__main__":
    unittest.main()
