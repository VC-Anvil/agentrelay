# AgentRelay validation

The current 0.11.2 work is covered by [report integrity and stored-result validation](VALIDATION_0_11.md).
Earlier [execution discovery validation](VALIDATION_0_10.md) remains available.
The preceding [retained worker proposal validation](VALIDATION_0_9.md) is archived.
Earlier [multi-project overview validation](VALIDATION_0_8.md) remains available;
its pending ticket acceptance has not been changed. No pending acceptance or
CI job is counted as a successful review.

## Previous release — AgentRelay 0.7.1

Date: 2026-10-10 (Europe/Madrid). Windows, Python 3.12.14, MCP SDK 1.30.0.
Previous release: [0.7 database and graph robustness](VALIDATION_0_7.md).

## Active work and help recovery

Three defects were reproduced in isolated databases before correction:

- An urgent task requested help, but the help entered the queue at normal priority.
- Adding a legitimate acceptance criterion to an active ticket raised TypeError
  during audit serialization. The transaction rolled back, preventing the update.
- After requesting help, the assigned parent became blocked and could then have
  its acceptance criteria reduced, bypassing the protection on active work.

Help now inherits the current parent priority at creation, like split children.
Later priority changes remain independent; no active owner is preempted. The
explicit target profile, help dependency and independent review stay intact.
[Priority report](help-priority-report.md).

Acceptance can grow in progress, review, or blocked with an owner. Its previous
and new values are recorded correctly without replacing the audit dictionary
with a set. Existing criteria cannot be removed in those states. Planning in
queued, backlog or unassigned blocked tasks retains scope-editing behavior.
[Acceptance report](acceptance-update-report.md).

## Checks

The full suite ran **104 tests in 31.526 seconds: 102 passed, two skipped** for
Windows symbolic-link privileges. Private log: `.agentrelay/v071-tests.log`.
Store tests cover queue order, later reprioritization, self-review rejection,
independent completion, acceptance expansion in progress/review/blocked,
correct audit values, conflict/ownership rejection and planning compatibility.

A real MCP SDK stdio client claimed an urgent task, added a required criterion,
read its before/after audit, attempted a forbidden reduction, requested targeted
help, attempted another reduction while blocked, and discovered the urgent help
before other high-priority work through filtered ticket summaries. The test uses
an explicit fixture model declaration and makes no LLM provider call.

An independent reviewer identified the blocked-owner acceptance gap during review
of the MCP test; the integrator reproduced it before the additional correction.
Specialist sandbox test setup limitations are recorded separately from the
integrator's normal suite above.

Distribution verification checks an isolated wheel install, packaged source and
skill bytes, and source archive contents before publication. The
[CI history](https://github.com/VC-Anvil/agentrelay/actions/workflows/tests.yml)
records exact commit outcomes; pending runs do not count as passing.

## Limits

Priority inheritance applies at help creation, not retroactively to existing
help tickets, and does not propagate later edits. Accepted criteria remain a
reviewer's assertion backed by their evidence, not an automated quality verdict.
Explicit requeueing still remains necessary after help is reviewed.

These regression fixtures do not modify the four game projects or their source
files. Existing documentary pilots remain separate. Fresh browser QA is still
pending explicit authorization after the earlier tool denial; protocol and CLI
checks do not constitute visual verification.
