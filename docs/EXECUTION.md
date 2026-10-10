# Explicit worker execution

AgentRelay can launch trusted local worker processes. The normal board and MCP
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

For a provider-neutral walkthrough of the complete handoff, help, correction,
review and backup lifecycle, run the deterministic local
[handoff example](HANDOFF_EXAMPLE.md). Its fixture workers make no model, provider
or network call.

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

CLI `run` requires an existing recognized AgentRelay database and does not initialize a missing path. See [database selection](DATABASES.md).

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
`.agentrelay/artifacts/<uuid>/report.md` by default. Append `--artifacts-dir` and an
absolute output base to the adapter's trusted command to keep outputs outside a
read-only project. Each run gets a fresh UUID subdirectory; relative bases resolve
from the worker cwd. The bridge attaches the report's exact path as evidence and
saves a receipt including cwd, output directory and the saved report hash. New
deliveries always attach this receipt, including when no input snapshot was used.
Use the explicit local [report integrity check](REPORT_INTEGRITY.md) to compare
the two fixed artifact files; old receipts without a report hash remain uncheckable.
Recommended ticket profile, configured worker model and provider
attestation are distinct: generic workers declare model/effort; AgentRelay cannot
prove which model a custom executable used. Reports still require independent review.

## Any agent, any provider

A trusted worker executable receives one UTF-8 JSON value on stdin:

```json
{"protocol":"agentrelay.worker.v1","context":{"ticket":{}},"worker":{"id":"worker","model":"configured-model","effort":"default"}}
```

`context` includes the complete current ticket, parent, dependencies, children,
checkpoint, target `profile` (or null) and `profiles` catalog for help routing.
Starting in 0.6, `events` contains the newest 20 audit events and `events_page`
reports the total and next cursor for older history. Retrieve older events through
an already-authorized read-only connection only when needed, or request missing
context. No events are removed from the database. See [history semantics](HISTORY.md).
Profile settings are recommendations, not proof of model availability. Stdout must contain exactly one
JSON result (up to 1 MiB). Diagnostic output belongs on stderr, also bounded.
Normalized proposals may contain at most 64 nested object/array containers,
counting the root object as one. Excessive depth is rejected before capture or
ticket application so retained output remains readable across supported runtimes.

```json
{"outcome":"submit","summary":"What changed and what was checked","evidence":[{"kind":"file","label":"Result","uri":"/absolute/result.md"}]}
```

Other outcomes: `help` requires `title`, `description`, optional `profile_id`;
`split` requires 1–16 `children`, each containing `title` and only the optional
fields `description`, `profile_id` and `acceptance`; `blocked` uses `summary` as
the reason. Split children inherit the parent's priority. Unused `title`,
`description`, `profile_id`, `children` may be omitted or null. `summary` is
required and capped at 4096 characters. The worker must not
mutate its own claimed ticket through MCP while this result protocol is active;
that changes its revision and deliberately causes a result conflict. Long-running
external agents that need live checkpoints can use MCP directly instead.

A worker can also retain an exact bounded `artifact_markdown` report in its run
proposal. This supports review through `get_run_result` without opening a local
artifact URI; it remains untrusted proposal text and requires independent review.
See [inline reports](INLINE_REPORTS.md) for limits and legacy behavior.

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

New runs retain their parsed protocol proposal in SQLite before attempting ticket
application. Use the explicit CLI `run-result --db DATABASE --run RUN_ID` or MCP
`get_run_result` to compare a conflicted proposal with current ticket context.
Discover that ID through `runs --db DATABASE --ticket TICKET_ID --status conflict`
or MCP `list_runs(ticket_id, status="conflict")`; the bounded summaries include
`has_result` so the caller can select a proposal without fetching every body.
This does not reapply output or accept evidence. Older runs can have no retained
proposal even when local diagnostic logs contain output. See [run results](RUN_RESULTS.md)
for the response contract and cancellation/crash limits.

## Backup and restore

External agents using MCP can reserve one of several explicitly reviewed tickets
with `claim_next_ticket`; [scoped claim receipts](CLAIM_NEXT.md) prevent a repeated
request from reserving additional work. This does not start an execution manager
or replace the configured worker's existing queue. SQLite backup preserves these
receipts alongside plan receipts; the bulk JSON export is not a complete restore.

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

SQLite backup also preserves retained worker proposals. Bulk JSON exports and
run summaries omit proposal bodies; use the explicit single-run query to inspect one.
