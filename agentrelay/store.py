"""Persistent ticket domain for AgentRelay.

Only explicit actions change tickets.  A completed ticket records a human review
decision; references in ``evidence`` are never treated as verified facts.
"""

from __future__ import annotations

import json
import hashlib
import sqlite3
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import __version__


TYPES = {"objective", "task", "bug", "research", "review", "help"}
STATUSES = {"backlog", "queued", "in_progress", "blocked", "review", "done", "cancelled"}
PRIORITIES = {"urgent", "high", "normal", "low"}
PREFERENCES = {"quality", "balanced", "speed"}
EFFORTS = {"none", "default", "low", "medium", "high", "xhigh", "max", "ultra"}
EDITABLE = {"title", "description", "type", "priority", "parent_id", "depends_on",
            "profile_id", "acceptance", "checkpoint"}
PROFILE_EDITABLE = {"name", "role", "provider", "model", "effort", "capabilities",
                    "preference", "description"}
DEFAULT_PROFILES = (
    ("astra", "Astra", "coordinator", "OpenAI", "gpt-6-astra", "high", ["planning", "integration", "review"], "quality", "Coordinación y resolución compleja; modelo fijado por la dirección."),
    ("sol", "Sol", "complex implementation", "OpenAI", "gpt-6-sol", "high", ["implementation", "design", "integration"], "quality", "Implementación e integración complejas."),
    ("terra", "Terra", "bounded implementation", "OpenAI", "gpt-5.6-terra", "medium", ["implementation", "qa"], "balanced", "Paquetes delimitados de implementación y QA."),
    ("luna", "Luna", "extraction", "OpenAI", "gpt-6-luna", "medium", ["extraction", "inventory"], "speed", "Extracción e inventarios con criterios fijos."),
)


class DomainError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _nonempty(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DomainError(f"{field} must be a nonempty string")
    return value.strip()


def _optional_text(value, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise DomainError(f"{field} must be a string or null")
    return value.strip() or None


def _choice(value, choices: set[str], field: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise DomainError(f"invalid {field}: {value!r}")
    return value


def _strings(value, field: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
        raise DomainError(f"{field} must be an array of nonempty strings")
    out = [x.strip() for x in value]
    if len(out) != len(set(out)):
        raise DomainError(f"{field} contains duplicates")
    if nonempty and not out:
        raise DomainError(f"{field} must not be empty")
    return out


def _evidence(value, *, nonempty: bool = False) -> list[dict]:
    if not isinstance(value, list) or (nonempty and not value):
        raise DomainError("evidence must be a nonempty array" if nonempty else "evidence must be an array")
    result = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"kind", "label", "uri"}:
            raise DomainError("each evidence item needs kind, label, and uri")
        result.append({key: _nonempty(item[key], f"evidence.{key}") for key in ("kind", "label", "uri")})
    return result


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS profiles (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
                    provider TEXT NOT NULL, model TEXT NOT NULL, effort TEXT NOT NULL,
                    capabilities TEXT NOT NULL, preference TEXT NOT NULL,
                    description TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tickets (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
                    type TEXT NOT NULL, status TEXT NOT NULL, priority TEXT NOT NULL,
                    parent_id TEXT REFERENCES tickets(id),
                    profile_id TEXT REFERENCES profiles(id), acceptance TEXT NOT NULL,
                    checkpoint TEXT NOT NULL, evidence TEXT NOT NULL,
                    assignee TEXT, actual_model TEXT, actual_effort TEXT,
                    blocked_reason TEXT NOT NULL, revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS dependencies (
                    ticket_id TEXT NOT NULL REFERENCES tickets(id),
                    depends_on TEXT NOT NULL REFERENCES tickets(id),
                    PRIMARY KEY (ticket_id, depends_on)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id TEXT REFERENCES tickets(id), actor TEXT NOT NULL,
                    action TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS plan_requests (
                    request_id TEXT PRIMARY KEY, actor TEXT NOT NULL,
                    payload_hash TEXT NOT NULL, result TEXT NOT NULL
                );
            """)
            for row in DEFAULT_PROFILES:
                db.execute("INSERT OR IGNORE INTO profiles VALUES (?,?,?,?,?,?,?,?,?)",
                           (*row[:6], _json(row[6]), *row[7:]))
            db.commit()

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=30000")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def _write(self):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    def _next_ticket_id(self, db) -> str:
        row = db.execute("SELECT value FROM metadata WHERE key='ticket_sequence'").fetchone()
        number = int(row[0]) + 1 if row else 1
        db.execute("INSERT INTO metadata(key,value) VALUES('ticket_sequence',?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(number),))
        return f"AR-{number:04d}"

    def _next_profile_id(self, db) -> str:
        row = db.execute("SELECT value FROM metadata WHERE key='profile_sequence'").fetchone()
        number = int(row[0]) + 1 if row else 1
        db.execute("INSERT INTO metadata(key,value) VALUES('profile_sequence',?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(number),))
        return f"profile-{number:04d}"

    def _event(self, db, ticket_id, actor, action, details):
        db.execute("INSERT INTO events(ticket_id,actor,action,details,created_at) VALUES(?,?,?,?,?)",
                   (ticket_id, actor, action, _json(details), _utc()))

    def _require_ticket(self, db, ticket_id):
        ticket_id = _nonempty(ticket_id, "id")
        row = db.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
        if row is None:
            raise DomainError(f"ticket {ticket_id} not found", 404)
        return row

    def _require_profile(self, db, profile_id):
        if profile_id is not None:
            profile_id = _nonempty(profile_id, "profile_id")
        if profile_id is not None and db.execute("SELECT 1 FROM profiles WHERE id=?", (profile_id,)).fetchone() is None:
            raise DomainError(f"profile {profile_id} not found", 404)

    def _expect(self, row, data):
        revision = data.get("expected_revision")
        if isinstance(revision, bool) or not isinstance(revision, int):
            raise DomainError("expected_revision must be an integer")
        if row["revision"] != revision:
            raise DomainError(f"revision conflict for {row['id']}: expected {revision}, current {row['revision']}", 409)

    def _deps(self, db, ticket_id):
        return [r[0] for r in db.execute("SELECT depends_on FROM dependencies WHERE ticket_id=? ORDER BY depends_on", (ticket_id,))]

    def _ticket(self, db, ticket_id):
        row = self._require_ticket(db, ticket_id)
        item = dict(row)
        item["acceptance"] = json.loads(item["acceptance"])
        item["evidence"] = json.loads(item["evidence"])
        item["depends_on"] = self._deps(db, ticket_id)
        blockers = []
        for dep in item["depends_on"]:
            status = self._require_ticket(db, dep)["status"]
            if status != "done":
                blockers.append(f"Dependency {dep} is {status}")
        for child in db.execute("SELECT id,status FROM tickets WHERE parent_id=? ORDER BY id", (ticket_id,)):
            if child["status"] not in ("done", "cancelled"):
                blockers.append(f"Child {child['id']} is {child['status']}")
        if item["status"] == "blocked":
            blockers.insert(0, item["blocked_reason"] or "Manually blocked")
        item["blockers"] = blockers
        item["ready"] = item["status"] == "queued" and not blockers
        return item

    def _profile(self, row):
        item = dict(row)
        item["capabilities"] = json.loads(item["capabilities"])
        return item

    def _events(self, db, where="", args=(), limit=None):
        sql = "SELECT * FROM events " + where + " ORDER BY id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            args = (*args, limit)
        result = []
        for row in db.execute(sql, args):
            item = dict(row)
            item["details"] = json.loads(item["details"])
            result.append(item)
        return result

    @staticmethod
    def _history_limit(value, name="limit"):
        if type(value) is not int or not 1 <= value <= 100:
            raise DomainError(f"{name} must be an integer from 1 to 100")
        return value

    def _ticket_events_page(self, db, ticket_id, limit, before_id=None):
        total = db.execute("SELECT COUNT(*) FROM events WHERE ticket_id=?", (ticket_id,)).fetchone()[0]
        where = "WHERE ticket_id=?"
        args = (ticket_id,)
        if before_id is not None:
            where += " AND id<?"
            args = (ticket_id, before_id)
        rows = self._events(db, where, args, limit + 1)
        has_older = len(rows) > limit
        events = rows[:limit]
        return {"events": events, "total": total, "count": len(events), "limit": limit,
                "next_before_id": events[-1]["id"] if has_older else None}

    def ticket_events(self, ticket_id, *, limit=20, before_id=None):
        """Read one ticket's older audit events; cursor excludes its starting ID."""
        limit = self._history_limit(limit)
        if before_id is not None and (type(before_id) is not int or not 1 <= before_id <= 2**63 - 1):
            raise DomainError("before_id must be an integer from 1 to 2**63-1 or null")
        with self._connection() as db:
            db.execute("BEGIN")
            ticket = self._require_ticket(db, ticket_id)
            page = self._ticket_events_page(db, ticket["id"], limit, before_id)
            db.commit()
            return {"ticket_id": ticket["id"], **page, "before_id": before_id}

    def state(self):
        with self._connection() as db:
            db.execute("BEGIN")
            tickets = [self._ticket(db, row[0]) for row in db.execute("SELECT id FROM tickets ORDER BY id")]
            profiles = [self._profile(row) for row in db.execute("SELECT * FROM profiles ORDER BY id")]
            counts = {status: sum(t["status"] == status for t in tickets) for status in sorted(STATUSES)}
            state = {"tickets": tickets, "profiles": profiles,
                     "events": self._events(db, limit=100),
                     "runs": self._execution_history(db, 100),
                     "demo": db.execute("SELECT 1 FROM metadata WHERE key='demo_seeded'").fetchone() is not None,
                     "stats": {"total": len(tickets), "ready": sum(t["ready"] for t in tickets), "by_status": counts}}
            db.commit()
            return state

    def context(self, ticket_id, *, event_limit=None):
        if event_limit is not None:
            self._history_limit(event_limit, "event_limit")
        with self._connection() as db:
            db.execute("BEGIN")
            ticket = self._ticket(db, ticket_id)
            parent = self._ticket(db, ticket["parent_id"]) if ticket["parent_id"] else None
            dependencies = [self._ticket(db, dep) for dep in ticket["depends_on"]]
            children = [self._ticket(db, r[0]) for r in db.execute("SELECT id FROM tickets WHERE parent_id=? ORDER BY id", (ticket_id,))]
            profiles = [self._profile(row) for row in db.execute("SELECT * FROM profiles ORDER BY id")]
            page = self._ticket_events_page(db, ticket["id"], event_limit) if event_limit is not None else None
            context = {"ticket": ticket, "parent": parent, "dependencies": dependencies,
                       "children": children, "events": page["events"] if page is not None else self._events(db, "WHERE ticket_id=?", (ticket["id"],)),
                       "profile": next((p for p in profiles if p["id"] == ticket["profile_id"]), None),
                       "profiles": profiles,
                       "instructions": "Review acceptance, dependencies, checkpoint and evidence. Evidence references require independent verification. Record progress with checkpoint, then submit for review."}
            if page is not None:
                context["events_page"] = {key: page[key] for key in ("total", "count", "limit", "next_before_id")}
            db.commit()
            return context

    def is_demo(self):
        with self._connection() as db:
            return db.execute("SELECT 1 FROM metadata WHERE key='demo_seeded'").fetchone() is not None

    def _execution_history(self, db, limit=None):
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_runs'").fetchone() is None:
            return []
        query = ("SELECT id,ticket_id,worker_id,status,started_at,finished_at,summary,error,model,effort "
                 "FROM execution_runs ORDER BY started_at DESC,id DESC")
        return [dict(row) for row in db.execute(query + (" LIMIT ?" if limit is not None else ""),
                                                (limit,) if limit is not None else ())]

    def execution_history(self):
        with self._connection() as db:
            return self._execution_history(db, 100)

    def backup(self, destination):
        """Online SQLite backup. Never overwrite an existing file or copy a live WAL."""
        path = Path(destination).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents accidental destruction even under races.
        with path.open("xb"):
            pass
        with self._connection() as source:
            target = sqlite3.connect(path)
            try:
                source.backup(target)
            finally:
                target.close()
        return path

    def export(self):
        with self._connection() as db:
            db.execute("BEGIN")
            tickets = [self._ticket(db, row[0]) for row in db.execute("SELECT id FROM tickets ORDER BY id")]
            profiles = [self._profile(row) for row in db.execute("SELECT * FROM profiles ORDER BY id")]
            events = self._events(db)
            runs = self._execution_history(db)
            demo = db.execute("SELECT 1 FROM metadata WHERE key='demo_seeded'").fetchone() is not None
            db.commit()
            return {"version": __version__, "exported_at": _utc(), "demo": demo, "tickets": tickets,
                    "profiles": profiles, "events": events, "runs": runs}

    def _check_graph(self, db):
        """Every parent waits for children; every ticket waits for dependencies."""
        graph = {r[0]: set() for r in db.execute("SELECT id FROM tickets")}
        for row in db.execute("SELECT id,parent_id FROM tickets WHERE parent_id IS NOT NULL"):
            graph[row["parent_id"]].add(row["id"])
        for row in db.execute("SELECT ticket_id,depends_on FROM dependencies"):
            graph[row["ticket_id"]].add(row["depends_on"])
        indegree = {node: 0 for node in graph}
        for successors in graph.values():
            for successor in successors:
                indegree[successor] += 1
        ready = deque(node for node, count in indegree.items() if count == 0)
        visited = 0
        while ready:
            node = ready.popleft()
            visited += 1
            for successor in graph[node]:
                indegree[successor] -= 1
                if indegree[successor] == 0:
                    ready.append(successor)
        if visited != len(graph):
            raise DomainError("relationship creates a hierarchy/dependency deadlock", 409)

    def _normalize_ticket_fields(self, db, fields, *, creating=False):
        if not isinstance(fields, dict):
            raise DomainError("data must be an object")
        unknown = set(fields) - EDITABLE
        if unknown:
            raise DomainError(f"fields not editable: {', '.join(sorted(unknown))}")
        out = {}
        for key, value in fields.items():
            if key == "title":
                out[key] = _nonempty(value, key)
            elif key in ("description", "checkpoint"):
                if not isinstance(value, str):
                    raise DomainError(f"{key} must be a string")
                out[key] = value.strip()
            elif key == "type":
                out[key] = _choice(value, TYPES, key)
            elif key == "priority":
                out[key] = _choice(value, PRIORITIES, key)
            elif key in ("parent_id", "profile_id"):
                out[key] = _optional_text(value, key)
                if key == "parent_id" and out[key]:
                    parent = self._require_ticket(db, out[key])
                    if parent["status"] in ("done", "cancelled"):
                        raise DomainError("reopen closed parent before adding or moving child scope", 409)
                if key == "profile_id":
                    self._require_profile(db, out[key])
            elif key == "depends_on":
                out[key] = _strings(value, key)
                for dep in out[key]:
                    self._require_ticket(db, dep)
            elif key == "acceptance":
                out[key] = _strings(value, key)
        if creating and "title" not in out:
            raise DomainError("title is required")
        return out

    def _insert_ticket(self, db, fields, actor, action="create_ticket", *, record_event=True):
        fields = self._normalize_ticket_fields(db, fields, creating=True)
        ticket_id, now = self._next_ticket_id(db), _utc()
        db.execute("""INSERT INTO tickets
            (id,title,description,type,status,priority,parent_id,profile_id,acceptance,
             checkpoint,evidence,assignee,actual_model,actual_effort,blocked_reason,revision,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ticket_id, fields["title"], fields.get("description", ""), fields.get("type", "task"),
             "queued", fields.get("priority", "normal"), fields.get("parent_id"),
             fields.get("profile_id"), _json(fields.get("acceptance", [])),
             fields.get("checkpoint", ""), "[]", None, None, None, "", 1, now, now))
        for dep in fields.get("depends_on", []):
            db.execute("INSERT INTO dependencies VALUES (?,?)", (ticket_id, dep))
        self._check_graph(db)
        created = self._ticket(db, ticket_id)
        if record_event:
            self._event(db, ticket_id, actor, action, {"after": created})
        return created

    @staticmethod
    def _plan_identifier(value, name, limit):
        if (not isinstance(value, str) or not value or value != value.strip()
                or len(value) > limit):
            raise DomainError(f"{name} must be a nonempty string up to {limit} characters without surrounding whitespace")
        return value

    def _create_plan(self, db, data, actor):
        if set(data) != {"request_id", "tickets"}:
            raise DomainError("create_plan requires request_id and tickets only")
        request_id = self._plan_identifier(data["request_id"], "request_id", 128)
        entries = data["tickets"]
        if not isinstance(entries, list) or not 1 <= len(entries) <= 64:
            raise DomainError("tickets must contain 1 to 64 entries")
        try:
            canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            payload_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        except (TypeError, ValueError, UnicodeError) as exc:
            raise DomainError("create_plan data must be JSON-compatible") from exc
        prior = db.execute("SELECT actor,payload_hash,result FROM plan_requests WHERE request_id=?",
                           (request_id,)).fetchone()
        if prior is not None:
            if prior["actor"] != actor or prior["payload_hash"] != payload_hash:
                raise DomainError("request_id already used with different actor or payload", 409)
            return json.loads(prior["result"])

        allowed = EDITABLE | {"key", "parent_key", "depends_on_keys", "status"}
        keys = set()
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) - allowed:
                raise DomainError("invalid create_plan ticket fields")
            key = self._plan_identifier(entry.get("key"), "key", 64)
            if key in keys:
                raise DomainError("duplicate create_plan key")
            keys.add(key)
            if "parent_key" in entry and "parent_id" in entry:
                raise DomainError("parent_key and parent_id are mutually exclusive")
            _choice(entry.get("status", "backlog"), {"backlog", "queued"}, "status")
            if "parent_key" in entry:
                self._plan_identifier(entry["parent_key"], "parent_key", 64)
            if "depends_on_keys" in entry:
                _strings(entry["depends_on_keys"], "depends_on_keys")
                for dep_key in entry["depends_on_keys"]:
                    self._plan_identifier(dep_key, "depends_on_keys item", 64)
        for entry in entries:
            if "parent_key" in entry and entry["parent_key"] not in keys:
                raise DomainError(f"parent_key {entry['parent_key']} not found")
            for dep_key in entry.get("depends_on_keys", []):
                if dep_key not in keys:
                    raise DomainError(f"depends_on_keys item {dep_key} not found")

        existing_ids = {row[0] for row in db.execute("SELECT id FROM tickets")}
        for entry in entries:
            parent_id = _optional_text(entry.get("parent_id"), "parent_id")
            if parent_id is not None and parent_id not in existing_ids:
                raise DomainError(f"existing parent ticket {parent_id} not found", 404)
            for dep_id in _strings(entry.get("depends_on", []), "depends_on"):
                if dep_id not in existing_ids:
                    raise DomainError(f"existing dependency ticket {dep_id} not found", 404)

        key_to_id = {}
        for entry in entries:
            base = {field: value for field, value in entry.items() if field in EDITABLE
                    and field not in {"parent_id", "depends_on"}}
            created = self._insert_ticket(db, base, actor, record_event=False)
            key_to_id[entry["key"]] = created["id"]

        for entry in entries:
            ticket_id = key_to_id[entry["key"]]
            parent_id = (key_to_id[entry["parent_key"]] if "parent_key" in entry
                         else _optional_text(entry.get("parent_id"), "parent_id"))
            dependencies = (_strings(entry.get("depends_on", []), "depends_on")
                            + [key_to_id[key] for key in entry.get("depends_on_keys", [])])
            if len(dependencies) != len(set(dependencies)):
                raise DomainError("resolved dependencies contain duplicates")
            full = {field: value for field, value in entry.items() if field in EDITABLE
                    and field not in {"parent_id", "depends_on"}}
            full["parent_id"] = parent_id
            full["depends_on"] = dependencies
            normalized = self._normalize_ticket_fields(db, full, creating=True)
            db.execute("UPDATE tickets SET parent_id=?,status=? WHERE id=?",
                       (normalized["parent_id"], entry.get("status", "backlog"), ticket_id))
            for dep_id in normalized["depends_on"]:
                db.execute("INSERT INTO dependencies VALUES (?,?)", (ticket_id, dep_id))
        self._check_graph(db)
        tickets = [self._ticket(db, key_to_id[entry["key"]]) for entry in entries]
        result = {"request_id": request_id, "key_to_id": key_to_id, "tickets": tickets}
        for entry, ticket in zip(entries, tickets):
            self._event(db, ticket["id"], actor, "create_plan_ticket",
                        {"request_id": request_id, "key": entry["key"], "after": ticket})
        self._event(db, None, actor, "create_plan", {"request_id": request_id, "key_to_id": key_to_id})
        db.execute("INSERT INTO plan_requests(request_id,actor,payload_hash,result) VALUES(?,?,?,?)",
                   (request_id, actor, payload_hash, _json(result)))
        return result

    def _update_row(self, db, ticket_id, changes):
        changes = {**changes, "updated_at": _utc()}
        sql = ", ".join(f"{name}=?" for name in changes) + ", revision=revision+1"
        db.execute(f"UPDATE tickets SET {sql} WHERE id=?", (*changes.values(), ticket_id))

    def _update_ticket(self, db, data, actor):
        row = self._require_ticket(db, data.get("id"))
        self._expect(row, data)
        if row["status"] == "done":
            raise DomainError("reopen completed ticket before editing scope", 409)
        if row["status"] in ("in_progress", "review") or (row["status"] == "blocked" and row["assignee"]):
            self._actor_can_work(row, actor)
        before = self._ticket(db, row["id"])
        fields = self._normalize_ticket_fields(db, {k: v for k, v in data.items() if k not in ("id", "expected_revision")})
        if not fields:
            raise DomainError("no fields to update")
        if "acceptance" in fields and row["status"] in ("in_progress", "review"):
            before = set(json.loads(row["acceptance"]))
            if not before.issubset(fields["acceptance"]):
                raise DomainError("acceptance cannot be weakened while active", 409)
        deps = fields.pop("depends_on", None)
        if deps is not None:
            db.execute("DELETE FROM dependencies WHERE ticket_id=?", (row["id"],))
            for dep in deps:
                db.execute("INSERT INTO dependencies VALUES (?,?)", (row["id"], dep))
        updates = {k: _json(v) if k == "acceptance" else v for k, v in fields.items()}
        self._update_row(db, row["id"], updates)
        self._check_graph(db)
        after = self._ticket(db, row["id"])
        changed = sorted(set(fields) | ({"depends_on"} if deps is not None else set()))
        self._event(db, row["id"], actor, "update_ticket",
                    {"before": {key: before[key] for key in changed},
                     "after": {key: after[key] for key in changed}})
        return self._ticket(db, row["id"])

    def _actor_can_work(self, row, actor):
        if actor != "human" and self._actor_identity(actor) != self._actor_identity(row["assignee"]):
            raise DomainError("only assignee or human may work on this ticket", 409)

    @staticmethod
    def _actor_identity(actor):
        return actor.removeprefix("agent:") if isinstance(actor, str) else actor

    def _transition(self, db, data, actor):
        row = self._require_ticket(db, data.get("id"))
        self._expect(row, data)
        status = _choice(data.get("status"), {"backlog", "queued", "blocked", "cancelled"}, "status")
        reason = _optional_text(data.get("reason"), "reason") or ""
        if status == row["status"]:
            raise DomainError("ticket already has that status", 409)
        if status == "blocked" and not reason:
            raise DomainError("blocking requires a reason")
        if row["status"] == "done" and not reason:
            raise DomainError("reopening completed ticket requires a reason")
        if row["status"] in ("in_progress", "review") or (row["status"] == "blocked" and row["assignee"]):
            self._actor_can_work(row, actor)
        if row["status"] == "blocked" and not row["assignee"] and actor != "human":
            raise DomainError("only human may transition an unassigned blocked ticket", 409)
        changes = {"status": status, "blocked_reason": reason if status == "blocked" else ""}
        if status in ("backlog", "queued", "cancelled"):
            changes["assignee"] = None
        self._update_row(db, row["id"], changes)
        self._event(db, row["id"], actor, "transition", {"from": row["status"], "to": status, "reason": reason})
        return self._ticket(db, row["id"])

    def _claim(self, db, data, actor):
        row = self._require_ticket(db, data.get("id"))
        self._expect(row, data)
        assignee = _nonempty(data.get("assignee"), "assignee")
        if actor != "human" and self._actor_identity(actor) != self._actor_identity(assignee):
            raise DomainError("agent actor must match assignee", 409)
        ticket = self._ticket(db, row["id"])
        if not ticket["ready"]:
            raise DomainError("ticket is not queued and ready: " + "; ".join(ticket["blockers"]), 409)
        actual_model = _optional_text(data.get("actual_model"), "actual_model")
        actual_effort = _optional_text(data.get("actual_effort"), "actual_effort")
        if row["profile_id"] == "astra" and (actual_model not in (None, "gpt-6-astra") or
                                              actual_effort not in (None, "high")):
            raise DomainError("Astra coordinator claim conflicts with locked model or effort", 409)
        self._update_row(db, row["id"], {"status": "in_progress", "assignee": assignee,
                                         "actual_model": actual_model, "actual_effort": actual_effort})
        self._event(db, row["id"], actor, "claim_ticket", {"assignee": assignee, "actual_model": actual_model, "actual_effort": actual_effort})
        return self._ticket(db, row["id"])

    def _checkpoint(self, db, data, actor):
        row = self._require_ticket(db, data.get("id"))
        self._expect(row, data)
        if row["status"] != "in_progress":
            raise DomainError("checkpoint requires in_progress ticket", 409)
        self._actor_can_work(row, actor)
        note = _nonempty(data.get("checkpoint"), "checkpoint")
        self._update_row(db, row["id"], {"checkpoint": note})
        self._event(db, row["id"], actor, "checkpoint", {"checkpoint": note})
        return self._ticket(db, row["id"])

    def _submit(self, db, data, actor):
        row = self._require_ticket(db, data.get("id"))
        self._expect(row, data)
        if row["status"] != "in_progress":
            raise DomainError("submit requires in_progress ticket", 409)
        self._actor_can_work(row, actor)
        summary = _nonempty(data.get("summary"), "summary")
        evidence = _evidence(data.get("evidence"), nonempty=True)
        self._update_row(db, row["id"], {"status": "review", "checkpoint": summary, "evidence": _json(evidence)})
        self._event(db, row["id"], actor, "submit_ticket", {"summary": summary, "evidence": evidence})
        return self._ticket(db, row["id"])

    def _complete(self, db, data, actor):
        row = self._require_ticket(db, data.get("id"))
        self._expect(row, data)
        if row["status"] != "review":
            raise DomainError("complete requires review ticket", 409)
        if self._actor_identity(actor) == self._actor_identity(row["assignee"]):
            raise DomainError("assignee cannot review own work", 409)
        verification = _nonempty(data.get("verification"), "verification")
        accepted = _strings(data.get("accepted_criteria"), "accepted_criteria", nonempty=True)
        required = json.loads(row["acceptance"])
        if not required:
            raise DomainError("meaningful acceptance criteria required", 409)
        if set(required) != set(accepted):
            raise DomainError("accepted_criteria must match all acceptance criteria", 409)
        ticket = self._ticket(db, row["id"])
        if ticket["blockers"]:
            raise DomainError("cannot complete with blockers: " + "; ".join(ticket["blockers"]), 409)
        self._update_row(db, row["id"], {"status": "done"})
        self._event(db, row["id"], actor, "complete_ticket", {"reviewer": actor, "verification": verification, "accepted_criteria": accepted})
        return self._ticket(db, row["id"])

    def _help(self, db, data, actor):
        row = self._require_ticket(db, data.get("id"))
        self._expect(row, data)
        if row["status"] in ("done", "cancelled"):
            raise DomainError("cannot request help for closed ticket", 409)
        if row["status"] in ("in_progress", "review") or (row["status"] == "blocked" and row["assignee"]):
            self._actor_can_work(row, actor)
        title = _nonempty(data.get("title"), "title")
        description = _nonempty(data.get("description"), "description")
        profile_id = _optional_text(data.get("profile_id"), "profile_id")
        self._require_profile(db, profile_id)
        child = self._insert_ticket(db, {"title": title, "description": description, "type": "help",
                                         "parent_id": row["id"], "profile_id": profile_id,
                                         "acceptance": ["La ayuda solicitada está documentada y revisada."]},
                                    actor, "create_help")
        db.execute("INSERT INTO dependencies VALUES (?,?)", (row["id"], child["id"]))
        self._check_graph(db)
        self._update_row(db, row["id"], {"status": "blocked", "blocked_reason": f"Waiting for help {child['id']}: {title}"})
        self._event(db, row["id"], actor, "request_help", {"child_id": child["id"], "title": title})
        return {"parent": self._ticket(db, row["id"]), "child": self._ticket(db, child["id"])}

    def _split(self, db, data, actor):
        row = self._require_ticket(db, data.get("id"))
        self._expect(row, data)
        if row["status"] in ("done", "cancelled"):
            raise DomainError("cannot split closed ticket", 409)
        if row["status"] in ("in_progress", "review") or (row["status"] == "blocked" and row["assignee"]):
            self._actor_can_work(row, actor)
        raw = data.get("children")
        if not isinstance(raw, list) or not raw:
            raise DomainError("children must be a nonempty array")
        children = []
        for child in raw:
            if not isinstance(child, dict) or set(child) - {"title", "description", "profile_id", "acceptance"}:
                raise DomainError("invalid split child fields")
            children.append(self._insert_ticket(db, {"priority": row["priority"],
                                                    "profile_id": row["profile_id"],
                                                    **child, "parent_id": row["id"]},
                                                actor, "create_split_child"))
        self._update_row(db, row["id"], {"status": "blocked", "blocked_reason": "Waiting for split children"})
        self._event(db, row["id"], actor, "split_ticket", {"children": [x["id"] for x in children]})
        return {"parent": self._ticket(db, row["id"]), "children": children}

    def _profile_fields(self, fields, *, creating=False):
        if not isinstance(fields, dict) or set(fields) - PROFILE_EDITABLE:
            raise DomainError("invalid profile fields")
        out = {}
        for key, value in fields.items():
            if key in ("name", "role", "model"):
                out[key] = _nonempty(value, key)
            elif key in ("provider", "description"):
                if not isinstance(value, str):
                    raise DomainError(f"{key} must be a string")
                out[key] = value.strip()
            elif key == "effort":
                out[key] = _choice(value, EFFORTS, key)
            elif key == "preference":
                out[key] = _choice(value, PREFERENCES, key)
            elif key == "capabilities":
                out[key] = _strings(value, key)
        if creating and any(k not in out for k in ("name", "role", "model")):
            raise DomainError("name, role, and model are required")
        return out

    def _create_profile(self, db, data, actor):
        fields = self._profile_fields(data, creating=True)
        profile_id = self._next_profile_id(db)
        db.execute("INSERT INTO profiles VALUES(?,?,?,?,?,?,?,?,?)",
                   (profile_id, fields["name"], fields["role"], fields.get("provider", ""),
                    fields["model"], fields.get("effort", "medium"), _json(fields.get("capabilities", [])),
                    fields.get("preference", "balanced"), fields.get("description", "")))
        created = self._profile(db.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone())
        self._event(db, None, actor, "create_profile", {"after": created})
        return created

    def _update_profile(self, db, data, actor):
        profile_id = _nonempty(data.get("id"), "id")
        row = db.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()
        if row is None:
            raise DomainError(f"profile {profile_id} not found", 404)
        fields = self._profile_fields({k: v for k, v in data.items() if k != "id"})
        if not fields:
            raise DomainError("no fields to update")
        if profile_id == "astra" and (fields.get("model", row["model"]) != "gpt-6-astra" or
                                      fields.get("role", row["role"]) != "coordinator" or
                                      fields.get("effort", row["effort"]) != "high"):
            raise DomainError("Astra coordinator model and effort are locked", 409)
        before = self._profile(row)
        fields = {key: _json(value) if key == "capabilities" else value for key, value in fields.items()}
        db.execute("UPDATE profiles SET " + ", ".join(f"{key}=?" for key in fields) + " WHERE id=?",
                   (*fields.values(), profile_id))
        updated = self._profile(db.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone())
        self._event(db, None, actor, "update_profile",
                    {"profile_id": profile_id,
                     "before": {key: before[key] for key in fields},
                     "after": {key: updated[key] for key in fields}})
        return updated

    def action(self, action: str, data: dict, actor: str = "human"):
        if not isinstance(data, dict):
            raise DomainError("data must be an object")
        actor = _nonempty(actor, "actor")
        with self._write() as db:
            if action == "create_plan":
                return self._create_plan(db, data, actor)
            if action == "create_ticket":
                return self._insert_ticket(db, data, actor)
            if action == "update_ticket":
                return self._update_ticket(db, data, actor)
            if action == "transition":
                return self._transition(db, data, actor)
            if action == "claim_ticket":
                return self._claim(db, data, actor)
            if action == "checkpoint":
                return self._checkpoint(db, data, actor)
            if action == "submit_ticket":
                return self._submit(db, data, actor)
            if action == "complete_ticket":
                return self._complete(db, data, actor)
            if action == "request_help":
                return self._help(db, data, actor)
            if action == "split_ticket":
                return self._split(db, data, actor)
            if action == "add_comment":
                row = self._require_ticket(db, data.get("id"))
                body = _nonempty(data.get("body"), "body")
                self._event(db, row["id"], actor, "add_comment", {"body": body})
                return self._ticket(db, row["id"])
            if action == "create_profile":
                return self._create_profile(db, data, actor)
            if action == "update_profile":
                return self._update_profile(db, data, actor)
            raise DomainError(f"unknown action: {action}")

    def seed_demo(self):
        """Install fictional examples only when explicitly requested on an empty DB."""
        with self._write() as db:
            if db.execute("SELECT 1 FROM metadata WHERE key='demo_seeded'").fetchone():
                return False
            if db.execute("SELECT 1 FROM tickets LIMIT 1").fetchone():
                raise DomainError("demo requires an empty ticket database", 409)

            def make(title, **kwargs):
                return self._insert_ticket(db, {"title": title, **kwargs}, "demo")

            objective = make("DEMO FICTICIA · Publicar una guía local accesible", type="objective", priority="high",
                             description="Ejemplo de coordinación editorial; no representa trabajo real.",
                             acceptance=["La guía se revisa con teclado y lector de pantalla."])
            outline = make("Definir índice y público de la guía", parent_id=objective["id"], priority="high",
                           description="Acordar capítulos, personas lectoras y temas fuera de alcance.",
                           acceptance=["Índice aprobado con público y alcance explícitos."], profile_id="sol")
            pdf = make("Preparar PDF accesible", parent_id=objective["id"], priority="high", type="objective",
                       description="Coordinar estructura, alternativas de figuras y revisión asistida.",
                       acceptance=["PDF etiquetado y revisado en lector de pantalla."])
            structure = make("Comprobar encabezados y orden de lectura", parent_id=pdf["id"], profile_id="terra",
                             description="Inspeccionar la secuencia de títulos, listas y tablas en el PDF de muestra.",
                             acceptance=["Jerarquía de títulos y lectura documentadas."])
            alt = make("Escribir textos alternativos de figuras", parent_id=pdf["id"], profile_id="luna",
                       description="Resumir el significado de cada figura sin repetir su pie.",
                       acceptance=["Cada figura informativa tiene alternativa útil."])
            help_ticket = make("Resolver criterio de contraste de diagramas", parent_id=alt["id"], type="help",
                               description="Documentar una regla de contraste aplicable a los diagramas de ejemplo.",
                               acceptance=["Criterio de contraste documentado y revisado."])
            qa = make("Revisar PDF con lector de pantalla", parent_id=pdf["id"], type="review",
                      description="Recorrer la guía de principio a fin y registrar obstáculos de navegación.",
                      depends_on=[structure["id"], alt["id"]],
                      acceptance=["Recorrido de lectura con incidencias registradas."])
            release = make("Redactar nota de publicación", parent_id=objective["id"], priority="low",
                           description="Explicar audiencia, contenido, cambios y limitaciones conocidas.",
                           depends_on=[pdf["id"]], acceptance=["Nota clara sobre contenido y límites."])
            # Genuine fictional states, with no claim that a model ran or verified anything.
            self._update_row(db, outline["id"], {"status": "done", "checkpoint": "Índice ficticio revisado para esta muestra.",
                                                  "evidence": _json([{"kind": "note", "label": "Ejemplo de índice", "uri": "demo://indice"}])})
            self._event(db, outline["id"], "demo", "demo_review", {"verification": "Revisión ficticia de interfaz, no una comprobación real."})
            self._update_row(db, structure["id"], {"status": "review", "checkpoint": "Pendiente de revisión humana en esta demo.",
                                                    "evidence": _json([{"kind": "note", "label": "Lista ilustrativa", "uri": "demo://encabezados"}])})
            self._event(db, structure["id"], "demo", "demo_state", {"status": "review", "fictitious": True})
            self._update_row(db, alt["id"], {"status": "blocked", "blocked_reason": f"Waiting for help {help_ticket['id']}"})
            db.execute("INSERT INTO dependencies VALUES (?,?)", (alt["id"], help_ticket["id"]))
            self._event(db, alt["id"], "demo", "demo_state", {"status": "blocked", "fictitious": True})
            self._update_row(db, qa["id"], {"status": "backlog"})
            self._event(db, qa["id"], "demo", "demo_state", {"status": "backlog", "fictitious": True})
            self._check_graph(db)
            db.execute("INSERT INTO metadata(key,value) VALUES('demo_seeded','1')")
            return True
