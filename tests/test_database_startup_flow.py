"""A real CLI server can create a project and preserve HTTP-written work."""

from http.client import HTTPConnection
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
import threading
import unittest

from agentrelay.store import Store


class DatabaseStartupFlowTests(unittest.TestCase):
    def test_new_cli_server_accepts_work_and_existing_project_reopens(self):
        with tempfile.TemporaryDirectory(prefix="agentrelay-startup-flow-") as directory:
            database = Path(directory) / "new-project" / "workspace.sqlite"
            with tempfile.TemporaryFile() as errors:
                options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
                process = subprocess.Popen([sys.executable, "-X", "utf8", "-m", "agentrelay",
                    "serve", "--db", str(database), "--port", "0"],
                    stdout=subprocess.PIPE, stderr=errors, text=True, encoding="utf-8", **options)
                lines = queue.Queue()
                reader = threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True)
                reader.start()
                try:
                    try:
                        banner = lines.get(timeout=12)
                    except queue.Empty:
                        self.fail("CLI server did not announce startup")
                    matched = re.search(r"http://127\.0\.0\.1:(\d+)", banner)
                    if not matched:
                        errors.seek(0)
                        self.fail(f"No server URL: {banner!r}; {errors.read().decode('utf-8', 'replace')}")
                    port = int(matched[1])

                    def request(method, path, payload=None):
                        connection = HTTPConnection("127.0.0.1", port, timeout=10)
                        try:
                            connection.request(method, path, json.dumps(payload) if payload else None,
                                {"Content-Type": "application/json", "X-AgentRelay-Client": "browser"})
                            response = connection.getresponse()
                            return response.status, json.loads(response.read())
                        finally:
                            connection.close()

                    self.assertEqual(request("GET", "/api/health")[0], 200)
                    code, result = request("POST", "/api/actions", {"action": "create_ticket",
                        "data": {"title": "Created through running HTTP application",
                                 "acceptance": ["Reopen exact saved work"]}})
                    self.assertEqual(code, 200, result)
                    ticket = result["result"]
                    code, context = request("GET", f"/api/tickets/{ticket['id']}/context")
                    self.assertEqual(code, 200, context)
                    self.assertEqual(context["ticket"], ticket)
                finally:
                    if process.poll() is None:
                        if os.name == "nt":
                            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
                                creationflags=subprocess.CREATE_NO_WINDOW)
                        else:
                            process.terminate()
                    process.wait(timeout=10)
                    process.stdout.close()
                    reader.join(timeout=2)
            self.assertEqual(Store(database).context(ticket["id"])["ticket"], ticket)


if __name__ == "__main__":
    unittest.main()
