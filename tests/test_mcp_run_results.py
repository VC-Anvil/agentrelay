"""MCP exposes the same exact retained proposal through a read-only tool."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from tests.test_cli_run_results import domain_rows, prepare_database


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Install .[mcp] for SDK integration")
class MCPRunResultTests(unittest.IsolatedAsyncioTestCase):
    async def test_selected_legacy_and_invalid_results_are_isolated_and_read_only(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory(prefix="agentrelay-mcp-run-result-") as directory:
            database = Path(directory) / "workspace.sqlite"
            _, proposal = prepare_database(database)
            before = domain_rows(database)
            params = StdioServerParameters(command=sys.executable, args=[
                "-m", "agentrelay", "mcp", "--db", str(database),
                "--actor", "agent:run-result-reader"],
                cwd=str(Path(__file__).resolve().parents[1]))

            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    tools = await client.list_tools()
                    selected_tool = next(tool for tool in tools.tools
                                         if tool.name == "get_run_result")
                    self.assertTrue(selected_tool.annotations.readOnlyHint)

                    async def call(run_id):
                        response = await client.call_tool("get_run_result", {"run_id": run_id})
                        self.assertFalse(response.isError, str(response))
                        return (response.structuredContent if response.structuredContent is not None
                                else json.loads(response.content[0].text))

                    selected = await call("run-á")
                    self.assertEqual(selected["run"]["id"], "run-á")
                    self.assertEqual(selected["result"], proposal)
                    self.assertEqual(selected["result"]["summary"],
                                     "Propuesta útil en español: ágil")
                    self.assertEqual(selected["current_ticket"]["id"], "AR-0001")
                    self.assertNotIn("owner_instance", selected["run"])
                    self.assertNotIn("result_json", selected["run"])
                    self.assertNotIn("Otro resultado", json.dumps(selected, ensure_ascii=False))

                    legacy = await call("run-legacy")
                    self.assertIsNone(legacy["result"])
                    self.assertEqual(legacy["run"]["error"], "Legacy output unavailable")

                    for value in ("", "   ", "missing", 7, True, None):
                        with self.subTest(value=value):
                            rejected = await client.call_tool("get_run_result", {"run_id": value})
                            self.assertTrue(rejected.isError, str(rejected))

            self.assertEqual(domain_rows(database), before)


if __name__ == "__main__":
    unittest.main()
