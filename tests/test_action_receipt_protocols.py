"""Real CLI, HTTP and MCP surfaces for durable ticket-action receipts."""

from __future__ import annotations

import asyncio
from contextlib import closing
from http.client import HTTPConnection
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from agentrelay.server import AppServer
from agentrelay.store import Store


ROOT = Path(__file__).resolve().parents[1]


def wrapper(request_id: str, action: str, data: dict) -> dict:
    return {"action": "apply_ticket_action", "data": {
        "request_id": request_id, "action": action, "data": data,
    }}


class CLIActionReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-action-receipt-cli-")
        self.root = Path(self.temp.name)
        self.counter = 0

    def tearDown(self):
        self.temp.cleanup()

    def call(self, database: Path, payload: dict, actor: str = "agent:cli-writer"):
        self.counter += 1
        request = self.root / f"request-{self.counter}.json"
        request.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return subprocess.run([
            sys.executable, "-m", "agentrelay", "action", "--db", str(database),
            "--actor", actor, "--input", str(request),
        ], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=20, check=False)

    def test_wrapper_bootstraps_only_inner_create_and_replays(self):
        database = self.root / "new" / "workspace.sqlite"
        payload = wrapper("cli-create-á", "create_ticket", {
            "title": "Única creación", "acceptance": ["Una salida"],
        })
        first = self.call(database, payload)
        self.assertEqual(first.returncode, 0, first.stderr)
        first_receipt = json.loads(first.stdout)
        self.assertFalse(first_receipt["replayed"])
        self.assertEqual(first_receipt["actor"], "agent:cli-writer")
        self.assertEqual(first_receipt["action"], "create_ticket")

        second = self.call(database, payload)
        self.assertEqual(second.returncode, 0, second.stderr)
        second_receipt = json.loads(second.stdout)
        self.assertTrue(second_receipt["replayed"])
        self.assertEqual(second_receipt["result"], first_receipt["result"])
        self.assertEqual(second_receipt["committed_at"], first_receipt["committed_at"])
        store = Store(database)
        self.assertEqual([ticket["title"] for ticket in store.state()["tickets"]],
                         ["Única creación"])
        self.assertEqual(len([event for event in store.export()["events"]
                              if event["action"] == "create_ticket"]), 1)

        changed = self.call(database, wrapper("cli-create-á", "create_ticket", {
            "title": "Otra intención", "acceptance": ["Una salida"],
        }))
        self.assertNotEqual(changed.returncode, 0)
        self.assertNotIn("Traceback", changed.stderr)
        self.assertEqual(len(store.state()["tickets"]), 1)

    def test_invalid_or_nonbootstrap_wrapper_does_not_create_database(self):
        cases = [
            wrapper("missing-comment", "add_comment", {"id": "AR-0001", "body": "x"}),
            {"action": "apply_ticket_action", "data": {
                "request_id": "bad-reserved", "action": "create_ticket",
                "data": {"title": "No crear", "actor": "agent:spoof"},
            }},
            {"action": "apply_ticket_action", "data": {
                "request_id": "bad-extra", "action": "create_ticket",
                "data": {"title": "No crear"}, "extra": True,
            }},
        ]
        for index, payload in enumerate(cases):
            database = self.root / f"missing-{index}" / "workspace.sqlite"
            result = self.call(database, payload)
            self.assertNotEqual(result.returncode, 0, (index, result.stdout, result.stderr))
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(database.exists())
            self.assertFalse(database.parent.exists())


class HTTPActionReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-action-receipt-http-")
        self.store = Store(Path(self.temp.name) / "workspace.sqlite")
        self.server = AppServer(("127.0.0.1", 0), self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.temp.cleanup()

    def post(self, payload):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request("POST", "/api/actions", json.dumps(payload), {
                "Content-Type": "application/json", "X-AgentRelay-Client": "browser",
            })
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_postcommit_failure_replays_one_child_with_current_state(self):
        parent = self.store.action("create_ticket", {"title": "Padre"})
        payload = wrapper("http-child-once", "create_ticket", {
            "title": "Hija única", "parent_id": parent["id"],
        })
        with mock.patch.object(self.server, "snapshot", side_effect=ValueError("fallo tras commit")):
            with mock.patch("agentrelay.server.logging.exception"):
                first_status, first_body = self.post(payload)
        self.assertEqual(first_status, 500, first_body)
        children = self.store.context(parent["id"])["children"]
        self.assertEqual(len(children), 1)
        child = children[0]
        changed = self.store.action("update_ticket", {
            "id": child["id"], "expected_revision": child["revision"],
            "title": "Título actual posterior",
        })

        replay_status, replay_body = self.post(payload)
        self.assertEqual(replay_status, 200, replay_body)
        receipt = replay_body["result"]
        self.assertTrue(receipt["replayed"])
        self.assertEqual(receipt["result"]["title"], "Hija única")
        current = next(ticket for ticket in replay_body["state"]["tickets"]
                       if ticket["id"] == child["id"])
        self.assertEqual(current["title"], "Título actual posterior")
        self.assertEqual(current["revision"], changed["revision"])
        self.assertEqual(len(self.store.context(parent["id"])["children"]), 1)

    def test_postcommit_comment_replay_and_invalid_payload_do_not_duplicate(self):
        ticket = self.store.action("create_ticket", {"title": "Comentable"})
        payload = wrapper("http-comment-once", "add_comment", {
            "id": ticket["id"], "body": "Una observación",
        })
        with mock.patch.object(self.server, "snapshot", side_effect=ValueError("fallo tras commit")):
            with mock.patch("agentrelay.server.logging.exception"):
                first_status, _ = self.post(payload)
        self.assertEqual(first_status, 500)
        status, body = self.post(payload)
        self.assertEqual(status, 200, body)
        self.assertTrue(body["result"]["replayed"])
        comments = [event for event in self.store.context(ticket["id"])["events"]
                    if event["action"] == "add_comment"]
        self.assertEqual(len(comments), 1)

        before = self.store.state()
        invalid_status, _ = self.post(wrapper("invalid-nested", "add_comment", {
            "id": ticket["id"], "body": "No guardar", "request_id": "nested",
        }))
        self.assertEqual(invalid_status, 400)
        self.assertEqual(self.store.state()["tickets"], before["tickets"])
        self.assertEqual(self.store.state()["events"], before["events"])


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Install .[mcp] for SDK integration")
class MCPActionReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def test_schema_actor_binding_concurrency_and_replay(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory(prefix="agentrelay-action-receipt-mcp-") as directory:
            database = Path(directory) / "workspace.sqlite"
            setup = Store(database)
            claimable = setup.action("create_ticket", {
                "title": "Claim actor fixture", "acceptance": ["Reviewed"],
            })
            astra_claimable = setup.action("create_ticket", {
                "title": "Astra declaration fixture", "acceptance": ["Reviewed"],
                "profile_id": "astra",
            })
            review = setup.action("create_ticket", {
                "title": "Reviewer fixture", "acceptance": ["Reviewed"],
            })
            review = setup.action("claim_ticket", {
                "id": review["id"], "expected_revision": review["revision"],
                "assignee": "agent:receipt-writer", "actual_model": "unknown",
                "actual_effort": "unknown",
            }, actor="agent:receipt-writer")
            review = setup.action("submit_ticket", {
                "id": review["id"], "expected_revision": review["revision"],
                "summary": "Fixture", "evidence": [{
                    "kind": "test", "label": "Fixture", "uri": "fixture://review",
                }],
            }, actor="agent:receipt-writer")
            acceptance_token = setup.context(review["id"])["acceptance_context"]["token"]
            args = ["-m", "agentrelay", "mcp", "--db", str(database),
                    "--actor", "agent:receipt-writer"]
            params = StdioServerParameters(command=sys.executable, args=args, cwd=str(ROOT))
            async with stdio_client(params) as (read_a, write_a), \
                    stdio_client(params) as (read_b, write_b):
                async with ClientSession(read_a, write_a) as first, \
                        ClientSession(read_b, write_b) as second:
                    await asyncio.gather(first.initialize(), second.initialize())
                    listed = await first.list_tools()
                    tools = {tool.name: tool for tool in listed.tools}
                    self.assertTrue(tools["apply_ticket_action"].annotations.idempotentHint)
                    self.assertTrue(tools["create_plan"].annotations.idempotentHint)
                    self.assertFalse(tools["create_ticket"].annotations.idempotentHint)
                    action_schema = tools["apply_ticket_action"].inputSchema
                    self.assertEqual(set(action_schema["required"]),
                                     {"request_id", "action", "data"})

                    arguments = {"request_id": "mcp-concurrent-once",
                                 "action": "create_ticket",
                                 "data": {"title": "Creación MCP única"}}

                    async def call(client, value):
                        response = await client.call_tool("apply_ticket_action", value)
                        self.assertFalse(response.isError, str(response))
                        return (response.structuredContent if response.structuredContent is not None
                                else json.loads(response.content[0].text))

                    receipts = await asyncio.gather(call(first, arguments), call(second, arguments))
                    self.assertEqual({receipt["replayed"] for receipt in receipts}, {False, True})
                    self.assertEqual(receipts[0]["result"], receipts[1]["result"])
                    replay = await call(first, arguments)
                    self.assertTrue(replay["replayed"])

                    unknown = await first.call_tool("apply_ticket_action", {
                        **arguments, "request_id": "mcp-unknown", "action": "start_run",
                    })
                    self.assertTrue(unknown.isError, str(unknown))
                    reserved = await first.call_tool("apply_ticket_action", {
                        "request_id": "mcp-reserved", "action": "create_ticket",
                        "data": {"title": "No crear", "actor": "agent:spoof"},
                    })
                    self.assertTrue(reserved.isError, str(reserved))
                    mismatched_assignee = await first.call_tool("apply_ticket_action", {
                        "request_id": "mcp-claim-spoof", "action": "claim_ticket",
                        "data": {"id": claimable["id"],
                                 "expected_revision": claimable["revision"],
                                 "assignee": "agent:other-writer",
                                 "actual_model": "unknown", "actual_effort": "unknown"},
                    })
                    self.assertTrue(mismatched_assignee.isError, str(mismatched_assignee))
                    invalid_declarations = [
                        {"id": astra_claimable["id"],
                         "expected_revision": astra_claimable["revision"],
                         "assignee": "agent:receipt-writer"},
                        {"id": astra_claimable["id"],
                         "expected_revision": astra_claimable["revision"],
                         "assignee": "agent:receipt-writer",
                         "actual_model": None, "actual_effort": "high"},
                        {"id": astra_claimable["id"],
                         "expected_revision": astra_claimable["revision"],
                         "assignee": "agent:receipt-writer",
                         "actual_model": "gpt-6-astra", "actual_effort": ""},
                    ]
                    for index, claim_data in enumerate(invalid_declarations):
                        invalid_claim = await first.call_tool("apply_ticket_action", {
                            "request_id": f"mcp-astra-declaration-{index}",
                            "action": "claim_ticket", "data": claim_data,
                        })
                        self.assertTrue(invalid_claim.isError, str(invalid_claim))
                    self_review = await first.call_tool("apply_ticket_action", {
                        "request_id": "mcp-self-review", "action": "complete_ticket",
                        "data": {"id": review["id"],
                                 "expected_revision": review["revision"],
                                 "expected_acceptance_context_token": acceptance_token,
                                 "verification": "No debe aceptarse",
                                 "accepted_criteria": ["Reviewed"]},
                    })
                    self.assertTrue(self_review.isError, str(self_review))

            other_params = StdioServerParameters(command=sys.executable, args=[
                "-m", "agentrelay", "mcp", "--db", str(database),
                "--actor", "agent:other-writer"], cwd=str(ROOT))
            async with stdio_client(other_params) as (read_other, write_other):
                async with ClientSession(read_other, write_other) as other:
                    await other.initialize()
                    conflict = await other.call_tool("apply_ticket_action", arguments)
                    self.assertTrue(conflict.isError, str(conflict))

            store = Store(database)
            tickets = {ticket["title"]: ticket for ticket in store.state()["tickets"]}
            self.assertEqual(set(tickets), {
                "Claim actor fixture", "Astra declaration fixture",
                "Reviewer fixture", "Creación MCP única",
            })
            self.assertEqual(tickets["Claim actor fixture"]["status"], "queued")
            self.assertEqual(tickets["Astra declaration fixture"]["status"], "queued")
            self.assertIsNone(tickets["Astra declaration fixture"]["assignee"])
            self.assertEqual(tickets["Reviewer fixture"]["status"], "review")
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM action_requests").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
