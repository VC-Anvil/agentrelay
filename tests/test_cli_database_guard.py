"""CLI database selection must not turn typos or unrelated files into projects."""

from contextlib import closing, redirect_stderr
import hashlib
from io import StringIO
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from agentrelay import __main__ as cli


class CliDatabaseGuardTests(unittest.TestCase):
    guarded_commands = ("action", "run", "serve", "mcp")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-database-guard-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def command(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "agentrelay", *map(str, args)],
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )

    def action_file(self, directory, action, data):
        request = directory / f"{action}.json"
        request.write_text(json.dumps({"action": action, "data": data}), encoding="utf-8")
        return request

    def guarded(self, command, database, directory):
        if command == "action":
            request = self.action_file(directory, "create_ticket", {"title": "Must not be created"})
            return self.command("action", "--db", database, "--actor", "human", "--input", request)
        if command == "run":
            return self.command("run", "--db", database, "--workers", directory / "missing-workers.json",
                                "--worker", "fixture")
        if command == "serve":
            return self.command("serve", "--db", database, "--port", "0")
        return self.command("mcp", "--db", database, "--actor", "agent:fixture")

    @staticmethod
    def tables(database):
        with closing(sqlite3.connect(database)) as connection:
            return connection.execute(
                "SELECT type,name,sql FROM sqlite_master ORDER BY type,name"
            ).fetchall()

    def test_existing_foreign_database_is_rejected_unchanged_by_all_entry_points(self):
        for command in self.guarded_commands:
            with self.subTest(command=command):
                case = self.root / f"foreign-{command}"
                case.mkdir()
                database = case / "sentinel.sqlite"
                with closing(sqlite3.connect(database)) as connection:
                    connection.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
                    connection.execute("INSERT INTO sentinel VALUES ('preserve me')")
                    connection.commit()
                before_hash = hashlib.sha256(database.read_bytes()).digest()
                before_tables = self.tables(database)

                result = self.guarded(command, database, case)

                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("database", result.stderr.lower())
                self.assertNotIn("traceback", result.stderr.lower())
                self.assertEqual(hashlib.sha256(database.read_bytes()).digest(), before_hash)
                self.assertEqual(self.tables(database), before_tables)

    def test_empty_and_corrupt_files_are_rejected_without_traceback(self):
        for kind in ("empty", "corrupt"):
            for command in self.guarded_commands:
                with self.subTest(kind=kind, command=command):
                    case = self.root / f"{kind}-{command}"
                    case.mkdir()
                    database = case / "input.sqlite"
                    original = b"" if kind == "empty" else b"not a sqlite database\x00sentinel"
                    database.write_bytes(original)

                    result = self.guarded(command, database, case)

                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertIn("database", result.stderr.lower())
                    self.assertNotIn("traceback", result.stderr.lower())
                    self.assertEqual(database.read_bytes(), original)

    def test_non_bootstrap_actions_and_run_do_not_create_typo_paths(self):
        cases = (
            ("claim", ["action", "--actor", "human", "--input"],
             "claim_ticket", {"id": "AR-0001", "expected_revision": 1, "assignee": "human"}),
            ("unknown", ["action", "--actor", "human", "--input"], "future_action", {}),
        )
        for name, prefix, action, data in cases:
            with self.subTest(case=name):
                case = self.root / f"missing-{name}"
                database = case / "nested" / "workspace.sqlite"
                request = self.action_file(self.root, action, data)
                result = self.command(*prefix, request, "--db", database)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("does not exist", result.stderr.lower())
                self.assertFalse(database.parent.exists())

        case = self.root / "missing-run"
        database = case / "nested" / "workspace.sqlite"
        result = self.command("run", "--db", database, "--workers", self.root / "absent.json",
                              "--worker", "fixture")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not exist", result.stderr.lower())
        self.assertFalse(database.parent.exists())

    def test_only_three_creation_actions_bootstrap_a_new_database(self):
        actions = (
            ("create_ticket", {"title": "Nueva tarea"}, "title", "Nueva tarea"),
            ("create_plan", {"request_id": "plan-nuevo", "tickets": [
                {"key": "first", "title": "Plan nuevo"}
            ]}, "request_id", "plan-nuevo"),
            ("create_profile", {"name": "Especialista", "role": "qa", "model": "unknown"},
             "name", "Especialista"),
        )
        for action, data, field, expected in actions:
            with self.subTest(action=action):
                case = self.root / action
                database = case / "nested" / "workspace.sqlite"
                request = self.action_file(self.root, action, data)

                result = self.command("action", "--db", database, "--actor", "human",
                                      "--input", request)

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)[field], expected)
                self.assertTrue(database.is_file())

    def test_action_envelope_and_mcp_actor_are_validated_before_database_creation(self):
        bad_input = self.root / "bad.json"
        bad_input.write_text("not json", encoding="utf-8")
        action_database = self.root / "bad-action" / "nested" / "workspace.sqlite"
        action = self.command("action", "--db", action_database, "--actor", "human",
                              "--input", bad_input)
        self.assertNotEqual(action.returncode, 0)
        self.assertFalse(action_database.parent.exists())

        mcp_database = self.root / "bad-mcp" / "nested" / "workspace.sqlite"
        mcp = self.command("mcp", "--db", mcp_database, "--actor", "human")
        self.assertNotEqual(mcp.returncode, 0)
        self.assertIn("agent:<name>", mcp.stderr)
        self.assertFalse(mcp_database.parent.exists())

        deep_input = self.root / "deep.json"
        deep_input.write_text('{"action":"create_ticket","data":' + "[" * 1100 + "0" + "]" * 1100 + "}",
                              encoding="utf-8")
        deep_database = self.root / "deep-action" / "workspace.sqlite"
        deep = self.command("action", "--db", deep_database, "--actor", "human",
                            "--input", deep_input)
        self.assertNotEqual(deep.returncode, 0)
        self.assertIn("action input", deep.stderr.lower())
        self.assertNotIn("traceback", deep.stderr.lower())
        self.assertFalse(deep_database.parent.exists())

        valid_input = self.action_file(self.root, "create_ticket", {"title": "No empty actor"})
        actor_database = self.root / "bad-actor" / "workspace.sqlite"
        actor = self.command("action", "--db", actor_database, "--actor", "   ",
                             "--input", valid_input)
        self.assertNotEqual(actor.returncode, 0)
        self.assertIn("nonempty identity", actor.stderr.lower())
        self.assertFalse(actor_database.parent.exists())

    def test_home_expansion_failure_is_a_concise_database_error(self):
        # POSIX may resolve a user's home from the account database even with
        # HOME unset. Inject the actual path failure without touching any home.
        errors = StringIO()
        with patch.object(sys, "argv", ["agentrelay", "serve", "--db",
                                       "~/.agentrelay/workspace.sqlite", "--port", "0"]), \
                patch.object(Path, "expanduser", side_effect=RuntimeError("Home unavailable")), \
                patch.object(cli, "Store") as store, redirect_stderr(errors):
            with self.assertRaises(SystemExit) as stopped:
                cli.main()
        self.assertEqual(stopped.exception.code, 1)
        self.assertIn("database", errors.getvalue().lower())
        self.assertNotIn("traceback", errors.getvalue().lower())
        store.assert_not_called()

    def test_dangling_database_symlink_is_not_resolved_into_a_new_project(self):
        target = self.root / "missing-target" / "workspace.sqlite"
        link = self.root / "dangling.sqlite"
        try:
            link.symlink_to(target)
        except OSError as exc:
            self.skipTest(f"symlink creation is unavailable: {exc}")
        request = self.action_file(self.root, "create_ticket", {"title": "Do not follow alias"})

        result = self.command("action", "--db", link, "--actor", "human", "--input", request)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("database", result.stderr.lower())
        self.assertNotIn("traceback", result.stderr.lower())
        self.assertTrue(link.is_symlink())
        self.assertFalse(target.parent.exists())

    def test_serve_and_mcp_can_initialize_new_projects_without_launching_services(self):
        serve_database = self.root / "serve" / "workspace.sqlite"
        with patch.object(sys, "argv", ["agentrelay", "serve", "--db", str(serve_database),
                                        "--port", "0"]), \
                patch("agentrelay.server.serve") as serve:
            cli.main()
        self.assertTrue(serve_database.is_file())
        self.assertEqual(serve.call_count, 1)

        mcp_database = self.root / "mcp" / "workspace.sqlite"
        with patch.object(sys, "argv", ["agentrelay", "mcp", "--db", str(mcp_database),
                                        "--actor", "agent:fixture"]), \
                patch("agentrelay.mcp_server.run") as run:
            cli.main()
        self.assertTrue(mcp_database.is_file())
        self.assertEqual(run.call_args.args[1], "agent:fixture")


if __name__ == "__main__":
    unittest.main()
