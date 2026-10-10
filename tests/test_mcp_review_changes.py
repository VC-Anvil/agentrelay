"""Real MCP and generic CLI coverage for independent review returns."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from agentrelay.store import Store


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ACCEPTANCE = ["Claim corrected", "Source qualification explicit"]
EVIDENCE = [{"kind": "report", "label": "Historical draft", "uri": "local://draft"}]


def submitted_ticket(store: Store, actor: str = "agent:author") -> dict:
    ticket = store.action("create_ticket", {
        "title": "Review factual claims",
        "description": "Keep the historical delivery intact",
        "priority": "high",
        "acceptance": ACCEPTANCE,
    })
    ticket = store.action("claim_ticket", {
        "id": ticket["id"], "expected_revision": ticket["revision"],
        "assignee": "author", "actual_model": "unknown", "actual_effort": "unknown",
    }, actor)
    ticket = store.action("checkpoint", {
        "id": ticket["id"], "expected_revision": ticket["revision"],
        "checkpoint": "Draft preserved before independent review",
    }, actor)
    return store.action("submit_ticket", {
        "id": ticket["id"], "expected_revision": ticket["revision"],
        "summary": "Historical draft delivered", "evidence": EVIDENCE,
    }, actor)


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Install .[mcp] for SDK integration")
class MCPReviewChangesTests(unittest.IsolatedAsyncioTestCase):
    async def test_author_rejected_reviewer_returns_and_context_exposes_feedback(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory(prefix="agentrelay-mcp-review-changes-") as directory:
            database = Path(directory) / "workspace.sqlite"
            store = Store(database)
            delivered = submitted_ticket(store)
            before = store.context(delivered["id"])["ticket"]
            runs_before = store.export()["runs"]

            def parameters(actor):
                return StdioServerParameters(
                    command=sys.executable,
                    args=["-m", "agentrelay", "mcp", "--db", str(database),
                          "--actor", actor],
                    cwd=str(PROJECT_ROOT),
                )

            async with stdio_client(parameters("agent:author")) as (author_read, author_write), \
                    stdio_client(parameters("agent:reviewer")) as (review_read, review_write):
                async with ClientSession(author_read, author_write) as author, \
                        ClientSession(review_read, review_write) as reviewer:
                    await asyncio.gather(author.initialize(), reviewer.initialize())
                    tools = await reviewer.list_tools()
                    by_name = {tool.name: tool for tool in tools.tools}
                    tool = by_name["request_ticket_changes"]
                    self.assertFalse(tool.annotations.readOnlyHint)
                    self.assertFalse(tool.annotations.idempotentHint)
                    self.assertEqual(tool.inputSchema["properties"]["expected_revision"]["type"],
                                     "integer")

                    async def call(client, name, arguments):
                        response = await client.call_tool(name, arguments)
                        self.assertFalse(response.isError, str(response))
                        return (response.structuredContent if response.structuredContent is not None
                                else json.loads(response.content[0].text))

                    author_context, reviewer_context = await asyncio.gather(
                        call(author, "get_ticket_context", {"ticket_id": delivered["id"]}),
                        call(reviewer, "get_ticket_context", {"ticket_id": delivered["id"]}),
                    )
                    self.assertEqual(author_context["ticket"]["revision"], delivered["revision"])
                    self.assertEqual(reviewer_context["ticket"]["status"], "review")
                    self.assertIsNone(reviewer_context["review_feedback"])

                    arguments = {
                        "ticket_id": delivered["id"],
                        "expected_revision": delivered["revision"],
                        "reason": "Correct the factual claim and label its source.",
                    }
                    self_review = await author.call_tool("request_ticket_changes", arguments)
                    self.assertTrue(self_review.isError, str(self_review))
                    self.assertEqual(store.context(delivered["id"])["ticket"]["revision"],
                                     delivered["revision"])

                    for invalid in (True, "4", 0):
                        with self.subTest(expected_revision=invalid):
                            rejected = await reviewer.call_tool("request_ticket_changes", {
                                **arguments, "expected_revision": invalid})
                            self.assertTrue(rejected.isError, str(rejected))

                    returned = await call(reviewer, "request_ticket_changes", arguments)
                    self.assertEqual((returned["status"], returned["assignee"]), ("queued", None))
                    self.assertEqual(returned["revision"], delivered["revision"] + 1)
                    for field in ("description", "acceptance", "checkpoint", "evidence",
                                  "actual_model", "actual_effort"):
                        self.assertEqual(returned[field], before[field], field)

                    current = await call(reviewer, "get_ticket_context", {
                        "ticket_id": delivered["id"], "event_limit": 1})
                    feedback = current["review_feedback"]
                    self.assertEqual(feedback["reviewer"], "agent:reviewer")
                    self.assertEqual(feedback["reason"], arguments["reason"])
                    self.assertEqual(feedback["previous_assignee"], "author")
                    self.assertEqual(feedback["submitted_revision"], delivered["revision"])
                    self.assertEqual(feedback["returned_revision"], returned["revision"])
                    self.assertFalse(feedback["submission_after_request"])
                    self.assertFalse(feedback["completion_after_request"])
                    self.assertIn("later submission is not acceptance", current["instructions"])

            exported = store.export()
            self.assertEqual(exported["runs"], runs_before)
            request_events = [event for event in exported["events"]
                              if event["action"] == "request_changes"]
            self.assertEqual(len(request_events), 1)
            self.assertFalse(any(event["action"] in {"claim_ticket", "start_run"}
                                 and event["id"] > request_events[0]["id"]
                                 for event in exported["events"]))


class CLIReviewChangesTests(unittest.TestCase):
    def test_generic_action_returns_delivery_without_launching_execution(self):
        with tempfile.TemporaryDirectory(prefix="agentrelay-cli-review-changes-") as directory:
            root = Path(directory)
            database = root / "workspace.sqlite"
            store = Store(database)
            delivered = submitted_ticket(store)
            before = store.context(delivered["id"])["ticket"]
            envelope = root / "request.json"
            envelope.write_text(json.dumps({
                "action": "request_changes",
                "data": {
                    "id": delivered["id"],
                    "expected_revision": delivered["revision"],
                    "reason": "Separate host evidence from independent verification.",
                },
            }), encoding="utf-8")
            environment = os.environ.copy()
            current_path = environment.get("PYTHONPATH")
            environment["PYTHONPATH"] = (str(PROJECT_ROOT) if not current_path else
                                          str(PROJECT_ROOT) + os.pathsep + current_path)

            process = subprocess.run([
                sys.executable, "-m", "agentrelay", "action", "--db", str(database),
                "--actor", "agent:cli-reviewer", "--input", str(envelope),
            ], cwd=root, env=environment, capture_output=True, text=True,
                encoding="utf-8", timeout=20)

            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertNotIn("Traceback", process.stderr)
            returned = json.loads(process.stdout)
            self.assertEqual((returned["status"], returned["assignee"]), ("queued", None))
            self.assertEqual(returned["evidence"], before["evidence"])
            self.assertEqual(returned["checkpoint"], before["checkpoint"])
            context = store.context(delivered["id"], event_limit=1)
            self.assertEqual(context["review_feedback"]["reviewer"], "agent:cli-reviewer")
            self.assertEqual(context["review_feedback"]["reason"],
                             "Separate host evidence from independent verification.")
            self.assertEqual(store.export()["runs"], [])


if __name__ == "__main__":
    unittest.main()
