"""Store bootstraps new paths but never stamps an unrelated existing file."""

from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from agentrelay.database import BASE_SCHEMA_COLUMNS as SHARED_BASE_SCHEMA
from agentrelay.store import DomainError, Store
from agentrelay.workspaces import (BASE_SCHEMA_COLUMNS, require_agentrelay_database)


class StoreDatabaseGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-database-guard-")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def schema(path):
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            return db.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall()

    def assert_rejected_unchanged(self, path, *, sqlite_schema=False):
        before = path.read_bytes()
        schema = self.schema(path) if sqlite_schema else None
        with self.assertRaises(DomainError):
            Store(path)
        self.assertEqual(path.read_bytes(), before)
        if sqlite_schema:
            self.assertEqual(self.schema(path), schema)
        self.assertFalse((path.parent / (path.name + "-wal")).exists())
        self.assertFalse((path.parent / (path.name + "-shm")).exists())

    def test_new_path_bootstraps_and_existing_valid_database_reopens(self):
        path = self.root / "nested" / "project.sqlite"
        self.assertFalse(path.exists())
        store = Store(path)
        self.assertTrue(path.is_file())
        self.assertIs(BASE_SCHEMA_COLUMNS, SHARED_BASE_SCHEMA)
        ticket = store.action("create_ticket", {"title": "Existing work",
            "acceptance": ["Independent check"]})
        self.assertEqual(require_agentrelay_database(path), path.resolve())
        reopened = Store(path)
        self.assertEqual(reopened.context(ticket["id"])["ticket"]["title"], "Existing work")

    def test_expanduser_inspects_and_connects_the_same_file(self):
        simulated_home = self.root / "home"
        simulated_home.mkdir()
        home_database = simulated_home / "project.sqlite"
        ticket = Store(home_database).action("create_ticket", {"title": "Real home database"})
        literal_home = self.root / "~"
        literal_home.mkdir()
        decoy = literal_home / "project.sqlite"
        with closing(sqlite3.connect(decoy)) as db:
            db.execute("CREATE TABLE sentinel(value TEXT)")
        decoy_bytes = decoy.read_bytes()

        original_cwd = Path.cwd()
        try:
            os.chdir(self.root)
            with patch.dict(os.environ, {"HOME": str(simulated_home),
                                         "USERPROFILE": str(simulated_home)}):
                reopened = Store(Path("~") / "project.sqlite")
                self.assertEqual(reopened.path, str(home_database.resolve()))
                self.assertEqual(reopened.context(ticket["id"])["ticket"]["title"],
                                 "Real home database")
                new = Store(Path("~") / "new.sqlite")
                self.assertEqual(new.path, str((simulated_home / "new.sqlite").resolve()))
                self.assertTrue((simulated_home / "new.sqlite").is_file())
                self.assertFalse((literal_home / "new.sqlite").exists())
        finally:
            os.chdir(original_cwd)
        self.assertEqual(decoy.read_bytes(), decoy_bytes)
        self.assertEqual([row[1] for row in self.schema(decoy)], ["sentinel"])

    def test_foreign_corrupt_empty_and_incomplete_databases_are_untouched(self):
        foreign = self.root / "foreign.sqlite"
        with closing(sqlite3.connect(foreign)) as db:
            with db:
                db.execute("CREATE TABLE sentinel(value TEXT)")
                db.execute("INSERT INTO sentinel VALUES ('preserve')")
        self.assert_rejected_unchanged(foreign, sqlite_schema=True)
        with self.assertRaises(DomainError):
            require_agentrelay_database(foreign)

        corrupt = self.root / "corrupt.sqlite"
        corrupt.write_bytes(b"foreign data, not a SQLite database\x00")
        self.assert_rejected_unchanged(corrupt)

        zero = self.root / "zero.sqlite"
        zero.write_bytes(b"")
        self.assert_rejected_unchanged(zero)

        empty = self.root / "empty.sqlite"
        with closing(sqlite3.connect(empty)) as db:
            with db:
                db.execute("CREATE TABLE temporary(value TEXT)")
                db.execute("DROP TABLE temporary")
        self.assert_rejected_unchanged(empty, sqlite_schema=True)

        incomplete = self.root / "incomplete.sqlite"
        with closing(sqlite3.connect(incomplete)) as db:
            db.execute("CREATE TABLE profiles(id TEXT)")
        self.assert_rejected_unchanged(incomplete, sqlite_schema=True)

        missing_column = self.root / "missing-column.sqlite"
        with closing(sqlite3.connect(missing_column)) as db:
            for table, required in BASE_SCHEMA_COLUMNS.items():
                columns = sorted(required - ({"effort"} if table == "profiles" else set()))
                db.execute(f'CREATE TABLE "{table}" (' +
                           ", ".join(f'"{column}" TEXT' for column in columns) + ")")
        self.assert_rejected_unchanged(missing_column, sqlite_schema=True)

        views = self.root / "views.sqlite"
        with closing(sqlite3.connect(views)) as db:
            for name in BASE_SCHEMA_COLUMNS:
                db.execute(f'CREATE VIEW "{name}" AS SELECT 1 AS id')
        self.assert_rejected_unchanged(views, sqlite_schema=True)

    def test_directory_is_not_bootstrapped(self):
        directory = self.root / "named.sqlite"
        directory.mkdir()
        with self.assertRaises(DomainError):
            Store(directory)
        self.assertEqual(list(directory.iterdir()), [])

    def test_dangling_symlink_is_not_bootstrapped(self):
        dangling = self.root / "dangling.sqlite"
        try:
            dangling.symlink_to(self.root / "absent.sqlite")
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable on this host")
        with self.assertRaises(DomainError):
            Store(dangling)
        self.assertTrue(dangling.is_symlink())
        self.assertFalse((self.root / "absent.sqlite").exists())

    def test_legacy_base_schema_migrates_without_data_loss(self):
        path = self.root / "legacy.sqlite"
        store = Store(path)
        ticket = store.action("create_ticket", {"title": "Legacy ticket"})
        with store._write() as db:
            db.execute("DROP TABLE plan_requests")
            db.execute("DROP TABLE claim_requests")
        with store._connection() as db:
            self.assertNotIn("claim_requests", {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")})
        self.assertEqual(require_agentrelay_database(path), path.resolve())
        reopened = Store(path)
        self.assertEqual(reopened.context(ticket["id"])["ticket"]["title"], "Legacy ticket")
        with reopened._connection() as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"plan_requests", "claim_requests"}.issubset(tables))

    def test_valid_symlink_remains_supported(self):
        path = self.root / "project.sqlite"
        store = Store(path)
        ticket = store.action("create_ticket", {"title": "Existing linked ticket"})
        alias = self.root / "alias.sqlite"
        try:
            alias.symlink_to(path)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable on this host")
        self.assertEqual(require_agentrelay_database(alias), path.resolve())
        self.assertEqual(Store(alias).context(ticket["id"])["ticket"]["title"],
                         "Existing linked ticket")


if __name__ == "__main__":
    unittest.main()
