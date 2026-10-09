# Frontend implementation report

## Delivered

The local web UI is implemented in `agentrelay/static/` with plain HTML, CSS, and JavaScript. It has no build step, remote assets, framework, or embedded credential.

- Responsive project shell with a narrow charcoal sidebar, warm off-white workspace, muted purple accent, keyboard-visible controls, mobile navigation, dialogs, drawer, empty states, connection state, API errors, and transient action feedback.
- Project board with six real lifecycle columns (`backlog`, `queued`, `in_progress`, `blocked`, `review`, `done`). Cancelled tickets stay out of the default view and appear through the status filter. The list view uses the same live filters.
- Search, priority, profile, and status filters. Board/list preference persists in local storage.
- Four summary cards computed only from fetched tickets: active work, ready queue, work in progress/review, and blocked work. There are no invented usage, presence, or running-agent values.
- The demo badge renders only when `GET /api/state` returns `demo: true`.
- Ticket creation and a detail drawer covering editable definition, parent/dependencies/profile/acceptance, child creation, valid transitions, ready-queue claim, checkpoint, comment, submission with evidence, independent review with acceptance checkboxes, help request, split, relations, blockers, context, evidence, and history.
- Ticket mutations send `actor: "human"`, the `X-AgentRelay-Client: browser` header, and the revision represented by the open form for optimistic concurrency. Background refreshes update the board without replacing open edits; a conflict therefore remains detectable rather than silently overwriting another writer.
- Profiles view supports display, creation, and editing of role, provider, recommended model/effort, capabilities, preference, and description. Copy explicitly identifies model/effort as recommendations rather than availability evidence.
- Activity and ticket history use Spanish action labels and compact field-change summaries. Full audit JSON remains recoverable in a collapsed disclosure, without injecting data as HTML.
- JSON export uses `GET /api/export` and a local object URL download.

## State-aware controls

The browser only offers claim for a `queued` ticket whose derived `ready` value is true, submit only for `in_progress`, completion only for `review`, and scope editing only before `done`. Completion renders every acceptance criterion as an explicit checkbox. The backend remains authoritative for graph rules, ownership, valid transitions, evidence, and review independence.

The claim form defaults the human-facing assignee to `human` and keeps it editable for explicit ownership. Actual model and effort start empty and are recorded only when known; the recommendation is displayed separately and the UI states that claiming does not start inference.

State changes remain available from active and review states, allowing a human to pause/requeue active work or reject a review through the backend transition rules. Profile effort also supports an explicit default/not-indicated value.

## Safety and accessibility

All API-originated strings are inserted with `textContent` or form values; the implementation does not use `innerHTML`, `outerHTML`, or HTML string insertion. Forms have visible labels, native validation for required action data, dialogs use native focus behavior, buttons have accessible names, the drawer exposes its labelled state, and Escape closes it.

No delete/reset action exists. Evidence URIs are displayed as inert text because a reference does not establish correctness and arbitrary schemes should not become executable links.

## Verification

- `node --check agentrelay/static/app.js` passes.
- `python -m unittest discover -s tests -v` passes all 10 current domain tests.
- Static audit confirms no dynamic HTML injection API and confirms the state, context, actions, and export endpoints are wired.
- Integrated browser testing was intentionally left to the root integrator to avoid two agents driving the same server/browser session. This report does not claim visual or end-to-end browser validation.

The HTTP server now exposes `/static/app.js` and `/static/style.css` from the package static directory, matching `index.html`.
