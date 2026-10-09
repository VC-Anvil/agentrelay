# Explicit worker execution

AgentRelay 0.2 can launch trusted local worker processes. The normal board and MCP
server still work without execution configured. No inference happens on startup.

## Setup

Install AgentRelay into the Python environment used by the worker (`python -m pip
install -e .` for a checkout). Copy [the Codex configuration](../examples/workers.codex.json)
outside version control and replace the Python executable and project directory.
On Windows use `D:/path/to/venv/Scripts/python.exe`; JSON supports forward slashes.
The `cwd` must be an existing project directory. Relative `cwd` paths resolve from
the configuration file. Executable paths should be absolute. Keep credentials out
of command arguments and configuration files.

```sh
agentrelay serve --db /absolute/project/.agentrelay/workspace.sqlite --workers /absolute/workers.json
```

On Windows the launcher also accepts `-Workers` and `-Db`. Choose a queued, ready
ticket with acceptance criteria and the matching profile. Click **Ejecutar tarea**.
The **Ejecuciones** page shows actual process state and can cancel a running worker.
The worker can deliver, ask for help, split work or report a blocker. Delivery enters
review; the person or another MCP identity verifies acceptance before completion.

The configuration is trusted executable code. Tickets and web requests cannot
choose arbitrary commands, arguments or working directories. Each entry contains
`id`, `name`, `command` (an argv array, no shell), `cwd`, `model`, `effort`,
`profile_ids`, and `timeout_seconds` (1–3600). An empty profile list accepts any
profile; a nonempty list requires an exact ticket profile match. Astra always
requires `gpt-6-astra` / `high`.

There is one running worker and one execution manager per database. Separate
databases are separate projects; the user must avoid concurrent workers changing
the same files through different databases. Urgency never interrupts active work.

## Bounded queue processing

```sh
agentrelay run --db /absolute/project/.agentrelay/workspace.sqlite --workers /absolute/workers.json --worker codex-sol --limit 3
```

This explicitly processes up to three compatible ready tickets, serially, ordered
urgent → high → normal → low, then creation time. It never auto-reviews. It stops
on execution failure or a conflict. `--ticket AR-0001` runs one exact ticket instead.
Use either the execution-enabled web server or this CLI against a database, not
both simultaneously. The default limit is one; no background scheduler is installed.

## Built-in bridges

**Codex CLI** uses the installed CLI and its existing login. Its default sandbox is
read-only. To authorize file changes, explicitly append `--sandbox`,
`workspace-write` to the adapter command in the trusted config. The adapter never
uses `danger-full-access`, bypasses approval, installs tools or publishes changes.
The CLI is run with approval policy `never`, an explicit model/effort, a JSON output
schema, and `--ignore-user-config` to avoid importing unrelated personal automation.
Project instructions and the CLI's own sandbox still apply. Unsupported CLI flags
or unavailable model names fail visibly; no fallback model is substituted.
Validated CLI version and inference evidence are recorded in [validation](VALIDATION.md).

The implementation follows the installed `codex exec --help` and OpenAI's
[structured execution example](https://developers.openai.com/cookbook/examples/codex/build_iterative_repair_loops_with_codex).
Using this bridge can consume the connected account's usage allowance.

**Ollama** is a text-only bridge to loopback port 11434, using the documented
[`/api/chat` endpoint](https://docs.ollama.com/api/chat). It can write an analysis
report from the supplied ticket context; it cannot inspect source files, use tools
or claim to have tested code. It requires an already-installed model. It does not
download models. Effort is `default` (model default) or `none` (thinking disabled);
other efforts are rejected. Cloud-named models are rejected. Local endpoint access
alone does not attest where a custom Ollama server performs inference.

Both bridges save the written deliverable under the configured working directory's
`.agentrelay/artifacts/<uuid>/report.md`, attach that exact path as evidence and save
a receipt. Recommended ticket profile, configured worker model and provider
attestation are distinct: generic workers declare model/effort; AgentRelay cannot
prove which model a custom executable used. Reports still require independent review.

## Any agent, any provider

A trusted worker executable receives one UTF-8 JSON value on stdin:

```json
{"protocol":"agentrelay.worker.v1","context":{"ticket":{}},"worker":{"id":"worker","model":"configured-model","effort":"default"}}
```

`context` is the full existing ticket context endpoint, including parents,
dependencies, children, history and checkpoint. Stdout must contain exactly one
JSON result (up to 1 MiB). Diagnostic output belongs on stderr, also bounded.

```json
{"outcome":"submit","summary":"What changed and what was checked","evidence":[{"kind":"file","label":"Result","uri":"/absolute/result.md"}]}
```

Other outcomes: `help` requires `title`, `description`, optional `profile_id`;
`split` requires 1–16 `children` with normal ticket fields; `blocked` uses `summary`
as the reason. Unused `title`, `description`, `profile_id`, `children` may be omitted
or null. `summary` is required and capped at 4096 characters. The worker must not
mutate its own claimed ticket through MCP while this result protocol is active;
that changes its revision and deliberately causes a result conflict. Long-running
external agents that need live checkpoints can use MCP directly instead.

## Failure, cancellation and recovery

Timeouts, nonzero exits, malformed/oversized output and rejected results produce a
visible failed run and block the unchanged owned ticket. A concurrent edit causes
a conflict and is preserved. The manager terminates its owned process tree on
cancel/timeout; provider-side computation may take time to notice disconnection.
Cancellation does not undo files already changed. Inspect those files before
requeuing. A crash marks unfinished runs interrupted on the next enabled startup;
it never automatically retries or declares success.

Process logs are local diagnostics, not served to the browser. Keep the database,
logs, worker configs, receipts and provider authentication outside version control.

## Backup and restore

JSON export includes ticket/profile/audit/run history for inspection. For a complete
restorable database, use SQLite's online backup through AgentRelay:

```sh
agentrelay backup --db /absolute/workspace.sqlite --output /absolute/backups/workspace-2026-10-09.sqlite
```

The destination must be new. To restore, stop the old execution manager, inspect
any outstanding files/processes, and start the server with `--db` pointing to the
backup. The backup contains the demo marker and execution history, but not external
artifact files, worker config or credentials; preserve those separately. An active
run in a backup is treated as interrupted, never silently resumed.
