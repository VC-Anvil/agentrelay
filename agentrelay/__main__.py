"""Explicit local entry points; execution is enabled only by a worker config."""

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

from .store import DomainError, Store


BOOTSTRAP_ACTIONS = {"create_ticket", "create_plan", "create_profile"}
SOURCE_SNAPSHOT_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _source_identifier(value):
    if not value or value != value.strip() or len(value) > 128:
        raise argparse.ArgumentTypeError(
            "must be 1..128 characters without surrounding whitespace")
    return value


def _source_positive_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if not 1 <= number <= 2**63 - 1:
        raise argparse.ArgumentTypeError("must be an integer from 1 to 2**63-1")
    return number


def _source_limit(value):
    number = _source_positive_int(value)
    if number > 100:
        raise argparse.ArgumentTypeError("must be an integer from 1 to 100")
    return number


def _source_path(value):
    if not value or "\x00" in value:
        raise argparse.ArgumentTypeError("must be an explicit filesystem path")
    return Path(value)


def _source_snapshot_id(value):
    if not SOURCE_SNAPSHOT_ID.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "must be sha256: plus 64 lowercase hexadecimal characters")
    return value


def main():
    # JSON command output is UTF-8 even when Windows pipes default to a code page.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="agentrelay", description="Local ticket coordination for people and agents")
    sub = parser.add_subparsers(dest="command", required=True)
    snapshot = sub.add_parser("snapshot", help="Freeze explicit project files outside their source tree")
    snapshot.add_argument("--root", type=Path, required=True)
    snapshot.add_argument("--file", action="append", required=True, dest="files")
    snapshot.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify-snapshot", help="Check the bytes of a captured input bundle")
    verify.add_argument("directory", type=Path)
    compare = sub.add_parser("compare-snapshot", help="Compare captured inputs with an explicit current source root")
    compare.add_argument("directory", type=Path)
    compare.add_argument("--root", type=Path, required=True)
    snapshot_diff = sub.add_parser(
        "diff-snapshots", help="Compare two verified historical input snapshots")
    snapshot_diff.add_argument("--before", type=_source_path, required=True,
                               help="Earlier captured input directory")
    snapshot_diff.add_argument("--after", type=_source_path, required=True,
                               help="Later captured input directory")
    snapshot_diff.add_argument("--expected-before-id", type=_source_snapshot_id, required=True,
                               help="Exact lowercase sha256 identity of the earlier snapshot")
    snapshot_diff.add_argument("--expected-after-id", type=_source_snapshot_id, required=True,
                               help="Exact lowercase sha256 identity of the later snapshot")
    snapshot_diff.add_argument("--file", action="append", dest="files",
                               help="Canonical relative path to compare; repeat to select several")
    report = sub.add_parser("verify-report", help="Compare a fixed report with its adjacent host receipt")
    report.add_argument("directory", type=Path, help="Directory containing receipt.json and report.md")
    report.add_argument("--receipt-sha256", help="Previously trusted SHA-256 anchor for receipt.json")
    overview = sub.add_parser("overview", help="Read a bounded summary of configured projects")
    overview.add_argument("--workspaces", type=Path, required=True, help="Explicit trusted project registry")
    overview.add_argument("--limit", type=int, default=5, help="Tickets per category in each project (1..20)")
    for name in ("serve", "mcp", "export", "run", "runs", "run-result", "backup", "action",
                 "context", "history", "check-sources", "source-checks", "source-check"):
        command = sub.add_parser(name)
        command.add_argument("--db", type=Path, required=name in {
            "check-sources", "source-checks", "source-check"
        }, help="SQLite database shared by web and MCP")
        if name == "action":
            command.add_argument("--input", type=Path, required=True, help="UTF-8 JSON file containing action and data")
            command.add_argument("--actor", required=True, help="Audit identity; local declaration, not authentication")
        if name in {"context", "history"}:
            command.add_argument("--ticket", required=True)
        if name == "context":
            history_options = command.add_mutually_exclusive_group()
            history_options.add_argument("--event-limit", type=int, default=20, help="Recent events to include (1..100)")
            history_options.add_argument("--all-events", action="store_true", help="Explicitly include the complete audit history")
        if name == "history":
            command.add_argument("--limit", type=int, default=20)
            command.add_argument("--before-id", type=int, help="Exclusive event ID cursor from the previous page")
        if name == "run-result":
            command.add_argument("--run", required=True, dest="run_id",
                                 help="Exact execution run ID")
        if name == "check-sources":
            command.add_argument("--ticket", required=True, dest="ticket_id",
                                 type=_source_identifier,
                                 help="Existing ticket receiving the advisory observation")
            command.add_argument("--expected-revision", required=True, type=_source_positive_int)
            command.add_argument("--snapshot", required=True, type=_source_path,
                                 help="Explicit captured input directory")
            command.add_argument("--expected-snapshot-id", required=True, type=_source_snapshot_id,
                                 help="Exact lowercase sha256 snapshot identity")
            command.add_argument("--root", required=True, type=_source_path,
                                 help="Explicit current project root")
            command.add_argument("--request-id", required=True, type=_source_identifier,
                                 help="Stable ID for exact historical replay")
            command.add_argument("--actor", required=True, type=_source_identifier,
                                 help="Audit identity; local declaration, not authentication")
        if name == "source-checks":
            command.add_argument("--ticket", required=True, dest="ticket_id",
                                 type=_source_identifier)
            command.add_argument("--limit", type=_source_limit, default=20)
            command.add_argument("--before-id", type=_source_positive_int,
                                 help="Exclusive source-check ID cursor from the previous page")
        if name == "source-check":
            command.add_argument("--check-id", required=True, type=_source_positive_int)
        if name == "runs":
            command.add_argument("--ticket", dest="ticket_id", help="Optional exact ticket ID")
            command.add_argument("--status", help="Optional execution status")
            command.add_argument("--limit", type=int, default=20, help="Runs per page (1..100)")
            command.add_argument("--before-id", help="Exclusive run ID cursor from the previous page")
        if name == "backup":
            command.add_argument("--output", type=Path, required=True, help="New SQLite file; refuses overwrite")
        if name == "serve":
            command.add_argument("--port", type=int, default=8787)
            command.add_argument("--demo", action="store_true", help="Seed isolated, clearly fictional demo data")
            command.add_argument("--workers", type=Path, help="Trusted JSON worker configuration; enables explicit launches")
            command.add_argument("--workspaces", type=Path, help="Trusted registry of existing project databases")
        if name == "run":
            command.add_argument("--workers", type=Path, required=True)
            command.add_argument("--worker", required=True)
            command.add_argument("--ticket", help="Exact ticket; otherwise choose ready work by priority")
            command.add_argument("--limit", type=int, default=1, help="Maximum sequential tickets (1..20), never auto-review")
        if name == "mcp":
            command.add_argument("--actor", required=True, help="Stable agent identity, e.g. agent:sol-01")
    args = parser.parse_args()
    if args.command == "verify-report":
        from .report_integrity import verify_report
        try:
            result = verify_report(args.directory, receipt_sha256=args.receipt_sha256)
        except (ValueError, OSError) as exc:
            parser.exit(1, f"Report verification failed: {exc}\n")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["status"] != "unchanged":
            raise SystemExit(2)
        return
    if args.command == "diff-snapshots":
        from .snapshot_diff import diff_snapshots
        try:
            result = diff_snapshots(
                args.before, args.after,
                expected_before_id=args.expected_before_id,
                expected_after_id=args.expected_after_id,
                paths=args.files,
            )
        except (ValueError, OSError) as exc:
            parser.exit(1, f"Snapshot diff failed: {exc}\n")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if any(result["summary"][key] for key in ("modified", "added", "removed")):
            raise SystemExit(2)
        return
    if args.command == "overview":
        from .overview import project_overview
        try:
            result = project_overview(args.workspaces, limit=args.limit)
        except (DomainError, OSError, sqlite3.Error) as exc:
            parser.exit(1, f"Overview failed: {exc}\n")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.command == "serve" and args.workspaces:
        if args.db or args.workers or args.demo:
            parser.error("--workspaces cannot be combined with --db, --workers or --demo")
        from .workspaces import load_workspaces
        from .server import serve
        workspaces = {}
        try:
            workspaces, default = load_workspaces(args.workspaces)
            serve(workspaces[default].store, args.port, workspaces=workspaces, default_workspace_id=default)
        except (DomainError, OSError) as exc:
            parser.exit(1, f"Workspace configuration: {exc}\n")
        finally:
            for workspace in workspaces.values():
                if workspace.execution:
                    workspace.execution.close()
        return
    if args.command in {"snapshot", "verify-snapshot", "compare-snapshot"}:
        from .snapshots import create_snapshot, verify_snapshot
        try:
            if args.command == "compare-snapshot":
                from .freshness import compare_snapshot
                result = compare_snapshot(args.directory, args.root)
            else:
                result = (create_snapshot(args.root, args.files, args.output) if args.command == "snapshot"
                          else verify_snapshot(args.directory))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if args.command == "verify-snapshot" and not result["valid"]:
                raise SystemExit(1)
            if args.command == "compare-snapshot" and any(
                    result["summary"][key] for key in ("modified", "missing", "uncheckable")):
                raise SystemExit(2)
        except (ValueError, OSError) as exc:
            parser.exit(1, f"Snapshot failed: {exc}\n")
        return
    if args.command == "action":
        # Validate the envelope before creating a database, and bound input reads.
        try:
            with args.input.open("rb") as stream:
                raw = stream.read(1_048_577)
            if len(raw) > 1_048_576:
                raise ValueError("Action input exceeds 1 MiB")
            request = json.loads(raw.decode("utf-8-sig"))
            if (not isinstance(request, dict) or set(request) != {"action", "data"}
                    or not isinstance(request["action"], str) or not isinstance(request["data"], dict)):
                raise ValueError("Expected an object with exactly action (string) and data (object)")
        except (ValueError, OSError, RecursionError) as exc:
            parser.exit(1, f"Action input: {exc}\n")
        if not args.actor.strip():
            parser.error("--actor must be a nonempty identity")
    if args.command == "mcp" and (not args.actor.startswith("agent:") or not args.actor[6:].strip()):
        # Reject an invalid identity before a default or explicit database path can be initialized.
        parser.error("--actor must be a nonempty agent:<name> identity")
    demo = getattr(args, "demo", False)
    database = args.db or Path.cwd() / ".agentrelay" / ("demo.sqlite" if demo else "workspace.sqlite")
    requires_existing = args.command in {
        "context", "history", "export", "runs", "run-result", "backup", "run",
        "check-sources", "source-checks", "source-check",
    } or (args.command == "action" and request["action"] not in BOOTSTRAP_ACTIONS)
    try:
        # Store/the read preflight inspect the selected path before resolving it, including symlinks.
        database = database.expanduser()
        if requires_existing:
            from .workspaces import require_agentrelay_database
            database = require_agentrelay_database(database)
        store = Store(database)
        if demo:
            store.seed_demo()
    except (DomainError, OSError, RuntimeError, sqlite3.Error) as exc:
        parser.exit(1, f"Database: {exc}\n")
    if args.command in {"check-sources", "source-checks", "source-check"}:
        try:
            if args.command == "check-sources":
                from .source_checks import check_sources
                result = check_sources(
                    store, ticket_id=args.ticket_id, expected_revision=args.expected_revision,
                    snapshot=args.snapshot, expected_snapshot_id=args.expected_snapshot_id,
                    root=args.root, request_id=args.request_id, actor=args.actor,
                )
            elif args.command == "source-checks":
                from .source_checks import list_source_checks
                result = list_source_checks(store, args.ticket_id, limit=args.limit,
                                            before_id=args.before_id)
            elif args.command == "source-check":
                from .source_checks import get_source_check
                result = get_source_check(store, args.check_id)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except (DomainError, OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
            parser.exit(1, f"{exc}\n")
    elif args.command in {"action", "context", "history", "runs", "run-result"}:
        try:
            if args.command == "action":
                result = store.action(request["action"], request["data"], args.actor)
            elif args.command == "run-result":
                from .run_results import get_run_result
                result = get_run_result(store, args.run_id)
            elif args.command == "runs":
                from .run_history import list_runs
                result = list_runs(store, ticket_id=args.ticket_id, status=args.status,
                                   limit=args.limit, before_id=args.before_id)
            elif args.command == "history":
                result = store.ticket_events(args.ticket, limit=args.limit, before_id=args.before_id)
            else:
                result = store.context(args.ticket, event_limit=None if args.all_events else args.event_limit)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except DomainError as exc:
            parser.exit(1, f"{exc}\n")
    elif args.command == "serve":
        from .server import serve
        from .execution import ExecutionManager
        try:
            execution = ExecutionManager(store, args.workers) if args.workers else None
        except DomainError as exc:
            parser.exit(1, f"Execution configuration: {exc}\n")
        try:
            serve(store, args.port, demo, execution)
        finally:
            if execution:
                execution.close()
    elif args.command == "run":
        from .execution import ExecutionManager
        if not 1 <= args.limit <= 20 or (args.ticket and args.limit != 1):
            parser.error("--limit must be 1..20, and 1 when --ticket is supplied")
        try:
            manager = ExecutionManager(store, args.workers)
        except DomainError as exc:
            parser.exit(1, f"Execution configuration: {exc}\n")
        try:
            workers = {w["id"]: w for w in manager.snapshot()["workers"]}
            if args.worker not in workers:
                parser.error("Unknown configured worker")
            worker = workers[args.worker]
            for _ in range(args.limit):
                candidates = ready_work(store, worker)
                if args.ticket:
                    candidates = [store.context(args.ticket)["ticket"]]
                if not candidates:
                    print(json.dumps({"status": "idle", "reason": "No compatible ready tickets"}))
                    break
                ticket = candidates[0]
                run = manager.start(ticket["id"], args.worker, ticket["revision"])
                print(json.dumps(run, ensure_ascii=False), flush=True)
                while run["status"] == "running":
                    time.sleep(0.2)
                    run = next(r for r in manager.snapshot()["runs"] if r["id"] == run["id"])
                print(json.dumps(run, ensure_ascii=False), flush=True)
                if run["status"] in {"failed", "cancelled", "interrupted", "conflict"}:
                    raise SystemExit(1)
        except DomainError as exc:
            parser.exit(1, f"{exc}\n")
        except KeyboardInterrupt:
            parser.exit(130, "Run cancelled\n")
        finally:
            manager.close()
    elif args.command == "backup":
        try:
            print(store.backup(args.output))
        except OSError as exc:
            parser.exit(1, f"Backup failed: {exc}\n")
    elif args.command == "mcp":
        try:
            from .mcp_server import run
        except ImportError as exc:
            parser.error(f"MCP requires the optional SDK: pip install '.[mcp]' ({exc})")
        run(store, args.actor)
    else:
        print(json.dumps(store.export(), ensure_ascii=False, indent=2))


def ready_work(store, worker):
    """Priority ordering never preempts owners or ignores dependency readiness."""
    priority = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
    tickets = [t for t in store.state()["tickets"] if t["status"] == "queued" and t["ready"]
               and t["acceptance"]
               and (not worker["profile_ids"] or t["profile_id"] in worker["profile_ids"])
               and (t["profile_id"] != "astra" or (worker["model"], worker["effort"]) == ("gpt-6-astra", "high"))]
    return sorted(tickets, key=lambda t: (priority[t["priority"]], t["created_at"], t["id"]))


if __name__ == "__main__":
    main()
