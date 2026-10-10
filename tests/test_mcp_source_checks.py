"""MCP reads stored source observations without accepting filesystem paths."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from agentrelay.source_checks import check_sources
from tests.test_cli_source_checks import persisted_rows, prepare_source_check_fixture


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Install .[mcp] for SDK integration")
class MCPSourceChecksTests(unittest.IsolatedAsyncioTestCase):
    async def test_sdk_lists_compact_history_and_reads_one_stored_report(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory(prefix="agentrelay-mcp-source-checks-") as directory:
            root = Path(directory)
            database = root / "workspace.sqlite"
            store, ticket, snapshot, snapshot_id, current = prepare_source_check_fixture(database, root)
            first = check_sources(
                store, ticket_id=ticket["id"], expected_revision=ticket["revision"],
                snapshot=snapshot, expected_snapshot_id=snapshot_id, root=current,
                request_id="mcp-source-one", actor="agent:local-checker",
            )
            (current / "entrada.txt").write_text("cambio útil\n", encoding="utf-8")
            second = check_sources(
                store, ticket_id=ticket["id"], expected_revision=ticket["revision"],
                snapshot=snapshot, expected_snapshot_id=snapshot_id, root=current,
                request_id="mcp-source-two", actor="agent:local-checker",
            )
            before = persisted_rows(database)
            params = StdioServerParameters(command=sys.executable, args=[
                "-m", "agentrelay", "mcp", "--db", str(database),
                "--actor", "agent:source-history-reader",
            ], cwd=str(Path(__file__).resolve().parents[1]))

            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    tools = await client.list_tools()
                    listed = next(tool for tool in tools.tools if tool.name == "list_source_checks")
                    detailed = next(tool for tool in tools.tools if tool.name == "get_source_check")
                    self.assertTrue(listed.annotations.readOnlyHint)
                    self.assertTrue(detailed.annotations.readOnlyHint)
                    self.assertEqual(set(listed.inputSchema["properties"]),
                                     {"ticket_id", "limit", "before_id"})
                    self.assertEqual(set(detailed.inputSchema["properties"]), {"check_id"})
                    self.assertNotIn("root", json.dumps(listed.inputSchema).lower())
                    self.assertNotIn("snapshot", json.dumps(detailed.inputSchema).lower())

                    async def call(name, arguments):
                        response = await client.call_tool(name, arguments)
                        self.assertFalse(response.isError, str(response))
                        return (response.structuredContent if response.structuredContent is not None
                                else json.loads(response.content[0].text))

                    page = await call("list_source_checks", {
                        "ticket_id": ticket["id"], "limit": 1,
                    })
                    self.assertEqual(page["checks"], [second])
                    self.assertEqual(page["total"], 2)
                    self.assertEqual(page["next_before_id"], second["check_id"])
                    self.assertNotIn("report", page["checks"][0])
                    self.assertNotIn("files", page["checks"][0])

                    older = await call("list_source_checks", {
                        "ticket_id": ticket["id"], "limit": 1,
                        "before_id": page["next_before_id"],
                    })
                    self.assertEqual(older["checks"], [first])
                    self.assertIsNone(older["next_before_id"])

                    detail = await call("get_source_check", {"check_id": second["check_id"]})
                    self.assertEqual(detail["report"]["summary"]["modified"], 1)
                    self.assertEqual(detail["report"]["files"][0]["path"], "entrada.txt")
                    self.assertEqual(detail["report_sha256"], second["report_sha256"])

                    context = await call("get_ticket_context", {"ticket_id": ticket["id"]})
                    self.assertEqual([item["check_id"] for item in context["source_checks"]],
                                     [second["check_id"], first["check_id"]])
                    self.assertTrue(all(item["ticket_revision_matches_now"]
                                        for item in context["source_checks"]))
                    self.assertNotIn("report", context["source_checks"][0])

                    invalid_lists = (
                        {"ticket_id": ticket["id"], "limit": 0},
                        {"ticket_id": ticket["id"], "limit": 101},
                        {"ticket_id": ticket["id"], "limit": True},
                        {"ticket_id": ticket["id"], "limit": "1"},
                        {"ticket_id": ticket["id"], "before_id": 0},
                        {"ticket_id": ticket["id"], "before_id": True},
                        {"ticket_id": "missing"},
                    )
                    for arguments in invalid_lists:
                        with self.subTest(arguments=arguments):
                            response = await client.call_tool("list_source_checks", arguments)
                            self.assertTrue(response.isError, str(response))

                    for check_id in (0, True, "1", 999999):
                        with self.subTest(check_id=check_id):
                            response = await client.call_tool("get_source_check", {"check_id": check_id})
                            self.assertTrue(response.isError, str(response))

            self.assertEqual(persisted_rows(database), before)


if __name__ == "__main__":
    unittest.main()
