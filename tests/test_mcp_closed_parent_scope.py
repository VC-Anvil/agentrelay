"""CLI and real MCP coverage for closed parent source-scope protection."""

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
ACCEPTANCE = ["Parent scope reviewed"]
EVIDENCE = [{"kind": "test", "label": "Deterministic fixture", "uri": "fixture://scope"}]


def closed_scope_fixture(store: Store) -> tuple[dict, dict, dict]:
    parent = store.action("create_ticket", {
        "title": "Closed parent", "acceptance": ACCEPTANCE,
    }, "human")
    child = store.action("create_ticket", {
        "title": "Cancelled child", "parent_id": parent["id"],
    }, "human")
    child = store.action("transition", {
        "id": child["id"], "expected_revision": child["revision"],
        "status": "cancelled", "reason": "Fixture cancellation",
    }, "agent:author")
    parent = store.action("claim_ticket", {
        "id": parent["id"], "expected_revision": parent["revision"],
        "assignee": "author", "actual_model": "unknown", "actual_effort": "unknown",
    }, "agent:author")
    parent = store.action("submit_ticket", {
        "id": parent["id"], "expected_revision": parent["revision"],
        "summary": "Fixture parent delivered", "evidence": EVIDENCE,
    }, "agent:author")
    parent = store.action("complete_ticket", {
        "id": parent["id"], "expected_revision": parent["revision"],
        "verification": "Fixture scope reviewed", "accepted_criteria": ACCEPTANCE,
    }, "agent:reviewer")
    target = store.action("create_ticket", {"title": "Open target"}, "human")
    return parent, child, target


def domain_state(store: Store) -> dict:
    exported = store.export()
    return {key: exported[key] for key in ("demo", "tickets", "profiles", "events", "runs")}


class CLIClosedParentScopeTests(unittest.TestCase):
    def test_detach_and_move_fail_until_source_parent_is_explicitly_reopened(self):
        with tempfile.TemporaryDirectory(prefix="agentrelay-cli-closed-parent-") as directory:
            root = Path(directory)
            database = root / "workspace.sqlite"
            store = Store(database)
            parent, child, target = closed_scope_fixture(store)
            environment = os.environ.copy()
            current_path = environment.get("PYTHONPATH")
            environment["PYTHONPATH"] = (str(PROJECT_ROOT) if not current_path else
                                          str(PROJECT_ROOT) + os.pathsep + current_path)
            request_index = 0

            def action(name: str, data: dict, actor: str = "agent:scope-editor"):
                nonlocal request_index
                request_index += 1
                request = root / f"request-{request_index}.json"
                request.write_text(json.dumps({"action": name, "data": data}), encoding="utf-8")
                return subprocess.run([
                    sys.executable, "-m", "agentrelay", "action", "--db", str(database),
                    "--actor", actor, "--input", str(request),
                ], cwd=PROJECT_ROOT, env=environment, capture_output=True, text=True,
                    encoding="utf-8", timeout=20)

            before = domain_state(store)
            for new_parent in (None, target["id"]):
                with self.subTest(parent_id=new_parent):
                    rejected = action("update_ticket", {
                        "id": child["id"], "expected_revision": child["revision"],
                        "parent_id": new_parent,
                    })
                    self.assertEqual(rejected.returncode, 1, rejected.stderr)
                    self.assertEqual(rejected.stdout.strip(), "")
                    self.assertIn("reopen closed parent", rejected.stderr.lower())
                    self.assertNotIn("traceback", rejected.stderr.lower())
                    self.assertEqual(domain_state(store), before)

            reopened_process = action("transition", {
                "id": parent["id"], "expected_revision": parent["revision"],
                "status": "queued", "reason": "Authorized scope correction",
            }, actor="agent:reviewer")
            self.assertEqual(reopened_process.returncode, 0, reopened_process.stderr)
            reopened = json.loads(reopened_process.stdout)
            self.assertEqual((reopened["status"], reopened["revision"]),
                             ("queued", parent["revision"] + 1))

            fresh_child = store.context(child["id"])["ticket"]
            moved_process = action("update_ticket", {
                "id": child["id"], "expected_revision": fresh_child["revision"],
                "parent_id": target["id"],
            })
            self.assertEqual(moved_process.returncode, 0, moved_process.stderr)
            moved = json.loads(moved_process.stdout)
            self.assertEqual(moved["parent_id"], target["id"])
            self.assertEqual(store.context(parent["id"])["ticket"]["status"], "queued")
            self.assertEqual([item["id"] for item in store.context(target["id"])["children"]],
                             [child["id"]])


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Install .[mcp] for SDK integration")
class MCPClosedParentScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_detach_and_move_errors_are_atomic_then_fresh_reopen_allows_move(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory(prefix="agentrelay-mcp-closed-parent-") as directory:
            database = Path(directory) / "workspace.sqlite"
            store = Store(database)
            parent, child, target = closed_scope_fixture(store)
            before = domain_state(store)
            parameters = StdioServerParameters(
                command=sys.executable,
                args=["-m", "agentrelay", "mcp", "--db", str(database),
                      "--actor", "agent:scope-editor"],
                cwd=str(PROJECT_ROOT),
            )

            async with stdio_client(parameters) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()

                    async def call(name: str, arguments: dict) -> dict:
                        response = await client.call_tool(name, arguments)
                        self.assertFalse(response.isError, str(response))
                        return (response.structuredContent if response.structuredContent is not None
                                else json.loads(response.content[0].text))

                    for new_parent in (None, target["id"]):
                        with self.subTest(parent_id=new_parent):
                            rejected = await client.call_tool("update_ticket", {
                                "ticket_id": child["id"],
                                "expected_revision": child["revision"],
                                "changes": {"parent_id": new_parent},
                            })
                            self.assertTrue(rejected.isError, str(rejected))
                            error_text = " ".join(block.text for block in rejected.content
                                                  if hasattr(block, "text"))
                            self.assertIn("409", error_text)
                            self.assertIn("reopen closed parent", error_text.lower())
                            self.assertEqual(domain_state(store), before)

                    parent_context = await call("get_ticket_context", {
                        "ticket_id": parent["id"], "event_limit": 1,
                    })
                    reopened = await call("transition_ticket", {
                        "ticket_id": parent["id"],
                        "expected_revision": parent_context["ticket"]["revision"],
                        "status": "queued", "reason": "Authorized scope correction",
                    })
                    self.assertEqual(reopened["status"], "queued")

                    child_context = await call("get_ticket_context", {
                        "ticket_id": child["id"], "event_limit": 1,
                    })
                    moved = await call("update_ticket", {
                        "ticket_id": child["id"],
                        "expected_revision": child_context["ticket"]["revision"],
                        "changes": {"parent_id": target["id"]},
                    })
                    self.assertEqual(moved["parent_id"], target["id"])

            current = store.context(child["id"])["ticket"]
            self.assertEqual(current["parent_id"], target["id"])
            self.assertEqual(store.context(parent["id"])["ticket"]["status"], "queued")


if __name__ == "__main__":
    unittest.main()
