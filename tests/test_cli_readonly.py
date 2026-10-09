"""Read-only CLI commands must reject typo and unrelated database paths."""

from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from agentrelay.store import Store
from agentrelay.workspaces import BASE_SCHEMA_COLUMNS


class ReadOnlyCliTests(unittest.TestCase):
    commands = ("context", "history", "export", "backup")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-readonly-cli-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def command(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "agentrelay", *map(str, args)],
            capture_output=True, text=True, encoding="utf-8", timeout=20,
        )

    def readonly(self, command, database, *, output=None, ticket="AR-0001"):
        args = [command, "--db", database]
        if command in {"context", "history"}:
            args += ["--ticket", ticket]
        if command == "backup":
            args += ["--output", output]
        return self.command(*args)

    @staticmethod
    def schema(path):
        with closing(sqlite3.connect(path)) as database:
            return [row[0] for row in database.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]

    def test_missing_database_does_not_create_parent_database_or_backup(self):
        for command in self.commands:
            with self.subTest(command=command):
                case = self.root / f"missing-{command}"
                database = case / "database" / "typo.sqlite"
                output = case / "output" / "backup.sqlite"
                result = self.readonly(command, database, output=output)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("database does not exist", result.stderr.lower())
                self.assertFalse(database.parent.exists())
                self.assertFalse(database.exists())
                self.assertFalse(output.parent.exists())
                self.assertFalse(output.exists())

    def test_empty_corrupt_and_unrelated_sqlite_are_never_mutated(self):
        for kind in ("empty", "corrupt", "foreign", "camouflaged", "views"):
            for command in self.commands:
                with self.subTest(kind=kind, command=command):
                    case = self.root / f"{kind}-{command}"
                    case.mkdir()
                    database = case / "input.sqlite"
                    if kind == "empty":
                        database.write_bytes(b"")
                    elif kind == "corrupt":
                        database.write_bytes(b"not a sqlite database\x00with bytes")
                    else:
                        with closing(sqlite3.connect(database)) as connection:
                            if kind == "foreign":
                                connection.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
                                connection.execute("INSERT INTO sentinel VALUES ('unchanged')")
                            elif kind == "camouflaged":
                                for table in ("tickets", "profiles", "dependencies", "events", "metadata"):
                                    connection.execute(f"CREATE TABLE {table} (bogus TEXT)")
                            else:
                                for table, columns in BASE_SCHEMA_COLUMNS.items():
                                    selection = ", ".join(f'NULL AS "{column}"' for column in columns)
                                    connection.execute(f'CREATE VIEW "{table}" AS SELECT {selection}')
                            connection.commit()
                    before = database.read_bytes()
                    before_schema = self.schema(database) if kind in {"foreign", "camouflaged", "views"} else None
                    output = case / "new-output" / "backup.sqlite"

                    result = self.readonly(command, database, output=output)

                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(hashlib.sha256(database.read_bytes()).digest(),
                                     hashlib.sha256(before).digest())
                    if kind in {"foreign", "camouflaged", "views"}:
                        self.assertEqual(self.schema(database), before_schema)
                    self.assertFalse(output.parent.exists())
                    self.assertFalse(output.exists())

    def test_original_schema_without_later_tables_is_recognized_and_migrated(self):
        database = self.root / "legacy.sqlite"
        with closing(sqlite3.connect(database)) as connection:
            connection.executescript("""
                CREATE TABLE profiles (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
                    provider TEXT NOT NULL, model TEXT NOT NULL, effort TEXT NOT NULL,
                    capabilities TEXT NOT NULL, preference TEXT NOT NULL,
                    description TEXT NOT NULL
                );
                CREATE TABLE tickets (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
                    type TEXT NOT NULL, status TEXT NOT NULL, priority TEXT NOT NULL,
                    parent_id TEXT REFERENCES tickets(id),
                    profile_id TEXT REFERENCES profiles(id), acceptance TEXT NOT NULL,
                    checkpoint TEXT NOT NULL, evidence TEXT NOT NULL,
                    assignee TEXT, actual_model TEXT, actual_effort TEXT,
                    blocked_reason TEXT NOT NULL, revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE dependencies (
                    ticket_id TEXT NOT NULL REFERENCES tickets(id),
                    depends_on TEXT NOT NULL REFERENCES tickets(id),
                    PRIMARY KEY (ticket_id, depends_on)
                );
                CREATE TABLE events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id TEXT REFERENCES tickets(id), actor TEXT NOT NULL,
                    action TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
        self.assertNotIn("plan_requests", self.schema(database))

        result = self.readonly("export", database)

        self.assertEqual(result.returncode, 0, result.stderr)
        exported = json.loads(result.stdout)
        self.assertEqual(len(exported["profiles"]), 4)
        self.assertIn("plan_requests", self.schema(database))

    def test_all_four_commands_read_a_valid_database(self):
        database = self.root / "valid.sqlite"
        store = Store(database)
        ticket = store.action("create_ticket", {
            "title": "Inspect existing data",
            "acceptance": ["Read without changing the selected database"],
        })

        context = self.readonly("context", database, ticket=ticket["id"])
        self.assertEqual(context.returncode, 0, context.stderr)
        self.assertEqual(json.loads(context.stdout)["ticket"]["id"], ticket["id"])

        history = self.readonly("history", database, ticket=ticket["id"])
        self.assertEqual(history.returncode, 0, history.stderr)
        self.assertEqual(json.loads(history.stdout)["ticket_id"], ticket["id"])

        exported = self.readonly("export", database)
        self.assertEqual(exported.returncode, 0, exported.stderr)
        self.assertEqual(json.loads(exported.stdout)["tickets"][0]["id"], ticket["id"])

        backup = self.root / "backup" / "valid-copy.sqlite"
        saved = self.readonly("backup", database, output=backup)
        self.assertEqual(saved.returncode, 0, saved.stderr)
        self.assertTrue(backup.is_file())
        self.assertEqual(Store(backup).context(ticket["id"])["ticket"]["title"],
                         "Inspect existing data")

    def test_action_keeps_explicit_database_bootstrap(self):
        database = self.root / "new" / "workspace.sqlite"
        request = self.root / "request.json"
        request.write_text(json.dumps({
            "action": "create_ticket",
            "data": {"title": "Authorized bootstrap"},
        }), encoding="utf-8")

        result = self.command("action", "--db", database, "--actor", "human",
                              "--input", request)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(database.is_file())
        self.assertEqual(json.loads(result.stdout)["title"], "Authorized bootstrap")


if __name__ == "__main__":
    unittest.main()
