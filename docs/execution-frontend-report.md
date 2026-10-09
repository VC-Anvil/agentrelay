# Execution frontend report

## Delivered

The v0.2 browser UI consumes the optional `state.execution` contract without changing the existing manual or MCP workflow.

- A new **Ejecuciones** navigation view lists configured workers and the newest execution runs.
- Worker cards state only configuration: ID, configured model, configured effort, timeout, and compatible profiles. They do not claim connectivity, availability, token usage, or provider telemetry.
- Run cards show the Spanish status, worker, ticket, configured execution model and effort, start/finish times, summary, and error. The ticket can be opened directly; only a `running` run exposes cancellation.
- All specified run states have Spanish labels: `running`, `submitted`, `help_requested`, `split`, `blocked`, `failed`, `cancelled`, `interrupted`, and `conflict`.
- A global active-run notice and disabled launch control reflect the one-run limit. The backend remains authoritative if state changes concurrently.
- When execution is disabled or no workers are configured, the view explains that manual/MCP work remains available and shows the explicit `agentrelay serve --workers workers.json` setup command plus documentation guidance.

## Ticket launch flow

A ticket drawer shows **Ejecución local** only while the ticket is `queued` and its derived `ready` value is true. The panel:

1. Filters workers exactly by configuration: an empty `profile_ids` accepts any ticket; otherwise the ticket's recommended `profile_id` must match.
2. Shows the selected worker's configured execution model, effort, and timeout separately from the ticket's recommended profile.
3. States that a delivered result moves to human review and still requires human acceptance.
4. Posts `start_run` with `ticket_id`, `worker_id`, and the revision represented by the open drawer.
5. Disables launch while another run is active. A concurrent backend conflict still surfaces as a real API error.

No worker starts on page load. Launch requires a deliberate button submission.

## Refresh behavior

The existing polling refreshes execution history. When a drawer is open and untouched, a changed ticket revision or run status reloads its context. Once the user edits or changes a drawer control, polling leaves those inputs intact so optimistic revision checks can expose stale work instead of silently overwriting it.

The default ticket status filter is now labelled **Todos salvo cancelados**, matching its behavior: completed tickets remain visible and cancelled tickets require an explicit filter.

## Verification boundary

`node --check agentrelay/static/app.js` is the frontend syntax acceptance check. Integrated HTTP and browser validation depend on the root-owned v0.2 API implementation; this report does not claim those checks before the integration owner runs them.
