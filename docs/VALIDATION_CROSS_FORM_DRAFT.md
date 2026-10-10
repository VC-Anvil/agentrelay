# Drafts in another form of the same ticket — 0.18.3

Date: 2026-10-10. This follows the pending-action protection in
[0.18.2](VALIDATION_PENDING_DRAWER.md).

## Reproduced behavior

The author and integrator independently reproduced two losses with the real
application JavaScript and its controlled DOM/fetch harness. With title and
description edited in Definition but not saved, submitting either a comment or
a checkpoint sends only that other action. The pending-action guard correctly
locks the controls during the requests. The subsequent context read then replaces
the existing Definition draft with the server values, clears the dirty flag and
provides no warning that the draft was discarded.

A positive control edits and submits Definition itself. Its update request
contains the new values and its confirmed context retains them. This separates
cross-form draft loss from ordinary saving or a generic harness failure.

The baseline probe is also pinned to the published 0.18.2 application at
`3cc69ddb49fb69a1e43ede40a93dc962b39b2ee7`; its two loss cases and positive control
passed their assertions in the integrator's repeat run. The observation concerns
rendered control values, node replacement, dirty state and request payloads. It
does not claim execution against a browser or a live project database.

## Correction and verification

Each rendered form now has a baseline scoped to its workspace, ticket and drawer
generation. The UI compares actual text, select and checkbox values with that
baseline. Reverting a control to its initial value removes the change; controls
that were originally disabled are excluded. A semantic acceptance draft awaiting
refresh or reconfirmation also counts even if its controls match their baseline.

Before submitting, the UI asks for explicit discard consent when another form
has a draft. Cancel leaves the controls intact and sends no request. Continuing
sends only the selected action; it does not automatically save Definition or
post a second form. Either of two edited forms can be submitted through this
decision, so they do not block one another indefinitely. A form with only its
own draft needs no additional confirmation. Starting a worker explicitly warns
that it uses the persisted ticket definition.

Ordinary rejections preserve the drafts. A completion-context conflict is a
special case that can force a context read; the discard prompt warns about that
path, and the acceptance token and reconfirmation requirements remain in force.
Failed reads retain the visible drafts. The replacement happens only after a
successful read whose workspace and ticket identity match the request. This is
an identity check, not complete context-schema validation.

Independent source review identified a separate edge in the special acceptance
conflict path: when its forced context read failed, the old handler rebuilt the
drawer from the previous context. That could discard the other form's draft
without a successful read. This was a static finding, distinct from the two
executed baseline reproductions above. The corrected handler keeps the existing
controls and offers a read-only retry. A regression now exercises the 409,
failed read and successful retry, checking that the other draft survives until
the valid response and that no acceptance POST is repeated.

Executed checks:

- The host suite ran 270 tests in 81.826 seconds: 263 passed; seven were skipped
  because this Windows host cannot create the required symlinks.
- After the final test-only assertion change, the Python UI wrapper passed in
  0.183 seconds and executed all 43 Node cases against the real application.
  The independent reviewer also ran 43 cases successfully before that assertion
  ordering change and reviewed its final delta.
- In an isolated copy, removing only the return that honors Cancel made the
  cancellation test fail: it observed one request instead of zero. The production
  application was unchanged by this experiment.

The counterfactual experiment also improved the test: its first copy had a
line-ending error in the experiment setup; a subsequent run stopped at an
unresolved promise before reaching the full case count. The Python wrapper's
required total already rejected such incomplete runs. Cancellation assertions
now check request count and control identity before waiting for the listener,
so the injected defect fails at its cause. Both earlier attempts were retained
separately from the final successful experiment.

The [interface report](cross-form-draft-interface-report.md) lists the covered
flows and remaining limits. No backend or database migration is part of this
patch.

## Scope and limits

This work concerns a drawer action that would discard a draft already present in
another form of the same drawer. It does not introduce autosave, save one form as
an implicit side effect of another action, merge revisions or preserve all drafts
across navigation. Global dialogs remain outside this change.

The DOM/fetch harness executes the real application code but does not establish
native dialog appearance, keyboard focus, layout or screen-reader behavior.
Browser access and restarting the pilot remain blocked by automatic approval
review. No alternative live server or rendering path was used. Source and package
verification do not mean the existing 0.17.1 pilot server has been reloaded.

The project sources of the documentary pilots and their paused work are unchanged.
