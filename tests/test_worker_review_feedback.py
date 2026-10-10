"""A restarted worker receives corrections even outside recent audit history."""

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
context=packet['context']
Path('received.json').write_text(json.dumps(context),encoding='utf-8')
feedback=context['review_feedback']
assert feedback['reason']=='Distinguish unknown evidence from absent implementation'
assert feedback['reviewer']=='agent:reviewer'
assert not feedback['submission_after_request']
assert not feedback['completion_after_request']
assert feedback['event_id'] not in [e['id'] for e in context['events']]
assert context['ticket']['checkpoint']=='Original report, not silently overwritten'
assert context['ticket']['evidence'][0]['uri']=='local://original'
json.dump({'outcome':'submit','summary':'Corrected documentary interpretation',
 'evidence':[{'kind':'fixture','label':'Corrected report','uri':'local://corrected'}]},sys.stdout)
"""


class WorkerReviewFeedbackTests(unittest.TestCase):
    def test_actual_worker_receives_old_feedback_without_losing_delivery(self):
        with tempfile.TemporaryDirectory(prefix="agentrelay-review-feedback-") as temp:
            root = Path(temp).resolve()
            store = Store(root / "project.sqlite")
            ticket = store.action("create_ticket", {"title": "Documentary correction",
                "acceptance": ["Accurate interpretation"]})
            ticket = store.action("claim_ticket", {"id": ticket["id"],
                "expected_revision": ticket["revision"], "assignee": "agent:author",
                "actual_model": "unknown", "actual_effort": "unknown"}, actor="agent:author")
            ticket = store.action("submit_ticket", {"id": ticket["id"],
                "expected_revision": ticket["revision"],
                "summary": "Original report, not silently overwritten",
                "evidence": [{"kind": "fixture", "label": "Original", "uri": "local://original"}]},
                actor="agent:author")
            returned = store.action("request_changes", {"id": ticket["id"],
                "expected_revision": ticket["revision"],
                "reason": "Distinguish unknown evidence from absent implementation"}, actor="agent:reviewer")
            for number in range(25):
                store.action("add_comment", {"id": ticket["id"], "body": f"Later observation {number}"})
            script = root / "worker.py"
            script.write_text(WORKER, encoding="utf-8")
            config = root / "workers.json"
            config.write_text(json.dumps({"workers": [{"id": "fixture", "name": "Fixture",
                "command": [sys.executable, str(script)], "cwd": str(root), "model": "fixture",
                "effort": "none", "profile_ids": [], "timeout_seconds": 10}]}), encoding="utf-8")
            manager = ExecutionManager(store, config)
            try:
                run = manager.start(ticket["id"], "fixture", returned["revision"])
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    current = next(r for r in manager.snapshot()["runs"] if r["id"] == run["id"])
                    if current["status"] != "running":
                        break
                    time.sleep(0.05)
                self.assertEqual(current["status"], "submitted", current)
                received = json.loads((root / "received.json").read_text(encoding="utf-8"))
                self.assertEqual(received["review_feedback"]["returned_revision"], returned["revision"])
                context = store.context(ticket["id"], event_limit=1)
                self.assertEqual(context["ticket"]["status"], "review")
                self.assertTrue(context["review_feedback"]["submission_after_request"])
                self.assertFalse(context["review_feedback"]["completion_after_request"])
                submissions = [e for e in store.context(ticket["id"])["events"] if e["action"] == "submit_ticket"]
                self.assertEqual(len(submissions), 2)
                self.assertTrue(any(e["details"]["evidence"][0]["uri"] == "local://original" for e in submissions))
            finally:
                manager.close()


if __name__ == "__main__":
    unittest.main()
