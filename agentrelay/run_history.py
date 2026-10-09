"""Bounded, read-only discovery of execution runs across one AgentRelay database."""

from .run_results import PUBLIC_RUN_FIELDS
from .store import DomainError, Store


RUN_STATUSES = frozenset({"running", "submitted", "help_requested", "split", "blocked",
                          "failed", "conflict", "cancelled", "interrupted"})


def _optional_identifier(value, name):
    if value is not None and (not isinstance(value, str) or not value or value != value.strip()):
        raise DomainError(f"{name} must be a nonempty string without surrounding whitespace")
    return value


def list_runs(store: Store, *, ticket_id=None, status=None, limit=20, before_id=None) -> dict:
    """Page run metadata by immutable start time and ID; never load proposal bodies."""
    ticket_id = _optional_identifier(ticket_id, "ticket_id")
    before_id = _optional_identifier(before_id, "before_id")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise DomainError("limit must be an integer from 1 to 100")
    if status is not None and (not isinstance(status, str) or status not in RUN_STATUSES):
        raise DomainError("invalid run status")

    with store._connection() as db:
        db.execute("BEGIN")
        if ticket_id is not None and db.execute("SELECT 1 FROM tickets WHERE id=?", (ticket_id,)).fetchone() is None:
            raise DomainError(f"ticket {ticket_id} not found", 404)
        table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_runs'").fetchone()
        if table is None:
            if before_id is not None:
                raise DomainError(f"run {before_id} not found", 404)
            db.commit()
            return {"runs": [], "ticket_id": ticket_id, "status": status, "total": 0,
                    "count": 0, "limit": limit, "before_id": None, "next_before_id": None}

        anchor = None
        if before_id is not None:
            anchor = db.execute("SELECT ticket_id,started_at,id FROM execution_runs WHERE id=?",
                                (before_id,)).fetchone()
            if anchor is None:
                raise DomainError(f"run {before_id} not found", 404)
            if ticket_id is not None and anchor["ticket_id"] != ticket_id:
                raise DomainError("before_id belongs to a different ticket")

        filters, parameters = [], []
        if ticket_id is not None:
            filters.append("ticket_id=?")
            parameters.append(ticket_id)
        if status is not None:
            filters.append("status=?")
            parameters.append(status)
        where = " WHERE " + " AND ".join(filters) if filters else ""
        total = db.execute("SELECT COUNT(*) FROM execution_runs" + where, parameters).fetchone()[0]

        page_filters = list(filters)
        page_parameters = list(parameters)
        if anchor is not None:
            page_filters.append("(started_at < ? OR (started_at = ? AND id < ?))")
            page_parameters.extend((anchor["started_at"], anchor["started_at"], anchor["id"]))
        page_where = " WHERE " + " AND ".join(page_filters) if page_filters else ""
        columns = {row[1] for row in db.execute("PRAGMA table_info(execution_runs)")}
        has_result = "result_json IS NOT NULL" if "result_json" in columns else "0"
        selected = ",".join(PUBLIC_RUN_FIELDS) + f",{has_result} AS has_result"
        rows = db.execute(f"SELECT {selected} FROM execution_runs" + page_where +
                          " ORDER BY started_at DESC,id DESC LIMIT ?", (*page_parameters, limit + 1)).fetchall()
        page = rows[:limit]
        runs = [{**{field: row[field] for field in PUBLIC_RUN_FIELDS},
                 "has_result": bool(row["has_result"])} for row in page]
        next_before_id = page[-1]["id"] if len(rows) > limit else None
        db.commit()
        return {"runs": runs, "ticket_id": ticket_id, "status": status, "total": total,
                "count": len(runs), "limit": limit, "before_id": before_id,
                "next_before_id": next_before_id}
