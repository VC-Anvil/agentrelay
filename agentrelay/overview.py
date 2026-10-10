"""Bounded multi-project summaries without worker activation or task recovery."""

from pathlib import Path

from .store import DomainError
from .workspaces import load_workspaces


SUMMARY_FIELDS = ("id", "title", "type", "status", "priority", "parent_id",
                  "profile_id", "assignee", "revision", "ready", "blockers")
PRIORITY_ORDER = {"urgent": 0, "high": 1, "normal": 2, "low": 3}


def _category(tickets, predicate, limit):
    selected = [ticket for ticket in tickets if predicate(ticket)]
    selected.sort(key=lambda ticket: (
        PRIORITY_ORDER.get(ticket["priority"], len(PRIORITY_ORDER)),
        ticket["created_at"], ticket["id"],
    ))
    return {
        "total": len(selected),
        "tickets": [{field: ticket[field] for field in SUMMARY_FIELDS}
                    for ticket in selected[:limit]],
    }


def project_overview(config_path, *, limit=5):
    """Summarize configured projects without opening worker configs or launching execution."""
    if type(limit) is not int or not 1 <= limit <= 20:
        raise DomainError("limit must be an integer from 1 to 20")
    workspaces, default = load_workspaces(config_path, enable_execution=False)
    projects = []
    for workspace in workspaces.values():
        state = workspace.store.state()
        tickets = state["tickets"]
        urgent = _category(
            tickets,
            lambda ticket: (ticket["priority"] == "urgent"
                            and ticket["status"] not in {"done", "cancelled"}),
            limit,
        )
        projects.append({
            "id": workspace.id,
            "name": workspace.name,
            "database": str(Path(workspace.store.path).resolve()),
            "demo": state["demo"],
            "stats": state["stats"],
            "urgent_open": urgent["total"],
            "urgent": urgent,
            "ready": _category(tickets, lambda ticket: ticket["ready"], limit),
            "review": _category(tickets, lambda ticket: ticket["status"] == "review", limit),
            "blocked": _category(
                tickets,
                lambda ticket: (ticket["status"] == "blocked"
                                or (ticket["status"] == "queued" and bool(ticket["blockers"]))),
                limit,
            ),
        })
    return {
        "schema_version": 1,
        "default_workspace_id": default,
        "count": len(projects),
        "limit": limit,
        "projects": projects,
    }
