"""Real MCP listing with bounded summaries and stable pages when data is unchanged."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from agentrelay.store import Store


HAS_MCP = importlib.util.find_spec("mcp") is not None
SUMMARY_FIELDS = {"id", "title", "type", "status", "priority", "parent_id",
                  "profile_id", "assignee", "revision", "ready", "blockers"}


@unittest.skipUnless(HAS_MCP, "Install .[mcp] to run actual protocol integration tests")
class MCPListingTests(unittest.IsolatedAsyncioTestCase):
    async def test_pages_filters_details_and_invalid_requests(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory(prefix="agentrelay-mcp-list-") as directory:
            database = Path(directory) / "tickets.sqlite"
            store = Store(database)
            priorities = ("urgent", "high", "normal", "low")
            created = []
            for index in range(30):
                created.append(store.action("create_ticket", {
                    "title": f"Item {index:02d}", "description": f"Private detail {index}",
                    "priority": priorities[index % 4],
                    "profile_id": "sol" if index % 2 else None,
                    "acceptance": [f"Criterion {index}"],
                }))
            first = store.action("claim_ticket", {"id": created[1]["id"], "expected_revision": 1,
                                                        "assignee": "agent:owner"}, actor="agent:owner")
            second = store.action("claim_ticket", {"id": created[2]["id"], "expected_revision": 1,
                                                         "assignee": "agent:owner"}, actor="agent:owner")
            store.action("transition", {"id": second["id"], "expected_revision": second["revision"],
                                        "status": "blocked", "reason": "Awaiting input"}, actor="agent:owner")
            store.action("transition", {"id": created[3]["id"], "expected_revision": 1,
                                        "status": "backlog"})

            params = StdioServerParameters(command=sys.executable,
                args=["-m", "agentrelay", "mcp", "--db", str(database), "--actor", "agent:list-test"],
                cwd=str(Path(__file__).resolve().parents[1]))
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    tools = await client.list_tools()
                    self.assertIn("list_tickets", {tool.name for tool in tools.tools})

                    async def call(args):
                        result = await client.call_tool("list_tickets", args)
                        self.assertFalse(result.isError, str(result))
                        return (result.structuredContent if result.structuredContent is not None
                                else json.loads(result.content[0].text))

                    state = store.state()
                    expected = sorted(state["tickets"], key=lambda t: (
                        priorities.index(t["priority"]), t["created_at"], t["id"]))
                    pages = [await call({"limit": 11, "offset": offset}) for offset in (0, 11, 22)]
                    self.assertEqual([page["count"] for page in pages], [11, 11, 8])
                    self.assertEqual([page["total"] for page in pages], [30, 30, 30])
                    self.assertEqual([page["next_offset"] for page in pages], [11, 22, None])
                    self.assertEqual([item["id"] for page in pages for item in page["tickets"]],
                                     [ticket["id"] for ticket in expected])
                    self.assertEqual(pages[0]["actor"], "agent:list-test")
                    for page in pages:
                        self.assertEqual(page["limit"], 11)
                        for ticket in page["tickets"]:
                            self.assertEqual(set(ticket), SUMMARY_FIELDS)
                            self.assertNotIn("Private detail", json.dumps(ticket))
                    beyond = await call({"offset": 100})
                    self.assertEqual((beyond["count"], beyond["total"], beyond["next_offset"]),
                                     (0, 30, None))
                    self.assertEqual((await call({}))["count"], 20)

                    owners = await call({"assignee": "agent:owner"})
                    self.assertEqual(owners["total"], 2)
                    self.assertEqual({ticket["status"] for ticket in owners["tickets"]},
                                     {"in_progress", "blocked"})
                    self.assertTrue(any("Awaiting input" in ticket["blockers"]
                                        for ticket in owners["tickets"]))
                    urgent = await call({"priority": "urgent", "ready_only": True})
                    self.assertEqual(urgent["total"], 8)
                    self.assertTrue(all(ticket["ready"] and ticket["priority"] == "urgent"
                                        for ticket in urgent["tickets"]))
                    self.assertEqual((await call({"status": "backlog"}))["total"], 1)
                    self.assertEqual((await call({"profile_id": "sol"}))["total"], 15)
                    detailed = await call({"assignee": "agent:owner", "include_details": True})
                    self.assertEqual(detailed["total"], 2)
                    for ticket in detailed["tickets"]:
                        self.assertEqual(ticket, next(t for t in state["tickets"] if t["id"] == ticket["id"]))
                        self.assertIn("description", ticket)
                        self.assertIn("acceptance", ticket)

                    invalid = ({"status": "unknown"}, {"priority": "now"},
                               {"profile_id": "unknown"}, {"assignee": " "},
                               {"limit": 0}, {"limit": 101}, {"offset": -1},
                               {"limit": True}, {"limit": 1.5}, {"limit": "4"},
                               {"offset": False}, {"ready_only": "yes"},
                               {"include_details": "not-a-boolean"})
                    for args in invalid:
                        with self.subTest(args=args):
                            result = await client.call_tool("list_tickets", args)
                            self.assertTrue(result.isError, str(result))


if __name__ == "__main__":
    unittest.main()
