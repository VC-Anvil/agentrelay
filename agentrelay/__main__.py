"""Explicit local entry points; no inference requests and no automatic agents."""

import argparse
import json
from pathlib import Path

from .store import Store


def main():
    parser = argparse.ArgumentParser(prog="agentrelay", description="Local ticket coordination for people and agents")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("serve", "mcp", "export"):
        command = sub.add_parser(name)
        command.add_argument("--db", type=Path, help="SQLite database shared by web and MCP")
        if name == "serve":
            command.add_argument("--port", type=int, default=8787)
            command.add_argument("--demo", action="store_true", help="Seed isolated, clearly fictional demo data")
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
        serve(store, args.port, demo)
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


if __name__ == "__main__":
    main()
