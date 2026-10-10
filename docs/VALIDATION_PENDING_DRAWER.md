# Editing while a ticket action is pending — 0.18.2

Date: 2026-10-10. This follows the cross-drawer isolation in
[0.18.1](VALIDATION_DRAWER_ISOLATION.md).

## Reproduced behavior

The application kept the current drawer editable while its Save or checkpoint
request was pending. The author and integrator independently exercised both
handlers through the actual application's DOM/fetch harness: submit V1, enter V2
in the still-enabled field, then resolve the request and its context read. V2
remained visible until the final read replaced the control with V1 and cleared
the dirty flag. Both paths reproduced the loss.

Workspace, ticket ID and drawer-generation guards prevent a response from
overwriting a different or reopened drawer. They do not distinguish later input
entered into the same form while its own request is pending.

A separate probe pinned the published 0.18.1 source and harness to commit
`868dd6b834572f3130dcda58cfb9b219dd23d7af`. Its author and the integrator reproduced
three related error paths:

- a confirmed Save at revision 2 followed by a failed context GET left the old
  revision-1 form enabled and marked clean;
- after confirmed child creation and a failed context GET, submitting that old
  form emitted a second identical creation request without a revision precondition;
- a transport failure during the POST did not retry automatically, but left a
  second identical manual request possible while the first outcome was unknown.

These are observed client requests and states, not proof of a duplicated database
row or a server commit after a network cut. The baseline harness's simplified
FormData did not model disabled controls, so these probes also do not prove the
ordering of form serialization and locking in the fix.

## Correction and verification

The drawer captures and validates its submitted values before disabling all of
its controls. The lock covers both the action and the subsequent context read.
A known rejection restores the original controls and their previous restrictions,
with the draft still marked dirty. A successful context read renders the new
state. Opening a different drawer or reopening the same ticket invalidates the
old guard, so its eventual response cannot unlock or replace the newer form.

When the service confirms an action but reading its context fails, the UI says
the action was saved and keeps the old values available to copy. Mutating
controls remain disabled; the recovery button retries only the context GET.
Network, invalid-response and 5xx outcomes instead remain explicitly uncertain.
Neither path automatically repeats the POST. `aria-busy` describes an actual
pending request, not the idle wait for the user to retry a read.

Independent review caught an uncertainty warning that initially existed only in
the DOM and disappeared on the next automatic context refresh. The warning now
has state scoped to the open drawer generation and survives those refreshes.
The regression exercises a failed POST, successful explicit read, later state
poll and changed context while checking that exactly one POST was sent. Closing
or explicitly navigating the drawer ends this warning's scope; it is not a
persistent operation log.

Integration review also found that the HTTP handler built its response snapshot
after the Store action had committed, within the same exception handler used for
request errors. A later ValueError or DomainError could therefore be reported as
a 4xx rejection despite an applied action. The response phase must classify such
failures as 500; the client must treat 5xx responses as uncertain rather than as
proof that no action was applied. The server change and real HTTP fixtures are
verified alongside the client guard.

Executed checks:

- Five isolated real-HTTP tests pass: two snapshot failures and a response
  serialization failure after commit return 500 while the created ticket
  remains in SQLite; malformed input and a stale claim retain 400/409 without
  changing tickets or events. The first test run caught a faulty fixture that
  attempted a valid claim instead of a conflict; the fixture was corrected.
- The host suite ran 270 tests in 82.233 seconds: 263 passed and seven were
  skipped because this Windows host cannot create the required symlinks.
- After the last warning-state correction, the final Python UI wrapper passed
  in 0.146 seconds, executing all 32 Node cases against the real application
  JavaScript. The full suite above preceded that last UI correction.

The HTTP author's sandbox could not open its temporary SQLite database during
setup. That attempt is not counted as a pass; the integrator ran the HTTP tests
successfully in the normal host environment. Separate implementation reports
describe the [HTTP behavior](pending-drawer-http-report.md) and
[interface checks](pending-drawer-interface-report.md).

## Scope and limits

The change addresses input entered while a drawer action is pending. It does not
implement autosave, merge concurrent drafts or preserve a draft already left in
another panel before the action began. Global ticket/profile dialogs and
execution-list cancellation are outside the drawer-specific scope.

A read after an uncertain POST is only an observation at that instant: it may
precede the original request's eventual commit. It cannot prove that the action
did not happen or provide exactly-once delivery. This patch does not add general
request idempotency to ticket creation. No automatic repost is permitted, and an
uncertain outcome must not be relabelled as a confirmed failure or success merely
because a subsequent read succeeds.

The JavaScript harness uses controlled DOM/fetch adapters around the real product
code. It can establish request, control-state and recovery behavior, but it does
not prove focus, screen-reader output, layout or pointer usability in a browser.
Browser access and restarting the pilot server remain blocked by automatic
approval review; no alternative live server or rendering path was used. Source
and isolated-package verification do not imply that the pilot has been reloaded:
the existing server remains at 0.17.1.

No game sources, paused work, database contract or worker execution policy are
changed by this patch.
