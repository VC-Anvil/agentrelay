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

Three categories include `{total, tickets}`:

- `ready`: queued tickets whose dependency and child blockers are resolved.
- `review`: submitted tickets awaiting review; they may still have blockers.
- `blocked`: explicitly blocked tickets, plus queued tickets with derived blockers.

Each category's sample contains at most `limit` summaries, ordered by priority,
creation time and ID. The default limit is 5 and accepted values are 1–20.
`total` counts all matching tickets even when the sample is shorter. The blocked
category can therefore exceed `stats.by_status.blocked`, which counts only the
explicit status. It does not relabel tickets or change their lifecycle.

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
