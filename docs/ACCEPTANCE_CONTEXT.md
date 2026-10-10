# Accept the context you reviewed

Since 0.18, completion requires a context token as well as the ticket revision.
This is an intentional contract change for Store, HTTP, MCP and generic CLI
clients. Existing completed tickets and audit history are not rewritten.

## Why a ticket revision is insufficient

A reviewer reads a parent at revision 3 with no children. Another actor then adds
and completes a child. The parent's own row has not changed: revision 3 still
matches, and its current blockers are empty. Before 0.18, acceptance could succeed
against the reviewer's earlier view of the parent.

The additional token compares the immediate acceptance context read earlier
with the covered material currently present when accepting. A reviewer must inspect the changed context and make a new
decision after a conflict. The server does not silently refresh the token or
approve anything automatically.

## Read, inspect, then accept

`Store.context`, HTTP `GET /api/tickets/{id}/context`, CLI `context` and MCP
`get_ticket_context` return this additional object for a ticket in `review`:

```json
{
  "acceptance_context": {
    "schema_version": 1,
    "token": "sha256:<64 lowercase hexadecimal characters>",
    "children_count": 2,
    "dependencies_count": 1,
    "source_checks_count": 4
  }
}
```

Outside `review`, `acceptance_context` is `null`. The token is calculated in the
same read transaction as the returned context. Retain that token while inspecting
the ticket, relationships and evidence; do not replace it immediately before
submitting merely to avoid a conflict.

For the generic `complete_ticket` action, include:

```json
{
  "action": "complete_ticket",
  "data": {
    "id": "AR-0001",
    "expected_revision": 3,
    "expected_acceptance_context_token": "<token from the inspected context>",
    "verification": "What the independent reviewer actually checked",
    "accepted_criteria": ["Every exact acceptance criterion"]
  }
}
```

The placeholders above must be replaced with actual returned values. MCP
`review_ticket` uses `ticket_id` instead of `id` and requires the same
`expected_acceptance_context_token`. CLI accepts the ordinary JSON action file;
there is no new command or provider call.

A missing or malformed token gives 400 at the domain/HTTP boundary; MCP can reject
a missing required argument at its schema boundary first. A well-formed token whose covered context
changed gives 409: `acceptance context changed; reread ticket context before
completing`. No ticket, relationship, revision or audit event is changed by the
rejected action. The usual ticket revision, review state, distinct reviewer,
criteria and current blocker checks still apply. The token is an additional
precondition, not a replacement for any of them.

## Exactly what is covered

The versioned hash includes ordered, length-delimited records:

| Included | Fields |
| --- | --- |
| Addressed ticket | ID, revision, status |
| Immediate children, ordered by ID | ID, revision, status, parent ID |
| Immediate dependencies, ordered by ID | ID, revision, status |
| Direct ticket source checks | Total count and latest three receipts' check ID, snapshot ID, report SHA-256 and observed ticket revision |

Normal Store writes to descriptions, criteria, evidence, checkpoints and other
ticket fields increment their ticket revision. A covered child's or dependency's
revision therefore detects those changes without copying all of its text into
the hash. New source checks are covered separately because recording them does
not increment the ticket revision. Replaying the same source-check request
without inserting a receipt does not change the token.

Comments, event pagination, profiles, worker runs, the ticket's parent, grandchildren,
dependencies of dependencies and external evidence files are excluded. Comments
alone do not invalidate a prepared review. Material corrections should use the
explicit correction workflow or change the ticket's recorded scope/evidence.

This is not a recursive graph guarantee. Reopening a grandchild does not change
the token unless a covered immediate ticket also changes. An accepted immediate
child remains a historical acceptance; no ancestor is reopened automatically.
The token does not verify that files referenced in evidence still exist or retain
their content. Explicit source checks remain historical observations too.

It compares the covered material currently present, not every event between
reads. For example, adding a new child, cancelling it and detaching it can restore
the original child list and token if no covered ticket revision changed. That
equality does not assert that nothing happened in the interim; the audit retains
those separate actions.

## Transactions and retained evidence

Completion recomputes the token within its `BEGIN IMMEDIATE` write transaction.
A concurrent covered change either commits before that check and causes conflict,
or follows the completed transaction. The earlier ticket revision CAS still
ensures that two completion attempts cannot both succeed.

The completion event records `acceptance_context_schema_version` and the validated
`expected_acceptance_context_token` alongside the reviewer, verification and
accepted criteria. SQLite backup preserves both the source rows and audit event;
an unchanged copy produces the same token. This event is a comparison receipt,
not a stored reconstruction of the entire historical context.

No table migration, execution, polling or new state propagation is involved. Hash
output and metadata have fixed size. Hashing streams immediate relation rows,
with work proportional to their count and constant additional relation memory;
the existing context response still enumerates those relationships. No constant
SQL execution time or bound on the existing full context response is claimed.

## Client migration and UI

Old completion requests without the new field are rejected. Upgrade included
clients and update external integrations to fetch and inspect `acceptance_context`
before accepting. There is no optional-token fallback that bypasses this check.
Tickets already in `review` need a new context read, not a migration. Workers
still submit for review and cannot accept their own work; the worker protocol is
unchanged.

The web review form retains the token for the context presented with that form.
On conflict, it preserves the verification draft, displays refreshed context and
requires another explicit confirmation. It must never resubmit automatically or
replace a token just before submitting an unchanged decision. A server and web
client must run matching versions; an old server lacking tokens cannot support
this completion flow.

SHA-256 here is a change fingerprint, not a signature or identity check. A process
able to edit SQLite directly can bypass application rules. Token possession does
not establish that anyone read, understood or correctly assessed the evidence.
