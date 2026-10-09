# Validation — AgentRelay 0.5.0

Date: 2026-10-10 (Europe/Madrid). Windows, Python 3.12.14, MCP SDK 1.30.0.
Previous evidence: [v0.4 plans and freshness](VALIDATION_0_4.md),
[v0.3 four project pilots](VALIDATION_0_3.md), [v0.1 browser review](VALIDATION_0_1.md).

## Agent context and continuity

MCP ticket listing now returns filtered, priority-ordered pages of summaries.
The default page contains at most 20 tickets; the limit is configurable from 1 to
100. An owner filter supports resuming work. Full detail remains available by
explicit request or through individual ticket context. This changes the previous
unpaginated default; the README and API contract explain client migration.

Real MCP stdio calls were made against all four project-pilot databases and the
separate AgentRelay development database. For the same 41 tickets, compact UTF-8
JSON structured results totaled **11,424 bytes summarized versus 50,605 bytes
with full details**. The measurement excludes protocol envelopes, tool definitions
and subsequent context requests. It is not a token count or measured quota saving.
Raw per-project measurements stay private in `.agentrelay/v05-listing-measurement.json`.
The service still loads local Store state; no SQL performance improvement is claimed.

The companion skill was updated and validated with the skill-creator validator.
A separate evaluator then used the skill against an isolated fixture, without
seeing the checker's baseline or expected results. Through the real CLI it:

- Resumed a chosen blocked ticket after inspecting completed help.
- Replayed the interrupted plan request without duplicate tickets or events.
- Counted four source records correctly: three PDF and one DOCX.
- Preserved the source hash, backlog proposals and an unrelated urgent task.
- Saved a checkpoint and submitted its report for independent review, without
  approving its own delivery or starting the unrelated task.

The coordinator independently compared the outcome against the withheld baseline,
source bytes, report and audit events. This is one observed agent workflow, not
proof of reliable behavior for arbitrary models or tasks. No additional provider
worker or deployment was launched by the evaluator. Private evidence is under
`.agentrelay/skill-eval-v05/`; the public skill includes no private fixture inputs.

## Automated checks and review

The final complete suite ran **82 tests in 18.947 seconds: 80 passed, two skipped**
for unavailable Windows symbolic-link privileges. Log: `.agentrelay/v05-tests-final.log`.
The new actual MCP SDK test creates 30 fixture tickets and checks ordered pages,
owner/state/profile/urgency filters, full detail, empty pages and strict invalid
input handling. It rejects booleans, strings and fractional pagination values.

An earlier full run encountered one Windows loopback connection abort (WinError
10053) in the unchanged HTTP rejection test. The error is retained in
`.agentrelay/v05-tests.log`; the four isolated HTTP tests and final full suite then
passed. No root cause or product fix is claimed. The test now reports the exact
header subcase if the failure recurs; no retries or relaxed assertions were added.

The skill's initial edit unnecessarily blocked non-Astra work when host metadata
was unavailable. Review restored an explicit `unknown` declaration for those
profiles. The locked Astra role still requires known compatible host settings;
recommendations never become evidence of actual execution. The final skill was
used in the independent fixture exercise above.

The wheel and source archive built successfully. The isolated wheel installation
passed snapshot, freshness, plan replay, registry and persistence checks. All 13
package files and the packaged skill matched working source bytes; the source
archive also matched code, tests, docs, skills and examples. Private pilot data
was absent. Distribution hashes are in `dist/SHA256SUMS-0.5.0.txt`.

The previous v0.4 [CI matrix passed all four jobs](https://github.com/VC-Anvil/agentrelay/actions/runs/37996962498).
The [workflow history](https://github.com/VC-Anvil/agentrelay/actions/workflows/tests.yml)
records exact subsequent commit outcomes; pending jobs are not counted as passing.

## Limits

Listing bounds record count and selected fields, not arbitrary string lengths or
bytes. Offset pages may shift while another participant changes the board; clients
must read fresh context before a mutation. The skill coordinates existing scope
and host permissions and does not install or launch workers by itself.

The four game projects were used through their separate documentary pilot records.
Their sources and chats were not modified. New multi-project browser verification
still awaits explicit authorization after the earlier browser-tool denial. API,
CLI, MCP and deterministic JavaScript checks do not establish visual quality.
