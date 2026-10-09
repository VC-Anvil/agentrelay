"""A project overview can inspect a database owned by a live execution manager."""

import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

from agentrelay.execution import ExecutionManager
from agentrelay.overview import project_overview
from agentrelay.store import Store


WORKER = """import json,sys,time
from pathlib import Path
json.load(sys.stdin)
Path('ready').write_text('waiting',encoding='utf-8')
deadline=time.monotonic()+15
while not Path('release').exists():
 if time.monotonic()>deadline:
  raise RuntimeError('fixture was not released')
 time.sleep(0.02)
json.dump({'outcome':'submit','summary':'Fixture resumed normally','evidence':[
 {'kind':'fixture','label':'Process result','uri':'fixture://result'}]},sys.stdout)
"""


class RunningOverviewTests(unittest.TestCase):
    def test_overview_preserves_live_worker_then_original_manager_finishes(self):
        with tempfile.TemporaryDirectory(prefix="agentrelay-running-overview-") as directory:
            root = Path(directory).resolve()
            store = Store(root / "workspace.sqlite")
            ticket = store.action("create_ticket", {
                "title": "Running fixture", "acceptance": ["Review process output"]})
            script = root / "worker.py"
            script.write_text(WORKER, encoding="utf-8")
            config = root / "workers.json"
            config.write_text(json.dumps({"workers": [{
                "id": "fixture", "name": "Fixture", "command": [sys.executable, str(script)],
                "cwd": str(root), "model": "fixture-model", "effort": "none",
                "profile_ids": [], "timeout_seconds": 20,
            }]}), encoding="utf-8")
            registry = root / "workspaces.json"
            registry.write_text(json.dumps({"workspaces": [{
                "id": "active", "name": "Active fixture", "db": "workspace.sqlite",
                "workers": "workers.json",
            }]}), encoding="utf-8")
            manager = ExecutionManager(store, config)
            try:
                run = manager.start(ticket["id"], "fixture", ticket["revision"])
                deadline = time.monotonic() + 8
                while not (root / "ready").exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue((root / "ready").exists(), manager.snapshot())
                before = store.state()

                overview = project_overview(registry, limit=1)

                after = store.state()
                for key in ("tickets", "profiles", "events", "runs"):
                    self.assertEqual(after[key], before[key])
                self.assertEqual(after["runs"][0]["status"], "running")
                self.assertEqual(overview["projects"][0]["stats"]["by_status"]["in_progress"], 1)
                self.assertEqual(overview["projects"][0]["ready"]["total"], 0)

                (root / "release").write_text("continue", encoding="utf-8")
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    result = next(item for item in manager.snapshot()["runs"] if item["id"] == run["id"])
                    if result["status"] != "running":
                        break
                    time.sleep(0.02)
                self.assertEqual(result["status"], "submitted", result)
                self.assertEqual(store.context(ticket["id"])["ticket"]["status"], "review")
            finally:
                manager.close()


if __name__ == "__main__":
    unittest.main()
