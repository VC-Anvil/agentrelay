# AgentRelay 0.12 — scoped atomic claims

Date: 2026-10-10 (Europe/Madrid). Windows, Python 3.12.14, MCP SDK 1.30.0.
Previous release: [report integrity and portable result depth](VALIDATION_0_11.md).

## Observed workflow and change

Two real MCP connections read the same two isolated fixture tickets and both
tried to claim the urgent one. The existing revision guard correctly allowed one
claim and returned 409 to the other, while the second reviewed ticket remained
ready. This demonstrated an extra selection/claim round trip, not duplicate
ownership or a broken lock. No provider or model ran in this fixture.

`claim_next_ticket` selects at most one eligible ticket from an explicit reviewed
candidate set, by priority, creation time and ID. Revisions and readiness are
checked inside the write transaction. It never expands that set or preempts an
owner. Durable request receipts make exact retries historical and prevent an
uncertain response from causing another reservation. An idle response is also
retained. The operation is available through MCP and the existing CLI/HTTP action
envelopes; it does not launch workers or accept delivery.

## Independent review and actual use

Independent service review reproduced a request-ID collision across `create_plan`
and `claim_next_ticket`. Both had separate receipt tables and initially accepted
the same ID. The correction adds symmetric cross-action checks before new
mutations, preserving legitimate historical replays. Store and CLI regressions
cover both directions and verify tickets, events and receipts are unchanged on
rejection. The original finding remains in the local review evidence.

The root integrator used the new MCP tool to reserve actual independent review
tickets AR-0030 and AR-0031 in AgentRelay's development database. Exact retries
returned the original receipts without another claim. After the reviews were
submitted and independently completed, the same receipts still described the
historical assignments, while fresh context reported the tickets done. Replaying
them did not modify tickets, profiles, events or runs. An initial verification
mistakenly compared export-generation timestamps; the corrected comparison
excludes that timestamp and retains all domain fields.

Actual host model/effort remain unknown in these records. Recommended profiles
are not provider attestations. Earlier pending acceptance for AR-0018/AR-0019
and their parent remains unchanged.

## Verification

The final full suite ran **166 tests: 163 passed and three Windows symlink tests
were skipped**, in 50.527 seconds. A prior full run had an intermittent Windows
connection-aborted error in an existing HTTP host-rejection test. Its original
log was preserved; the isolated test passed, followed by the successful full
rerun without changing or weakening that test or the HTTP implementation.

Service tests cover distinct and repeated concurrent requests, priority ties,
explicit scope, strict revisions, graph/lifecycle blockers, acceptance, Astra
declarations, rollback, historical idle receipts, canonical payload replay and
backup recovery. CLI tests exercise exact envelopes and both cross-action guards.

The real SDK MCP integration passed independently in 2.002 seconds: two clients
read both candidate contexts, obtained different tickets, preserved an urgent
out-of-scope ticket, and retried without extra claims. A specialist's earlier
sandbox stdio attempt stalled and was interrupted; it is not reported as success.
The root HTTP integration passed in 0.642 seconds and verifies identical ticket
and request IDs in two independent projects, unchanged unrelated project state,
and a historical receipt beside the current state envelope.

SQLite backups of LEVIATHAN, Dirt Riot, Valley of Rains and Cartógrafo Imposible
were migrated in isolation. Only the empty `claim_requests` table was added;
all existing rows, including 33 tickets, remained equal. Original pilot databases
were read-only for that check. No pilot ticket was claimed and no game work ran.

The companion skill passed its structural validator. Source changes were reviewed
independently across service and interfaces. Author reports:
[service](claim-next-service-report.md), [interfaces](claim-next-interface-report.md).

The local release check compares wheel/source-archive contents to the working
sources. An isolated wheel installation exercises actual fixture worker execution,
retained-result inspection, scoped claim priority, exact retry, backup recovery,
cross-action collision rejection and report integrity. Package hashes are stored
with local artifacts. CI must be verified for the exact published commit.

## Limits

The server cannot attest that a caller reviewed or was authorized to execute every
candidate; clients must enforce that requirement. Preserve a user-selected task
with ordinary `claim_ticket`. This feature is scoped reservation, not broad queue
consumption, model execution, proof of model availability or acceptance of work.
Historical receipts require fresh context before further actions. SQLite backup
preserves receipts; bulk JSON export is not a complete restore. No token-saving,
SQL-performance or fresh browser visual QA claim is made.
