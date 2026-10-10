# Returning a delivery for corrections

An independent reviewer can return a ticket in `review` to its queue when the
delivery needs explicit corrections. This is a review decision: it does not
accept the work, execute a worker, claim the ticket, or reopen completed work.

## MCP

Read current context first, verify the delivery independently, and call:

```json
{
  "name": "request_ticket_changes",
  "arguments": {
    "ticket_id": "AR-0042",
    "expected_revision": 7,
    "reason": "Correct the factual claim and distinguish host evidence from independent verification."
  }
}
```

The MCP server binds the reviewer to the actor fixed when that server session
started. Callers cannot supply another assignee or reviewer identity. The
revision is a strict positive integer; booleans and strings are rejected. The
service accepts a nonblank reason of at most 4,000 characters.

The ticket must currently be in `review`, the revision must match, and the
reviewer must be independent from the submitting owner. A reviewer cannot use
this action as a generic ownership bypass. Backlog, queued, in-progress,
blocked, done and cancelled tickets are rejected; completed work is never
reopened implicitly.

On success, the ticket becomes `queued`, its assignee is cleared and its
revision advances once. Its description, priority, profile, acceptance,
checkpoint, evidence, dependencies, children and declared model/effort remain
intact. Dependencies still determine `ready`, so queued does not necessarily
mean ready or authorized to start. Another agent must read current context and
claim through the ordinary workflow before doing any work.

There is no idempotency request ID. After an uncertain response, read current
context. Retrying the old exact revision after a successful return produces a
revision conflict and does not append duplicate feedback.

## Generic CLI action

The existing local action envelope exposes the same decision without adding a
filesystem surface to MCP. Save exactly this shape as `request-changes.json`:

```json
{
  "action": "request_changes",
  "data": {
    "id": "AR-0042",
    "expected_revision": 7,
    "reason": "Correct the factual claim and identify the source of each assertion."
  }
}
```

Then run it against an explicitly selected AgentRelay database:

```console
agentrelay action --db .agentrelay/workspace.sqlite --actor agent:independent-reviewer --input request-changes.json
```

The CLI uses the same Store transaction and identity rules. A successful JSON
response is the current queued ticket; it is not an execution receipt.

## Historical review feedback

`get_ticket_context` returns `review_feedback: null` when no return has been
recorded. Otherwise it projects the newest `request_changes` event independently
of the bounded recent-events page:

```json
{
  "event_id": 91,
  "reviewer": "agent:independent-reviewer",
  "reason": "Correct the factual claim.",
  "previous_assignee": "agent:author",
  "submitted_revision": 7,
  "returned_revision": 8,
  "created_at": "2026-10-10T12:00:00.000Z",
  "submission_after_request": false,
  "completion_after_request": false
}
```

The full sequence remains in ticket history. A newer change request replaces
only this latest projection, not older audit events or original report files.
`submission_after_request` means a later `submit_ticket` event exists;
`completion_after_request` means a later `complete_ticket` event exists. Neither
boolean certifies that the requested correction was addressed, that evidence is
valid, or that acceptance was justified. Review the delivery and its evidence.

Event context can be bounded, while `review_feedback` remains directly
discoverable. A later worker should read that feedback before resuming. Artifact
URIs and evidence remain historical references and are not rewritten or
verified by this action.

## Limits

This interface does not control a browser, launch providers or workers, inspect
artifact contents, or approve product quality. Actor strings are local audit
identities rather than authentication. Store serialization and revision checks
protect ordinary competing writes; they do not defend against a hostile process
replacing the database concurrently.
