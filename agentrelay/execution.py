"""Explicit, local subprocess execution for AgentRelay tickets.

Worker commands come only from a trusted JSON configuration file supplied to
the process. Tickets and HTTP requests cannot specify a command or working
directory. A worker's declared model is metadata, not provider attestation.
"""

from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .store import DomainError, EFFORTS, Store

if os.name == "nt":
    import msvcrt
else:
    import fcntl


MAX_OUTPUT = 1_048_576
MAX_SUMMARY = 4096
POLL_INTERVAL = 0.05


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _required_string(value, field: str, limit: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise DomainError(f"{field} must be a nonempty string up to {limit} characters")
    return value.strip()


@dataclass(frozen=True)
class Worker:
    id: str
    name: str
    command: tuple[str, ...]
    cwd: str
    model: str
    effort: str
    profile_ids: tuple[str, ...]
    timeout_seconds: int

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "model": self.model,
                "effort": self.effort, "profile_ids": list(self.profile_ids),
                "timeout_seconds": self.timeout_seconds}


@dataclass
class _Handle:
    run_id: str
    lock: threading.RLock = field(default_factory=threading.RLock)
    cancelled: threading.Event = field(default_factory=threading.Event)
    process: subprocess.Popen | None = None
    thread: threading.Thread | None = None


class ExecutionManager:
    """Runs at most one configured worker against a shared SQLite database."""

    def __init__(self, store: Store, config_path: str | Path | None = None):
        self.store = store
        self.id = uuid.uuid4().hex
        self._lock = threading.RLock()
        self._handles: dict[str, _Handle] = {}
        self._closed = False
        self._process_lock = None
        self.workers = self._load_workers(config_path) if config_path is not None else {}
        self.enabled = config_path is not None
        self._init_schema()
        if self.enabled:
            self._acquire_process_lock()
            try:
                self._recover()
            except Exception:
                self._release_process_lock()
                raise

    def _acquire_process_lock(self):
        path = Path(self.store.path + ".execution.lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise DomainError("another execution manager owns this database", 409) from exc
        self._process_lock = handle

    def _release_process_lock(self):
        handle = self._process_lock
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self._process_lock = None

    def _load_workers(self, config_path) -> dict[str, Worker]:
        path = Path(config_path).expanduser().resolve()
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise DomainError(f"cannot read worker configuration: {type(exc).__name__}") from exc
        if not isinstance(config, dict) or set(config) != {"workers"} or not isinstance(config["workers"], list):
            raise DomainError("worker configuration must contain a workers array")
        known_profiles = {p["id"] for p in self.store.state()["profiles"]}
        result: dict[str, Worker] = {}
        for item in config["workers"]:
            required = {"id", "name", "command", "cwd", "model", "effort", "profile_ids", "timeout_seconds"}
            if not isinstance(item, dict) or set(item) != required:
                raise DomainError("each worker requires id, name, command, cwd, model, effort, profile_ids and timeout_seconds")
            worker_id = _required_string(item["id"], "worker.id", 64)
            if not all(c.isascii() and (c.isalnum() or c in "_-") for c in worker_id):
                raise DomainError("worker.id must contain ASCII letters, digits, _ or -")
            if worker_id in result:
                raise DomainError(f"duplicate worker id: {worker_id}")
            name = _required_string(item["name"], "worker.name", 120)
            model = _required_string(item["model"], "worker.model", 120)
            effort = item["effort"]
            if not isinstance(effort, str) or effort not in EFFORTS:
                raise DomainError("worker.effort is invalid")
            command = item["command"]
            if not isinstance(command, list) or not command or any(not isinstance(arg, str) or not arg for arg in command):
                raise DomainError("worker.command must be a nonempty argv array")
            cwd_raw = item["cwd"]
            if not isinstance(cwd_raw, str) or not cwd_raw.strip():
                raise DomainError("worker.cwd must be a directory path")
            cwd = Path(cwd_raw)
            if not cwd.is_absolute():
                cwd = path.parent / cwd
            cwd = cwd.resolve()
            if not cwd.is_dir():
                raise DomainError(f"worker.cwd does not exist: {cwd}")
            profiles = item["profile_ids"]
            if (not isinstance(profiles, list) or any(not isinstance(x, str) or x not in known_profiles for x in profiles)
                    or len(profiles) != len(set(profiles))):
                raise DomainError("worker.profile_ids must list distinct existing profile IDs")
            timeout = item["timeout_seconds"]
            if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 3600:
                raise DomainError("worker.timeout_seconds must be an integer from 1 to 3600")
            if "astra" in profiles and (model != "gpt-6-astra" or effort != "high"):
                raise DomainError("Astra worker must declare gpt-6-astra at high effort", 409)
            result[worker_id] = Worker(worker_id, name, tuple(command), str(cwd), model, effort,
                                       tuple(profiles), timeout)
        return result

    def _init_schema(self):
        with self.store._write() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS execution_runs (
                id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL REFERENCES tickets(id),
                worker_id TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL,
                finished_at TEXT, summary TEXT NOT NULL, error TEXT NOT NULL,
                model TEXT NOT NULL, effort TEXT NOT NULL, claim_revision INTEGER NOT NULL,
                actor TEXT NOT NULL, owner_instance TEXT NOT NULL, owner_pid INTEGER NOT NULL
            )""")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_running_run ON execution_runs((1)) WHERE status='running'")

    @staticmethod
    def _public_run(row) -> dict:
        return {key: row[key] for key in ("id", "ticket_id", "worker_id", "status", "started_at",
                                         "finished_at", "summary", "error", "model", "effort")}

    def snapshot(self) -> dict:
        with self.store._connection() as db:
            runs = [self._public_run(row) for row in db.execute("SELECT * FROM execution_runs ORDER BY started_at DESC, id DESC LIMIT 100")]
        return {"workers": [worker.public() for worker in self.workers.values()],
                "runs": runs, "enabled": self.enabled}

    def _run(self, db, run_id):
        row = db.execute("SELECT * FROM execution_runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise DomainError(f"run {run_id} not found", 404)
        return row

    def _owned_current(self, db, run) -> bool:
        ticket = self.store._require_ticket(db, run["ticket_id"])
        return (ticket["revision"] == run["claim_revision"] and
                ticket["status"] == "in_progress" and ticket["assignee"] == run["actor"])

    def _block_owned(self, db, run, reason: str):
        if self._owned_current(db, run):
            self.store._transition(db, {"id": run["ticket_id"], "expected_revision": run["claim_revision"],
                                        "status": "blocked", "reason": reason}, run["actor"])
            return True
        return False

    def _recover(self):
        with self.store._write() as db:
            for run in db.execute("SELECT * FROM execution_runs WHERE status='running'").fetchall():
                self._block_owned(db, run, "Worker process interrupted; review checkpoint before retry")
                db.execute("UPDATE execution_runs SET status='interrupted',finished_at=?,error=? WHERE id=?",
                           (_now(), "Worker manager stopped before completion", run["id"]))

    def start(self, ticket_id: str, worker_id: str, expected_revision: int) -> dict:
        with self._lock:
            if self._closed:
                raise DomainError("execution manager is closed", 409)
            if not self.enabled:
                raise DomainError("worker execution is disabled", 409)
            worker = self.workers.get(worker_id)
            if worker is None:
                raise DomainError(f"worker {worker_id} not configured", 404)
            run_id = "run-" + uuid.uuid4().hex
            actor = "agent:" + run_id
            try:
                with self.store._write() as db:
                    if db.execute("SELECT 1 FROM execution_runs WHERE status='running' LIMIT 1").fetchone():
                        raise DomainError("another worker run is active", 409)
                    ticket = self.store._require_ticket(db, ticket_id)
                    if worker.profile_ids and ticket["profile_id"] not in worker.profile_ids:
                        raise DomainError("worker is not configured for ticket profile", 409)
                    if not json.loads(ticket["acceptance"]):
                        raise DomainError("worker execution requires ticket acceptance criteria", 409)
                    if ticket["profile_id"] == "astra" and (worker.model != "gpt-6-astra" or worker.effort != "high"):
                        raise DomainError("Astra ticket requires gpt-6-astra at high effort", 409)
                    claimed = self.store._claim(db, {"id": ticket_id, "expected_revision": expected_revision,
                                                     "assignee": actor, "actual_model": worker.model,
                                                     "actual_effort": worker.effort}, actor)
                    db.execute("""INSERT INTO execution_runs
                        (id,ticket_id,worker_id,status,started_at,finished_at,summary,error,model,effort,
                         claim_revision,actor,owner_instance,owner_pid)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (run_id, ticket_id, worker.id, "running", _now(), None, "", "", worker.model,
                         worker.effort, claimed["revision"], actor, self.id, os.getpid()))
                    result = self._public_run(self._run(db, run_id))
            except sqlite3.IntegrityError as exc:
                raise DomainError("another worker run is active", 409) from exc
            handle = _Handle(run_id)
            thread = threading.Thread(target=self._execute, args=(handle, worker),
                                      name=f"AgentRelay-{run_id[:12]}", daemon=True)
            handle.thread = thread
            self._handles[run_id] = handle
            try:
                thread.start()
            except Exception as exc:
                self._finalize_error(run_id, "Worker thread could not start", "failed")
                self._handles.pop(run_id, None)
                raise DomainError(f"worker thread could not start: {type(exc).__name__}", 500) from exc
            return result

    @staticmethod
    def _stop_process(process: subprocess.Popen):
        if process.poll() is not None:
            return
        if os.name == "nt":
            try:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=5, check=False)
            except (OSError, subprocess.TimeoutExpired):
                pass  # The direct kill below remains the fallback.
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    def _persist_logs(self, run_id, stdout_file, stderr_file):
        """Keep bounded local diagnostics; never include these bytes in snapshots."""
        try:
            directory = Path(self.store.path).parent / "runs" / run_id
            directory.mkdir(parents=True, exist_ok=True)
            if os.name != "nt":
                directory.chmod(0o700)
            for source, filename in ((stdout_file, "stdout.json"), (stderr_file, "stderr.log")):
                source.seek(0)
                target = directory / filename
                with target.open("wb") as output:
                    output.write(source.read(MAX_OUTPUT))
                if os.name != "nt":
                    target.chmod(0o600)
        except OSError:
            pass  # Diagnostics cannot change the ticket outcome.

    def _execute(self, handle: _Handle, worker: Worker):
        process = None
        try:
            if handle.cancelled.is_set():
                return
            with self.store._connection() as db:
                run = self._run(db, handle.run_id)
            context = self.store.context(run["ticket_id"], event_limit=20)
            context["instructions"] += (
                " Events contain recent history only; events_page.next_before_id identifies older events."
                " Retrieve older history through an authorized read-only connection when needed, or request missing context."
                " Do not assume omitted history is absent."
            )
            request = {"protocol": "agentrelay.worker.v1", "context": context,
                       "worker": {"id": worker.id, "model": worker.model, "effort": worker.effort}}
            payload = (json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8")
            with tempfile.TemporaryFile(mode="w+b") as stdin_file, \
                 tempfile.TemporaryFile(mode="w+b") as stdout_file, \
                 tempfile.TemporaryFile(mode="w+b") as stderr_file:
                try:
                    stdin_file.write(payload)
                    stdin_file.seek(0)
                    if handle.cancelled.is_set():
                        return
                    environment = os.environ.copy()
                    environment["PYTHONUTF8"] = "1"
                    environment["PYTHONIOENCODING"] = "utf-8"
                    options = {"stdin": stdin_file, "stdout": stdout_file, "stderr": stderr_file,
                               "cwd": worker.cwd, "shell": False, "close_fds": True, "env": environment}
                    if os.name == "nt":
                        options["creationflags"] = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) |
                                                    getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    else:
                        options["start_new_session"] = True
                    process = subprocess.Popen(worker.command, **options)
                    with handle.lock:
                        handle.process = process
                        if handle.cancelled.is_set():
                            self._stop_process(process)
                            return
                    deadline = time.monotonic() + worker.timeout_seconds
                    while process.poll() is None:
                        if handle.cancelled.is_set():
                            self._stop_process(process)
                            return
                        if os.fstat(stdout_file.fileno()).st_size > MAX_OUTPUT or os.fstat(stderr_file.fileno()).st_size > MAX_OUTPUT:
                            self._stop_process(process)
                            self._finalize_error(handle.run_id, "Worker output exceeded 1 MiB", "failed")
                            return
                        if time.monotonic() >= deadline:
                            self._stop_process(process)
                            self._finalize_error(handle.run_id, "Worker timed out", "failed")
                            return
                        time.sleep(POLL_INTERVAL)
                    if handle.cancelled.is_set():
                        return
                    if os.fstat(stdout_file.fileno()).st_size > MAX_OUTPUT or os.fstat(stderr_file.fileno()).st_size > MAX_OUTPUT:
                        self._finalize_error(handle.run_id, "Worker output exceeded 1 MiB", "failed")
                        return
                    if process.returncode != 0:
                        self._finalize_error(handle.run_id, f"Worker exited with code {process.returncode}", "failed")
                        return
                    stdout_file.seek(0)
                    raw = stdout_file.read(MAX_OUTPUT + 1)
                    try:
                        result = json.loads(raw.decode("utf-8", errors="strict"))
                        result = self._validate_result(result)
                    except (UnicodeError, json.JSONDecodeError, DomainError):
                        self._finalize_error(handle.run_id, "Worker returned invalid protocol JSON", "failed")
                        return
                    self._apply_result(handle.run_id, result)
                finally:
                    if process is not None and process.poll() is None:
                        self._stop_process(process)
                    self._persist_logs(handle.run_id, stdout_file, stderr_file)
        except Exception as exc:
            self._finalize_error(handle.run_id, f"Worker execution failed: {type(exc).__name__}", "failed")
        finally:
            with self._lock:
                self._handles.pop(handle.run_id, None)

    @staticmethod
    def _validate_result(value) -> dict:
        allowed = {"outcome", "summary", "evidence", "title", "description", "profile_id", "children"}
        if not isinstance(value, dict) or set(value) - allowed:
            raise DomainError("invalid worker output fields")
        outcome = value.get("outcome")
        if outcome not in ("submit", "help", "split", "blocked"):
            raise DomainError("invalid worker outcome")
        summary = _required_string(value.get("summary"), "summary", MAX_SUMMARY)
        evidence = value.get("evidence", [])
        if not isinstance(evidence, list):
            raise DomainError("evidence must be an array")
        if outcome == "submit" and not evidence:
            raise DomainError("submit requires evidence")
        title = value.get("title")
        description = value.get("description")
        profile_id = value.get("profile_id")
        children = value.get("children")
        if outcome == "help":
            _required_string(title, "title", 200)
            _required_string(description, "description", 4000)
            if profile_id is not None and (not isinstance(profile_id, str) or not profile_id.strip()):
                raise DomainError("profile_id must be a string or null")
        if outcome == "split":
            if not isinstance(children, list) or not 1 <= len(children) <= 16:
                raise DomainError("split requires 1 to 16 children")
        return {"outcome": outcome, "summary": summary, "evidence": evidence,
                "title": title, "description": description, "profile_id": profile_id,
                "children": children}

    def _apply_result(self, run_id: str, result: dict):
        try:
            with self.store._write() as db:
                run = self._run(db, run_id)
                if run["status"] != "running":
                    return
                if not self._owned_current(db, run):
                    db.execute("UPDATE execution_runs SET status='conflict',finished_at=?,error=? WHERE id=?",
                               (_now(), "Ticket changed during worker run", run_id))
                    return
                ticket_id = run["ticket_id"]
                rev = run["claim_revision"]
                actor = run["actor"]
                outcome = result["outcome"]
                if outcome == "submit":
                    self.store._submit(db, {"id": ticket_id, "expected_revision": rev,
                                            "summary": result["summary"], "evidence": result["evidence"]}, actor)
                    status = "submitted"
                else:
                    checkpointed = self.store._checkpoint(db, {"id": ticket_id, "expected_revision": rev,
                                                                 "checkpoint": result["summary"]}, actor)
                    rev = checkpointed["revision"]
                    if outcome == "help":
                        self.store._help(db, {"id": ticket_id, "expected_revision": rev,
                                              "title": result["title"], "description": result["description"],
                                              "profile_id": result["profile_id"]}, actor)
                        status = "help_requested"
                    elif outcome == "split":
                        self.store._split(db, {"id": ticket_id, "expected_revision": rev,
                                               "children": result["children"]}, actor)
                        status = "split"
                    else:
                        self.store._transition(db, {"id": ticket_id, "expected_revision": rev,
                                                    "status": "blocked", "reason": result["summary"]}, actor)
                        status = "blocked"
                db.execute("UPDATE execution_runs SET status=?,finished_at=?,summary=?,error='' WHERE id=?",
                           (status, _now(), result["summary"], run_id))
        except DomainError as exc:
            self._finalize_error(run_id, f"Worker result rejected: {str(exc)[:160]}", "failed")

    def _finalize_error(self, run_id: str, error: str, status: str):
        with self.store._write() as db:
            run = self._run(db, run_id)
            if run["status"] != "running":
                return
            current = self._owned_current(db, run)
            if current:
                self._block_owned(db, run, error[:240])
            elif status == "failed":
                status = "conflict"
                error = "Ticket changed during worker run"
            db.execute("UPDATE execution_runs SET status=?,finished_at=?,error=? WHERE id=?",
                       (status, _now(), error[:240], run_id))

    def cancel(self, run_id: str) -> dict:
        with self._lock:
            handle = self._handles.get(run_id)
            if handle is None:
                with self.store._connection() as db:
                    run = self._run(db, run_id)
                if run["status"] == "running":
                    raise DomainError("run belongs to another manager", 409)
                return self._public_run(run)
            with handle.lock:
                handle.cancelled.set()
                if handle.process is not None and handle.process.poll() is None:
                    self._stop_process(handle.process)
                self._finalize_error(run_id, "Worker run cancelled", "cancelled")
            with self.store._connection() as db:
                return self._public_run(self._run(db, run_id))

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            run_ids = list(self._handles)
        for run_id in run_ids:
            try:
                self.cancel(run_id)
            except DomainError:
                pass
        for handle in list(self._handles.values()):
            if handle.thread is not None:
                handle.thread.join(timeout=5)
        self._release_process_lock()
