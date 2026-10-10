"""Exercise the shipped deterministic handoff script as a real local process."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from agentrelay.run_results import get_run_result
from agentrelay.store import Store


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "examples" / "handoff_demo.py"


class HandoffExampleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-handoff-example-")
        self.root = Path(self.temp.name)
        self.output = self.root / "handoff"
        self.environment = os.environ.copy()
        existing = self.environment.get("PYTHONPATH")
        self.environment["PYTHONPATH"] = (str(PROJECT_ROOT) if not existing else
                                           str(PROJECT_ROOT) + os.pathsep + existing)
        self.environment["PYTHONUTF8"] = "1"
        self.environment["PYTHONIOENCODING"] = "utf-8"

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                              cwd=self.root, env=self.environment,
                              capture_output=True, text=True, encoding="utf-8", timeout=35)

    @staticmethod
    def files(directory):
        return {str(path.relative_to(directory)): path.read_bytes() for path in directory.rglob("*")
                if path.is_file()}

    def test_full_help_return_correction_parent_resume_backup_and_refusal(self):
        process = self.invoke("--output", self.output)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("Simulación completada", process.stdout)
        result = json.loads((self.output / "result.json").read_text(encoding="utf-8"))
        self.assertEqual((result["schema_version"], result["simulation"]), (1, True))
        self.assertEqual({key: Path(value) for key, value in result["paths"].items()}, {
            "database": self.output / "workspace.sqlite", "workers": self.output / "workers.json",
            "backup": self.output / "backup.sqlite", "report": self.output / "report.md",
            "result": self.output / "result.json",
        })
        self.assertEqual({key: value["status"] for key, value in result["tickets"].items()},
                         {"parent": "done", "help": "done"})
        self.assertEqual(result["tickets"]["help"]["priority"], "urgent")
        self.assertEqual(set(result["runs"]), {"help_initial", "help_corrected", "parent"})
        self.assertTrue(all(run["status"] == "submitted" for run in result["runs"].values()))
        self.assertEqual(len({run["id"] for run in result["runs"].values()}), 3)
        workers = json.loads((self.output / "workers.json").read_text(encoding="utf-8"))["workers"]
        self.assertEqual({worker["model"] for worker in workers}, {"fixture-python"})
        self.assertEqual({worker["effort"] for worker in workers}, {"none"})
        self.assertTrue(all(worker["command"][:2] == [sys.executable, str(SCRIPT)]
                            and worker["command"][2] == "--fixture-worker" for worker in workers))

        store = Store(self.output / "workspace.sqlite")
        backup = Store(self.output / "backup.sqlite")
        child_id = result["tickets"]["help"]["id"]
        parent_id = result["tickets"]["parent"]["id"]
        child = store.context(child_id)
        parent = store.context(parent_id)
        self.assertEqual(child["ticket"]["parent_id"], parent_id)
        self.assertEqual(child["ticket"]["priority"], parent["ticket"]["priority"])
        self.assertEqual(child["ticket"]["profile_id"], parent["ticket"]["profile_id"])
        self.assertEqual(child["review_feedback"]["reason"], result["review"]["reason"])
        self.assertEqual(child["review_feedback"]["reviewer"], result["review"]["reviewer"])
        self.assertEqual(child["review_feedback"]["event_id"], result["review"]["feedback_event_id"])
        self.assertTrue(child["review_feedback"]["submission_after_request"])
        self.assertTrue(child["review_feedback"]["completion_after_request"])
        self.assertEqual(sum(event["action"] == "submit_ticket" for event in child["events"]), 2)
        self.assertEqual(sum(event["action"] == "request_changes" for event in child["events"]), 1)
        self.assertEqual([event["actor"] for event in child["events"]
                          if event["action"] in {"request_changes", "complete_ticket"}],
                         ["agent:independent-reviewer", "agent:independent-reviewer"])
        parent_events = parent["events"]
        self.assertEqual(sum(event["action"] == "request_help" for event in parent_events), 1)
        resume = next(event for event in parent_events if event["action"] == "transition"
                      and event["details"]["to"] == "queued")
        self.assertEqual(resume["actor"], result["review"]["parent_requeued_by"])
        self.assertLess(next(event["id"] for event in child["events"]
                             if event["action"] == "complete_ticket"), resume["id"])
        self.assertEqual(next(event["actor"] for event in parent_events
                              if event["action"] == "complete_ticket"), "agent:independent-reviewer")

        reports = {}
        for name, run in result["runs"].items():
            original = get_run_result(store, run["id"])
            restored = get_run_result(backup, run["id"])
            self.assertEqual(original["result"], restored["result"])
            self.assertEqual(original["run"]["status"], "submitted")
            report = original["result"]["artifact_markdown"]
            self.assertIn("simulad", report.lower())
            self.assertEqual(hashlib.sha256(report.encode("utf-8")).hexdigest(), run["report_sha256"])
            reports[name] = report
        self.assertNotIn("23 MHz", reports["help_initial"])
        self.assertIn("23 MHz", reports["help_corrected"])
        self.assertIn(child_id, reports["parent"])
        self.assertIn("23 MHz", reports["parent"])
        self.assertIn(result["runs"]["help_initial"]["id"],
                      (self.output / "report.md").read_text(encoding="utf-8"))

        old_export = store.export()
        backup_export = backup.export()
        for key in ("tickets", "profiles", "events", "runs", "demo"):
            self.assertEqual(old_export[key], backup_export[key], key)

        before = self.files(self.output)
        rejected = self.invoke("--output", self.output)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("already exists", rejected.stderr)
        self.assertEqual(self.files(self.output), before)

    def test_no_output_argument_does_not_create_default_state(self):
        before = self.files(self.root)
        process = self.invoke()
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("--output", process.stderr)
        self.assertEqual(self.files(self.root), before)


if __name__ == "__main__":
    unittest.main()
