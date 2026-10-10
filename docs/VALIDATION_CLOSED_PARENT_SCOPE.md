# AgentRelay 0.17.2 — preserving closed parent scope

Date: 2026-10-10. Review and reproductions used Windows with Python 3.12.14.

## Real review and reproduced defect

AgentRelay reviewed its own code through an explicitly configured Codex worker
(`gpt-6-sol`, effort `high`, read-only sandbox). Those are configuration
declarations, not provider attestations. The worker received verified frozen text
of `store.py`, the API contract, architecture and domain tests from commit
`69782179713e446feb5f80cda81bf5d5102ca735`.

Input snapshot:
`sha256:809157fc5cac832dd73708f9015130cab2b1327f1a0230cd7fbaa97efd731d7a`.
The submitted report was recovered through the actual MCP SDK without filesystem
access in that retrieval. A separate host check matched its 3,820 UTF-8 bytes
against the adapter report and receipt. Report SHA-256:
`e3423f2e9c6d0980d34131f98edd8ad0947aa15c2129546dc13b12b9f4852265`.

The first launch failed before analysis because its working directory was an
external capture directory, outside a Git repository. The host corrected cwd to
the actual project and explicitly requeued the same ticket. It retained the
failed run and unchanged input snapshot and did not relax sandbox or trust
checks. The successful run took 61.266 seconds. The model's report was static
analysis; the host separately executed the public-action reproductions below.

The defect: create a parent and child, cancel the child, submit and independently
accept the parent, then detach the child with `update_ticket(parent_id=null)`.
Before the fix, this succeeded while the parent remained `done` at revision 4;
its current children list silently lost the cancelled child. Moving that child
to another parent used the same unguarded source relationship. Adding children
to a closed destination was already rejected and was not a new defect.

The fix checks the old parent when `parent_id` changes. A `done` or `cancelled`
old parent now causes 409 before any changes commit. Reopen that parent explicitly
before reorganizing its children. The existing destination guard remains in
place. No schema migration, automatic reopening or historical data rewrite is
needed.

## Scope decision and limits

The worker also identified a review-freshness risk: while a parent is in review,
another action may add and complete a child without changing the parent's own
revision. The host reproduced acceptance using the earlier parent revision.
Independent review concluded that this is not an unambiguous violation of the
current per-ticket optimistic concurrency contract. Aggregate context versioning
or freezing child membership during review would introduce a new guarantee and
must account for help, split, plan imports and active worker conflicts. Neither
was silently introduced in this patch; the contract now states the existing
boundary explicitly. Completion still checks current blockers transactionally.

Reopening a child or dependency without changing its relationship remains
possible; a parent's previous acceptance is historical. Unrelated edits to an
editable child remain possible when `parent_id` is omitted. Explicitly supplying
the same closed-parent ID retains the existing destination rejection. This patch
does not claim full historical context snapshots, cryptographic reviewer identity,
fresh browser QA, game validation or semantic correctness of evidence links.

## Verification

The focused suite passed **9/9 tests in 3.337 seconds**: seven domain tests and
two integration tests using the generic CLI and actual MCP SDK subprocesses.
The full suite ran **248 tests in 75.707 seconds: 241 passed and seven Windows
symbolic-link tests were skipped** because the host lacked link privileges.
No failing functional case was suppressed or converted into a skip.

The regressions cover both closed statuses, detaching and moving, rollback of
combined field/dependency changes, destination protection, stale revisions,
explicit parent reopening and allowed historical child reopening. CLI/MCP
fixtures use distinct logical actors, not independent human reviewers. Their
negative paths preserve exported domain state and their positive paths confirm
the new relationship after reopening.

Implementation and protocol packages received separate independent static
reviews. A specialist's restricted SQLite fixture attempt failed before any
functional assertion; the successful runs above belong to the root's normal
environment. See the [implementation report](closed-parent-scope-implementation.md)
and [protocol report](closed-parent-scope-interface-report.md).

Distribution verification compares wheel/source-archive bytes with the checkout
and exercises the guard, rollback and explicit reopening from an isolated wheel
installation. Reloading the existing local pilot server was blocked by automatic
execution approval; that running server remains on 0.17.1 pending authorization.
No successful 0.17.2 live reload or browser check is claimed.
Exact-head CI runs the full suite on Windows/Linux with Python 3.11/3.12; its
result is recorded at publication, separately from these local measurements.
