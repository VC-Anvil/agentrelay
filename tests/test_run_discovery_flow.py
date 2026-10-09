"""An MCP agent discovers a real conflicted run from only its ticket identity."""

import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

from agentrelay.execution import ExecutionManager
from agentrelay.store import Store


WORKER = """import json,sys,time
from pathlib import Path
json.load(sys.stdin)
Path('ready').write_text('waiting',encoding='utf-8')
deadline=time.monotonic()+20
while not Path('release').exists():
 if time.monotonic()>deadline: raise RuntimeError('fixture not released')
 time.sleep(0.02)
json.dump({'outcome':'submit','summary':'Propuesta descubierta: análisis ñ',
 'evidence':[{'kind':'fixture','label':'Worker output','uri':'fixture://discovered'}]},
 sys.stdout,ensure_ascii=False)
"""


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Install .[mcp] for SDK integration")
class RunDiscoveryFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_discover_live_run_then_retrieve_conflicted_proposal_without_mutation(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory(prefix="agentrelay-discovery-flow-") as directory:
            root = Path(directory).resolve()
            database = root / "tickets.sqlite"
            store = Store(database)
            ticket = store.action("create_ticket", {
                "title": "Find this worker result", "acceptance": ["Review evidence"]})
            script = root / "worker.py"
            script.write_text(WORKER, encoding="utf-8")
            config = root / "workers.json"
            config.write_text(json.dumps({"workers": [{
                "id": "fixture", "name": "Fixture", "command": [sys.executable, str(script)],
                "cwd": str(root), "model": "fixture-model", "effort": "none",
                "profile_ids": [], "timeout_seconds": 25,
            }]}), encoding="utf-8")
            manager = ExecutionManager(store, config)
            try:
                manager.start(ticket["id"], "fixture", ticket["revision"])
                deadline = time.monotonic() + 8
                while not (root / "ready").exists() and time.monotonic() < deadline:
                    await asyncio.sleep(0.02)
                self.assertTrue((root / "ready").exists(), manager.snapshot())
                params = StdioServerParameters(command=sys.executable, args=[
                    "-m", "agentrelay", "mcp", "--db", str(database),
                    "--actor", "agent:proposal-reviewer"],
                    cwd=str(Path(__file__).resolve().parents[1]))
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as client:
                        await client.initialize()

                        async def call(name, arguments):
                            response = await client.call_tool(name, arguments)
                            self.assertFalse(response.isError, str(response))
                            return (response.structuredContent if response.structuredContent is not None
                                    else json.loads(response.content[0].text))

                        before = store.state()
                        live = await call("list_runs", {"ticket_id": ticket["id"], "limit": 1})
                        self.assertEqual(live["count"], 1)
                        self.assertEqual(live["runs"][0]["status"], "running")
                        self.assertFalse(live["runs"][0]["has_result"])
                        self.assertEqual(store.state(), before)
                        store.action("update_ticket", {
                            "id": ticket["id"], "expected_revision": 2,
                            "description": "Current instructions supersede the original worker input"})
                        (root / "release").write_text("continue", encoding="utf-8")
                        deadline = time.monotonic() + 8
                        while time.monotonic() < deadline:
                            if manager.snapshot()["runs"][0]["status"] != "running":
                                break
                            await asyncio.sleep(0.02)

                        before = store.state()
                        history = await call("list_runs", {
                            "ticket_id": ticket["id"], "status": "conflict", "limit": 1})
                        self.assertEqual(history["total"], 1)
                        selected = history["runs"][0]
                        self.assertTrue(selected["has_result"])
                        self.assertNotIn("result_json", selected)
                        self.assertNotIn("result", selected)
                        proposal = await call("get_run_result", {"run_id": selected["id"]})
                        current = await call("get_ticket_context", {"ticket_id": ticket["id"]})
                        self.assertEqual(proposal["result"]["summary"], "Propuesta descubierta: análisis ñ")
                        self.assertEqual(proposal["current_ticket"]["revision"], current["ticket"]["revision"])
                        self.assertGreater(current["ticket"]["revision"], proposal["run"]["claim_revision"])
                        self.assertEqual(current["ticket"]["status"], "in_progress")
                        self.assertEqual(current["ticket"]["evidence"], [])
                        self.assertEqual(store.state(), before)
                        self.assertEqual(len(store.execution_history()), 1)
            finally:
                manager.close()


if __name__ == "__main__":
    unittest.main()
