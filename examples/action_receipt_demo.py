"""Isolated durable-receipt walkthrough; no model, worker or live project."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import uuid

from agentrelay import __version__
from agentrelay.store import DomainError, Store


def run(output: Path) -> dict:
    # A new directory prevents accidental replacement of a previous run or project.
    output.mkdir(parents=True, exist_ok=False)
    store = Store(output / "workspace.sqlite")
    actor = "agent:receipt-example"
    request = {
        "request_id": str(uuid.uuid4()),
        "action": "create_ticket",
        "data": {
            "title": "Investigate an uncertain response",
            "description": "Fictional ticket in an isolated receipt example.",
            "acceptance": ["Document the observation and its limits"],
        },
    }
    (output / "request.json").write_text(
        json.dumps({"action": "apply_ticket_action", "data": request}, indent=2),
        encoding="utf-8",
    )

    # The first write commits. Deliberately discard its return value to model a
    # client that did not receive a result; this is not an actual network failure.
    store.action("apply_ticket_action", request, actor=actor)
    recovered = store.action("apply_ticket_action", request, actor=actor)
    assert recovered["replayed"] is True
    ticket = recovered["result"]
    assert len(store.state()["tickets"]) == 1

    # A later independent edit makes the historical/current distinction visible.
    current = store.action("update_ticket", {
        "id": ticket["id"], "expected_revision": ticket["revision"],
        "title": "Observation recorded; fresh context required",
    }, actor=actor)
    historical = Store(output / "workspace.sqlite").action(
        "apply_ticket_action", request, actor=actor,
    )
    assert historical == recovered
    assert current["revision"] > historical["result"]["revision"]

    comment_request = {
        "request_id": str(uuid.uuid4()), "action": "add_comment",
        "data": {"id": ticket["id"], "body": "One explicit observation."},
    }
    first_comment = store.action("apply_ticket_action", comment_request, actor=actor)
    second_comment = store.action("apply_ticket_action", comment_request, actor=actor)
    assert first_comment["replayed"] is False and second_comment["replayed"] is True
    assert first_comment["result"] == second_comment["result"]
    context = store.context(ticket["id"])
    assert sum(event["action"] == "add_comment" for event in context["events"]) == 1

    changed_request = {**request, "data": {**request["data"], "title": "Different intent"}}
    try:
        store.action("apply_ticket_action", changed_request, actor=actor)
    except DomainError as error:
        assert error.status == 409
        conflict = str(error)
    else:
        raise AssertionError("Different intent reused a committed request ID")

    store.backup(output / "backup.sqlite")
    from_backup = Store(output / "backup.sqlite").action(
        "apply_ticket_action", request, actor=actor,
    )
    assert from_backup == recovered
    assert store.context(ticket["id"]) == context
    report = {
        "version": __version__, "fictional": True,
        "simulation": "First committed return value deliberately discarded; no network or model call",
        "recovered_receipt": recovered,
        "current_ticket": context["ticket"],
        "tickets": len(store.state()["tickets"]), "comment_events": 1,
        "conflicting_reuse": {"status": 409, "message": conflict},
        "backup_preserved_receipt": from_backup == recovered,
        "limits": "Explicit retries only; receipts are historical and grant no execution or acceptance permission",
    }
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New isolated output directory")
    args = parser.parse_args()
    try:
        report = run(args.output.resolve())
    except (OSError, DomainError) as error:
        print(f"Receipt example failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
