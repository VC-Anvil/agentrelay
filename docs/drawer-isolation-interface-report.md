# Drawer mutation isolation interface report

## Result

Ticket-drawer mutations now capture the originating workspace, ticket ID and
drawer generation before starting their API request. A response may update the
board from confirmed server state, but drawer-specific effects only run while
that exact drawer instance remains current.

The scope is applied to:

- the definition form's `update_ticket` save handler;
- every action routed through `submitActionForm`, including claim, checkpoint,
  submit, comment, child creation, help, split, transition and completion; and
- the queued-ticket execution form's `start_run` action.

For a current originating drawer, behavior is unchanged: successful mutations
load fresh context and clear the dirty state. Generic revision/conflict handling
still refreshes board state without overwriting an edited form. Completion keeps
its stricter acceptance-context handling, draft preservation and explicit
reconfirmation.

If the user opens another ticket, closes the drawer, or closes and reopens the
same ticket while a request is pending, the response cannot force a context GET,
show a drawer-specific toast, clear dirty state, reset the acceptance draft or
alter controls in the newer drawer. A confirmed successful response still
updates `app.state` and rerenders board-level views.

The mutation helper also rechecks drawer identity before its post-error state
reload and carries that scope through the pending state request. This prevents
a revision conflict from ticket A from initiating or finishing a state refresh
whose follow-up context load belongs to an unrelated current drawer.

## Regression coverage

The Node harness loads the real `agentrelay/static/app.js` and replaces only its
final bootstrap. Twenty-one checks pass. The new 0.18.1 cases exercise:

- the real definition Save listener: successful `update_ticket` for A preserves
  the same edited title control in B while the board adopts A's confirmed state;
- a current `checkpoint` success still requests and renders fresh context for
  its original A drawer, then clears dirty state;
- a pending `submit_ticket` from an older A drawer cannot replace controls in a
  closed and reopened A drawer;
- a revision conflict from A's comment keeps B's exact edited comment control,
  performs no forced context request and does not change unconfirmed board
  state; and
- a conflict state reload started for A may update the board, but cannot follow
  B with a context request if B opens while that state request is pending. The
  fixture returns B at revision 2 while the rendered context remains at revision
  1, so the context-refresh condition is necessarily exercised; and
- the real execution form's `start_run` success updates board/run state without
  replacing B's edited verification control.

The suite retains the earlier completion success/409, workspace, same-ticket
reopen, acceptance retry, stale context and source-check rendering cases.

Commands executed:

```text
node --check agentrelay/static/app.js
node --check tests/test_ui_races.js
node tests/test_ui_races.js
.runtime\Scripts\python.exe -m unittest tests.test_ui_races -v
```

The Node harness reported `21 pruebas de carreras UI superadas`; the Python
wrapper reported one passing test.

As a negative control, the same harness was pointed at a private copy of
`app.js` with only the post-state drawer guard removed. The new case failed with
four requests instead of three because the stale A reload requested B's
context. The production source was not changed for that experiment.

## Files

- `agentrelay/static/app.js`
- `tests/test_ui_races.js`
- `tests/test_ui_races.py`
- `docs/drawer-isolation-interface-report.md`

## Limits

Global ticket/profile dialogs and execution-list cancellation are not ticket
drawer operations and remain outside this change. No backend, API contract, CSS
or persistence behavior changed. No browser or visual QA was performed; the
tests use controlled DOM and fetch adapters around the real application code.
