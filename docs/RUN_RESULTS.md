# Inspect a retained worker proposal

Worker protocol output can be retained with its execution run so a conflict can be reviewed without launching the worker again. Read one exact run from an existing AgentRelay database:

```sh
agentrelay run-result --db /absolute/project.sqlite --run RUN_ID
```

The command validates that `--db` already exists and is an AgentRelay database. A typo path, unrelated SQLite file, empty run ID or unknown run fails with a diagnostic; it does not create a project or backup. Recognized databases still pass through normal `Store` initialization and its idempotent schema migrations, so this is not a filesystem-level read-only session.

The result has this shape:

```json
{
  "schema_version": 1,
  "run": {
    "id": "run-id",
    "ticket_id": "AR-0001",
    "worker_id": "worker-id",
    "status": "conflict",
    "started_at": "...",
    "finished_at": "...",
    "summary": "...",
    "error": "...",
    "model": "...",
    "effort": "...",
    "claim_revision": 2,
    "actor": "agent:run-id"
  },
  "result": {
    "outcome": "submit",
    "summary": "...",
    "evidence": [{"kind": "file", "label": "Worker output", "uri": "local://result"}]
  },
  "current_ticket": {
    "id": "AR-0001",
    "revision": 3,
    "status": "in_progress",
    "assignee": "agent:other"
  }
}
```

`run` records the execution that produced the output, including its claim revision and actor; `current_ticket` is the current minimal ticket identity. Both are read in one SQLite transaction. `result` is the decoded worker protocol proposal retained for that run. It is not an applied update, verified evidence or an accepted deliverable. In particular, a `conflict` means the execution could not safely apply its proposal to the claimed revision.

After a conflict, fetch current ticket context and compare its revision, state, owner, acceptance and dependencies with the retained proposal. Decide whether any finding is still relevant and record a new authorized action with the current revision. Never replay the result automatically or overwrite newer work.

MCP clients can call the read-only tool `get_run_result(run_id)`. It returns the same document and follows the same review boundary.

Only results produced after proposal retention was added can have a stored object. Legacy runs return `result: null`; their old summary and error remain in `run`. A new run can return null while no valid proposal has been captured, including during execution or when cancellation, timeout, nonzero exit, malformed output or a crash happens first. A running run can already contain a proposal during the short interval between capture and application. Cancelled, failed, interrupted or conflicted runs can likewise retain one if capture succeeded before cancellation/crash or application failed afterward. Status never means that the proposal was accepted.

Existing local worker logs can still be inspected manually under their established permissions, but AgentRelay does not reconstruct old protocol output retroactively. Worker stdout remains capped at 1 MiB; normalized strict JSON has a separate 4 MiB ASCII storage cap.

SQLite backups include retained proposals because they copy the database. The existing bulk JSON export remains unchanged and does not add run proposals. This query does not construct an `ExecutionManager`, recover runs, read worker log files, launch a worker or mutate ticket state.
