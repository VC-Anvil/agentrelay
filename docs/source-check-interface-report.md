# Source-check CLI and MCP interface report

## Implemented surface

The local `check-sources` command requires an explicit existing database, ticket revision, snapshot path, expected snapshot identity, current root, request ID and actor. Argparse validates identifier bounds, positive integer ranges, expected snapshot form and nonempty selections before opening the database. It delegates comparison and persistence to `agentrelay.source_checks.check_sources` and prints the exact compact receipt. Every successful record or historical replay exits 0, including advisory findings.

`source-checks` pages compact receipts for a ticket and `source-check` reads one stored report by positive integer ID. Both require explicit `--db` and use the recognized-database preflight. They never initialize a typo path. Domain, snapshot, filesystem and SQLite service failures are rendered as concise stderr diagnostics without success JSON.

MCP adds `list_source_checks` and `get_source_check` with read-only annotations and strict integer limit/cursor/ID parameters. Their schemas contain no path or report-ingest arguments. Server instructions and tool descriptions state that observations are historical, advisory and do not establish current source state. Existing ticket context automatically carries its three compact receipts from Store.

## Verification scope

`tests/test_cli_source_checks.py` covers unchanged and modified observations, exit 0 for findings, exact compact output, list pagination, explicit detail, context visibility, replay after ticket/path changes, expected-ID mismatch before root inspection, stale revision before source reads, strict read errors, explicit database requirements and typo-path noncreation.

`tests/test_mcp_source_checks.py` uses the real SDK/stdio client and server. It discovers both read-only tools, asserts path-free schemas, pages compact receipts, reads one selected report, observes compact context, rejects strict invalid inputs and compares persisted domain/source-check rows before and after the read session. No model provider, worker, game, browser or arbitrary filesystem MCP access is involved.

The root integrator ran the final focused modules with the real CLI and SDK/stdio server after the SQLite-diagnostic regression: **5/5 tests passed in 4.802 s**, recorded in `.agentrelay/v014-interface-tests-final.log`. This includes early argparse validation and an in-process injected `sqlite3.OperationalError` check. Python compilation and `git diff --check` also cover the final source locally. The earlier 4/4 run preceded that final delta and is retained as intermediate evidence rather than presented as the final result.

## Limits

These interfaces report stored service facts; they do not independently attest the caller identity, filesystem authorization, source quality or review impact. A receipt replay is intentionally historical. Full reports remain available only by explicit check ID and never appear in list/state/export responses.
