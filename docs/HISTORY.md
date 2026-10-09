# Current context and recoverable history

Ticket state and audit history serve different purposes. Context gives the current
revision, acceptance, checkpoint, evidence and relations. Audit events explain how
the ticket reached that state; their embedded ticket fields may be obsolete.

Starting in 0.6, MCP `get_ticket_context`, CLI `context` and configured worker packets
include the newest 20 audit events by default. The ticket remains complete. The
`events_page` object gives `total`, `count`, `limit` and `next_before_id`.
A non-null next cursor means older events exist, not that they were discarded.

## MCP

Call `get_ticket_context(ticket_id, event_limit=20)`. When older history matters,
pass its `events_page.next_before_id` to
`list_ticket_events(ticket_id, limit=20, before_id=CURSOR)`.
That tool returns `{ticket_id,events,total,count,limit,before_id,next_before_id}`.
Continue using the returned cursor until the needed evidence is found or it is null.
There is no need to read every page before ordinary work.

## CLI

```sh
agentrelay context --db /absolute/project.sqlite --ticket AR-0001
agentrelay context --db /absolute/project.sqlite --ticket AR-0001 --event-limit 5
agentrelay history --db /absolute/project.sqlite --ticket AR-0001 --limit 20 --before-id 123
agentrelay context --db /absolute/project.sqlite --ticket AR-0001 --all-events
```

Use the actual cursor returned by the previous response; 123 is only an example.
`--all-events` and `--event-limit` are mutually exclusive. Invalid limits/cursors
and unknown tickets fail with a diagnostic rather than silently changing scope.

## Consistency and compatibility

Pages are ordered by descending global event ID and always filtered to one ticket.
The cursor is exclusive: the next page selects IDs smaller than it. Newer events
arriving between reads do not shift those older pages. Each response has its own
SQLite read transaction; multiple calls do not share a frozen database snapshot.
`total` is the current total for that ticket, including events newer than a supplied
cursor; `count` is only the number returned in this page.

Limits are strict integers from 1 to 100. A cursor is null or a positive SQLite
integer ID, up to 2**63-1. Pagination limits event count, not event size or model
tokens. Current relations and evidence are not summarized by this feature.

`Store.context(ticket_id)` and the browser's HTTP context preserve their previous
complete history. Python callers opt in with `event_limit`. `Store.ticket_events`
provides the same cursor API. Full export and SQLite backup retain every event.
Clients upgrading MCP/CLI/worker integrations must handle the new default and
must not interpret an omitted event as nonexistent.

Worker instructions explain the history boundary. A worker may retrieve older
history through an already-authorized read-only connection, or request missing
context; this feature does not grant filesystem access or permission to launch
another process. Read-only history calls do not change ticket revisions. Use a
current revision for subsequent mutations and reconcile conflicts normally.
