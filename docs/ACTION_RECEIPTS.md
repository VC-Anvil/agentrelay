# Recovering ticket writes after an uncertain response

Since 0.19, `apply_ticket_action` records a ticket operation and its receipt in
one SQLite transaction. Generate and retain a request ID **before the first
send**. If the response is lost, explicitly repeat the same request in the same
project, with the same actor and data, to recover its original result without
another ticket, comment, checkpoint or acceptance event.

This is optional. Existing unwrapped actions keep their existing behavior;
repeating them can repeat their effects. Adding a `request_id` field to an old
action does **not** enable this guarantee. Use the new wrapper: old versions
reject its unknown action name before writing instead of silently ignoring a key.

## One operation, one retained request

For HTTP `POST /api/actions` or a CLI action input file:

```json
{
  "action": "apply_ticket_action",
  "data": {
    "request_id": "review-note-8ba2f753-93c2-4725-a410-423a70e59853",
    "action": "add_comment",
    "data": {
      "id": "AR-0042",
      "body": "The isolated reproduction confirms a duplicate after a lost response."
    }
  }
}
```

Select an already authorized project explicitly:

```sh
agentrelay action --db /absolute/project/.agentrelay/workspace.sqlite --actor agent:reviewer --input /absolute/comment.json
```

MCP exposes the same operation as
`apply_ticket_action(request_id, action, data)`, with a required key and a closed
action enumeration. Its actor is the configured connection identity. Its
`idempotentHint` annotation is true; ordinary unkeyed mutation tools remain
available without this guarantee. Domain action names differ from some dedicated
MCP names: use `checkpoint`, `transition`, `complete_ticket` and `request_changes`
inside the wrapper, rather than `save_checkpoint`, `transition_ticket`,
`review_ticket` or `request_ticket_changes`.

The CLI and MCP return a receipt:

```json
{
  "request_id": "review-note-8ba2f753-93c2-4725-a410-423a70e59853",
  "action": "add_comment",
  "actor": "agent:reviewer",
  "committed_at": "2026-10-10T12:00:00Z",
  "replayed": true,
  "result": {"id": "AR-0042", "revision": 3}
}
```

The example abbreviates `result`; the service stores the action's full original
result. The first commit returns `replayed: false`. Exact retries return that
same result and commit time with `replayed: true`, even after restart or later
ticket changes. HTTP returns `{result: RECEIPT, state: CURRENT_SNAPSHOT}`. Its
`state` is a fresh observation made after retrieving the receipt, and may be
newer than the historical ticket inside `result.result`.

Always fetch current ticket context before deciding any new work. A historical
claim is not a current assignment; a historical acceptance does not close a
subsequently reopened ticket. A replay never runs the action again.

## Identity, conflicts and bounds

The wrapper contains exactly `request_id`, `action` and `data`. The key must be
a nonempty string of at most 128 characters without surrounding whitespace.
`data` must be a JSON object and cannot contain reserved `actor` or `request_id`
fields. The actor comes from the normal transport contract, not from nested data.

The stored intent includes the action and complete data object. Object key order
does not matter; array order, string contents and omitted versus explicitly
supplied defaults do. Both canonical JSON and its SHA-256 are compared, alongside
the normalized actor. Reusing a committed key with different intent or actor is
409, with no action applied. Different keys represent different operations and
can deliberately produce identical comments or tickets.

Keys share one namespace per project database with `create_plan`,
`claim_next_ticket` and persisted source checks. Never reuse a key for another
kind of operation. Upgrade every writer before relying on these cross-operation
guards; an older process does not know the new receipt table. Different project
databases remain independent.

Canonical intent is limited to 1 MiB UTF-8 and the saved action result to 4 MiB,
in addition to transport limits. Exceeding these byte limits returns 413.
Invalid JSON, nonfinite numbers, invalid Unicode
and container nesting deeper than 64 levels within `data` are rejected. The
`data` object itself counts as level one. If the result cannot be serialized or exceeds
its limit, the entire action rolls back, including its events and receipt. Large
existing ticket evidence can therefore cause a small new request to be rejected.
No payload or result is silently truncated.
Direct Python callers also have a traversal budget of 1,048,576 JSON values to
stop exponential expansion of shared containers before serialization; ordinary
JSON inputs within the byte limit cannot exceed that value count.

Receipts do not expire. Online SQLite backup includes them; project JSON export
does not. Receipt bodies are not added to bulk state or ticket context. Durable
recovery costs database space, and restoring an older backup loses receipts and
effects created after that backup. No guarantee spans replacement or rollback of
the database file.

## Scope and safe recovery

Eligible actions are `create_ticket`, `update_ticket`, `transition`,
`claim_ticket`, `checkpoint`, `submit_ticket`, `complete_ticket`,
`request_changes`, `request_help`, `split_ticket` and `add_comment`.
They use the existing lifecycle and ownership rules. A wrapped `claim_ticket`
also requires nonempty `actual_model` and `actual_effort` declarations. Use
`unknown` explicitly when host metadata is unavailable for a non-Astra profile;
the Astra profile requires its actual locked model and effort. Recommendations
are not evidence that a model ran. A new keyed operation still
needs its expected revision and, for acceptance, the token of the context actually
reviewed. Exact replay is checked before those current-state conditions because
it retrieves a past result, not a new decision. Changing a review token or revision
is different intent and cannot be smuggled into an existing receipt.

Plans, scoped claims and source checks retain their own receipt contracts.
Profile changes, seeding and worker launch/cancellation are excluded. A database
receipt cannot make an external process or filesystem comparison atomic.

After a 500, connection failure or malformed response, the outcome may be
committed. Preserve the exact original request and choose an explicit retry with
its original key. There is no automatic repost or worker execution. A 4xx rejects
that attempt; it does not erase any earlier receipt under the key. After a 409,
inspect the conflict and current context rather than generating a new key merely
to force the old intention through. Corrected or newly decided work uses a new
key after reconciliation. Neither a key nor a receipt grants permission to act.

The CLI can initialize a new authorized database for a structurally validated
wrapper whose inner action is `create_ticket`. Other wrapped actions require an
existing database. Validation of the full ticket still occurs in the domain;
bootstrap is not a promise that every rejected ticket leaves no database file.
See [database selection](DATABASES.md).

Run [the isolated recovery example](../examples/action_receipt_demo.py) from an
installed checkout with a new output directory. It demonstrates a committed write
whose response is deliberately discarded, historical replay, current context,
conflicting key reuse and a receipt preserved by SQLite backup. It makes no model
calls and does not connect to a live project.

The intervening title edit deliberately uses an ordinary unkeyed action to show
that later writes can make a receipt historical. It does not demonstrate durable
recovery for that edit.

```sh
python examples/action_receipt_demo.py --output .agentrelay/receipt-example
```

[Validation coverage and observed limits](VALIDATION_ACTION_RECEIPTS.md).
