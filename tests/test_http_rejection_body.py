"""Early HTTP rejection drains only a bounded framed body, without accepting work."""
from email.message import Message
from http.client import HTTPConnection
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from agentrelay.server import AppServer, Handler, MAX_BODY
from agentrelay.store import Store


class RejectedBodyTests(unittest.TestCase):
    def handler(self, headers=None, body=b"not even JSON", command="POST"):
        handler = object.__new__(Handler)
        handler.command = command
        handler.server = SimpleNamespace(server_port=8787)
        handler.headers = Message()
        actual = {"Host": "127.0.0.1:8787", "Content-Type": "application/json",
                  "X-AgentRelay-Client": "browser", "Content-Length": str(len(body))}
        actual.update(headers or {})
        for name, value in actual.items():
            handler.headers[name] = value
        handler.rfile = BytesIO(body)
        handler.connection = Mock()
        handler.connection.gettimeout.return_value = 4
        replies = []
        handler._json = lambda status, value: replies.append((status, value, handler.rfile.tell()))
        return handler, replies

    def test_each_header_rejection_consumes_exact_body_before_error(self):
        for headers, status in (({"Host": "evil.test"}, 403),
                ({"Origin": "https://example.org"}, 403),
                ({"Sec-Fetch-Site": "cross-site"}, 403),
                ({"X-AgentRelay-Client": ""}, 403),
                ({"Content-Type": "text/plain"}, 415)):
            with self.subTest(headers=headers):
                handler, replies = self.handler(headers, body=b"bad JSONsuffix")
                handler.headers.replace_header("Content-Length", "8")
                self.assertFalse(handler._write_ok())
                self.assertEqual(replies[0][0], status)
                self.assertEqual(replies[0][2], 8)
                self.assertEqual(handler.rfile.read(), b"suffix")
                handler.connection.settimeout.assert_called_with(4)

    def test_unframed_oversized_ambiguous_and_get_bodies_are_not_read(self):
        for headers in ({"Content-Length": str(MAX_BODY + 1)}, {"Content-Length": "-1"},
                {"Content-Length": "invalid"}, {"Content-Length": "9" * 100},
                {"Content-Length": "0"}, {"Content-Length": ""},
                {"Transfer-Encoding": "chunked"}):
            with self.subTest(headers=headers):
                handler, replies = self.handler(headers)
                handler._reject_unread(403, "Denied")
                self.assertEqual(replies, [(403, {"error": "Denied"}, 0)])
                handler.connection.settimeout.assert_not_called()
        handler, replies = self.handler(command="GET")
        handler._reject_unread(403, "Denied")
        self.assertEqual(replies[0][2], 0)
        handler, replies = self.handler()
        handler.headers['Content-Length'] = '4'
        handler._reject_unread(403, "Denied")
        self.assertEqual(replies[0][2], 0)

    def test_total_deadline_eof_and_socket_error_preserve_rejection(self):
        handler, replies = self.handler(body=b"abcdef")
        original = handler.rfile
        handler.rfile = Mock()
        handler.rfile.read1.side_effect = lambda size: original.read(1)
        handler.rfile.tell.side_effect = original.tell
        with patch('agentrelay.server.time.monotonic', side_effect=[0, 0, 2]):
            handler._reject_unread(403, "Denied")
        self.assertEqual(replies[0][2], 1)
        handler.connection.settimeout.assert_called_with(4)
        for outcome in (b"", TimeoutError("fixture timeout")):
            handler, replies = self.handler()
            if isinstance(outcome, Exception):
                handler.rfile = Mock(read1=Mock(side_effect=outcome), tell=Mock(return_value=0))
            else:
                handler.rfile = BytesIO()
            handler._reject_unread(403, "Denied")
            self.assertEqual(replies[0][0], 403)
            handler.connection.settimeout.assert_called_with(4)

    def test_real_delayed_post_body_receives_error_and_never_creates_work(self):
        with tempfile.TemporaryDirectory(prefix="agentrelay-reject-body-") as directory:
            store = Store(Path(directory) / 'workspace.sqlite')
            server = AppServer(('127.0.0.1', 0), store)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for extra in ({'Host': 'evil.test'}, {'X-AgentRelay-Client': ''}):
                    conn = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                    try:
                        body = b'{"action":"create_ticket","data":{"title":"Rejected"}}'
                        conn.putrequest('POST', '/api/actions', skip_host=True)
                        headers = {'Host': f'127.0.0.1:{server.server_port}',
                            'X-AgentRelay-Client': 'browser', 'Content-Type': 'application/json',
                            'Content-Length': str(len(body)), **extra}
                        for name, value in headers.items():
                            conn.putheader(name, value)
                        conn.endheaders()
                        time.sleep(.02)
                        conn.send(body)
                        response = conn.getresponse()
                        self.assertEqual(response.status, 403)
                        self.assertIn(b'error', response.read())
                    finally:
                        conn.close()
                self.assertEqual(store.state()['tickets'], [])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(2)


if __name__ == '__main__':
    unittest.main()
