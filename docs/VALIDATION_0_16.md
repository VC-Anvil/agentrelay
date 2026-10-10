# AgentRelay 0.16 — independent requests for correction

Date: 2026-10-10 (Europe/Madrid). Windows, Python 3.12.14, MCP SDK 1.30.0.
Previous release: [frozen snapshot differences](VALIDATION_0_15.md).

## Real use and discovered gap

Two configured Codex workers reviewed the frozen change context from Dirt Riot
and Cartógrafo Imposible. Each received supplied text only, under the existing
read-only documentary profile with declared `gpt-6-sol` / `high`. The host verified
the captures before sending them. Neither ticket authorized game work, external
messages or following references into the live projects.

Both workers delivered reports and entered review. Independent reviewers found
real corrections: Dirt Riot's report confused an earlier lack of verification
with missing implementation and overlooked a declared comparative performance
figure; Cartógrafo classified three historical checks as currently pending even
though the supplied continuity document had been superseded.

An isolated reproduction then confirmed a workflow gap: an independent agent
could complete a review but could not return it to the queue using its own
identity. Generic `transition` correctly rejected that ownership change with
409 and left context unchanged. A specific review decision was needed.

## Resulting behavior

`request_changes` / MCP `request_ticket_changes` returns only a `review` ticket
to queued, with a nonempty bounded reason, current revision and independent
reviewer. It preserves the author's checkpoint, evidence, acceptance, scope,
dependencies and model declarations while releasing the assignee. It does not
claim, start work, remove blockers or reopen a completed ticket.

The latest request appears as `review_feedback` in the same transactional context
read, independently of the recent-event page. Later submission and completion
flags describe audit events only. They do not infer that corrections were right.
No new database table or migration was needed. [Exact contract](REVIEW_CHANGES.md).

## Verification

Domain tests cover independent/self identities, malformed fields, revision
conflicts, competing reviewers, exact preservation of delivery and other tickets,
dependency blockers, all rejected states, historical feedback, resubmission,
completion and backup. A final focused service/MCP/CLI run passed **8/8 tests in
3.003 seconds**. The SDK tests use separate author/reviewer stdio connections;
CLI tests use actual subprocesses and the existing action command.

A real fixture worker received a correction request after 25 newer comments
had pushed it outside the newest 20 events. Its packet still contained the
reviewer, reason, revisions and preserved original delivery. Resubmission added a
new delivery while the old submission remained in audit history. The focused
service/worker run passed **7/7 in 1.207 seconds** before the final ID-validation
delta; the final full suite includes that delta and the worker fixture.

The complete local suite ran **228 tests: 221 passed and seven Windows symlink
tests were skipped**, in 68.119 seconds. The companion skill passed structural
validation. Both implementation packages received independent cross-review.
Specialist temporary-fixture restrictions were reported as environment limits;
executed results here belong to the root's ordinary local environment.

Two actual reviewer MCP sessions returned the real documentary tickets from
review revision 3 to queued revision 4. Both author checkpoints and evidence
lists were identical before/after. Other tickets and execution records were
unchanged, and no process started from the review action. The existing configured
worker was launched explicitly afterwards for each correction, one at a time.
Original report files and receipts were preserved in their original directories.

Both corrected provider deliveries subsequently passed independent documentary
review against the same four frozen inputs and the precise correction reasons.
The host verified both snapshots and all four report/receipt pairs; original
execution records and every unrelated ticket remained unchanged. Independent
MCP review then completed both documentary tickets at revision 7. Their feedback
history now records later submission and completion. The corrected reports do
not claim new verification of either game. This exercises the full real cycle:
submission, requested correction, explicit relaunch, resubmission and acceptance.

The live five-workspace server restarted into 0.16.0 with no active worker;
all database rows were equal across that restart. The package release check
compares wheel/source archive and skill bytes to working sources and exercises
the correction workflow plus backup from an isolated installation. Exact-head CI
covers Windows/Linux and Python 3.11/3.12; its result is reported with publication.
Author reports: [service](review-changes-service-report.md),
[interfaces](review-changes-interface-report.md).

## Limits

Review identities are trusted local declarations, not multi-user authentication.
Returning work makes it queued; dependency readiness and existing execution
authorization still apply. It does not automatically retry a worker. A stale
request conflicts; reread context instead of replaying an old revision blindly.

The new action preserves existing generic transition ownership rules. Original
reports remain filesystem artifacts referenced by evidence, and report hashes
prove byte equality only. Documentary acceptance is not acceptance of a game,
ROM, audio, art or runtime performance. Declared model settings and provider
attestation remain distinct; no token-saving claim is made.

No new browser control was added. Browser access remains pending, so this release
claims tested domain/CLI/MCP/worker behavior, not fresh browser visual QA.
