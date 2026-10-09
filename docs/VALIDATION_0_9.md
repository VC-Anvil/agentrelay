# AgentRelay 0.9 — retained worker proposals

Date: 2026-10-10 (Europe/Madrid). Windows, Python 3.12.14, MCP SDK 1.30.0.
Previous release: [multi-project overview](VALIDATION_0_8.md).

## Reproduction and behavior

A real local Python worker produced a summary and evidence while a concurrent
human edit changed its ticket. AgentRelay correctly preserved the edit and
recorded a conflict, but the run query showed only an empty summary and an error.
The produced proposal remained in local `stdout.json` diagnostics.

New execution managers retain normalized protocol output in SQLite before
attempting application. Explicit CLI/MCP queries retrieve one proposal with its
claim revision and the current ticket identity. They do not rerun the worker,
replay its edits or accept its evidence. A separate transaction preserves the
proposal when application rolls back. Bulk snapshots and exports stay unchanged.

## Verification

The integrated suite ran **123 tests: 121 passed, two Windows symlink tests
skipped**, in 39.448 seconds. Coverage includes actual worker processes,
concurrent edits, rejected help that rolls back partial changes, cancellation
before and after capture, UTF-8 output expansion, legacy schema migration and
SQLite backup. After strengthening the cancellation test to wait for its
application callback, its author reran that one test successfully.

The root integration test reads an active worker through the CLI, causes a
conflict, retrieves its output, rejects submission using the old revision and
then explicitly submits the reviewed fixture output with fresh context. The
concurrent description survives; one run remains recorded as conflict and the
ticket is delivered for review, not completed. This proves the mechanism with
a fixture, not the correctness of an arbitrary model's deliverable.

The real MCP client/server test verifies tool discovery, Unicode output, legacy
null results, invalid input and isolation without domain mutation. Three CLI
tests additionally reject missing and unrelated databases without bootstrapping
them. The companion skill passes its structural validator.

Six historical runs across the four documentary pilots — LEVIATHAN, Dirt Riot,
Valley of Rains and Cartógrafo Imposible — return the expected null proposals.
Their 33 tickets, profiles, audit events and execution history are unchanged.
No game source was edited or game worker relaunched. One initial private pilot
check used the wrong development registry ID and failed its final project-count
assertion; correcting the checker to the actual ID resolved that check.

The service author and interface author reviewed each other's surfaces. Their
review found and corrected documentation of the capture-to-application interval:
a run can still be `running` while its proposal is already available. Reports:
[service](run-results-service-report.md), [interfaces](run-results-interface-report.md).
The interface author's sandbox stdio run was interrupted; the root's normal
environment executed MCP successfully. Those outcomes are recorded separately.

## Limits and release evidence

Older runs are not reconstructed from logs. An interrupted or cancelled run can
retain a proposal if capture preceded interruption, or return null otherwise.
Stored protocol structure does not validate evidence or attest provider/model
execution. One query is a SQLite snapshot, not a reservation for a later write.
No model-token savings or fresh browser visual review is claimed.

The local wheel and source archive are checked against source bytes, with an
isolated wheel installation exercising a real worker and result retrieval.
Artifact hashes and build/test logs are kept in the local release directory.
CI applies to the exact pushed commit and must be checked separately.

The earlier overview tickets AR-0018/AR-0019 remain in review pending the
outstanding approval after an automatic execution-policy rejection. This
release does not change that acceptance or claim its integration parent.
