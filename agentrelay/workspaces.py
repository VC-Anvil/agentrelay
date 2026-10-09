"""Explicit startup registry. Browser input selects IDs, never database paths."""

from dataclasses import dataclass
import json
from pathlib import Path
import re
import sqlite3

from .store import DomainError, Store


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


@dataclass
class Workspace:
    id: str
    name: str
    store: Store
    execution: object = None

    def public(self):
        return {"id": self.id, "name": self.name,
                "database": str(Path(self.store.path).resolve()), "demo": self.store.is_demo()}


def require_agentrelay_database(database):
    """Resolve and identify an existing AgentRelay database without migrating it."""
    path = Path(database).expanduser().resolve()
    if not path.is_file():
        raise DomainError(f"Workspace database does not exist: {path}")
    try:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if not BASE_SCHEMA_COLUMNS.keys() <= tables:
                raise DomainError(f"Not an initialized AgentRelay database: {path}")
            columns = {
                table: {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
                for table in BASE_SCHEMA_COLUMNS
            }
            missing = {table: required - columns[table]
                       for table, required in BASE_SCHEMA_COLUMNS.items()
                       if not required.issubset(columns[table])}
            if missing:
                raise DomainError(f"Not an initialized AgentRelay database: {path}")
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise DomainError(f"Cannot read AgentRelay database: {path}") from exc
    return path


def load_workspaces(config_path, *, enable_execution=True):
    """Load existing AgentRelay databases, optionally activating configured workers."""
    config_path = Path(config_path).expanduser().resolve()
    try:
        with config_path.open("rb") as stream:
            raw = stream.read(1_048_577)
        if len(raw) > 1_048_576:
            raise DomainError("Workspace configuration exceeds 1 MiB")
        config = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise DomainError(f"Cannot read workspace configuration: {exc}") from exc
    if not isinstance(config, dict) or set(config) - {"workspaces", "default_workspace_id"}:
        raise DomainError("Workspace configuration needs workspaces and optional default_workspace_id")
    entries = config.get("workspaces")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 16:
        raise DomainError("Configure between 1 and 16 workspaces")
    prepared, ids, paths = [], set(), set()
    for item in entries:
        if (not isinstance(item, dict) or set(item) - {"id", "name", "db", "workers"}
                or not {"id", "name", "db"}.issubset(item)):
            raise DomainError("Workspace entries need id, name, db and optional workers")
        identity, name, database = item["id"], item["name"], item["db"]
        if not isinstance(identity, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", identity):
            raise DomainError("Workspace IDs use 1–64 lowercase letters, digits, underscore or hyphen")
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise DomainError("Workspace name needs 1–120 characters")
        if not isinstance(database, str) or not database.strip():
            raise DomainError("Workspace db must be an explicit path")
        path = Path(database).expanduser()
        path = (config_path.parent / path).resolve() if not path.is_absolute() else path.resolve()
        if identity in ids or path in paths or any(path.exists() and path.samefile(p) for p in paths):
            raise DomainError("Workspace IDs and database files must be unique")
        # Refuse typo paths and unrelated SQLite files before any Store migrations.
        path = require_agentrelay_database(path)
        worker_path = item.get("workers")
        if worker_path is not None:
            if not isinstance(worker_path, str) or not worker_path.strip():
                raise DomainError("workers must be an explicit configuration path")
            worker_path = Path(worker_path).expanduser()
            if not worker_path.is_absolute():
                worker_path = config_path.parent / worker_path
            worker_path = worker_path.resolve()
        ids.add(identity)
        paths.add(path)
        prepared.append((identity, name.strip(), path, worker_path))
    default = config.get("default_workspace_id", prepared[0][0])
    if not isinstance(default, str) or default not in ids:
        raise DomainError("default_workspace_id must identify a configured workspace")
    workspaces = {}
    try:
        for identity, name, path, worker_path in prepared:
            store = Store(path)
            execution = None
            if enable_execution and worker_path is not None:
                from .execution import ExecutionManager
                execution = ExecutionManager(store, worker_path)
            workspaces[identity] = Workspace(identity, name, store, execution)
    except Exception:
        for workspace in workspaces.values():
            if workspace.execution:
                workspace.execution.close()
        raise
    return workspaces, default
