# Acceptance-context UI integration report

## Result

The browser interface now binds every `complete_ticket` request to the
acceptance-context token that was present in the context actually rendered to
the reviewer. It sends that value as
`expected_acceptance_context_token`; it never substitutes the latest value from
application state immediately before submission.

Review contexts without a valid version 1 `sha256:<64 lowercase hex>` token are
shown as incompatible with the required contract. The completion button is
disabled and the Spanish message asks the user to update the service and reload
or reopen the ticket. No legacy fallback sends an unguarded acceptance.

On the exact acceptance-context 409, or a ticket revision-conflict 409 from
`complete_ticket`, the interface:

1. keeps the verification text and selected acceptance criteria in a draft
   scoped to the current workspace epoch and ticket;
2. loads fresh ticket context with the already captured workspace header;
3. renders the refreshed relations, evidence and history together with the
   preserved draft;
4. requires the reviewer to select an explicit confirmation checkbox before a
   second submission is enabled; and
5. does not retry the completion automatically.

Other 409 responses, such as self-review, incomplete criteria or current
blockers, keep the existing form in place and show the backend error. They do not
mislabel the rejection as a changed context or create a reconfirmation draft.

If the refreshed ticket is no longer in review, the draft is discarded and the
current state is shown. If the refresh fails, the drawer is rebuilt from the
previous context with the preserved draft, completion disabled and a visible
`Reintentar carga de contexto` action. A successful retry displays the new
context and then requires confirmation; it never sends completion itself. Edits
made to verification or criterion selections in the retry form are synchronized
to the draft before the GET starts. Those controls are disabled while the GET is
pending, so a later render cannot discard edits made mid-request.
Closing the drawer, reopening a ticket, or changing workspace clears the draft.
Late context responses from the previous workspace remain subject to the
existing workspace epoch and request nonce guards.

Completion also captures a stable drawer generation in addition to the workspace
and ticket ID. Opening or closing a drawer increments that generation. A pending
completion may still update the board from its confirmed response, but it cannot
refresh or clear another ticket's form, a newly reopened instance of the same
ticket, or a drawer in another workspace. Likewise, a late context/revision 409
cannot install its draft into a different drawer.

The generic mutation refresh was excluded for `complete_ticket` conflicts. That
action uses the dedicated refresh above so a background state reload cannot
replace the review token before the draft has been captured. Other actions keep
their existing conflict refresh behavior.

The drawer now exposes the material a reviewer can inspect for the immediate
relations covered by the token. Each parent, dependency and child has an inline
disclosure with status, revision, description, acceptance criteria, last
checkpoint and recorded evidence. Opening a related ticket remains optional.
The drawer also lists the latest source-check receipts already present in
context: displayed count and total, check ID, observed ticket revision, snapshot
ID, report hash, revision-match indicator and summary counts. These are labelled
as historical observations; the UI does not fetch reports or source paths
automatically.

## Verification

The Node harness loads the real `agentrelay/static/app.js`; it only replaces the
final bootstrap calls and supplies controlled DOM, FormData, storage and fetch
adapters. Fifteen checks passed:

- the four existing state, context and workspace race checks;
- the submitted completion keeps the token from the rendered form;
- a controlled API 409 preserves the draft, fetches new context and performs no
  automatic resubmission;
- the new context cannot be submitted until explicit reconfirmation;
- a workspace change discards the old draft and ignores its late context; and
- a legacy context without an acceptance token cannot be completed;
- unrelated 409 responses retain the form without a context refresh;
- a failed context refresh renders a working retry path, retains edits made
  before retry and disables those controls during the pending GET;
  and
- the DOM contains inspectable immediate-ticket material and the latest source
  checks with their total;
- a successful pending completion for ticket A updates board state without
  refreshing or clearing an edited ticket B drawer;
- a context 409 for A cannot install a draft or refresh B; and
- closing and reopening A creates a new drawer generation that an older pending
  completion cannot overwrite.

Commands executed on 2026-10-10:

```text
node --check agentrelay/static/app.js
node --check tests/test_ui_races.js
node tests/test_ui_races.js
.runtime\Scripts\python.exe -m unittest tests.test_ui_races -v
```

All commands exited successfully. The Node harness reported `15 pruebas de
carreras UI superadas`; the Python wrapper reported one passing test.

## Files

- `agentrelay/static/app.js`
- `tests/test_ui_races.js`
- `tests/test_ui_races.py`
- `docs/acceptance-context-interface-report.md`

## Limits

No browser or visual QA was performed because automatic approval review for that
browser run remains pending. This is a constraint on that specific test action,
not a lack of authorization for the UI package. The harness verifies request
data, conflict behavior, draft preservation and race guards, but it does not
assess real layout, focus, screen-reader output or pointer interaction. Backend
token calculation and transactional enforcement are outside this UI package.
