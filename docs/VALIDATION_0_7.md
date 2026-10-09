# Validation — AgentRelay 0.7.0

Date: 2026-10-10 (Europe/Madrid). Windows, Python 3.12.14, MCP SDK 1.30.0.
Earlier evidence: [v0.6 audit cursors](VALIDATION_0_6.md),
[v0.5 context and skill](VALIDATION_0_5.md),
[v0.4 plans and freshness](VALIDATION_0_4.md),
[v0.3 project pilots](VALIDATION_0_3.md).

## Defects reproduced before correction

A valid hierarchy of 2,500 tickets caused the recursive relationship validator
to raise `RecursionError` when a public action tried to add another ticket.
The transaction rolled back, but valid work could not be added. Iterative
topological traversal now accepts this graph and still rejects mixed hierarchy
and dependency cycles with a 409 domain error. A late cycle preserves revision,
dependencies, ticket counter and audit records after rollback. Shared prerequisites
are also covered. [Author report](deep-graph-report.md).

CLI `context`, `history`, `export` and `backup` used to initialize a database even
when its path was a typo. They also changed unrelated SQLite files before trying
to read them. A read-only preflight now checks an existing file, the five original
tables and their required columns before Store initialization. The workspace
registry shares that preflight. Tests reject empty/corrupt files, unrelated
tables, matching table names with incompatible columns, and matching views,
without changing input bytes or creating backup output. An original schema
without later tables still migrates successfully. Explicit creation through
`action` remains available. [Author report](readonly-cli-report.md).

## Checks

The complete suite ran **98 tests in 30.569 seconds: 96 passed, two skipped** for
Windows symbolic-link privileges. Private log: `.agentrelay/v07-tests.log`.
This includes real MCP SDK stdio, HTTP isolation, real configured fixture
processes, CLI subprocesses and JavaScript race checks. No LLM provider was
invoked by the test suite. Independent integration review caught the initial
table-name-only validation gap before release.

The updated CLI queried the four existing documentary pilot databases for
context, history and full export: **33 tickets**, with **34 audit events** on
the four selected review tickets. All queries succeeded; ticket, profile and
event contents were unchanged. This validates existing project records, not new
game implementation. Private trace: `.agentrelay/v07-cli-pilots.json`.

The wheel and source archive were checked against source bytes and an isolated
wheel installation, including all 13 package files and the bundled skill.
The [v0.7 CI matrix passed all four jobs](https://github.com/VC-Anvil/agentrelay/actions/runs/37999760414)
at commit `420e2b40c7ac3ae107a8dc0de3c7a57bfef0bfcf`.

## Limits

The database preflight prevents accidental initialization of missing or
unrecognized files. It does not authenticate hostile databases or eliminate a
path-replacement race. Recognized AgentRelay files still receive Store schema
migrations; these commands are not filesystem-level read-only sessions.

The graph test exercises validation and rollback on prepared coherent data. It
does not establish UI or end-to-end throughput for thousands of tickets.

Fresh multi-project browser QA remains pending explicit authorization after the
earlier tool denial. API, CLI and MCP checks do not substitute for visual QA.
No source project changes, worker launches or game acceptance follow from these
documentary pilot queries.
