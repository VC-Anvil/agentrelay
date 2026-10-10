# Action receipt lookup validation — 0.20

AgentRelay 0.19 can recover a committed ticket-action receipt by repeating the
original keyed operation. If the first request never committed, that repetition
can still apply it. Version 0.20 adds a separate observation: read the receipt
without dispatching any action. The [lookup contract](ACTION_RECEIPT_LOOKUP.md)
keeps historical results separate from current context and explains why 404 is
not evidence that an in-flight writer will never commit.

## Reproduce the checks

From an installed checkout with the optional MCP dependency:

```sh
python -m unittest tests.test_action_receipt_lookup tests.test_action_receipt_lookup_protocols -v
python examples/action_receipt_lookup_demo.py --output .agentrelay/new-lookup-example
python -m unittest discover -s tests -v
```

The full local suite ran 295 tests in 90.932 seconds: 288 passed and seven
Windows symbolic-link checks were skipped because of local permissions.

The focused domain run passed six tests. Coverage includes exact historical
results after edits and reopening, SQLite backup, actor-scoped absence, keys used
by other receipt types, invalid selectors before opening the database, corrupt
stored data and a missing receipt table. The operation's read transaction does
not recreate that table; ordinary Store construction still applies migrations.

The concurrency test runs a real `apply_ticket_action(create_ticket)` on a second
Store connection. A gate pauses it after inserting the ticket, event and receipt
but before commit. The reader sees 404 and the previous counts. After commit it
sees the complete receipt and one new ticket/event; the rollback variant leaves
neither effect nor receipt. This replaces an initial narrower fixture that only
inserted a receipt row directly.

The focused protocol run passed three tests using subprocess CLI commands, an
isolated HTTP server and real MCP SDK stdio clients. They exercise Unicode and
slash-containing keys, the 128-character boundary, explicit database/workspace
selection, actor binding, read-only tool discovery, strict query parsing and
controlled corruption errors. An HTTP response-construction failure is injected
after a comment commits, then GET retrieves its receipt without another write.

The first protocol run incorrectly compared two full JSON exports, including
their intentionally fresh export timestamps. The corrected fixture compares
stable domain state and every action-receipt row. It preserves the requirement
that the lookup must not change persistent data; it does not freeze timestamps
or alter the product to satisfy the test.

## Executed example and real project use

The example uses an actual isolated loopback HTTP server with an explicitly
injected snapshot error after commit. Its POST returns 500, GET returns 200, and
the server records exactly **one POST**. The result remains at revision 1 after
an independent edit moves the ticket to revision 2. Another actor gets 404, and
an SQLite backup preserves the receipt. Its output directory must be new.
The example does not simulate a network disconnection or a provider failure.

The integrator also used CLI and MCP to retrieve a real 0.19 development comment
receipt from AgentRelay's own database. Both returned identical historical data,
and before/after comparisons of all eleven existing tables were identical. No
action was resent. The receipt records the ticket's then-`in_progress` state;
a separate current-context read found the already reviewed ticket `done` at
revision 4. This distinction is expected, not a stale-read defect.

The isolated installed-wheel check reruns the HTTP example against the installed
package and compares package, source and archived documentation/test/example
bytes. The companion skill passes its structural validator. Neither packaging
nor that validator alone proves that an agent will follow the recovery policy.

## Review and limits

Independent domain and protocol reviews found no open defect in this scope.
Functional results above belong to the integrator's normal runtime. Specialist
SQLite/TEMP restrictions prevented their own fixture execution; those setup
failures are not counted as passes.

The lookup is not an action replay and has no `replayed` field. It does not return
current ticket context, authenticate a local actor, expose another actor's receipt,
retrieve other receipt types or make external processes atomic. A 404 may precede
a later commit and never triggers an automatic retry or acceptance. A malformed
stored receipt produces a controlled error rather than partial historical data.

No new browser QA, pilot-server restart, game source edit or model inference is
claimed. The new endpoint/tool must exist on the selected server; an older
version's unknown-route response cannot establish the absence of a receipt.
