# AgentRelay 0.13 — database selection before initialization

Date: 2026-10-10 (Europe/Madrid). Windows, Python 3.12.14, MCP SDK 1.30.0.
Previous release: [scoped atomic claims](VALIDATION_0_12.md).

## Observed problem and correction

An isolated CLI reproduction attempted to claim a ticket in a SQLite fixture that
contained only a `sentinel` table. The claim correctly failed because the ticket
did not exist, but startup had already added AgentRelay tables and default profiles
to the unrelated file. Its sentinel row survived; the observed defect was unwanted
schema/data addition. No neighboring application's database was used or altered.

`Store` now recognizes an existing file before obtaining its initialization write
connection. Empty, corrupt, incomplete and unrelated databases are rejected.
Recognition is shared with workspace/query preflight without a circular import.
New paths may initialize, and recognized legacy databases may migrate normally.

The CLI requires an existing project for `run` and non-creation actions. Only
`serve`, `mcp`, `create_ticket`, `create_plan` and `create_profile` may bootstrap a
new path. Action-envelope and actor validation precede initialization. Opening
errors are concise diagnostics. See [selection semantics](DATABASES.md).

Root review found a path-normalization mismatch in the initial implementation:
recognition expanded `~` while the write connection retained the literal path.
The correction makes both use the recognized absolute path, while inspecting the
selected file before resolution so a dangling symlink cannot become a new target.
A simulated home and unrelated literal-tilde decoy test this without touching the
real home directory. CLI resolution and directory creation were moved behind the
same boundary.

Independent interface review also found that a blank `action --actor` could
initialize a new database before the domain rejected it. The CLI now rejects
that identity before opening the database, with a regression checking that no
parent directory is created. Both packages passed cross-review after correction.

## Verification

The original foreign-file claim now fails before initialization; file bytes,
complete schema and sentinel rows remain equal. Direct Store and actual CLI
subprocess tests cover foreign, corrupt, empty and incomplete files; missing
non-creation paths create neither files nor parent directories. Creation actions,
legacy migration, simulated home expansion and supported links are covered.

A real CLI server started on a new disposable project, accepted a ticket over
HTTP, returned its context and preserved that exact ticket when reopened after
process shutdown. Its focused run passed in 0.616 seconds. MCP initialization is
covered by focused boundary tests and the existing real SDK integration suite.
No LLM provider is invoked by these tests.

SQLite online backups of LEVIATHAN, Dirt Riot, Valley of Rains and Cartógrafo
Imposible passed the new recognition and reopened successfully. All rows in the
copies remained equal, including 33 tickets; original pilot rows also remained
equal. No game worker or new game task was started by this check.

The initial 182-test suite passed with six Windows symlink skips. A second run
after the actor correction exposed the earlier intermittent Windows HTTP rejection
failure. The failing log is retained separately. Investigation sent HTTP headers
and bodies separately: 40 of 50 requests lost the rejection response with
WinError 10053, while all 60 ordinary immediate requests succeeded. No rejected
request created a ticket.

The server was closing early rejected POST requests with the body unread. It now
discards a uniquely framed body of at most 1 MiB before sending the existing
403/415 (or early 404), with a one-second total deadline and restored socket
timeout. It never interprets the discarded JSON or changes tickets. Unit checks
cover framing, exact consumption, deadline, EOF and socket errors; a real delayed
body test retains the required 403 assertion. The focused eight-test HTTP suite
passed in 2.801 seconds. The same 50-request reproduction then returned all 50
403 responses without an abort. Backend independently reviewed the root's fix.
Oversized, malformed or incomplete bodies may still lose their response when the
bounded discard ends; the change does not promise an error delivery to an
uncooperative peer.

The final full suite ran **186 tests: 180 passed and six Windows symlink tests
were skipped**, in 55.872 seconds. The companion skill passed structural
validation. Both specialist packages and the root HTTP change received independent
review. Development tickets AR-0032, AR-0033 and AR-0034 record their separate
deliveries; earlier pending acceptance was left unchanged.

The release check compares wheel and source-archive contents with the final
working sources. An isolated wheel installation exercises foreign/empty-file
rejection, new-path initialization, real fixture execution, retained results,
scoped claim replay and backup recovery. Local artifact hashes are recorded with
the package. CI is checked for the exact pushed commit across Windows/Linux and
Python 3.11/3.12; the run URL is reported alongside that commit.
Author reports: [service](database-guard-service-report.md),
[interfaces](database-guard-interface-report.md).

## Limits

The base-schema check recognizes compatibility; it does not authenticate a file
or defend against hostile concurrent path replacement. Valid project startup can
still perform migrations and SQLite bookkeeping. Existing zero-byte or empty
SQLite files are intentionally rejected; initialization requires a new path.

Windows hosts may not permit symlink fixtures; skips are explicit and Linux CI
exercises those cases. Specialist sandbox socket restrictions are not successes;
the root runs HTTP verification in its ordinary environment. There is no fresh
browser visual QA, new real-inference run or measured token-saving claim for this
release. Actual host model/effort remain unknown in development ticket records.
