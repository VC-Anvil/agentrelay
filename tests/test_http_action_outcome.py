"""An action that committed must not be reported as a rejected request."""

import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest import mock

from agentrelay.server import AppServer
from agentrelay.store import DomainError, Store


class HTTPActionOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-http-outcome-")
        self.store = Store(Path(self.temp.name) / "outcome.sqlite")
        self.server = AppServer(("127.0.0.1", 0), self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.temp.cleanup()

    def post(self, payload):
        conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            conn.request("POST", "/api/actions", json.dumps(payload), {
                "Content-Type": "application/json",
                "X-AgentRelay-Client": "browser",
            })
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def test_snapshot_value_error_after_commit_is_500_and_ticket_persists(self):
        with mock.patch.object(self.server, "snapshot", side_effect=ValueError("snapshot value failure")):
            with mock.patch("agentrelay.server.logging.exception"):
                status, body = self.post({"action": "create_ticket", "data": {"title": "Committed before snapshot"}})

        self.assertEqual(status, 500, body)
        self.assertEqual(body, {"error": "Error interno. Revisa el registro local."})
        tickets = self.store.state()["tickets"]
        self.assertEqual([(ticket["id"], ticket["title"]) for ticket in tickets],
                         [("AR-0001", "Committed before snapshot")])

    def test_snapshot_domain_conflict_after_commit_is_500_and_ticket_persists(self):
        with mock.patch.object(self.server, "snapshot", side_effect=DomainError("snapshot conflict", 409)):
            with mock.patch("agentrelay.server.logging.exception"):
                status, body = self.post({"action": "create_ticket", "data": {"title": "Also committed"}})

        self.assertEqual(status, 500, body)
        self.assertEqual(body, {"error": "Error interno. Revisa el registro local."})
        self.assertEqual([ticket["title"] for ticket in self.store.state()["tickets"]], ["Also committed"])

    def test_response_serialization_error_after_commit_is_500_and_ticket_persists(self):
        original_dumps = json.dumps
        response_attempts = []

        def fail_success_response(value, *args, **kwargs):
            if isinstance(value, dict) and "result" in value and "state" in value:
                response_attempts.append(True)
                raise ValueError("response serialization failed after commit")
            return original_dumps(value, *args, **kwargs)

        with mock.patch("agentrelay.server.json.dumps", side_effect=fail_success_response):
            with mock.patch("agentrelay.server.logging.exception"):
                status, body = self.post({"action": "create_ticket", "data": {"title": "Serialized too late"}})

        self.assertEqual(response_attempts, [True])
        self.assertEqual(status, 500, body)
        self.assertEqual(body, {"error": "Error interno. Revisa el registro local."})
        self.assertEqual([ticket["title"] for ticket in self.store.state()["tickets"]], ["Serialized too late"])

    def test_malformed_payload_stays_400_without_write(self):
        before = self.store.state()
        status, body = self.post([1, 2])
        self.assertEqual(status, 400, body)
        self.assertEqual(self.store.state()["tickets"], before["tickets"])
        self.assertEqual(self.store.state()["events"], before["events"])

    def test_domain_conflict_before_result_stays_409_without_new_write(self):
        created_status, created_body = self.post({"action": "create_ticket", "data": {"title": "Queued ticket"}})
        self.assertEqual(created_status, 200, created_body)
        ticket_id = created_body["result"]["id"]
        before = self.store.state()

        status, body = self.post({"action": "claim_ticket", "data": {
            "id": ticket_id, "expected_revision": 2, "assignee": "human",
            "actual_model": "unknown", "actual_effort": "unknown",
        }})

        self.assertEqual(status, 409, body)
        self.assertNotEqual(body["error"], "Error interno. Revisa el registro local.")
        after = self.store.state()
        self.assertEqual(after["tickets"], before["tickets"])
        self.assertEqual(after["events"], before["events"])


if __name__ == "__main__":
    unittest.main()
