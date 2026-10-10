# Inspect several projects without starting workers

Use the same trusted workspace registry as the web server:

```sh
agentrelay overview --workspaces /absolute/workspaces.json --limit 5
```

The command returns UTF-8 JSON with `schema_version: 1`, the configured default
workspace ID, project `count`, the sample `limit`, and a `projects` array in registry
order. It requires the registry and existing recognized AgentRelay databases;
it does not create a default project. The registry supports up to 16 projects.

Each project includes its ID, name, database path, demo marker, `stats` and an
integer `urgent_open` count. Urgent open includes backlog, queued, active,
blocked and review tickets, excluding done/cancelled. A proposed urgent ticket
remains a proposal; the count does not authorize its execution.

Since 0.21, four categories include `{total, tickets}`:

- `urgent`: all urgent open tickets, including proposals still in backlog.
- `ready`: queued tickets whose dependency and child blockers are resolved.
- `review`: submitted tickets awaiting review; they may still have blockers.
- `blocked`: explicitly blocked tickets, plus queued tickets with derived blockers.

Each category's sample contains at most `limit` summaries, ordered by priority,
creation time and ID. The default limit is 5 and accepted values are 1–20.
`total` counts all matching tickets even when the sample is shorter. The blocked
category can therefore exceed `stats.by_status.blocked`, which counts only the
explicit status. It does not relabel tickets or change their lifecycle.

`urgent.total` equals `urgent_open`; the integer remains available to existing
clients. A project can have an urgent proposal even when all three operational
categories are empty. Its summary retains `status: "backlog"` and `ready: false`.
Urgency does not resolve dependencies, resume paused work or authorize a claim.
An urgent review or blocked ticket also appears in its corresponding category;
these are overlapping views of the same ticket, not additional work items.

The new `urgent` field is additive within `schema_version: 1`. Clients that ignore
unknown fields can keep using the previous categories and counter. Clients that
validate an exact set of project keys must allow the new field. The CLI and Python
function expose this summary; there is no multi-project overview MCP tool or HTTP
endpoint in this release.

Summaries include ID, title, type, status, priority, parent, target profile,
assignee, revision, ready flag and blocker messages. They omit descriptions,
acceptance, checkpoints, evidence and audit history. Open current context in the
selected database before acting:

```sh
agentrelay context --db /absolute/selected/workspace.sqlite --ticket AR-0001
```

Ticket IDs are local to a database. Two projects can both have `AR-0001`; always
retain the project identity and database path. Ready does not prove model
availability, meaningful acceptance or worker compatibility. Review does not
prove that a ticket is approvable or that the caller is an independent reviewer.

## Operational boundaries

Overview does not construct execution managers, open worker configuration files,
acquire their execution locks, recover unfinished runs, claim tickets or start
processes. It can inspect registered databases while the web server owns their
managers. Existing recorded running states are not proof a provider is alive.

Registry/database validation happens before Store initialization. Recognized
AgentRelay databases still receive normal schema migrations, as with other CLI
inspection commands; this is not a filesystem-level read-only session.

Each project is read through one Store snapshot. Different projects are read
sequentially and do not share a global snapshot. The service still loads each
project's normal Store state before building summaries. Sample limits bound the
number of returned tickets, not string lengths, bytes, token spend or SQL work.
The output contains local project names, paths and task titles; treat it as
project data when sharing it.

The Python entry point is `agentrelay.overview.project_overview(config_path,
limit=5)`. The workspace loader's `enable_execution=False` mode supports this
inspection path; its default remains execution-enabled for the existing server.

## Urgent proposal validation in 0.21

The observed problem was a project with `urgent_open: 1` and empty ready, review
and blocked lists: its urgent backlog proposal could not be identified from the
summary. The new category exposes its ID, title, status and blockers without
turning the proposal into executable work.

Seven focused tests passed using the Python service and subprocess CLI. They
cover open states, exclusion of done/cancelled tickets, empty categories,
truncation, project-local IDs, existing summary fields, unchanged domain state
and the absence of execution-manager activation. Run them with:

```sh
python -m unittest tests.test_project_overview tests.test_cli_overview -v
```

Real-use validation captured consistent SQLite copies of the five configured
projects through read-only source connections. On those same copies, the
installed 0.20 CLI and the new CLI/Python output had identical previous fields.
The new category identified one urgent backlog proposal each in LEVIATHAN and
Valley; neither became ready. All tables in the copies remained unchanged after
the reads. This validates the captured data, not the games' current state or
permission to resume them. No worker, game or live-server upgrade was involved.
