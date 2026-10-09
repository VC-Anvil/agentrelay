"""MCP discovers a run before reading only its selected retained proposal."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from tests.test_cli_run_results import domain_rows, prepare_database


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Install .[mcp] for SDK integration")
class MCPRunHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_paged_discovery_then_selected_result_are_isolated_and_read_only(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory(prefix="agentrelay-mcp-run-history-") as directory:
            database = Path(directory) / "workspace.sqlite"
            _, proposal = prepare_database(database)
            before = domain_rows(database)
            params = StdioServerParameters(command=sys.executable, args=[
                "-m", "agentrelay", "mcp", "--db", str(database),
                "--actor", "agent:run-history-reader"],
                cwd=str(Path(__file__).resolve().parents[1]))

            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    tools = await client.list_tools()
                    listed_tool = next(tool for tool in tools.tools if tool.name == "list_runs")
                    self.assertTrue(listed_tool.annotations.readOnlyHint)

                    async def call(name, arguments):
                        response = await client.call_tool(name, arguments)
                        self.assertFalse(response.isError, str(response))
                        return (response.structuredContent if response.structuredContent is not None
                                else json.loads(response.content[0].text))

                    first = await call("list_runs", {"ticket_id": "AR-0001", "limit": 1})
                    self.assertEqual([run["id"] for run in first["runs"]], ["run-á"])
                    self.assertEqual(first["total"], 2)
                    self.assertEqual(first["next_before_id"], "run-á")
                    self.assertTrue(first["runs"][0]["has_result"])
                    self.assertNotIn("result", first["runs"][0])
                    self.assertNotIn("result_json", first["runs"][0])
                    self.assertNotIn("Otro resultado", json.dumps(first, ensure_ascii=False))

                    selected = await call("get_run_result", {"run_id": first["runs"][0]["id"]})
                    self.assertEqual(selected["result"], proposal)
                    self.assertEqual(selected["current_ticket"]["id"], "AR-0001")
                    self.assertNotIn("Otro resultado", json.dumps(selected, ensure_ascii=False))

                    second = await call("list_runs", {
                        "ticket_id": "AR-0001", "limit": 1,
                        "before_id": first["next_before_id"],
                    })
                    self.assertEqual([run["id"] for run in second["runs"]], ["run-legacy"])
                    self.assertFalse(second["runs"][0]["has_result"])
                    self.assertIsNone(second["next_before_id"])

                    filtered = await call("list_runs", {"status": "failed", "limit": 20})
                    self.assertEqual({run["id"] for run in filtered["runs"]},
                                     {"run-other", "run-legacy"})

                    invalid = (
                        {"limit": 0}, {"limit": 101}, {"limit": True}, {"limit": "1"},
                        {"ticket_id": "missing"}, {"ticket_id": " AR-0001"},
                        {"status": "unknown"}, {"status": " failed"},
                        {"before_id": "missing"},
                        {"ticket_id": "AR-0001", "before_id": "run-other"},
                        {"ticket_id": 7}, {"status": 7}, {"before_id": 7},
                    )
                    for arguments in invalid:
                        with self.subTest(arguments=arguments):
                            rejected = await client.call_tool("list_runs", arguments)
                            self.assertTrue(rejected.isError, str(rejected))

            self.assertEqual(domain_rows(database), before)


if __name__ == "__main__":
    unittest.main()
