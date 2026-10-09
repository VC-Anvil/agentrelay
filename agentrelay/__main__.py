"""Explicit local entry points; execution is enabled only by a worker config."""

import argparse
import json
import time
from pathlib import Path

from .store import DomainError, Store


def main():
    parser = argparse.ArgumentParser(prog="agentrelay", description="Local ticket coordination for people and agents")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("serve", "mcp", "export", "run", "backup"):
        command = sub.add_parser(name)
        command.add_argument("--db", type=Path, help="SQLite database shared by web and MCP")
        if name == "backup":
            command.add_argument("--output", type=Path, required=True, help="New SQLite file; refuses overwrite")
        if name == "serve":
            command.add_argument("--port", type=int, default=8787)
            command.add_argument("--demo", action="store_true", help="Seed isolated, clearly fictional demo data")
            command.add_argument("--workers", type=Path, help="Trusted JSON worker configuration; enables explicit launches")
        if name == "run":
            command.add_argument("--workers", type=Path, required=True)
            command.add_argument("--worker", required=True)
            command.add_argument("--ticket", help="Exact ticket; otherwise choose ready work by priority")
            command.add_argument("--limit", type=int, default=1, help="Maximum sequential tickets (1..20), never auto-review")
        if name == "mcp":
            command.add_argument("--actor", required=True, help="Stable agent identity, e.g. agent:sol-01")
    args = parser.parse_args()
    demo = getattr(args, "demo", False)
    database = args.db or Path.cwd() / ".agentrelay" / ("demo.sqlite" if demo else "workspace.sqlite")
    database = database.expanduser().resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    store = Store(database)
    if demo:
        store.seed_demo()
    if args.command == "serve":
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
        if not args.actor.startswith("agent:") or not args.actor[6:].strip():
            parser.error("--actor must be a nonempty agent:<name> identity")
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
