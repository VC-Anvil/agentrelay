# Run history CLI and MCP interfaces

## Implementation

The `runs` CLI command accepts optional ticket and status filters plus a bounded exclusive run-ID cursor. It participates in the existing AgentRelay database preflight, delegates all selection and validation to `agentrelay.run_history.list_runs`, and writes UTF-8 JSON. It never constructs an execution manager.

The read-only MCP `list_runs` tool delegates to the same helper and converts domain failures through the established MCP error convention. Its instructions direct agents to discover summaries first, retrieve only a selected proposal with `get_run_result`, then compare it with current ticket context. Neither interface exposes `result_json` or a decoded result body in list responses.

## Contract boundaries

Entries contain the ten public execution fields plus `has_result`. That boolean records proposal presence only; status, successful capture, application and independent acceptance remain separate facts. Result details require the existing explicit single-run query.

Pages are ordered by start time and ID, newest first. The keyset cursor avoids repeating already returned rows while their ordering fields remain stable. Calls do not share a SQLite snapshot: an insertion whose ordering pair falls after the anchor can appear later, and status changes can change filter membership and totals. A cursor can remain valid after its own status changes. Legacy databases without a run table return no runs, and legacy tables without `result_json` report no retained results.

## Verification

`tests/test_cli_run_history.py` covers UTF-8 run IDs, ordering, pagination, ticket and status filters, `has_result`, absence of proposal bodies, invalid limits/filters/cursors, missing database paths, legacy schemas and domain immutability. It completed with **4/4 tests passing in 10.131 s**.

`tests/test_mcp_run_history.py` uses the real SDK stdio transport to discover one ticket's run, retrieve that selected proposal with `get_run_result`, continue the cursor page and reject invalid types and cross-ticket cursors. It compares tickets, profiles, dependencies, events, metadata and execution rows before and after. My sandbox run stalled in stdio and was interrupted after 60 seconds, so it is not recorded as passing. The integrator ran this test successfully within the full suite using the real SDK/stdio transport. The integrator's separate real worker and MCP discovery flow completed with **1/1 test passing in 2.019 s**.

The integrator's complete validation finished with **133 tests: 131 passing and 2 Windows symlink skips in 44.418 s**; its log is `.agentrelay/v010-tests.log`.

No worker, provider, browser or network call is part of my interface tests. The integrator's separate discovery flow did launch its controlled local worker fixture; no provider, browser or network call was used.
