# Pending actions and ticket forms — 0.18.1

Date: 2026-10-10. This patch extends the completion-form protection introduced in
0.18 to the other operations started from a ticket drawer.

## Reproduced behavior

An independent review exercised the actual `app.js` through the project's
controlled DOM/fetch harness. In each case, an operation was submitted for ticket
A, ticket B was opened and edited while the request was pending, and A's response
then arrived. Four paths reproduced the same loss: the Save listener
(`update_ticket`), checkpoint, submission for review and comment.

The response correctly updated the board, but also fetched B's context and
reconstructed its form, clearing its dirty state. The integrator independently
ran the same four cases against the published 0.18 code and reproduced them all.
This was a client selection race, not a database revision or acceptance-token
failure. The existing completion-only guard did not cover those other callers.

## Correction and verification

The originating workspace, ticket and drawer generation are now captured by the
Save listener, every drawer action and the worker-start form. Their confirmed
responses still update the board. Refreshing the form, displaying its toast,
clearing dirty state and handling a later conflict are conditional on that same
drawer instance remaining open, including checks after awaits and in the mutation
helper's final cleanup. A state GET started after a conflict also rechecks the
origin before chaining any drawer-context read. Closing and reopening the same
ID creates a new instance.

Independent static review checked those callers, generic conflict reloads and
ordinary state polling; it found no remaining actionable issue within this scope.
The host ran the final actual-application JavaScript harness through its Python
wrapper: **21 JavaScript cases and one passing wrapper**. The six
new cases check Save A→B, a normal successful checkpoint in its originating
drawer, submission followed by reopening A, comment conflict A→B and worker-start
A→B, plus switching to an untouched B while a conflict's state GET is pending.
They inspect control identity and edited values as well as state. Earlier
completion, workspace, context-refresh and retry cases remain in the suite.
See the [interface report](drawer-isolation-interface-report.md).

Independent review caught an initially nondiscriminating state-GET test: its
response left B's revision unchanged, so removing the guard still would not have
triggered a context read. The corrected fixture returns B revision 2 while its
displayed context remains at revision 1. The author then removed only the guard
in private copies: the test failed on the extra context GET (`4 !== 3`), while
the production code passed. This control did not modify production source.

Distribution verification compares all 21 installed package files against the
wheel and checkout, checks source-archive contents, and runs the same Node harness
against the installed wheel's JavaScript. Python module path and version are
checked in isolation. CI runs the full Python suite and JavaScript syntax check
on Windows and Linux with Python 3.11 and 3.12; the exact commit's result is
available in [Actions](https://github.com/VC-Anvil/agentrelay/actions/workflows/tests.yml).

## Limits

The harness runs the product JavaScript with controlled adapters. It verifies
requests, state and form behavior; it does not establish layout, focus,
screen-reader output or pointer usability in a real browser. Global creation
dialogs are outside this patch's scope. No database contract, worker execution
policy or paused game work is changed.

Browser access and restarting the existing pilot server remain blocked by
automatic approval review pending the user's requested authorization. No alternate
live server or rendering path was used. The published source and isolated package
do not imply that the pilot server has been reloaded; it remains at 0.17.1.
