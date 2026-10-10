# Cross-form drawer draft protection

## Result

The ticket drawer now records a baseline for every rendered definition,
lifecycle and execution form. Text, select and checkbox values are compared
with that baseline on each submission, so returning a control to its rendered
value clears the draft state. Controls that were disabled when rendered do not
become drafts.

Before a drawer action captures `FormData` or sends a POST, the UI checks the
other forms in the same workspace, ticket and drawer generation. When another
form has changes, a synchronous Spanish confirmation identifies the affected
form and says that the context reload will discard its draft. Cancel sends no
request and keeps every control. Saving the form that owns the draft does not
prompt. `start_run` additionally states that the runner will use the persisted
ticket definition.

The acceptance-review draft is also semantic state. A pending reconfirmation
or failed acceptance-context refresh prompts before another form acts, even
when its visible values match their baseline. Submitting the completion form
itself does not mistake its review draft for an unrelated form, and this draft
still requires the acceptance-context token and explicit reconfirmation.

## Discard boundary and failures

Consent authorizes replacement only after a valid context response for the
same ticket. It does not clear another form or the semantic review draft when
the POST begins, when the service rejects the write with a known 4xx, or when
the subsequent context read fails. A successful retry of that read may perform
the already-authorized replacement without repeating the POST; all drawer
controls are locked while that retry is pending so newer edits cannot be lost
inside the same read. A 200 response with a missing or mismatched ticket
identity, or the wrong workspace identity, is treated as a failed read and
preserves the draft. This is an identity check rather than full schema
validation.

For completion conflicts, the confirmation explicitly warns that a conflict
can force the context reload. The existing completion flow keeps the drawer
mutation guard active during that read, preserves the submitted verification,
and requires a second explicit acceptance confirmation against the refreshed
token. Background polling remains blocked while a form differs from its
baseline or a semantic review draft is pending.

Navigation to another ticket, closing the drawer, changing workspace, or
reopening the same ticket creates a new drawer generation and drops the old
baseline and consent. Late responses therefore cannot apply an earlier
discard decision to the new form.

## Regression evidence

The Node harness loads the production `agentrelay/static/app.js`; it does not
copy the draft algorithm. Forty-three checks cover the existing workspace,
acceptance-context, pending-write and drawer-isolation cases plus:

- cancelling a cross-form discard with zero POSTs and unchanged controls;
- preserving another form through the POST and replacing it only after the
  valid context GET;
- saving the owning form without a prompt and reverting to the baseline;
- preserving visible and semantic review drafts on a known rejection;
- pre-authorizing the forced reload for an acceptance-context 409 while still
  requiring review reconfirmation;
- warning that `start_run` uses the persisted definition;
- rejecting a missing or mismatched ticket identity before discarding a draft;
- preserving a second form through a completion 409, failed context GET and
  read-only retry, then discarding it only when that retry returns valid data;
- requiring consent when saving a definition beside a comment draft, while
  sending exactly one `update_ticket` and no implicit comment;
- detecting checkbox changes while ignoring initially disabled controls; and
- clearing a consented semantic review draft only after a valid context GET.

Executed locally:

```text
node --check agentrelay/static/app.js
node --check tests/test_ui_races.js
node tests/test_ui_races.js
.runtime/Scripts/python.exe -m unittest tests.test_ui_races
```

Results: 43/43 Node checks passed and the Python wrapper passed 1/1.

The integrator also ran a private counterfactual that removed the early return
after a rejected confirmation. It exposed a weakness in the first asynchronous
test shape: Node could exit while the unintended POST promise remained
unresolved, although the Python wrapper's expected-count assertion still
failed. The four cancellation cases now assert zero requests and unchanged
controls immediately after dispatch, before awaiting the listener promise, so
that counterfactual fails at the causal boundary instead of relying on the
suite footer.

## Limits

This is an explicit discard guard, not autosave, form merging or offline
delivery. A user who confirms the prompt intentionally replaces the other
draft after a successful context read. An uncertain POST still requires the
existing read-only recovery and audit review; a later GET does not prove
whether that POST committed. Global dialogs and non-drawer actions remain
outside this change.

No browser or visual accessibility run was performed for this package. The
evidence covers the real application logic through the controlled Node DOM and
fetch harness; native confirmation presentation, focus and screen-reader
behavior remain for integrated browser QA.
