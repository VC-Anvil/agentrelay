"""The overview CLI reads configured projects without bootstrapping a default DB."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from agentrelay.store import Store


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = [{"kind": "file", "label": "Fixture result", "uri": "local://fixture"}]


class CliOverviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-cli-overview-")
        self.root = Path(self.temp.name)
        self.alpha = Store(self.root / "alpha.sqlite")
        self.beta = Store(self.root / "beta.sqlite")
        self.alpha.action("create_ticket", {"title": "Urgente alpha", "priority": "urgent",
            "acceptance": ["Alpha checked"]})
        review = self.beta.action("create_ticket", {"title": "Revisión beta", "priority": "high",
            "acceptance": ["Beta checked"]})
        review = self.beta.action("claim_ticket", {"id": review["id"],
            "expected_revision": review["revision"], "assignee": "agent:fixture"}, "agent:fixture")
        self.beta.action("submit_ticket", {"id": review["id"],
            "expected_revision": review["revision"], "summary": "Fixture for independent review",
            "evidence": EVIDENCE}, "agent:fixture")
        self.registry = self.root / "workspaces.json"
        self.registry.write_text(json.dumps({"default_workspace_id": "beta", "workspaces": [
            {"id": "alpha", "name": "Proyecto alfa", "db": "alpha.sqlite",
             "workers": "missing-workers.json"},
            {"id": "beta", "name": "Proyecto beta", "db": "beta.sqlite"},
        ]}, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def command(self, *args):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(PROJECT_ROOT)
        return subprocess.run([sys.executable, "-m", "agentrelay", "overview", *map(str, args)],
            cwd=self.root, env=environment, capture_output=True, text=True, encoding="utf-8",
            timeout=20)

    def test_two_projects_with_same_ticket_id_remain_separate_and_bounded(self):
        result = self.command("--workspaces", self.registry, "--limit", 1)
        self.assertEqual(result.returncode, 0, result.stderr)
        overview = json.loads(result.stdout)
        self.assertEqual(overview["schema_version"], 1)
        self.assertEqual(overview["default_workspace_id"], "beta")
        self.assertEqual(overview["count"], 2)
        self.assertEqual(overview["limit"], 1)
        projects = {project["id"]: project for project in overview["projects"]}
        self.assertEqual(set(projects), {"alpha", "beta"})
        self.assertEqual(projects["alpha"]["database"], str((self.root / "alpha.sqlite").resolve()))
        self.assertEqual(projects["beta"]["database"], str((self.root / "beta.sqlite").resolve()))
        self.assertEqual(projects["alpha"]["ready"]["tickets"][0]["id"], "AR-0001")
        self.assertEqual(projects["alpha"]["ready"]["tickets"][0]["title"], "Urgente alpha")
        self.assertEqual(projects["beta"]["review"]["tickets"][0]["id"], "AR-0001")
        self.assertEqual(projects["beta"]["review"]["tickets"][0]["title"], "Revisión beta")
        self.assertEqual(projects["alpha"]["urgent_open"], 1)
        self.assertEqual(projects["alpha"]["urgent"], {
            "total": 1,
            "tickets": [projects["alpha"]["ready"]["tickets"][0]],
        })
        self.assertEqual(projects["beta"]["urgent"], {"total": 0, "tickets": []})
        self.assertEqual(projects["beta"]["urgent_open"], 0)
        for project in projects.values():
            self.assertEqual(project["urgent_open"], project["urgent"]["total"])
            for category in ("urgent", "ready", "review", "blocked"):
                self.assertLessEqual(len(project[category]["tickets"]), 1)
                self.assertGreaterEqual(project[category]["total"], len(project[category]["tickets"]))
        self.assertFalse((self.root / ".agentrelay").exists())
        self.assertFalse((self.root / "missing-workers.json").exists())

        default_limit = self.command("--workspaces", self.registry)
        self.assertEqual(default_limit.returncode, 0, default_limit.stderr)
        self.assertEqual(json.loads(default_limit.stdout)["limit"], 5)

    def test_missing_registry_and_bad_limits_fail_without_default_database(self):
        for args in (("--workspaces", self.root / "missing.json"),
                     ("--workspaces", self.registry, "--limit", 0),
                     ("--workspaces", self.registry, "--limit", 21),
                     ("--workspaces", self.registry, "--limit", "fraction"),
                     ("--workspaces", self.registry, "--db", self.root / "wrong.sqlite"),
                     ("--workspaces", self.registry, "--workers", self.root / "workers.json")):
            with self.subTest(args=args):
                result = self.command(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertTrue(result.stderr.strip())
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse((self.root / ".agentrelay").exists())
                self.assertFalse((self.root / "wrong.sqlite").exists())

    def test_bad_second_database_has_no_partial_json_or_default_bootstrap(self):
        corrupt = self.root / "corrupt.sqlite"
        corrupt.write_bytes(b"not a sqlite database")
        registry = self.root / "corrupt-registry.json"
        registry.write_text(json.dumps({"workspaces": [
            {"id": "alpha", "name": "Alpha", "db": "alpha.sqlite"},
            {"id": "corrupt", "name": "Corrupt", "db": "corrupt.sqlite"},
        ]}), encoding="utf-8")
        result = self.command("--workspaces", registry)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr.strip())
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse((self.root / ".agentrelay").exists())


if __name__ == "__main__":
    unittest.main()
