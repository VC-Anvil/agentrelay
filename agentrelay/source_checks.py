"""Historical, advisory comparisons of explicit snapshots and source roots.

Only local Python callers run a comparison. Read methods never inspect the
filesystem paths stored in a report or accept a report supplied by a client.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

from .freshness import compare_snapshot
from .store import DomainError, Store, _utc


MAX_REPORT_BYTES = 1_048_576
_SNAPSHOT_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_STATUSES = ("unchanged", "modified", "missing", "uncheckable")
_RECEIPT_KEYS = {"schema_version", "check_id", "request_id", "ticket_id",
                 "ticket_revision", "actor", "method", "snapshot_id",
                 "report_sha256", "summary", "checked_at", "recorded_at"}


def _positive(value, name: str) -> int:
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise DomainError(f"{name} must be an integer from 1 to 2**63-1")
    return value


def _limit(value) -> int:
    if type(value) is not int or not 1 <= value <= 100:
        raise DomainError("limit must be an integer from 1 to 100")
    return value


def _selection(value, name: str) -> str:
    if not isinstance(value, (str, os.PathLike)):
        raise DomainError(f"{name} must be a filesystem path")
    try:
        raw = os.fspath(value)
        if not isinstance(raw, str) or not raw or "\x00" in raw:
            raise ValueError("empty or invalid path")
        # abspath is lexical here: no resolve(), lstat(), or source read.
        return os.path.abspath(os.path.expanduser(raw))
    except (OSError, ValueError, RuntimeError, TypeError) as exc:
        raise DomainError(f"{name} must be a valid filesystem path") from exc


def _canonical(value) -> tuple[str, bytes]:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
        return raw.decode("utf-8"), raw
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise DomainError("source check data is not valid JSON") from exc


def _summary(report: dict) -> dict:
    files = report.get("files") if isinstance(report, dict) else None
    if (not isinstance(files, list) or not 1 <= len(files) <= 64
            or any(not isinstance(item, dict) or item.get("status") not in _STATUSES
                   for item in files)):
        raise DomainError("source comparison report is invalid", 500)
    result = {"total": len(files), **{status: 0 for status in _STATUSES}}
    for item in files:
        result[item["status"]] += 1
    return result


def _receipt(row) -> dict:
    try:
        value = json.loads(row["receipt_json"])
        if (not isinstance(value, dict) or set(value) != _RECEIPT_KEYS
                or value["schema_version"] != 1 or value["check_id"] != row["id"]):
            raise ValueError("invalid stored receipt")
        return value
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise DomainError("stored source check receipt is invalid", 500) from exc


def _existing(db, request_id: str, actor: str, intent_json: str, intent_sha256: str):
    row = db.execute("SELECT id,actor,intent_json,intent_sha256,receipt_json "
                     "FROM source_checks WHERE request_id=?", (request_id,)).fetchone()
    if row is not None:
        if (row["actor"] != actor or row["intent_json"] != intent_json
                or row["intent_sha256"] != intent_sha256):
            raise DomainError("request_id already used with different actor or intent", 409)
        return _receipt(row)
    for table in ("plan_requests", "claim_requests", "action_requests"):
        if db.execute(f"SELECT 1 FROM {table} WHERE request_id=?", (request_id,)).fetchone():
            raise DomainError(f"request_id already used by {table}", 409)
    return None


def check_sources(store: Store, *, ticket_id, expected_revision, snapshot,
                  expected_snapshot_id, root, request_id, actor) -> dict:
    """Compare explicit local inputs and append one immutable ticket observation."""
    ticket_id = Store._plan_identifier(ticket_id, "ticket_id", 128)
    expected_revision = _positive(expected_revision, "expected_revision")
    request_id = Store._plan_identifier(request_id, "request_id", 128)
    actor = Store._plan_identifier(actor, "actor", 128)
    if not isinstance(expected_snapshot_id, str) or not _SNAPSHOT_ID.fullmatch(expected_snapshot_id):
        raise DomainError("expected_snapshot_id must be sha256: plus 64 lowercase hex characters")
    snapshot_path = _selection(snapshot, "snapshot")
    root_path = _selection(root, "root")
    intent_json, intent_bytes = _canonical({
        "ticket_id": ticket_id, "expected_revision": expected_revision,
        "expected_snapshot_id": expected_snapshot_id, "actor": actor,
        "snapshot": snapshot_path, "root": root_path,
    })
    intent_sha256 = hashlib.sha256(intent_bytes).hexdigest()

    # The receipt lookup precedes ticket and filesystem reads. A replay remains
    # historical even if the selected directories have disappeared.
    with store._connection() as db:
        db.execute("BEGIN")
        prior = _existing(db, request_id, actor, intent_json, intent_sha256)
        if prior is not None:
            db.commit()
            return prior
        row = store._require_ticket(db, ticket_id)
        store._expect(row, {"expected_revision": expected_revision})
        db.commit()

    report = compare_snapshot(Path(snapshot_path), Path(root_path),
                              expected_snapshot_id=expected_snapshot_id)
    checked_at = _utc()
    if report.get("snapshot_id") != expected_snapshot_id:
        raise DomainError("source comparison returned the wrong snapshot_id", 500)
    summary = _summary(report)
    report_json, report_bytes = _canonical(report)
    if len(report_bytes) > MAX_REPORT_BYTES:
        raise DomainError("source comparison report exceeds 1 MiB")
    report_sha256 = hashlib.sha256(report_bytes).hexdigest()
    summary_json, _ = _canonical(summary)

    with store._write() as db:
        prior = _existing(db, request_id, actor, intent_json, intent_sha256)
        if prior is not None:
            return prior
        row = store._require_ticket(db, ticket_id)
        store._expect(row, {"expected_revision": expected_revision})
        recorded_at = _utc()
        cursor = db.execute(
            "INSERT INTO source_checks(request_id,ticket_id,ticket_revision,actor,intent_json,"
            "intent_sha256,snapshot_id,report_sha256,report_json,summary_json,checked_at,"
            "recorded_at,receipt_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (request_id, ticket_id, expected_revision, actor, intent_json, intent_sha256,
             expected_snapshot_id, report_sha256, report_json, summary_json,
             checked_at, recorded_at, "{}"))
        receipt = {"schema_version": 1, "check_id": cursor.lastrowid,
                   "request_id": request_id, "ticket_id": ticket_id,
                   "ticket_revision": expected_revision, "actor": actor,
                   "method": "local_compare_snapshot_v1", "snapshot_id": expected_snapshot_id,
                   "report_sha256": report_sha256, "summary": summary,
                   "checked_at": checked_at, "recorded_at": recorded_at}
        receipt_json, _ = _canonical(receipt)
        db.execute("UPDATE source_checks SET receipt_json=? WHERE id=?",
                   (receipt_json, cursor.lastrowid))
        store._event(db, ticket_id, actor, "source_check_recorded", receipt)
        return receipt


def _page_in_tx(db, ticket_id: str, limit: int, before_id: int | None = None,
                *, current_revision: int | None = None) -> dict:
    total = db.execute("SELECT COUNT(*) FROM source_checks WHERE ticket_id=?",
                       (ticket_id,)).fetchone()[0]
    where = "ticket_id=?"
    params: tuple = (ticket_id,)
    if before_id is not None:
        where += " AND id<?"
        params += (before_id,)
    rows = list(db.execute("SELECT id,receipt_json FROM source_checks WHERE " + where
                           + " ORDER BY id DESC LIMIT ?", (*params, limit + 1)))
    has_more = len(rows) > limit
    checks = [_receipt(row) for row in rows[:limit]]
    if current_revision is not None:
        checks = [{**receipt,
                   "ticket_revision_matches_now": receipt["ticket_revision"] == current_revision}
                  for receipt in checks]
    return {"checks": checks, "total": total, "count": len(checks), "limit": limit,
            "next_before_id": checks[-1]["check_id"] if has_more else None}


def list_source_checks(store: Store, ticket_id, *, limit=20, before_id=None) -> dict:
    ticket_id = Store._plan_identifier(ticket_id, "ticket_id", 128)
    limit = _limit(limit)
    if before_id is not None:
        before_id = _positive(before_id, "before_id")
    with store._connection() as db:
        db.execute("BEGIN")
        store._require_ticket(db, ticket_id)
        page = _page_in_tx(db, ticket_id, limit, before_id)
        db.commit()
        return {"ticket_id": ticket_id, **page}


def get_source_check(store: Store, check_id) -> dict:
    check_id = _positive(check_id, "check_id")
    with store._connection() as db:
        db.execute("BEGIN")
        row = db.execute("SELECT * FROM source_checks WHERE id=?", (check_id,)).fetchone()
        if row is None:
            raise DomainError(f"source check {check_id} not found", 404)
        receipt = _receipt(row)
        try:
            report_bytes = row["report_json"].encode("utf-8")
            if (len(report_bytes) > MAX_REPORT_BYTES
                    or hashlib.sha256(report_bytes).hexdigest() != row["report_sha256"]
                    or row["report_sha256"] != receipt["report_sha256"]):
                raise ValueError("report hash or size mismatch")
            report = json.loads(report_bytes)
            if (not isinstance(report, dict) or report.get("snapshot_id") != receipt["snapshot_id"]
                    or _summary(report) != receipt["summary"]):
                raise ValueError("report content mismatch")
            _, canonical = _canonical(report)
            if canonical != report_bytes:
                raise ValueError("report is not canonical")
        except (TypeError, ValueError, UnicodeError, RecursionError, DomainError) as exc:
            raise DomainError("stored source check report is invalid", 500) from exc
        db.commit()
        return {**receipt, "report": report}
