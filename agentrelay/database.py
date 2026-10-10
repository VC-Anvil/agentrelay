"""Read-only recognition of an existing AgentRelay SQLite database."""

from pathlib import Path
import sqlite3


BASE_SCHEMA_COLUMNS = {
    "profiles": {"id", "name", "role", "provider", "model", "effort", "capabilities",
                 "preference", "description"},
    "tickets": {"id", "title", "description", "type", "status", "priority", "parent_id",
                "profile_id", "acceptance", "checkpoint", "evidence", "assignee",
                "actual_model", "actual_effort", "blocked_reason", "revision", "created_at",
                "updated_at"},
    "dependencies": {"ticket_id", "depends_on"},
    "events": {"id", "ticket_id", "actor", "action", "details", "created_at"},
    "metadata": {"key", "value"},
}


class DatabaseRecognitionError(Exception):
    """An existing path is not a readable AgentRelay database."""


def recognize_agentrelay_database(database):
    """Resolve and check the base schema without creating or migrating a database."""
    try:
        path = Path(database).expanduser().resolve()
        if not path.is_file():
            raise DatabaseRecognitionError(f"Workspace database does not exist: {path}")
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if not BASE_SCHEMA_COLUMNS.keys() <= tables:
                raise DatabaseRecognitionError(f"Not an initialized AgentRelay database: {path}")
            columns = {
                table: {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
                for table in BASE_SCHEMA_COLUMNS
            }
            if any(not required.issubset(columns[table])
                   for table, required in BASE_SCHEMA_COLUMNS.items()):
                raise DatabaseRecognitionError(f"Not an initialized AgentRelay database: {path}")
        finally:
            connection.close()
        return path
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        raise DatabaseRecognitionError(f"Cannot read AgentRelay database: {database}") from exc
