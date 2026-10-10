"""Scoped claim receipts stay within the selected HTTP project."""

from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import unittest

from agentrelay.server import AppServer
from agentrelay.store import Store
from agentrelay.workspaces import Workspace


class HTTPClaimNextTests(unittest.TestCase):
    def test_same_request_and_ticket_ids_are_project_scoped_and_replay_is_historical(self):
        with tempfile.TemporaryDirectory(prefix="agentrelay-http-claim-") as directory:
            stores = {key: Store(Path(directory) / f"{key}.sqlite") for key in ("alpha", "beta")}
            for key, store in stores.items():
                store.action("create_ticket", {"title": key, "acceptance": ["Review evidence"]})
            spaces = {key: Workspace(key, key, store) for key, store in stores.items()}
            server = AppServer(("127.0.0.1", 0), stores["alpha"], workspaces=spaces,
                               default_workspace_id="alpha")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            data = {"request_id": "same-id-in-two-projects",
                    "candidates": [{"ticket_id": "AR-0001", "expected_revision": 1}],
                    "assignee": "agent:fixture", "actual_model": "unknown", "actual_effort": "unknown"}

            def request(workspace, payload=data):
                headers = {"Content-Type": "application/json", "X-AgentRelay-Client": "browser"}
                if workspace is not None:
                    headers["X-AgentRelay-Workspace"] = workspace
                connection = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
                try:
                    connection.request("POST", "/api/actions", json.dumps({
                        "action": "claim_next_ticket", "data": payload}), headers)
                    response = connection.getresponse()
                    return response.status, json.loads(response.read())
                finally:
                    connection.close()

            try:
                beta_before = stores["beta"].state()
                self.assertEqual(request(None)[0], 400)
                code, first = request("alpha")
                self.assertEqual(code, 200, first)
                self.assertEqual(first["result"]["ticket"]["title"], "alpha")
                self.assertEqual(stores["beta"].state(), beta_before)
                self.assertFalse(first["state"]["execution"]["enabled"])
                claimed = first["result"]["ticket"]
                current = stores["alpha"].action("checkpoint", {"id": claimed["id"],
                    "expected_revision": claimed["revision"], "checkpoint": "Evidence inspected"},
                    actor="agent:fixture")
                code, replay = request("alpha")
                self.assertEqual(code, 200, replay)
                self.assertEqual(replay["result"], first["result"])
                self.assertEqual(replay["state"]["tickets"][0]["revision"], current["revision"])
                self.assertNotEqual(replay["result"]["ticket"]["revision"], current["revision"])
                code, other_project = request("beta")
                self.assertEqual(code, 200, other_project)
                self.assertEqual(other_project["result"]["ticket"]["title"], "beta")
                before_conflict = stores["alpha"].state()
                self.assertEqual(request("alpha", {**data, "actual_model": "changed"})[0], 409)
                self.assertEqual(stores["alpha"].state(), before_conflict)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(3)


if __name__ == "__main__":
    unittest.main()
