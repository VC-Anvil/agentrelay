# Validation — AgentRelay 0.6.0

Date: 2026-10-10 (Europe/Madrid). Windows, Python 3.12.14, MCP SDK 1.30.0.
Earlier evidence: [v0.5 context and skill](VALIDATION_0_5.md),
[v0.4 plans and freshness](VALIDATION_0_4.md), [v0.3 project pilots](VALIDATION_0_3.md).

## Recoverable audit context

Agent context previously repeated the complete ticket history on each handoff.
MCP context, CLI context and configured worker packets now include the newest
20 events, with an explicit total and cursor for older history. The current
revision, ticket, acceptance, checkpoint, evidence and relations remain complete.
Older events are recoverable through a ticket-scoped cursor; nothing is deleted.
Python callers using Store.context without an event limit and the browser HTTP
context preserve their previous behavior. Full export and backup preserve all
history. [Compatibility details and examples](HISTORY.md).

The cursor API was used against the four actual documentary pilot records with
three events per page. All **34 events across 12 pages** matched the full histories
exactly: 10, 12, 6 and 6 events respectively. Ticket status stayed completed.
This exercised retrieval of existing evidence, not new game work. Private trace:
`.agentrelay/v06-pilot-history.json`.

## Checks

The complete suite ran **90 tests in 26.462 seconds: 88 passed, two skipped** for
Windows symbolic-link privileges. Log: `.agentrelay/v06-tests.log` (ignored).
The companion skill validator, JavaScript syntax and whitespace checks passed.

New Store tests traverse over 60 events with interleaved IDs from other tickets,
insert newer events between reads, check current context, empty boundaries,
invalid types/ranges, reopened databases and SQLite backups. Recent context and
its metadata are read together in one SQLite transaction. Cursor pages exclude
their starting ID, so newer insertions do not shift the older segment.

An actual MCP SDK stdio client checked over 50 interleaved events, strict argument
handling, unknown tickets, metadata and ticket isolation. CLI tests recovered all
47 fixture events exactly, verified the explicit full-history option and rejected
invalid or conflicting arguments.

A real configured fixture process received 20 events from a 57-event history,
including the latest claim and its current revision. It submitted an exact saved
packet for review; the Store and export retained all 58 events after submission.
No LLM provider was invoked by these tests.

Independent review checked CLI and worker integration against the Store contract.
The MCP instructions were refined to use the current revision returned by context
or a successful mutation; they do not require a redundant context read before
every write. Historical values still require fresh context before being acted on,
and revision conflicts require reconciliation. Specialist sandbox setup failures
are distinguished from the integrator's normal test runs in their reports.

The wheel and source archive built successfully. An isolated wheel install checked
source provenance, static assets, snapshot/freshness, plan replay, registry loading,
and bounded context/history. All 13 package files and the installed skill payload
matched working sources; the archive matched code, tests, docs, skills and examples
without private data. Distribution hashes are in `dist/SHA256SUMS-0.6.0.txt`.

The previous v0.5 [CI matrix passed all four jobs](https://github.com/VC-Anvil/agentrelay/actions/runs/37997883242).
The [workflow history](https://github.com/VC-Anvil/agentrelay/actions/workflows/tests.yml)
records exact subsequent commit outcomes. Pending jobs are not counted as passing.

## Limits

Limits apply to event count, not payload bytes, tokens or arbitrary field lengths.
Relations are still full current tickets. Multiple pages do not share one frozen
database snapshot: the total can grow, while a cursor still selects older IDs.
An omitted event is not evidence it never occurred. Historical embedded ticket
fields may be obsolete and must not replace current state during mutation.

No new filesystem permissions, worker launches or acceptance decisions follow
from reading history. The four game projects' source files and chats remain
separate. Fresh multi-project browser QA is still pending explicit authorization
after the earlier tool denial; API/MCP/CLI tests are not visual verification.
