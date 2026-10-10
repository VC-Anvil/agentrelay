# Pending drawer mutation guard

## Result

Drawer-originated writes now capture and validate their form values before a
generation-scoped guard disables the visible drawer controls. The guard covers
the action POST and the context GET that follows a confirmed response. It is
used by definition saves, every lifecycle action routed through
`submitActionForm`, and `start_run`.

The guard records each control's prior `disabled` and `readOnly` values rather
than enabling controls indiscriminately. `aria-busy` is present only while a
POST or context GET is actually pending. Opening another ticket, closing the
drawer, or closing and reopening the same ticket invalidates the old guard and
clears its busy marker; the late operation may still update confirmed board
state, but cannot alter the newer form.

## Outcomes and recovery

- A confirmed POST followed by a successful context GET renders the confirmed
  context and its normal restrictions.
- A known HTTP rejection restores the exact submitted form, its values and its
  previous disabled states. The form remains dirty. Conflict state refreshes
  may update the board but do not replace the rejected form.
- The special completion 409 flow remains locked while it reads fresh context.
  The refreshed acceptance form still requires a valid token and explicit
  reconfirmation.
- If the POST is confirmed but the context GET fails, the old form remains as a
  read-only record. Mutating controls stay disabled and a single explicit
  **Reintentar lectura de contexto** action issues only a GET. The UI states
  that the action was saved and does not offer a second POST from the stale
  form. A failed read retry returns to the same recovery state.
- If the POST fails at the network or response boundary, including an HTTP 5xx,
  its result is uncertain. The form is likewise held for explicit context reading and is
  never resent automatically. Even after that read, the UI continues to warn
  persistently that the earlier result is uncertain, that the previous form was
  replaced, and that the audit history should be reviewed before any repeat.
  The warning is state attached to the current drawer generation, so subsequent
  poll/context renders preserve it. Explicitly closing or navigating away from
  that drawer discards the warning; uncertainty is not stored across openings.

A context GET after an uncertain network failure is not proof that the earlier
POST did or did not commit: it may race the original request. This UI does not
add a general idempotency key and does not claim exactly-once delivery.

## Regression coverage

The Node harness loads the real `agentrelay/static/app.js`. Its DOM adapter now
implements the selectors used by the guard, node removal, attributes and prior
disabled states. Its `FormData` subset omits disabled rendered controls, as the
browser API does. The test asserts both that the emitted payload contains the
pre-lock value and that a new `FormData` read after locking omits it. This is a
discriminating harness design; no separate counterfactual source mutation was
executed for this ordering check.

Thirty-two checks cover the previous workspace, acceptance-context and drawer
isolation races plus these 0.18.2 cases:

- definition and checkpoint payload capture before disabling, with every
  drawer control locked through POST and context GET;
- successful context replacement and busy cleanup;
- known rejection and revision conflict preservation without a destructive
  drawer reload;
- exact restoration of an invalid acceptance control and execution controls
  that were already disabled;
- completion 409 locking and explicit reconfirmation;
- confirmed child creation with failed context loading, repeated read failure,
  successful read recovery and exactly one POST from the UI;
- uncertain network or 5xx outcome, no automatic POST and a persistent
  uncertainty warning after explicit context reading and a later poll/context
  rerender;
- opening B and closing/reopening A while A is pending, without inherited
  controls or `aria-busy`; and
- `start_run` worker capture before controls are disabled.

Commands used:

```text
node --check agentrelay/static/app.js
node --check tests/test_ui_races.js
node tests/test_ui_races.js
.runtime/Scripts/python.exe -m unittest tests.test_ui_races -v
```

## Limits

This guard prevents edits made after a drawer mutation starts. It does not save
or reconcile a dirty draft that already existed in another form of the same
drawer before the user submitted an action. It is not autosave or a general
offline queue. Global dialogs, execution-list cancellation and backend delivery
semantics are unchanged.

The checks use controlled DOM and fetch adapters around the real application
code. No browser, server or database QA was performed, so keyboard focus,
visual presentation and screen-reader behavior remain outside this evidence.
