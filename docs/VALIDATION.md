# Validation — AgentRelay 0.2.0

Date: 2026-10-09. Windows, Python 3.12.14, MCP Python SDK 1.30.0, Codex CLI 0.162.0-alpha.2. The earlier browser validation is preserved in [v0.1 evidence](VALIDATION_0_1.md).

## Automated checks

Final command: `python -X utf8 -m unittest discover -s tests -v` — **35 passed in 11.543 seconds**. Raw local log: `.agentrelay/v02-final-localtemp.log` (ignored).

- 13 Store domain tests, 3 integrity regressions, 3 real HTTP tests and 1 actual SDK stdio client/server test preserve the existing ticket lifecycle.
- 8 subprocess execution tests cover claim/result transactions, help/split, failure, nonzero exit, malformed and oversized output, timeout, cancellation, contention, stale revision protection, restart recovery, profile constraints and required acceptance. These use explicitly identified Python fixtures, not LLMs.
- 7 integration/adapter tests cover HTTP launch through independent review and export, online backup/reopening and overwrite rejection, priority ordering, persistent demo labeling, API validation, exact saved report contents, explicit Codex model/sandbox/schema and rejection of unsupported Ollama settings.

JavaScript syntax, companion skill validation and `git diff --check` are additional release checks. Source and wheel distribution checks are recorded in the local build logs and `dist/SHA256SUMS.txt`. CI is not active: the GitHub publishing credential lacks `workflow` scope. The prepared Windows/Linux matrix remains [a template](github-actions-tests.yml), not a passing CI claim.

## Real inference and independent acceptance

A separate `.agentrelay/live-validation.sqlite` project was used; no fictional demo ticket was treated as real work.

- Ticket `AR-0001`: identify the dependency cycle A depends on B, B on C, C on A; remove one edge; report a valid execution order and explicitly state the limits of textual analysis.
- Worker `codex-sol`: installed Codex CLI, configured `gpt-6-sol` / `high`, read-only sandbox, isolated working directory, 240-second timeout. No fallback model.
- Run `run-19e5ecdfbaba49a9b6904bcbbbd225e9`: started 20:55:13.894 UTC, submitted 20:55:26.830 UTC. Wall-clock run duration 12.936 seconds includes the adapter and CLI, not just inference.
- The actual saved report correctly identified A → B → C → A, removed C's dependency on A and proposed C → B → A. It explicitly stated that no code tests had run. [Exact report copy](../examples/results/cycle-report.md), SHA-256 `22c113a77d7267f109612f9f5dbcffb6617f1bacda4d68c547682dcba9011ae2`.
- The ticket first entered `review`. The integrator read the artifact, checked all three criteria and completed it using the separate `agent:astra-reviewer` identity. This was an actual review, not worker self-approval.

This verifies one bounded real-model text task through the shipped Codex bridge. It does not benchmark general coding ability, attest provider internals or measure token savings. Ollama was installed but had no local models; no Ollama inference is claimed and no model was downloaded.

## Review and environment findings

Independent frontend review found and the integration corrected: running without acceptance criteria, incompatible wildcard workers offered for Astra, a cancellation race with an inaccurate success toast, discarded subprocess diagnostics, missing taskkill fallback, incoherent ticket/run snapshots and unhelpful configuration tracebacks. Late drawer-context responses are also guarded. Diagnostics remain bounded local files rather than web content.

A preliminary 35-test integrated run passed in 135.381 seconds. A subsequent run stalled and failed on the shared D: test directories. A faulthandler trace located a long wait in SQLite connection close during test setup; raw attempts remain `.agentrelay/v02-final-tests.log` and `.agentrelay/execution-diagnosis.log`. Tests now use the operating system's temporary directory instead of forcing test databases into the source/virtual-environment tree. The final full run above passed without changing acceptance checks, worker deadlines or SQLite durability settings. Interrupted and failed attempts are not counted as passing.

## Visual verification boundary

The v0.1 board and manual workflow were exercised in the browser and captured in `docs/preview.jpg`. During v0.2 validation the browser tool denied access to the local page, so the new execution UI has static review, syntax and HTTP-contract verification but **has not yet received a fresh browser walkthrough**. No alternate browser route was used after that denial. The pending user authorization is for the local preview at `http://127.0.0.1:8788`.

## Operational boundaries

One trusted local user, one execution manager and active worker per database. No unattended scheduler, provider spend metering, GitHub Issues sync, cross-project file locking or public hosting. Model fields are configured declarations. Evidence requires review. Cancellation stops owned processes under normal operation but cannot revert files. An abrupt manager/host crash can leave orphan children; restart blocks unfinished tickets without automatically retrying or killing potentially reused process IDs. Inspect processes and changed files before retrying interrupted work.

Continue with [execution setup](EXECUTION.md) and [local checkout configuration](LOCAL_SETUP.md). Remaining acceptance gates are the fresh v0.2 browser walkthrough and running the prepared GitHub CI matrix once an authorized credential can install it.
