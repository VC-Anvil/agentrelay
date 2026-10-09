"""A real configured worker receives recent history without deleting older events."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

from agentrelay.execution import ExecutionManager
from agentrelay.store import Store


WORKER = """import json,sys
from pathlib import Path
packet=json.load(sys.stdin)
Path('received.json').write_text(json.dumps(packet),encoding='utf-8')
context=packet['context']
assert len(context['events'])==20
assert context['events_page']['total']==57
assert context['events_page']['next_before_id'] is not None
assert context['ticket']['status']=='in_progress'
json.dump({'outcome':'submit','summary':'Recent context inspected','evidence':[
 {'kind':'fixture','label':'Exact received packet','uri':str(Path('received.json').resolve())}]},sys.stdout)
"""


class WorkerHistoryTests(unittest.TestCase):
    def test_actual_worker_receives_recent_history_and_current_claim(self):
        with tempfile.TemporaryDirectory(prefix="agentrelay-worker-history-") as tmp:
            root = Path(tmp).resolve()
            store = Store(root / "work.sqlite")
            ticket = store.action("create_ticket", {"title": "History fixture", "acceptance": ["Inspect packet"]})
            for index in range(55):
                store.action("add_comment", {"id": ticket["id"], "body": f"Observation {index}"})
            script = root / "worker.py"
            script.write_text(WORKER, encoding="utf-8")
            config = root / "workers.json"
            config.write_text(json.dumps({"workers": [{
                "id": "fixture", "name": "Fixture", "command": [sys.executable, str(script)],
                "cwd": str(root), "model": "fixture", "effort": "none", "profile_ids": [], "timeout_seconds": 10
            }]}), encoding="utf-8")
            manager = ExecutionManager(store, config)
            try:
                run = manager.start(ticket["id"], "fixture", ticket["revision"])
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    run = next(r for r in manager.snapshot()["runs"] if r["id"] == run["id"])
                    if run["status"] != "running":
                        break
                    time.sleep(0.05)
                self.assertEqual(run["status"], "submitted", run)
                received = json.loads((root / "received.json").read_text(encoding="utf-8"))["context"]
                self.assertEqual(received["events"][0]["action"], "claim_ticket")
                self.assertEqual(received["ticket"]["revision"], 2)
                self.assertEqual(store.context(ticket["id"])["ticket"]["status"], "review")
                self.assertEqual(len(store.context(ticket["id"])["events"]), 58)
                self.assertEqual(len(store.export()["events"]), 58)
            finally:
                manager.close()
