"""Existing MCP and CLI result readers expose persisted inline reports exactly."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.test_cli_run_results import domain_rows, prepare_database


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_MARKDOWN = (
    "# Revisión íntegra\r\n"
    "\r\n"
    "Línea Unicode: ágil, ñ, 漢字.\n"
    "  Espacios finales preservados.  \n"
    "Última línea sin salto"
)


def prepare_inline_database(path: Path, root: Path):
    store, proposal = prepare_database(path)
    report = root / "worker-report.md"
    report.write_bytes(ARTIFACT_MARKDOWN.encode("utf-8"))
    captured = report.read_bytes().decode("utf-8")
    proposal = {**proposal, "artifact_markdown": captured}
    with store._write() as database:
        database.execute(
            "UPDATE execution_runs SET result_json=? WHERE id=?",
            (json.dumps(proposal, ensure_ascii=False, separators=(",", ":")), "run-á"),
        )
    report.unlink()
    return store, proposal, report


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Install .[mcp] for SDK integration")
class MCPInlineReportTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_run_result_returns_exact_text_without_report_file_or_mutation(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory(prefix="agentrelay-mcp-inline-report-") as directory:
            root = Path(directory)
            database = root / "workspace.sqlite"
            _, proposal, deleted_report = prepare_inline_database(database, root)
            self.assertFalse(deleted_report.exists())
            before = domain_rows(database)
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "agentrelay", "mcp", "--db", str(database),
                      "--actor", "agent:inline-report-reviewer"],
                cwd=str(PROJECT_ROOT),
            )

            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    tools = await client.list_tools()
                    by_name = {tool.name: tool for tool in tools.tools}
                    self.assertIn("get_run_result", by_name)
                    self.assertTrue(by_name["get_run_result"].annotations.readOnlyHint)
                    self.assertFalse(any("inline" in name for name in by_name))

                    async def call(run_id):
                        response = await client.call_tool("get_run_result", {"run_id": run_id})
                        self.assertFalse(response.isError, str(response))
                        return (response.structuredContent if response.structuredContent is not None
                                else json.loads(response.content[0].text))

                    selected = await call("run-á")
                    self.assertEqual(selected["result"], proposal)
                    self.assertEqual(selected["result"]["artifact_markdown"], ARTIFACT_MARKDOWN)
                    self.assertEqual(selected["result"]["artifact_markdown"].encode("utf-8"),
                                     ARTIFACT_MARKDOWN.encode("utf-8"))
                    self.assertFalse(deleted_report.exists())

                    old_shape = await call("run-other")
                    self.assertIsInstance(old_shape["result"], dict)
                    self.assertNotIn("artifact_markdown", old_shape["result"])
                    legacy = await call("run-legacy")
                    self.assertIsNone(legacy["result"])

            self.assertEqual(domain_rows(database), before)
            self.assertFalse(deleted_report.exists())


class CLIInlineReportTests(unittest.TestCase):
    def test_run_result_prints_exact_persisted_markdown_and_keeps_legacy_shape(self):
        with tempfile.TemporaryDirectory(prefix="agentrelay-cli-inline-report-") as directory:
            root = Path(directory)
            database = root / "workspace.sqlite"
            _, proposal, deleted_report = prepare_inline_database(database, root)
            before = domain_rows(database)
            environment = os.environ.copy()
            current_path = environment.get("PYTHONPATH")
            environment["PYTHONPATH"] = (str(PROJECT_ROOT) if not current_path else
                                          str(PROJECT_ROOT) + os.pathsep + current_path)

            def command(run_id):
                return subprocess.run([
                    sys.executable, "-m", "agentrelay", "run-result",
                    "--db", str(database), "--run", run_id,
                ], cwd=root, env=environment, capture_output=True, text=True,
                    encoding="utf-8", timeout=20)

            selected_process = command("run-á")
            self.assertEqual(selected_process.returncode, 0, selected_process.stderr)
            self.assertNotIn("Traceback", selected_process.stderr)
            selected = json.loads(selected_process.stdout)
            self.assertEqual(selected["result"], proposal)
            self.assertEqual(selected["result"]["artifact_markdown"], ARTIFACT_MARKDOWN)
            self.assertEqual(selected["result"]["artifact_markdown"].encode("utf-8"),
                             ARTIFACT_MARKDOWN.encode("utf-8"))
            self.assertFalse(deleted_report.exists())

            old_process = command("run-other")
            self.assertEqual(old_process.returncode, 0, old_process.stderr)
            old_shape = json.loads(old_process.stdout)
            self.assertNotIn("artifact_markdown", old_shape["result"])
            legacy_process = command("run-legacy")
            self.assertEqual(legacy_process.returncode, 0, legacy_process.stderr)
            self.assertIsNone(json.loads(legacy_process.stdout)["result"])

            self.assertEqual(domain_rows(database), before)
            self.assertFalse(deleted_report.exists())


if __name__ == "__main__":
    unittest.main()
