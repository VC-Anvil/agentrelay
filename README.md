# AgentRelay

[![tests](https://github.com/VC-Anvil/agentrelay/actions/workflows/tests.yml/badge.svg)](https://github.com/VC-Anvil/agentrelay/actions/workflows/tests.yml)

**A local project board that agents can actually work with.**

Turn goals into prioritized tickets, share durable context between agents, and keep delivery separate from acceptance. Humans use the web board; agents use the MCP server. Both operate on the same SQLite database.

AgentRelay 0.18 combines a persistent ticket board, an MCP server and optional worker execution. Agents find work through filtered summaries and open current context with recent history; older audit events remain available by cursor. Register multiple local projects, inspect their priorities without starting workers, import complete plans without duplicates, capture exact review inputs and inspect changes between verified captures. Reserve one of several reviewed tickets by priority without duplicate claims after retries. Find a ticket's worker executions, recover a retained proposal after a conflict and review it against the current ticket without launching the worker again. Independent reviewers can return deliveries for correction while preserving the original evidence and keeping feedback in worker context. Acceptance checks that the immediate context presented to the reviewer still matches current state. Connect an existing agent or explicitly launch a configured Codex, Ollama or custom worker. Model recommendations stay separate from worker declarations; delivery always needs independent review.

![AgentRelay local board with explicitly fictional demo data](docs/preview.jpg)

## Try it

Requires Python 3.11+. The web app and domain service use only the standard library. No frontend build, CDN, cloud account or API key is needed.

```sh
python -m agentrelay serve --demo
```

Open **http://127.0.0.1:8787**. The demo is explicitly fictional and lives in `.agentrelay/demo.sqlite`. To use an empty real workspace instead:

```sh
python -m agentrelay serve
```

That uses `.agentrelay/workspace.sqlite`. Stop the first server or use another `--port`. Each database represents one project. Always pass an **absolute `--db` path** when connecting agents to an existing workspace; relative paths depend on the process's working directory.

Existing files must be recognized AgentRelay databases before any startup writes;
unrelated, empty or corrupt files are rejected. `serve`, `mcp` and the creation
actions `create_ticket`, `create_plan` and `create_profile` may initialize a new
path. Queries, backup, `run` and other actions require an existing project, so a
misspelled path does not create an empty one. Valid databases still receive normal
migrations. See [database selection and initialization](docs/DATABASES.md).

Windows quick launch: `powershell -File .\Start-AgentRelay.ps1 -Demo`. It prefers `.runtime` (the development environment) or `.venv`, and runs the local web service hidden with logs under `.agentrelay`. It never installs packages or configures clients automatically.

To exercise a complete handoff from a checkout, install it and choose a **new**
output directory:

```sh
python -m pip install -e .
python examples/handoff_demo.py --output .agentrelay/handoff-example
```

This uses actual worker processes and persistent tickets with deterministic
fixtures, without calling a model. It demonstrates help, a report returned for
correction, independent acceptance and explicit parent resumption. The retained
database and backup let you inspect what happened. See the
[handoff walkthrough](docs/HANDOFF_EXAMPLE.md) for outputs and limits.

## What works

- Searchable Kanban and list views, urgency and priority, proposed/queued/running/blocked/review/done/cancelled states.
- Task descriptions, acceptance criteria, nested subtasks and explicit dependencies.
- Agent profiles with role, provider, model, recommended effort, capabilities and quality/speed preference.
- Atomic claiming and optimistic revisions: two writers cannot silently overwrite the same ticket.
- Checkpoints, comments, help requests and task splitting with preserved history.
- Independent review with evidence references and explicit acceptance; cyclic dependency/hierarchy combinations are rejected.
- Required acceptance-context tokens detect differences in immediate review context at acceptance. Version 0.18 changes the completion contract; [migration and limits](docs/ACCEPTANCE_CONTEXT.md).
- Independent requests for correction through MCP/CLI, with preserved deliveries and durable feedback. [Correction workflow](docs/REVIEW_CHANGES.md).
- Persistent audit history, versioned JSON export and isolated demonstration data.
- MCP tools for external agents and a companion [skill](skills/agentrelay-work/SKILL.md).
- Explicit worker launch/cancel, timeouts, bounded output, durable run history and conflict-safe results.
- Single-run proposal retrieval through CLI `run-result` and MCP `get_run_result`, preserving output for review after conflicts without replaying stale changes. [Usage and limits](docs/RUN_RESULTS.md).
- Captured report text can be reviewed through MCP without filesystem access; exact UTF-8, bounded size and no import of older artifacts. [Inline reports](docs/INLINE_REPORTS.md).
- Execution discovery through CLI `runs` and MCP `list_runs`, filtered by ticket and status with cursor pagination and a retained-proposal indicator. [Run history](docs/RUN_HISTORY.md).
- Explicit local `verify-report` checks distinguish intact, modified, missing and uncheckable reports; optional previously retained receipt hashes detect receipt replacement. [Integrity limits](docs/REPORT_INTEGRITY.md).
- Codex CLI and Ollama text adapters, plus a provider-independent JSON worker protocol.
- Bounded priority queue processing and online SQLite backup/restore.
- Bounded input snapshots with SHA-256 verification, external artifact directories and a JSON action CLI for active-project pilots.
- Historical source checks bind an explicit snapshot comparison to a ticket revision. Agents receive three compact recent observations and can inspect older checks or one exact saved report. [Source checks and limits](docs/SOURCE_CHECKS.md).
- A trusted multi-project registry and explicit project selection for every browser request; matching ticket IDs in different databases stay separate.
- `overview --workspaces /absolute/workspaces.json` summarizes priorities, review queues and blockers across registered projects without activating execution. [Overview contract and limits](docs/OVERVIEW.md).
- Atomic, retry-safe plan imports with local forward references and backlog defaults, plus read-only comparison of captured inputs against current sources. [Usage and example](docs/PLANS_AND_FRESHNESS.md).
- Bounded text changes between explicitly identified frozen snapshots, with exact line endings and explicit omitted-content reasons. [Snapshot comparison](docs/SNAPSHOT_DIFF.md).

The initial profiles reflect the local author's workflow: Astra/high coordinates, with Sol, Terra and Luna as specialists. These names do not mean those models are connected or available. Add your own provider/model profiles in **Perfiles**. The Astra coordinator profile is deliberately locked under the current workspace policy.

## Execute a ticket

Copy and edit [the worker configuration](examples/workers.codex.json), then start:

```sh
agentrelay serve --db /absolute/project/.agentrelay/workspace.sqlite --workers /absolute/workers.json
```

The package must be installed in the configured worker's Python environment. Open a ready ticket with acceptance criteria and select **Ejecutar tarea**. The **Ejecuciones** page records the process result. A worker can submit evidence, request help, split the ticket or report a blocker; it cannot approve its own work. Nothing launches on page load.

[Execution setup, worker protocol, bounded queue and recovery](docs/EXECUTION.md). Codex defaults to read-only; enabling workspace edits is an explicit configuration choice. Provider runs may consume your connected account's allowance. Ollama requires an already-installed model and supports written analysis, not tool execution.

For a project another team is actively changing, [capture exact review inputs and coordinate a separate pilot](docs/PROJECT_PILOTS.md). The ticket context includes target profile recommendations and the available profile catalog for help routing.

## Connect an agent via MCP

Install the official MCP SDK in your chosen environment:

```sh
python -m pip install -e ".[mcp]"
```

Configure a stdio MCP entry in a compatible host. Example JSON for hosts using `mcpServers` (replace every absolute path):

```json
{
  "mcpServers": {
    "agentrelay": {
      "command": "/absolute/path/to/venv/bin/agentrelay",
      "args": ["mcp", "--db", "/absolute/path/to/project/.agentrelay/workspace.sqlite", "--actor", "agent:worker-01"]
    }
  }
}
```

On Windows, use the environment's `Scripts/agentrelay.exe`. From an uninstalled checkout, use its Python executable with `-m agentrelay` and set the host's working directory to the repository. [Local configuration example](docs/LOCAL_SETUP.md).

Use a different stable actor name for each worker/reviewer connection. The actor is fixed by the launch command, rather than supplied with each tool call. The MCP layer is for trusted local collaborators; it is not a multi-tenant authentication boundary.

Useful tools: `list_tickets`, `get_ticket_context`, `list_ticket_events`, `list_profiles`, `create_ticket`, `create_plan`, `update_ticket`, `claim_ticket`, `save_checkpoint`, `request_help`, `split_ticket`, `transition_ticket`, `submit_ticket`, `review_ticket`, `add_comment`. `agentrelay://workflow` exposes the handoff rules as a resource.

`list_tickets` returns up to 20 summaries by default, ordered by priority. Filter
with `assignee` to resume owned work or `ready_only` to find available tasks.
Follow `next_offset` only if needed, and use `get_ticket_context` before claiming
or editing. `include_details: true` restores full ticket fields for that page;
`limit` accepts 1–100. **Clients upgrading from 0.4 must handle pagination and
summary fields** instead of assuming one call returns every complete ticket.
Pages are fresh reads and can shift when another participant changes the board.

**In 0.6, MCP context, CLI context and worker packets include the newest 20 audit
events by default.** The current ticket, checkpoint and acceptance stay complete.
`events_page.next_before_id` identifies omitted older history; fetch it with
`list_ticket_events` only when needed. CLI equivalents are `context --event-limit`
and `history --before-id`; `context --all-events` explicitly restores the full
history. No audit events are deleted. [History and cursor examples](docs/HISTORY.md).

## A real workflow

1. Create “Fix PDF pagination”, with concrete acceptance and a target profile.
2. An external worker lists ready work and atomically claims the current revision.
3. It saves findings; if it needs specialist input, it opens a help child with a reproduction. The parent becomes blocked.
4. Another worker delivers the help. After review, the original owner or human explicitly requeues the parent.
5. The worker resumes with the shared context, then submits artifacts for review.
6. A different identity checks every criterion and closes the ticket, or returns it to the queue with concrete corrections using `request_ticket_changes`. The worker receives that feedback alongside the preserved delivery. Parent goals still need their own integrated review.

Creating a ticket does not start a process. Urgency orders pending work but does not preempt an active agent. Help inherits its parent's priority when created; later priority changes remain explicit on each ticket. Evidence links are recorded references, not automatically verified artifacts.

Workers can add acceptance criteria as they discover necessary checks. Existing
criteria remain required while work is in progress, awaiting review, or blocked
with an assigned owner. Every scope update records the previous and new values.

## Tests and architecture

```sh
python -m unittest discover -s tests -v
```

Install `.[mcp]` to include the real SDK stdio integration test; otherwise it is explicitly skipped. The tests use disposable databases, including a complete help → resume → independent review scenario. No LLM is called.

The latest [acceptance-context validation](docs/VALIDATION_0_18.md) covers the stronger review contract and its use in a real design review. [Closed-parent scope validation](docs/VALIDATION_CLOSED_PARENT_SCOPE.md) covers another defect found through an AgentRelay review of its own code. [Handoff-example validation](docs/VALIDATION_HANDOFF_EXAMPLE.md) covers the reproducible fixture walkthrough. [Inline-report validation](docs/VALIDATION_0_17.md) covers real report retrieval without filesystem access; [correction-workflow validation](docs/VALIDATION_0_16.md) covers real worker delivery, independent feedback and resubmission. The project also has earlier browser QA of the human workflow. See [validation](docs/VALIDATION.md), [architecture and boundaries](docs/ARCHITECTURE.md) and [API contract](docs/CONTRACT.md).

The active [GitHub Actions workflow](.github/workflows/tests.yml) tests Python 3.11/3.12 on Windows and Linux and checks JavaScript syntax. [See actual runs and results](https://github.com/VC-Anvil/agentrelay/actions/workflows/tests.yml); local and real-inference results are documented independently in the validation report.

## Current boundaries

This release supports explicit launches and bounded serial queue processing. It does not run an unattended scheduler, measure token spend, synchronize GitHub Issues or provide multi-user authentication. Recorded model/effort values are declarations, not provider-attested telemetry. The browser represents one local human identity, so self-authored manual work needs a different reviewer connection.

The service binds only to `127.0.0.1`, checks Host/Origin and rejects cross-origin mutations. Do not expose it through a public proxy. Use `agentrelay backup --db /absolute/workspace.sqlite --output /absolute/new-backup.sqlite` for an online SQLite backup; copying a live WAL database's main file alone is insufficient. JSON export is an inspection report; restore uses the SQLite backup. Cancellation cannot undo files already changed. After a host crash inspect orphan processes before retrying.

MIT licensed. Source stays separate from private project data, environments and logs. No telemetry.
