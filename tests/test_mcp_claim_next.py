"""Two real MCP connections reserve distinct tickets from one reviewed scope."""

import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from agentrelay.store import Store


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Install .[mcp] for SDK integration")
class MCPClaimNextTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_scoped_claims_replay_and_conflicts(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory(prefix="agentrelay-mcp-claim-next-") as directory:
            database = Path(directory) / "workspace.sqlite"
            store = Store(database)
            urgent = store.action("create_ticket", {
                "title": "Urgent candidate", "priority": "urgent",
                "acceptance": ["Reviewed"]})
            high = store.action("create_ticket", {
                "title": "High candidate", "priority": "high",
                "acceptance": ["Reviewed"]})
            outside = store.action("create_ticket", {
                "title": "Urgent outside scope", "priority": "urgent",
                "acceptance": ["Reviewed"]})
            candidates = [
                {"ticket_id": urgent["id"], "expected_revision": urgent["revision"]},
                {"ticket_id": high["id"], "expected_revision": high["revision"]},
            ]
            root = str(Path(__file__).resolve().parents[1])
            first_params = StdioServerParameters(command=sys.executable, args=[
                "-m", "agentrelay", "mcp", "--db", str(database),
                "--actor", "agent:first-candidate"], cwd=root)
            second_params = StdioServerParameters(command=sys.executable, args=[
                "-m", "agentrelay", "mcp", "--db", str(database),
                "--actor", "agent:second-candidate"], cwd=root)

            async with stdio_client(first_params) as (first_read, first_write), \
                    stdio_client(second_params) as (second_read, second_write):
                async with ClientSession(first_read, first_write) as first, \
                        ClientSession(second_read, second_write) as second:
                    await asyncio.gather(first.initialize(), second.initialize())
                    tools = await first.list_tools()
                    claim_next = next(tool for tool in tools.tools
                                      if tool.name == "claim_next_ticket")
                    ordinary = next(tool for tool in tools.tools if tool.name == "claim_ticket")
                    self.assertTrue(claim_next.annotations.idempotentHint)
                    self.assertFalse(claim_next.annotations.readOnlyHint)
                    self.assertFalse(ordinary.annotations.idempotentHint)

                    async def context(client, ticket_id):
                        response = await client.call_tool("get_ticket_context", {
                            "ticket_id": ticket_id,
                        })
                        self.assertFalse(response.isError, str(response))
                        return (response.structuredContent if response.structuredContent is not None
                                else json.loads(response.content[0].text))

                    reviewed = await asyncio.gather(
                        context(first, urgent["id"]), context(first, high["id"]),
                        context(second, urgent["id"]), context(second, high["id"]),
                    )
                    self.assertTrue(all(item["ticket"]["revision"] == 1 for item in reviewed))

                    first_args = {"request_id": "first-request", "candidates": candidates,
                                  "actual_model": "unknown", "actual_effort": "unknown"}
                    second_args = {"request_id": "second-request", "candidates": candidates,
                                   "actual_model": "unknown", "actual_effort": "unknown"}

                    async def call(client, arguments):
                        response = await client.call_tool("claim_next_ticket", arguments)
                        self.assertFalse(response.isError, str(response))
                        return (response.structuredContent if response.structuredContent is not None
                                else json.loads(response.content[0].text))

                    first_result, second_result = await asyncio.gather(
                        call(first, first_args), call(second, second_args))
                    claimed = {first_result["ticket"]["id"], second_result["ticket"]["id"]}
                    self.assertEqual(claimed, {urgent["id"], high["id"]})
                    self.assertNotEqual(first_result["ticket"]["assignee"],
                                        second_result["ticket"]["assignee"])
                    self.assertTrue(any(item["reason"] == "stale_revision"
                                        for result in (first_result, second_result)
                                        for item in result["skipped"]))

                    replay = await call(first, first_args)
                    self.assertEqual(replay, first_result)

                    actor_conflict = await second.call_tool("claim_next_ticket", first_args)
                    self.assertTrue(actor_conflict.isError, str(actor_conflict))
                    payload_conflict = await first.call_tool("claim_next_ticket", {
                        **first_args,
                        "candidates": [{"ticket_id": outside["id"],
                                        "expected_revision": outside["revision"]}],
                    })
                    self.assertTrue(payload_conflict.isError, str(payload_conflict))
                    invalid = await first.call_tool("claim_next_ticket", {
                        "request_id": "invalid-request",
                        "candidates": [{"ticket_id": outside["id"],
                                        "expected_revision": True}],
                        "actual_model": "unknown", "actual_effort": "unknown",
                    })
                    self.assertTrue(invalid.isError, str(invalid))

            state = {ticket["id"]: ticket for ticket in store.state()["tickets"]}
            self.assertEqual(state[outside["id"]]["status"], "queued")
            self.assertEqual({state[urgent["id"]]["assignee"], state[high["id"]]["assignee"]},
                             {"agent:first-candidate", "agent:second-candidate"})
            events = [event for event in store.export()["events"]
                      if event["action"] == "claim_ticket"]
            self.assertEqual(len(events), 2)
            self.assertEqual({event["ticket_id"] for event in events},
                             {urgent["id"], high["id"]})


if __name__ == "__main__":
    unittest.main()
