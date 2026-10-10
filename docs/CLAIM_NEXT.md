# Claim one ticket from an authorized candidate set

`claim_next_ticket` atomically reserves at most one ticket from a bounded list that the caller has already reviewed and is authorized to take. It reduces the race between listing ready work and claiming it; it does not authorize broad queue consumption.

MCP call:

```json
{
  "request_id": "claim-session-2026-10-10-01",
  "candidates": [
    {"ticket_id": "AR-0042", "expected_revision": 3},
    {"ticket_id": "AR-0048", "expected_revision": 1}
  ],
  "actual_model": "unknown",
  "actual_effort": "unknown"
}
```

The MCP connection binds `assignee` to its configured actor. Read current context for every candidate before the call and authorize all of them for this work session. Candidate entries contain exactly `ticket_id` and `expected_revision`; 1 through 64 distinct tickets are allowed. IDs, request ID and declared settings are exact nonblank strings of at most 128 characters without surrounding whitespace. Revisions are integers of at least 1, never booleans.

When the user has already chosen a specific ticket, preserve that decision and call ordinary `claim_ticket`. Do not turn one chosen task into an automatic selection set.

The existing CLI `action` envelope exposes the same backend operation without a new parser command. Save this exact UTF-8 JSON as `claim.json`:

```json
{
  "action": "claim_next_ticket",
  "data": {
    "request_id": "claim-session-2026-10-10-01",
    "candidates": [
      {"ticket_id": "AR-0042", "expected_revision": 3},
      {"ticket_id": "AR-0048", "expected_revision": 1}
    ],
    "assignee": "agent:worker-01",
    "actual_model": "unknown",
    "actual_effort": "unknown"
  }
}
```

Then run:

```sh
agentrelay action --db /absolute/project.sqlite \
  --actor agent:worker-01 --input claim.json
```

For non-human actors, actor and assignee must identify the same agent. Model and effort describe actual host metadata when known. `unknown` is an explicit declaration when a non-Astra host does not expose it; never copy profile recommendations as execution facts. An Astra candidate is eligible only with actual `gpt-6-astra` and `high`.

The backend validates the complete candidate scope in one write transaction. An unknown candidate fails with 404 and rolls back the whole request. Known candidates are considered only at the supplied revision. Ineligible candidates appear in `skipped` with one of:

- `stale_revision`: the ticket changed after its reviewed context.
- `not_ready`: it is no longer queued and dependency-ready.
- `missing_acceptance`: it has no acceptance criteria.
- `incompatible_profile`: an Astra candidate does not match the locked model and effort.

Among the remaining candidates, AgentRelay selects one by priority (`urgent`, `high`, `normal`, `low`), then creation time and ticket ID. It claims no ticket outside the supplied list and never preempts an owner. The response is:

```json
{
  "request_id": "claim-session-2026-10-10-01",
  "ticket": {"id": "AR-0042", "status": "in_progress"},
  "skipped": [
    {"ticket_id": "AR-0048", "reason": "stale_revision"}
  ]
}
```

`ticket` is the full claimed ticket or `null` when no candidate remains eligible. One request claims at most one ticket. It does not launch a worker, execute the task, verify evidence or accept delivery.

The request ID is a durable idempotency key shared with other receipt-bearing actions in the same database. Retrying with the exact same action, actor and payload returns the original response without another claim, including an original idle response. Reusing it for `create_plan`, or with another actor or any changed payload, returns 409; likewise, a plan request ID cannot later become a claim request. A replayed response is a historical receipt, not current ticket state: fetch fresh context for the returned ticket before starting work. Use a new request ID only for a newly reviewed selection attempt.
