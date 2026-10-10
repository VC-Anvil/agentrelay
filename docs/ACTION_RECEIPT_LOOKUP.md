# Read a committed action receipt without resending the write

Since 0.20, `get_action_receipt` retrieves the historical result of one
`apply_ticket_action` operation. It never applies an action, creates a receipt
or records a new event. Use it after an uncertain response when you want to
observe whether the original write is visible without sending the write again.

Keep the original request ID, actor, project and payload from **before** the first
send. Looking up matching ticket text cannot identify the original operation.
This lookup only covers ticket-action receipts introduced in 0.19. Plans, scoped
claims and source checks retain their separate receipt contracts.

## CLI, MCP and HTTP

The CLI requires all three selectors and an existing recognized database:

```sh
agentrelay action-receipt --db /absolute/project/.agentrelay/workspace.sqlite --actor agent:reviewer --request-id review-note-8ba2f753-93c2-4725-a410-423a70e59853
```

A successful lookup exits 0 and writes JSON. Invalid input or database selection,
an unavailable receipt or a corrupt stored result exits 1 with a concise error.
A missing database path does not create a directory or initialize a project.
The actor is a local declaration, not an authenticated credential.

MCP exposes `get_action_receipt(request_id)` with `readOnlyHint: true`. The
connection fixes the actor and project; the model cannot supply an actor override
or database path. Look for this tool in discovery before using it. A server that
does not advertise it has not established that a particular receipt is absent.

HTTP uses a query parameter so slashes, plus signs and Unicode can belong to a key:

```text
GET /api/action-receipts?request_id=review%2FAR-0042%2F%C3%A1%2Bone
X-AgentRelay-Workspace: project-id
```

The workspace header is required for this endpoint even with a single project.
Use `GET /api/workspaces` to discover the configured ID. Supply exactly one
`request_id` query field; duplicates, extra fields, malformed percent encoding
and invalid UTF-8 are rejected. HTTP uses the `human` actor, like its action
endpoint, and cannot retrieve an agent connection's receipt by overriding the
actor. Agents should use MCP or the explicitly selected CLI. Responses use
`Cache-Control: no-store` and include the selected public workspace metadata.

All three surfaces share this domain response:

```json
{
  "schema_version": 1,
  "receipt": {
    "request_id": "review-note-8ba2f753-93c2-4725-a410-423a70e59853",
    "action": "add_comment",
    "actor": "agent:reviewer",
    "committed_at": "2026-10-10T12:00:00Z",
    "result": {"id": "AR-0042", "revision": 3}
  }
}
```

The example abbreviates the original action result. The full stored result is
returned. There is no `replayed` flag: a read is not a repeated action request.
There is also no current ticket or state snapshot. Read ticket context separately
before deciding any new work. Finding an old acceptance does not accept a ticket
that was later reopened, and an old claim does not establish current ownership.

## What absence means

A missing key, a key belonging to another actor and a key used only by another
receipt type return the same 404. The lookup does not disclose that other record.
Different project databases remain independent even when their keys match.

**A 404 only says that this read did not find a visible matching receipt.** The
original writer may still be running and commit immediately afterward. A wrong
actor or project, an old writer without receipts, or restoration of an earlier
backup can also explain absence. Confirm the server version through
`/api/health` before interpreting a response from a newly introduced endpoint;
an old server's unknown-route 404 is not a receipt lookup.

Keep the original request and resolve any in-flight operation. A later explicit
lookup can observe a committed receipt; it does not poll or retry automatically.
If you decide to resend the original operation within its existing authorization,
use its exact original key, actor and payload. Never switch to an unkeyed write
or invent a new key merely because a lookup returned 404. The
[write receipt contract](ACTION_RECEIPTS.md) explains explicit replay and conflicts.

## Bounds and trust

Keys follow the write contract: valid UTF-8 strings of 1–128 characters without
surrounding whitespace. Valid slashes and Unicode are preserved. Some control
characters cannot travel through shell arguments; the lookup does not retroactively
change stored keys or promise every key is portable across every transport.

Stored result size is checked against the 4 MiB limit before loading the body.
Invalid or excessively deep JSON, nonfinite values, invalid Unicode and malformed
receipt metadata produce a controlled server error without returning a partial
receipt. The lookup does not expose the stored intent body or treat a hash as
proof of authorship, evidence quality or current state.

The read uses one SQLite snapshot and never dispatches an action. Opening a
recognized project still follows normal Store initialization and idempotent
migrations; “read-only” describes domain effects, not byte-for-byte filesystem
immutability or a SQLite `mode=ro` promise. This follows the existing
[database selection contract](DATABASES.md).

Online SQLite backup preserves committed receipts. Restoring an older backup
does not recover later commits. Actor binding prevents accidental cross-connection
disclosure; it is not a security boundary against a local operator who can declare
another identity or directly access the database.

## Run an actual HTTP recovery example

From an installed checkout, choose a new output directory:

```sh
python examples/action_receipt_lookup_demo.py --output .agentrelay/lookup-example
```

The example runs an isolated loopback server and deliberately fails response
construction after a ticket write commits. It retrieves the receipt by GET and
confirms that the server received exactly one POST. It also demonstrates later
ticket changes, actor-scoped absence and recovery from SQLite backup. Its data
is fictional; it does not connect to a live project, call a model or launch a worker.

[Validation coverage, real project use and limits](VALIDATION_ACTION_RECEIPT_LOOKUP.md).
