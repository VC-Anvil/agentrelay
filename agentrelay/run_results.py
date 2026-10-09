"""Read one persisted worker proposal without starting or replaying execution."""

import json

from .store import DomainError, Store


PUBLIC_RUN_FIELDS = ("id", "ticket_id", "worker_id", "status", "started_at",
                     "finished_at", "summary", "error", "model", "effort")
MAX_RESULT_JSON = 4_194_304  # ASCII escaping can expand a valid 1 MiB UTF-8 worker output.


def _invalid_constant(value):
    raise ValueError(f"non-finite JSON constant {value}")


def get_run_result(store: Store, run_id: str) -> dict:
    """Return a run, its captured protocol result, and current ticket in one read transaction."""
    if not isinstance(run_id, str) or not run_id.strip():
        raise DomainError("run_id must be a nonempty string")
    with store._connection() as db:
        db.execute("BEGIN")
        table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_runs'").fetchone()
        if table is None:
            raise DomainError(f"run {run_id} not found", 404)
        columns = {row[1] for row in db.execute("PRAGMA table_info(execution_runs)")}
        selected = ",".join((*PUBLIC_RUN_FIELDS, "claim_revision", "actor"))
        if "result_json" in columns:
            selected += ",length(CAST(result_json AS BLOB)) AS result_bytes"
        run = db.execute(f"SELECT {selected} FROM execution_runs WHERE id=?", (run_id,)).fetchone()
        if run is None:
            raise DomainError(f"run {run_id} not found", 404)
        ticket = db.execute("SELECT id,revision,status,assignee FROM tickets WHERE id=?",
                            (run["ticket_id"],)).fetchone()
        if ticket is None:
            raise DomainError(f"ticket {run['ticket_id']} not found", 404)
        if "result_json" in columns and run["result_bytes"] is not None:
            if run["result_bytes"] > MAX_RESULT_JSON:
                raise DomainError("stored worker result exceeds limit", 500)
            raw_result = db.execute("SELECT result_json FROM execution_runs WHERE id=?", (run_id,)).fetchone()[0]
            try:
                result = json.loads(raw_result, parse_constant=_invalid_constant)
            except (TypeError, ValueError, UnicodeError) as exc:
                raise DomainError("stored worker result is invalid", 500) from exc
            if not isinstance(result, dict):
                raise DomainError("stored worker result is not an object", 500)
        else:
            result = None
        response = {
            "schema_version": 1,
            "run": {**{field: run[field] for field in PUBLIC_RUN_FIELDS},
                    "claim_revision": run["claim_revision"], "actor": run["actor"]},
            "result": result,
            "current_ticket": {field: ticket[field] for field in ("id", "revision", "status", "assignee")},
        }
        db.commit()
        return response
