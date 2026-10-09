"""Real MCP history paging with bounded context; no provider or inference."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from agentrelay.store import Store


HAS_MCP = importlib.util.find_spec("mcp") is not None


@unittest.skipUnless(HAS_MCP, "Install .[mcp] to run actual protocol integration tests")
class MCPHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_recent_context_cursor_pages_isolation_and_strict_errors(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory(prefix="agentrelay-mcp-history-") as directory:
            database = Path(directory) / "tickets.sqlite"
            store = Store(database)
            target = store.action("create_ticket", {
                "title": "Target before update", "acceptance": ["History reviewed"]})
            other = store.action("create_ticket", {
                "title": "Interleaved ticket", "acceptance": ["Other history"]})
            target = store.action("update_ticket", {
                "id": target["id"], "expected_revision": target["revision"],
                "title": "Target current"})
            for index in range(55):
                store.action("add_comment", {"id": target["id"], "body": f"Target event {index:02d}"})
                store.action("add_comment", {"id": other["id"], "body": f"Other event {index:02d}"})

            expected = store.context(target["id"])["events"]
            other_ids = {event["id"] for event in store.context(other["id"])["events"]}
            self.assertGreater(len(expected), 50)

            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "agentrelay", "mcp", "--db", str(database),
                      "--actor", "agent:history-test"],
                cwd=str(Path(__file__).resolve().parents[1]),
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    tools = await client.list_tools()
                    by_name = {tool.name: tool for tool in tools.tools}
                    self.assertIn("list_ticket_events", by_name)
                    self.assertTrue(by_name["list_ticket_events"].annotations.readOnlyHint)

                    async def call(name, args):
                        result = await client.call_tool(name, args)
                        self.assertFalse(result.isError, str(result))
                        return (result.structuredContent if result.structuredContent is not None
                                else json.loads(result.content[0].text))

                    context = await call("get_ticket_context", {
                        "ticket_id": target["id"], "event_limit": 20})
                    self.assertEqual(context["ticket"]["title"], "Target current")
                    self.assertEqual(context["ticket"]["revision"], target["revision"])
                    self.assertEqual([event["id"] for event in context["events"]],
                                     [event["id"] for event in expected[:20]])
                    self.assertEqual(context["events_page"], {
                        "total": len(expected), "count": 20, "limit": 20,
                        "next_before_id": expected[19]["id"],
                    })

                    collected = []
                    cursor = None
                    while True:
                        args = {"ticket_id": target["id"], "limit": 13}
                        if cursor is not None:
                            args["before_id"] = cursor
                        page = await call("list_ticket_events", args)
                        self.assertEqual(page["ticket_id"], target["id"])
                        self.assertEqual(page["total"], len(expected))
                        self.assertEqual(page["limit"], 13)
                        self.assertEqual(page["before_id"], cursor)
                        self.assertEqual(page["count"], len(page["events"]))
                        self.assertTrue(all(event["ticket_id"] == target["id"]
                                            and event["id"] not in other_ids
                                            for event in page["events"]))
                        collected.extend(page["events"])
                        next_cursor = page["next_before_id"]
                        if next_cursor is None:
                            break
                        self.assertEqual(next_cursor, page["events"][-1]["id"])
                        cursor = next_cursor
                    self.assertEqual([event["id"] for event in collected],
                                     [event["id"] for event in expected])
                    self.assertEqual(len({event["id"] for event in collected}), len(expected))

                    invalid_context = ({"event_limit": 0}, {"event_limit": 101},
                                       {"event_limit": True}, {"event_limit": 1.5},
                                       {"event_limit": "20"})
                    for extra in invalid_context:
                        with self.subTest(context=extra):
                            result = await client.call_tool("get_ticket_context", {
                                "ticket_id": target["id"], **extra})
                            self.assertTrue(result.isError, str(result))
                    unknown = await client.call_tool("get_ticket_context", {
                        "ticket_id": "AR-9999", "event_limit": 20})
                    self.assertTrue(unknown.isError, str(unknown))

                    invalid_history = (
                        {"limit": 0}, {"limit": 101}, {"limit": True},
                        {"limit": 1.5}, {"limit": "20"}, {"before_id": 0},
                        {"before_id": -1}, {"before_id": 2**63},
                        {"before_id": True}, {"before_id": 1.5},
                        {"before_id": "5"},
                    )
                    for extra in invalid_history:
                        with self.subTest(history=extra):
                            result = await client.call_tool("list_ticket_events", {
                                "ticket_id": target["id"], **extra})
                            self.assertTrue(result.isError, str(result))
                    unknown = await client.call_tool("list_ticket_events", {
                        "ticket_id": "AR-9999", "limit": 20})
                    self.assertTrue(unknown.isError, str(unknown))


if __name__ == "__main__":
    unittest.main()
