# AgentRelay 0.14 — historical source checks

Date: 2026-10-10 (Europe/Madrid). Windows, Python 3.12.14, MCP SDK 1.30.0.
Previous release: [database guards and HTTP rejection](VALIDATION_0_13.md).

## Real use and resulting change

Comparing the existing documentary pilot captures against explicitly selected
current roots found one changed raw document in Dirt Riot and one in Cartógrafo
Imposible. LEVIATHAN and Valley of Rains matched their selected captured files.
The existing comparator could report this, but its result was not structured
context on the reviewing ticket.

The local `check-sources` command now records that point-in-time comparison against
an existing ticket revision. The service retains canonical report bytes and a
SHA-256, an immutable compact receipt and an audit event. Ticket context includes
three recent observations, with pagination and explicit detail through CLI/MCP.
An exact retry returns its historical receipt before reading source paths; fresh
measurement requires a new request ID. No check changes ticket state, revision,
acceptance, ownership or execution. [Contract and examples](SOURCE_CHECKS.md).

## Actual pilot exercise

Five checks were recorded through actual CLI subprocesses against the four
existing pilot databases, then retried with exactly the same arguments. Each
retry returned its original receipt without another check or event. Independent
detail reads recomputed each canonical report hash.

| Project and selected inputs | Unchanged | Modified | Missing / uncheckable |
| --- | ---: | ---: | ---: |
| LEVIATHAN reviewed documents | 4 | 0 | 0 |
| Dirt Riot original raw documents | 2 | 1 | 0 |
| Dirt Riot reviewed derived selection | 4 | 0 | 0 |
| Valley of Rains reviewed documents | 2 | 0 | 0 |
| Cartógrafo Imposible reviewed documents | 2 | 1 | 0 |

This distinction matters: Dirt Riot's original session-state document changed,
while all four files in the exact derived selection remained equal to the
reviewed capture. The two snapshot identities are kept separate. A comment on
the existing ticket explains their relationship without invalidating its prior
acceptance. Cartógrafo's changed file is its continuity document; that difference
alone does not invalidate all earlier work.

All existing ticket, dependency, profile, metadata, execution, plan-receipt and
claim-receipt rows remained equal. Existing audit events were preserved; the only
appended records were five source checks and their five events, plus the explicit
Dirt Riot clarification comment. The 33 pilot tickets were not reopened, claimed
or executed, and no game sources were edited.

Four real SDK/stdio MCP sessions then read those pilot contexts, paginated the
compact receipts and retrieved all five exact saved reports. Hashes and receipt
values matched the CLI observations; reads changed no domain state. The tools
have read-only annotations and no snapshot/root parameters. No new provider
inference was required.

## Implementation verification

Service tests cover canonical hashes, report bounds, exact replay after source
paths disappear and ticket revisions advance, all request-namespace collision
directions, concurrent identical requests, revision races, expected snapshot
identity before current-root access, bounded context, pagination, backups and
corrupt persisted reports. The root's focused run passed 10/10 in 0.814 seconds.

The real HTTP test passed in 0.705 seconds. Two projects with the same ticket ID
remain isolated; context exposes three historical summaries, a later ticket
revision produces a false revision-match flag, and an unsupported HTTP report
ingestion action cannot add a check. A changed source file does not rewrite an
earlier observation or silently turn it into a fresh measurement.

Final focused CLI and actual MCP SDK tests passed 5/5 in 4.802 seconds. They cover
explicit database selection, concise failures, stored reads and history, positive
integer bounds, read-only tools and the final controlled SQLite-error regression.
Both specialist packages received independent cross-review. A specialist sandbox
could not create snapshot fixtures through strict path resolution; this is
reported as an environment limitation, not a test success. Root verification
used the ordinary local environment.

The final full suite ran **202 tests: 196 passed and six Windows symlink tests
were skipped**, in 62.072 seconds. The companion skill passed structural
validation. The release check compares wheel/source-archive bytes to the working
sources and exercises persisted source-check detail, hash, exact replay and
backup recovery from an isolated wheel installation. Exact-commit CI covers
Windows/Linux with Python 3.11/3.12; its run is reported with the pushed commit.
Author reports: [service](source-check-service-report.md),
[interfaces](source-check-interface-report.md).

## Limits

Observations are historical and advisory. `ticket_revision_matches_now` compares
only ticket revisions, never current file contents. The explicit ticket/snapshot
association is not proof that the snapshot was the input of an earlier review.
The local method label and caller identity are not cryptographic attestations.
The comparison is bounded and per-file, not an atomic view of a changing project.

Full reports are excluded from bulk state, JSON export and worker context; SQLite
backup preserves them. Registered checks do not authorize game work, tool access,
publication or model execution. Normal database migrations remain possible.
Browser access remains pending, so this release claims CLI, HTTP and MCP behavior,
not fresh browser visual QA or a new browser control. No token-saving claim is made.
