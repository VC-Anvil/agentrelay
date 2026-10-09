"""Exercise the browser API through a real loopback HTTP connection."""

import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path

from agentrelay.server import AppServer
from agentrelay.store import Store


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-http-")
        self.store = Store(Path(self.temp.name) / "http.sqlite")
        self.server = AppServer(("127.0.0.1", 0), self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.temp.cleanup()

    def request(self, method, path, data=None, headers=None):
        conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        actual = {"Content-Type": "application/json", "X-AgentRelay-Client": "browser"}
        actual.update(headers or {})
        conn.request(method, path, json.dumps(data) if data is not None else None, actual)
        response = conn.getresponse()
        result = response.status, response.read(), dict(response.getheaders())
        conn.close()
        return result

    def test_browser_write_conflict_context_and_export(self):
        status, body, _ = self.request("POST", "/api/actions", {"action": "create_ticket", "data": {
            "title": "Persist across restart", "description": "HTTP exercise", "acceptance": ["Reload works"]}})
        self.assertEqual(status, 200, body)
        ticket = json.loads(body)["result"]
        self.assertFalse(json.loads(body)["state"]["demo"])
        status, body, _ = self.request("POST", "/api/actions", {"action": "update_ticket", "data": {
            "id": ticket["id"], "expected_revision": 1, "priority": "urgent"}})
        self.assertEqual(status, 200, body)
        status, body, _ = self.request("POST", "/api/actions", {"action": "update_ticket", "data": {
            "id": ticket["id"], "expected_revision": 1, "title": "Stale writer"}})
        self.assertEqual(status, 409, body)
        status, body, _ = self.request("GET", f"/api/tickets/{ticket['id']}/context")
        self.assertEqual(json.loads(body)["ticket"]["priority"], "urgent")
        self.assertEqual(Store(self.store.path).context(ticket["id"])["ticket"]["title"], "Persist across restart")
        status, body, headers = self.request("GET", "/api/export")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(len(json.loads(body)["tickets"]), 1)

    def test_rejects_cross_origin_host_spoofing_actor_and_path_escape(self):
        action = {"action": "create_ticket", "data": {"title": "Attack"}}
        for headers in ({"Origin": "https://example.org"}, {"Host": "evil.test"},
                        {"X-AgentRelay-Client": ""}, {"Sec-Fetch-Site": "cross-site"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request("POST", "/api/actions", action, headers)[0], 403)
        self.assertEqual(self.request("POST", "/api/actions", {**action, "actor": "agent:spoof"})[0], 403)
        self.assertEqual(self.request("GET", "/%2e%2e/README.md")[0], 404)
        self.assertEqual(self.store.state()["tickets"], [])

    def test_plan_retry_and_conflict_are_visible_through_http(self):
        request = {"action": "create_plan", "data": {"request_id": "browser-plan", "tickets": [
            {"key": "child", "title": "Review inputs", "parent_key": "objective"},
            {"key": "objective", "title": "Review project", "type": "objective"}]}}
        status, body, _ = self.request("POST", "/api/actions", request)
        self.assertEqual(status, 200, body)
        created = json.loads(body)
        self.assertEqual(len(created["state"]["tickets"]), 2)
        self.assertTrue(all(t["status"] == "backlog" for t in created["state"]["tickets"]))
        status, body, _ = self.request("POST", "/api/actions", request)
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["result"], created["result"])
        self.assertEqual(len(json.loads(body)["state"]["events"]), 3)
        request["data"]["tickets"][0]["title"] = "Different task"
        status, body, _ = self.request("POST", "/api/actions", request)
        self.assertEqual(status, 409, body)
        self.assertEqual(len(self.store.state()["tickets"]), 2)

    def test_malformed_request_and_missing_ticket_are_actionable(self):
        self.assertEqual(self.request("POST", "/api/actions", [1, 2])[0], 400)
        status, body, _ = self.request("GET", "/api/tickets/AR-9999/context")
        self.assertEqual(status, 404, body)
        self.assertIn("error", json.loads(body))
        self.assertEqual(self.request("GET", "/api/health")[0], 200)


if __name__ == "__main__":
    unittest.main()
