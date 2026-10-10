# Follow a ticket's agent workflow

Open a ticket from the board or list. **Flujo de trabajo** appears near the top
of its detail drawer. Select a step to see the recorded actor, date and details.
The latest event is selected initially; choosing an earlier step does not change
the ticket or any open form.

A correction cycle stays visible as separate steps:

`Claim → Submit → Request changes → Claim → Submit → Accept`

- Select a delivery to read its summary and evidence references.
- Select a correction to understand why the delivery was returned.
- Select an acceptance to read the recorded verification and accepted criteria.
- Expand the audit details to inspect the original event data.

These are historical records, not a live display of agents thinking. The ticket's
current status is shown separately. A recorded process start is not proof that
the process is still running; declared model settings are not provider telemetry.
An evidence reference is not proof that its artifact was checked.

## Interaction and data

The rail uses native buttons in chronological order. Keyboard users can tab to
a step and select it with Enter or Space. Each phase has a text label in addition
to its color. Unknown actions remain visible with their original action name.
Raw event data is rendered as text, never interpreted as HTML.

Selection only changes the event detail panel. It does not submit an action,
request new context or rebuild the ticket's forms. An explicit selection remains
selected when the same drawer is refreshed. Opening another ticket or project
starts a new selection. An empty history is labeled as empty; partial history is
identified rather than presented as the ticket's complete lifetime.

The web context currently supplies the full ticket history. This view adds no
history-loading endpoint, event mutations or automatic acceptance. Ticket
relationships remain available in the existing relations section.

## Evidence and limits

The implementation is checked with the real application JavaScript and a DOM
test harness, including correction cycles, draft preservation, navigation,
unknown events and text escaping. The harness does not establish browser layout,
contrast or mobile usability. Browser review of this release remains pending;
the existing pilot server must be updated before it can show the new view.

See the [review workflow](REVIEW_CHANGES.md), [history contract](HISTORY.md) and
[acceptance context](ACCEPTANCE_CONTEXT.md) for the underlying action semantics.
