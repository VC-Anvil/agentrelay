"""Versioned, bounded-size CAS token for a ticket's immediate review context."""

import hashlib
import json


SCHEMA_VERSION = 1
_DOMAIN = b"agentrelay.acceptance_context.v1\x00"


def acceptance_context_in_tx(db, ticket, checks_page):
    """Hash ordered immediate relations inside the caller's SQLite transaction.

    Each relation row is fed directly to the digest. ``checks_page`` is the same
    three-receipt page presented by Store.context, including its full total.
    """
    digest = hashlib.sha256(_DOMAIN)

    def feed(record):
        encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)

    feed(["ticket", ticket["id"], ticket["revision"], ticket["status"]])

    children_count = 0
    for child in db.execute(
            "SELECT id,revision,status,parent_id FROM tickets WHERE parent_id=? ORDER BY id",
            (ticket["id"],)):
        feed(["child", child["id"], child["revision"], child["status"], child["parent_id"]])
        children_count += 1

    dependencies_count = 0
    for dependency in db.execute(
            "SELECT t.id,t.revision,t.status FROM dependencies AS d "
            "JOIN tickets AS t ON t.id=d.depends_on WHERE d.ticket_id=? ORDER BY t.id",
            (ticket["id"],)):
        feed(["dependency", dependency["id"], dependency["revision"], dependency["status"]])
        dependencies_count += 1

    feed(["source_checks_total", checks_page["total"]])
    for check in checks_page["checks"]:
        feed(["source_check", check["check_id"], check["snapshot_id"],
              check["report_sha256"], check["ticket_revision"]])

    return {"schema_version": SCHEMA_VERSION,
            "token": "sha256:" + digest.hexdigest(),
            "children_count": children_count,
            "dependencies_count": dependencies_count,
            "source_checks_count": checks_page["total"]}
