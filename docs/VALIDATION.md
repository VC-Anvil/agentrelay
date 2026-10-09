# Validation — AgentRelay 0.3.0

Date: 2026-10-09. Windows, Python 3.12.14, MCP Python SDK 1.30.0,
Codex CLI 0.162.0-alpha.2. Earlier evidence is preserved in
[v0.2 validation](VALIDATION_0_2.md) and [v0.1 browser evidence](VALIDATION_0_1.md).

## Real active-project pilots

Four private, separate project databases were used for documentary reviews while
the source projects continued in their own sessions. The pilot did not edit their
sources, launch builds/emulators, message their sessions or certify their games.
All source bundles, configs, receipts and reports remain ignored under
`.agentrelay/pilots/`; this public report does not redistribute those inputs.

- Six actual Codex runs, configured `gpt-6-sol` / `high`, read-only sandbox:
  one requested help, five submitted reports (including one corrected attempt).
- In the first run, the host policy rejected file-reading commands. The worker
  honestly requested help and blocked its ticket. After explicit owner authorization,
  AgentRelay supplied verified snapshot text without changing the sandbox. A separate
  reviewer accepted the help before the original ticket was explicitly requeued.
- Independent inspection rejected one report's model recommendation because it
  contradicted that project's current policy. The pilot profiles and source context
  were corrected, and a second report was reviewed. The original attempt remains in
  the audit history. A separate false-positive review observation was explicitly
  withdrawn after checking the exact excerpt; it was not silently erased.
- Four documentary review tickets were accepted after inspecting their sources,
  limits and saved reports. The integrator created five proposed follow-ups per
  project, with priorities, profiles, acceptance, parentage and dependencies.
- A different reviewer checked all four snapshot/manifest/report identities,
  proposal graphs and model-policy handling, then accepted the four pilot objectives.
  The twenty proposed game tasks and their four parent objectives remain in backlog.
  None was executed or synchronized into the game development sessions.

The private trace includes `index.json`, `review-summary.json`, the per-project
`reviewed-plan.json`, and `independent-review.md`. These demonstrate one bounded
documentary workflow, not general autonomous coding performance or token savings.
Provider model fields are configured declarations, not independent attestation.

## Product changes driven by the pilots

Input snapshots preserve exact selected bytes and SHA-256 provenance. The first
real capture exposed Python 3.12 Windows path-stat versus descriptor-stat `ctime`
differences; the implementation and regression test now account for that without
discarding identity, size or modification-time checks. Captures are explicitly
non-atomic across multiple files and unsigned manifests are not authentication.

External artifact directories keep reports out of source projects. Explicit
snapshot text delivery supports providers without file tools, with strict UTF-8,
corruption checks and a 512 KiB context ceiling. Binary/oversized inputs fail before
provider invocation. Receipts record input provenance; new snapshot deliveries also
attach the receipt and hash the exact saved report bytes.

Ticket context now includes profile recommendations and the help-routing catalog.
A JSON action/context CLI uses the same revision and lifecycle checks; its output
is UTF-8 on Windows pipes. A startup workspace registry keeps projects separate
and binds requests to registered IDs, even when their ticket IDs are identical.

## Automated and independent checks

The final complete suite ran **62 tests in 16.089 seconds: 61 passed and one was
explicitly skipped** because this Windows account cannot create the symlink needed
by that case. Raw local log: `.agentrelay/v03-tests.log` (ignored). New tests cover input integrity and limits, adapter text supply and receipts,
CLI conflicts and Unicode, cross-project HTTP isolation and execution-manager
cleanup on startup failure. The actual MCP SDK stdio test is included. Fixtures
do not call LLMs.

Independent code review found two within-project UI races: a stale poll could
overwrite a confirmed mutation, and closing/reopening the same ticket could accept
an old context response. Data generations and context-request identities now guard
these paths; concurrent mutations are serialized in the UI. Four deterministic
JavaScript race scenarios passed against the actual application functions, via
the Node test included in the suite. A real two-manager HTTP/process fixture also
passed: identical ticket/worker IDs remain isolated, cross-project cancellation
returns 404, both reports land in their own database, and cancellation within the
selected project works. JavaScript syntax and whitespace checks passed.

The wheel and source archive built successfully. An isolated installation of the
wheel verified version/import provenance, packaged static assets, snapshot
capture/verification, the project registry and persistent tickets. Package and
source-archive bytes were compared with the corresponding working files, including
the JavaScript regression harness; private pilot directories were absent. Exact
distribution hashes are saved in `dist/SHA256SUMS-0.3.0.txt`.

The [CI matrix](https://github.com/VC-Anvil/agentrelay/actions/workflows/tests.yml)
records exact per-commit outcomes on Windows/Linux and Python 3.11/3.12.

The reviewer sandbox could not open SQLite files under its own temporary directory;
those setup failures are not counted as successful tests. The integrator's normal
environment ran the actual suite above. No filesystem sandbox was weakened by the
product. Specialist reports retain their environment limitations and test attempts.

## Visual boundary and operational limits

The board's earlier browser proof remains v0.1. The browser tool denied the previous
local preview; the new multi-project preview awaits explicit browser permission and
a fresh walkthrough. API checks and JavaScript syntax are not visual validation.

One trusted local user; one manager/active worker per database. Multiple configured
projects do not add shared-file locking across databases. No unattended scheduler,
automatic acceptance, signed provenance, provider spend metering, GitHub Issues
sync or public hosting. Inspect owned processes after a host crash before retrying.

See [project-pilot setup](PROJECT_PILOTS.md) and [execution boundaries](EXECUTION.md).
