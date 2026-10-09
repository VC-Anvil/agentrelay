# AgentRelay 0.10 — execution discovery

Date: 2026-10-10 (Europe/Madrid). Windows, Python 3.12.14, MCP SDK 1.30.0.
Previous release: [retained worker proposals](VALIDATION_0_9.md).

## Problem observed in an active pilot

An MCP inspection of Dirt Riot's documentary pilot found two historical runs
for the selected ticket. The server exposed `get_run_result` but no structured
operation to discover those run IDs. Audit actor strings sometimes referred to
runs, and the web/JSON export exposed history; this was a missing MCP discovery
step, not loss of the existing execution records.

`list_runs` and CLI `runs` now expose filtered, bounded summaries with a
`has_result` indicator. Agents can identify a relevant run by ticket and status,
then inspect its proposal explicitly. Listing does not fetch proposal bodies,
start an execution manager, recover runs or mutate ticket state.

## Verification

The integrated suite ran **133 tests: 131 passed, two Windows symlink tests
skipped**, in 44.418 seconds. Four service tests cover a synthetic history of
125 runs with repeated timestamps, insertion between pages, status changes of
the cursor run, ticket isolation, totals, strict inputs and legacy schemas.
These are metadata fixtures, not 125 model executions.

Four CLI tests verify UTF-8, filters, cursors, summaries without proposal bodies,
missing-database rejection and old schemas. The real MCP SDK/stdio test discovers
a selected run, retrieves its proposal, pages older history and rejects invalid
types and cross-ticket cursors while leaving database rows unchanged.

The root integration test launches one local Python worker and connects an MCP
client that starts with only the selected ticket ID. The client discovers the
active run; a concurrent human edit causes a conflict; the client discovers the
conflicted run and reads its retained proposal and fresh ticket context. The
ticket's newer revision survives, its evidence remains empty and no retry or
automatic submission occurs. This verifies the coordination flow, not the
correctness of an arbitrary LLM's work.

CLI pagination with one run per page read all six historical runs of LEVIATHAN,
Dirt Riot, Valley of Rains and Cartógrafo Imposible. MCP separately discovered
both runs of the selected Dirt Riot ticket. Their 33 tickets, profiles, audit
events and execution records remained unchanged. No game source was edited,
and no historical game worker was relaunched.

Independent review found one documentation error: a newly inserted run does not
necessarily sort ahead of an existing cursor. The guide now explains that a
new row with an older ordering pair can appear later; pages have no shared
snapshot. The service already followed this contract. The companion skill
passed its structural validator. Reports: [service](run-history-service-report.md)
and [interfaces](run-history-interface-report.md).

The interface author's sandbox stdio transport stalled and was interrupted;
the integrator's normal environment passed that MCP test as part of the full
suite. Those are distinct outcomes, not an unqualified sandbox pass.

## Packaging and limits

The local wheel and source archive are checked against working source bytes.
An isolated wheel installation exercises a real worker, discovers its completed
run and retrieves its retained proposal. Local hashes and logs accompany the
artifacts; CI must be checked against the exact pushed commit separately.

Pagination uses immutable start-time/ID keys within ordinary AgentRelay writes.
Status changes can alter filter membership and totals between calls. A page is
not a complete audit, and `has_result` is not evidence validation or approval.
Recognized databases still receive normal Store initialization; no filesystem
immutability, SQL performance gain, token savings or fresh browser QA is claimed.

The earlier acceptance requests for AR-0018/AR-0019 remain pending after their
automatic execution-policy rejection. This work leaves those tickets and their
integration parent unchanged.
