# Validation — AgentRelay 0.4.0

Date: 2026-10-09. Windows, Python 3.12.14, MCP Python SDK 1.30.0.
Earlier evidence: [v0.3 active-project pilots](VALIDATION_0_3.md),
[v0.2 execution](VALIDATION_0_2.md), [v0.1 browser review](VALIDATION_0_1.md).

## Changes from observed use

The four real project pilots exposed two coordination needs: creating a related
plan should not leave partial tasks after a validation error, and reviewers need
to distinguish captured evidence from source files that may have changed later.

`create_plan` creates an entire bounded graph transactionally, including local
forward references. Its persisted request receipt makes retries safe after lost
responses, restarts and SQLite backup/restore. Proposals default to backlog. It
never launches a worker or approves a ticket.

`compare-snapshot` verifies captured bytes before inspecting the explicitly chosen
current root. It reports unchanged, modified, missing and uncheckable files with
sizes, hashes and reasons. Metadata paths do not select the current directory.

The comparison was used against the original captures of four projects:
all **12 selected files matched** at 2026-10-09 21:56 UTC. No drift-review proposals
were needed. This says nothing about unlisted files or later changes. One provider
had received derived excerpts; its original source capture was used for the live
comparison, rather than mistaking unchanged staged excerpts for a current project.
Private evidence remains in `.agentrelay/pilots/freshness-summary.json` and the
per-project comparison files. Source projects were only read.

AgentRelay also tracks this iteration in its private development database.
The coordinator imported the integration/review graph and replayed the request:
the same ticket IDs were returned without duplicate tasks. Implementation,
integration and independent review remain separate responsibilities.

## Checks

The final complete local suite ran **81 tests in 17.710 seconds: 79 passed, two skipped**
because this Windows account cannot create symbolic links. Log:
`.agentrelay/v04-tests-final.log` (ignored). JavaScript syntax and whitespace checks passed.

New coverage includes forward references, rollback of tickets/events/counter,
concurrent identical requests, conflicting payloads/actors, normalized external
IDs, invalid Unicode and graph constraints. Real HTTP, MCP SDK stdio and CLI
round trips cover plan import/replay and conflicts. The documented JSON example
is exercised through a restarted CLI and restored SQLite backup.

Freshness checks cover same-size byte changes, disappearance, invalid/traversing
manifests before source access, explicit root selection, changed snapshot identity,
unsafe/nonregular paths, unstable reads and file/total limits. Failed reads reserve
their observed size; each stable-file reader can inspect one additional byte to
detect growth, bounded by the maximum 64 files. CLI tests distinguish a matching
comparison, drift and invalid input through JSON results and exit codes.

Integration review found and corrected raw-versus-normalized external relations
and an uncounted failed-read budget. A regression fixture initially created a real
parent/dependency cycle; it was corrected to use independent existing tickets,
preserving the product's rejection of deadlocks.

Specialist sandboxes could not use normal Windows temporary paths; their reports
distinguish those setup failures and patched diagnostics from the integrator's
normal complete run above. No product sandbox was weakened. Test workers use local
fixtures; these checks do not consume LLM inference.

Independent review also reproduced an operating-system read error that aborted
the entire comparison. The fix reports that file as uncheckable and continues;
the new regression verifies another readable file is still compared. The reviewer
checked the fix, and the complete suite above includes it.

The wheel and source distribution built successfully. An isolated wheel install
verified source provenance, packaged assets, persistence, snapshot verification,
freshness comparison, registry loading and plan replay. All 13 wheel package files
matched the working source; source-archive code/tests/docs also matched, without
private pilot data. Exact hashes are saved in `dist/SHA256SUMS-0.4.0.txt`.

The owned local preview was restarted after checking that no pilot worker was
running. Its health reports 0.4.0; API checks verified all four project databases
and the separate development database under their registered identities.

The published v0.4 commit's [four CI jobs passed](https://github.com/VC-Anvil/agentrelay/actions/runs/37996962498)
on Windows/Linux and Python 3.11/3.12. The
[CI matrix](https://github.com/VC-Anvil/agentrelay/actions/workflows/tests.yml)
records outcomes for each subsequent commit; pending runs are not acceptance.

## Boundaries

Plan receipts preserve creation-time revisions; clients must fetch current context
before later edits. Idempotency is scoped to the database and declared actor, not
multi-user authentication. JSON export remains an inspection report; SQLite backup
preserves request receipts for restore.

Snapshots are unsigned and do not provide an atomic multi-file view or protection
against a hostile local filesystem race. Freshness detects selected byte changes,
not semantic correctness. Completed historical reviews are not automatically
reopened. Execution remains explicit and reviewed separately.

Fresh multi-project browser QA still awaits the user's answer to the browser tool's
access denial. API and Node checks do not substitute for visual verification.
No claim of autonomous game completion, measured token savings or provider-attested
model execution is made. The other projects' source work and chats remain separate.
