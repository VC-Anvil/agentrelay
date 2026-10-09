"""Exercise the installed-style command boundary, including conflict behavior."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-cli-")
        self.root = Path(self.temp.name)
        self.db = self.root / "workspace.sqlite"

    def tearDown(self):
        self.temp.cleanup()

    def command(self, *args):
        return subprocess.run([sys.executable, "-m", "agentrelay", *map(str, args)],
                              capture_output=True, text=True, encoding="utf-8", timeout=20)

    def action(self, name, data, actor="human"):
        request = self.root / "request.json"
        request.write_text(json.dumps({"action": name, "data": data}), encoding="utf-8")
        return self.command("action", "--db", self.db, "--actor", actor, "--input", request)

    def test_ticket_action_context_and_conflict_preserve_owner(self):
        result = self.action("create_ticket", {"title": "Revisión", "acceptance": ["Verify source"]})
        self.assertEqual(result.returncode, 0, result.stderr)
        ticket = json.loads(result.stdout)
        data = {"id": ticket["id"], "expected_revision": ticket["revision"],
                "assignee": "agent:worker"}
        claimed = self.action("claim_ticket", data, "agent:worker")
        self.assertEqual(claimed.returncode, 0, claimed.stderr)
        stale = self.action("update_ticket", {"id": ticket["id"],
                            "expected_revision": ticket["revision"], "title": "Stale edit"})
        self.assertNotEqual(stale.returncode, 0)
        context = self.command("context", "--db", self.db, "--ticket", ticket["id"])
        self.assertEqual(context.returncode, 0, context.stderr)
        current = json.loads(context.stdout)["ticket"]
        self.assertEqual(current["title"], "Revisión")
        self.assertEqual(current["assignee"], "agent:worker")

    def test_invalid_envelope_does_not_create_database(self):
        request = self.root / "bad.json"
        for value in ([], {"action": "create_ticket", "data": {}, "actor": "agent:spoof"}):
            request.write_text(json.dumps(value), encoding="utf-8")
            result = self.command("action", "--db", self.db, "--actor", "human", "--input", request)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(self.db.exists())

    def test_example_plan_retries_after_restart_and_backup(self):
        example = Path(__file__).resolve().parents[1] / "examples" / "plan.json"
        request = json.loads(example.read_text(encoding="utf-8"))
        first = self.action(request["action"], request["data"], "agent:planner")
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.action(request["action"], request["data"], "agent:planner")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(first.stdout), json.loads(second.stdout))
        backup = self.root / "backup.sqlite"
        saved = self.command("backup", "--db", self.db, "--output", backup)
        self.assertEqual(saved.returncode, 0, saved.stderr)
        restored = self.command("action", "--db", backup, "--actor", "agent:planner", "--input", example)
        self.assertEqual(restored.returncode, 0, restored.stderr)
        self.assertEqual(json.loads(first.stdout), json.loads(restored.stdout))

    def test_snapshot_commands_do_not_create_default_database(self):
        source = self.root / "source"
        source.mkdir()
        (source / "notes.txt").write_bytes(b"exact\r\nbytes\n")
        destination = self.root / "captured"
        result = self.command("snapshot", "--root", source, "--file", "notes.txt", "--output", destination)
        self.assertEqual(result.returncode, 0, result.stderr)
        verified = self.command("verify-snapshot", destination)
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertTrue(json.loads(verified.stdout)["valid"])
        compared = self.command("compare-snapshot", destination, "--root", source)
        self.assertEqual(compared.returncode, 0, compared.stderr)
        self.assertEqual(json.loads(compared.stdout)["summary"]["unchanged"], 1)
        (source / "notes.txt").write_bytes(b"current source differs")
        compared = self.command("compare-snapshot", destination, "--root", source)
        self.assertEqual(compared.returncode, 2, compared.stderr)
        self.assertEqual(json.loads(compared.stdout)["summary"]["modified"], 1)
        self.assertNotEqual(self.command("compare-snapshot", destination).returncode, 0)
        (destination / "files" / "notes.txt").write_bytes(b"changed")
        self.assertNotEqual(self.command("verify-snapshot", destination).returncode, 0)
        self.assertEqual(self.command("compare-snapshot", destination, "--root", source).returncode, 1)
        self.assertEqual(sorted(p.name for p in source.iterdir()), ["notes.txt"])
