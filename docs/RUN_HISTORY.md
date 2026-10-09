# Discover execution runs

List bounded execution summaries from an existing AgentRelay database before choosing a retained proposal:

```sh
agentrelay runs --db /absolute/project.sqlite
agentrelay runs --db /absolute/project.sqlite --ticket AR-0002 --status conflict --limit 20
agentrelay runs --db /absolute/project.sqlite --ticket AR-0002 --limit 20 --before-id RUN_ID
```

`--ticket`, `--status` and `--before-id` are optional. `--limit` defaults to 20 and accepts 1 through 100. Ticket and run IDs are exact and reject surrounding whitespace. Status must be one of `running`, `submitted`, `help_requested`, `split`, `blocked`, `failed`, `cancelled`, `interrupted` or `conflict`. An unknown ticket or cursor fails instead of returning an ambiguous empty result. When a ticket filter is present, its cursor must belong to that ticket.

The response has this shape:

```json
{
  "runs": [
    {
      "id": "run-id",
      "ticket_id": "AR-0002",
      "worker_id": "worker-id",
      "status": "conflict",
      "started_at": "...",
      "finished_at": "...",
      "summary": "",
      "error": "Revision conflict",
      "model": "declared-model",
      "effort": "high",
      "has_result": true
    }
  ],
  "ticket_id": "AR-0002",
  "status": "conflict",
  "total": 2,
  "count": 1,
  "limit": 1,
  "before_id": null,
  "next_before_id": "run-id"
}
```

Runs are ordered by `started_at` descending and then ID descending. `total` counts all runs matching the ticket and status filters without applying the cursor; `count` describes this page. If `next_before_id` is non-null, pass it unchanged as `--before-id` to request the next older page. A cursor remains valid if that run later changes status, although status changes can add or remove entries from a filtered result.

Pagination is not a global snapshot across calls. Keyset pagination does not repeat rows already returned while their ordering fields remain unchanged, but an insertion whose `(started_at, id)` pair sorts after the anchor can appear on a later page. Clock movement or equal timestamps mean a newly inserted run is not guaranteed to sort before the cursor. Concurrent status changes can also change membership and totals between pages. Do not interpret a page as a complete execution audit unless pagination reaches a null cursor under stable data.

Each entry is a public run summary. `has_result` reports only whether this run has a retained protocol proposal; it does not expose the proposal and does not mean that output was applied, verified or accepted. Call `get_run_result(run_id)` through MCP, or `agentrelay run-result --db DATABASE --run RUN_ID`, only for a relevant selected run. Compare that proposal with fresh ticket context and never replay it automatically.

MCP clients use the read-only `list_runs(ticket_id=None, status=None, limit=20, before_id=None)` tool. It returns the same document. Listing or reading a proposal does not create an `ExecutionManager`, launch a worker, inspect worker logs or mutate ticket state.

Legacy databases without execution history return an empty list. Legacy run tables without retained proposal storage report `has_result: false`. The command uses the same existing-database validation as the other query commands: missing paths and unrelated SQLite files are rejected before `Store` initialization. Recognized databases still receive normal idempotent `Store` migrations, so this is not a filesystem-level immutable read.
