# Validation — AgentRelay 0.8.0 candidate

Date: 2026-10-10 (Europe/Madrid). Windows, Python 3.12.14, MCP SDK 1.30.0.
Previous release: [0.7.1 active work](VALIDATION_0_7_1.md).

The new `overview --workspaces REGISTRY --limit N` command reports status totals,
open urgent counts and bounded samples of ready work, reviews and blockers across
registered projects. Queued tasks waiting on dependencies appear as blocked in
the summary without changing their stored status. [Contract](OVERVIEW.md).

Overview omits execution-manager initialization, worker-config reads, recovery,
claims and process launches. Normal Store migrations on recognized databases
remain possible. The existing web server path retains its previous behavior.

The command was used with five actual local registry entries: **53 tickets and
six historical execution records**. Tickets, profiles, events and run records
were unchanged. Proposed game follow-ups stayed in backlog. Private trace:
`.agentrelay/v08-pilot-overview.json`.

The full suite ran **111 tests in 33.270 seconds: 109 passed, two skipped** for
Windows symbolic-link privileges. Private log: `.agentrelay/v08-tests.log`.
Tests cover bounded samples with complete totals, priority order, repeated ticket
IDs in separate projects, manual/derived blockers, strict limit validation,
missing/duplicate registries, UTF-8 CLI output, missing worker configurations and
failure on a corrupt second database without partial JSON or default DB creation.

A real fixture process waited under its existing manager while overview read its
database. Tickets, profiles, audit and run records stayed identical. The original
manager subsequently accepted the released process's submission normally. No LLM
provider was invoked by these tests. An independent reviewer checked that test,
the operational documentation and the updated companion skill. The skill
validator passed. [Service report](overview-service-report.md),
[CLI report](overview-cli-report.md).

During coordination, specialists corrected inferred model/effort declarations to
`unknown` using audited actions because exact host metadata was unavailable.
Earlier events and evidence were retained. This illustrates why recommendations
and worker declarations must not be treated as runtime attestation.

The wheel was installed in an isolated target and verified, including the new
overview service, all 14 package source files, bundled skill and source archive.
Final ticket acceptance remains pending. The
[CI history](https://github.com/VC-Anvil/agentrelay/actions/workflows/tests.yml)
records exact commit outcomes; a pending run is not a pass.

Each project is a separate Store snapshot. Sample limits do not bound field
lengths, SQL work, tokens or quota. Ready work still needs authorized scope,
current context and a compatible worker; review status does not prove acceptance.
Fresh browser QA remains pending explicit authorization after the earlier tool
denial. Protocol tests are not visual verification. No game source was changed.
