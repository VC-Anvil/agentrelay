# Snapshot diff CLI interface report

## Delivered interface

`agentrelay diff-snapshots` requires explicit before/after snapshot directories
and their two exact lowercase `sha256:` identities. Repeated `--file` values are
passed as the optional focused selection; omission selects the manifest union in
the service. The command imports and calls `snapshot_diff.diff_snapshots` before
the shared Store/default-database path can run.

The CLI emits the service JSON as UTF-8. It exits 0 only when all selected files
are unchanged, 2 when any file is modified, added or removed, and 1 with a
concise standard-error diagnostic for ordinary service or filesystem failures.
Malformed argparse input retains status 2 and usage output. There is no database,
root, actor, ticket, MCP or HTTP surface for this operation.

## Interface coverage

`tests/test_cli_snapshot_diff.py` uses real subprocess invocations and snapshots
created through the public capture API. It checks the sorted union and structured
modified/added/removed result, a focused unchanged UTF-8 selection, exact IDs,
exit statuses, concise unknown-selection/identity/corruption failures, malformed
usage, and absence of a default `.agentrelay` directory or SQLite file.

The root integrator ran the final service and real subprocess CLI modules after
the backend corrections: **16 tests, 15 passed and one Windows symlink test
skipped, in 1.879 s**. A real CLI exercise reported Dirt as ten added lines in
one hunk (3,698-byte report) and Cartografo as three added lines in one hunk
(2,007-byte report). Exact repetition and focused selection were deterministic,
and the snapshots and four project databases remained byte-for-byte unchanged.
These are integrator results, not executions performed in this specialist's
sandbox.

A focused local attempt stopped in fixture setup with `PermissionError` when
Python's temporary directory could not create its first child under the Windows
sandbox; it did not reach the CLI and is not presented as a product failure or
pass. Final Python compilation and `git diff --check` passed for the owned files.

## Preserved limits

The CLI does not turn structured hunks into an applicable patch or infer ticket
impact. Explicit `omitted` results remain visible and are not converted to
partial output. Snapshot hashes provide integrity evidence rather than author
authentication, and the command does not read live roots or mutate tickets,
acceptance, execution state, games or databases.
