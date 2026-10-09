"""Real SDK client/server stdio round-trip, no LLM and no inference spending."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from agentrelay.store import Store

HAS_MCP = importlib.util.find_spec("mcp") is not None


@unittest.skipUnless(HAS_MCP, "Install .[mcp] to run actual protocol integration tests")
class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_claim_help_resume_delivery_independent_review(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        test_root = Path(__file__).resolve().parents[1] / ".cache" / "tests"
        test_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=test_root) as directory:
            db = Path(directory) / "shared.sqlite"
            store = Store(db)
            params = StdioServerParameters(command=sys.executable, args=["-m", "agentrelay", "mcp", "--db", str(db), "--actor", "agent:integration-test"], cwd=str(Path(__file__).resolve().parents[1]))
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as client:
                    initialized = await client.initialize()
                    self.assertEqual(initialized.serverInfo.name, "AgentRelay")
                    tools = await client.list_tools()
                    self.assertIn("request_help", {t.name for t in tools.tools})

                    async def call(name, args):
                        result = await client.call_tool(name, args)
                        self.assertFalse(result.isError, str(result))
                        if result.structuredContent is not None:
                            return result.structuredContent
                        return json.loads(result.content[0].text)

                    task = await call("create_ticket", {"title": "Protocol exercise", "description": "Test handoff across UI/store and MCP", "acceptance": ["A concrete result is independently reviewed"]})
                    task = await call("claim_ticket", {"ticket_id": task["id"], "expected_revision": task["revision"], "actual_model": "protocol-test-no-llm", "actual_effort": "none"})
                    self.assertEqual(task["assignee"], "agent:integration-test")
                    help_result = await call("request_help", {"ticket_id": task["id"], "expected_revision": task["revision"], "title": "Clarify the result", "description": "Need an independently checkable output"})
                    child = help_result["child"]
                    child = store.action("claim_ticket", {"id": child["id"], "expected_revision": child["revision"], "assignee": "agent:helper"}, "agent:helper")
                    child = store.action("submit_ticket", {"id": child["id"], "expected_revision": child["revision"], "summary": "Use a persisted result", "evidence": [{"kind": "test", "label": "Protocol fixture", "uri": "test://mcp/help"}]}, "agent:helper")
                    store.action("complete_ticket", {"id": child["id"], "expected_revision": child["revision"], "verification": "Reviewed help fixture", "accepted_criteria": child["acceptance"]})
                    context = await call("get_ticket_context", {"ticket_id": task["id"]})
                    self.assertEqual(context["ticket"]["status"], "blocked")
                    task = await call("transition_ticket", {"ticket_id": task["id"], "expected_revision": context["ticket"]["revision"], "status": "queued", "reason": "Help reviewed"})
                    task = await call("claim_ticket", {"ticket_id": task["id"], "expected_revision": task["revision"], "actual_model": "protocol-test-no-llm", "actual_effort": "none"})
                    task = await call("save_checkpoint", {"ticket_id": task["id"], "expected_revision": task["revision"], "checkpoint": "Result persisted, ready to deliver"})
                    task = await call("submit_ticket", {"ticket_id": task["id"], "expected_revision": task["revision"], "summary": "Result delivered", "evidence": [{"kind": "test", "label": "Test result", "uri": "test://mcp/delivery"}]})
                    failed = await client.call_tool("review_ticket", {"ticket_id": task["id"], "expected_revision": task["revision"], "verification": "Self review", "accepted_criteria": task["acceptance"]})
                    self.assertTrue(failed.isError)
                    done = store.action("complete_ticket", {"id": task["id"], "expected_revision": task["revision"], "verification": "Independent integration review", "accepted_criteria": task["acceptance"]})
                    self.assertEqual(done["status"], "done")
                    context = await call("get_ticket_context", {"ticket_id": task["id"]})
                    self.assertEqual(context["ticket"]["status"], "done")
                    resource = await client.read_resource("agentrelay://workflow")
                    self.assertIn("agent:integration-test", resource.contents[0].text)


if __name__ == "__main__":
    unittest.main()
