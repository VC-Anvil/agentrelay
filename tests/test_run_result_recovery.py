"""Recover one real process proposal without replaying stale ticket mutations."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from agentrelay.execution import ExecutionManager
from agentrelay.store import DomainError, Store


WORKER = """import json,sys,time
from pathlib import Path
json.load(sys.stdin)
Path('ready').write_text('waiting',encoding='utf-8')
deadline=time.monotonic()+15
while not Path('release').exists():
 if time.monotonic()>deadline:
  raise RuntimeError('fixture was not released')
 time.sleep(0.02)
json.dump({'outcome':'submit','summary':'Propuesta recuperable: revisión ñ',
 'evidence':[{'kind':'fixture','label':'Process output','uri':'fixture://result'}]},
 sys.stdout,ensure_ascii=False)
"""


class RunResultRecoveryTests(unittest.TestCase):
    def test_cli_reads_live_run_then_recovers_conflict_for_explicit_review(self):
        with tempfile.TemporaryDirectory(prefix="agentrelay-recovery-") as directory:
            root = Path(directory).resolve()
            database = root / "workspace.sqlite"
            store = Store(database)
            ticket = store.action("create_ticket", {
                "title": "Recover a proposal", "acceptance": ["Review the output"]})
            script = root / "worker.py"
            script.write_text(WORKER, encoding="utf-8")
            config = root / "workers.json"
            config.write_text(json.dumps({"workers": [{
                "id": "fixture", "name": "Fixture", "command": [sys.executable, str(script)],
                "cwd": str(root), "model": "fixture-model", "effort": "none",
                "profile_ids": [], "timeout_seconds": 20,
            }]}), encoding="utf-8")
            manager = ExecutionManager(store, config)
            try:
                run = manager.start(ticket["id"], "fixture", ticket["revision"])
                deadline = time.monotonic() + 8
                while not (root / "ready").exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue((root / "ready").exists(), manager.snapshot())

                def read_proposal():
                    process = subprocess.run([
                        sys.executable, "-m", "agentrelay", "run-result", "--db",
                        str(database), "--run", run["id"],
                    ], cwd=Path(__file__).resolve().parents[1], capture_output=True,
                        text=True, encoding="utf-8", timeout=8)
                    self.assertEqual(process.returncode, 0, process.stderr)
                    return json.loads(process.stdout)

                before = store.state()
                live = read_proposal()
                self.assertEqual(live["run"]["status"], "running")
                self.assertIsNone(live["result"])
                self.assertEqual(store.state(), before)

                edited = store.action("update_ticket", {
                    "id": ticket["id"], "expected_revision": live["current_ticket"]["revision"],
                    "description": "Concurrent clarification must survive recovery"})
                (root / "release").write_text("continue", encoding="utf-8")
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    finished = next(item for item in manager.snapshot()["runs"] if item["id"] == run["id"])
                    if finished["status"] != "running":
                        break
                    time.sleep(0.02)
                self.assertEqual(finished["status"], "conflict", finished)
                before = store.state()
                recovered = read_proposal()
                self.assertEqual(store.state(), before)
                self.assertEqual(recovered["current_ticket"]["revision"], edited["revision"])
                self.assertEqual(recovered["result"]["summary"], "Propuesta recuperable: revisión ñ")

                # Reading the proposal grants no permission to apply the old revision.
                submission = {"id": ticket["id"], "expected_revision": recovered["run"]["claim_revision"],
                              "summary": recovered["result"]["summary"],
                              "evidence": recovered["result"]["evidence"]}
                with self.assertRaises(DomainError) as caught:
                    store.action("submit_ticket", submission, actor="human")
                self.assertEqual(caught.exception.status, 409)
                current = store.context(ticket["id"])["ticket"]
                self.assertEqual(current["description"], edited["description"])
                self.assertEqual(current["status"], "in_progress")

                # A separate reviewer of this fixture consciously reuses its output.
                # Production callers must assess relevance against the complete context.
                submission["expected_revision"] = current["revision"]
                reviewed = store.action("submit_ticket", submission, actor="human")
                self.assertEqual(reviewed["status"], "review")
                self.assertEqual(reviewed["description"], edited["description"])
                self.assertEqual(len(store.execution_history()), 1)
                after = read_proposal()
                self.assertEqual(after["run"]["status"], "conflict")
                self.assertEqual(after["result"], recovered["result"])
                self.assertEqual(after["current_ticket"]["status"], "review")
            finally:
                manager.close()


if __name__ == "__main__":
    unittest.main()
