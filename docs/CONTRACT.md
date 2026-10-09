# AgentRelay v0.4 contract

Local-first ticket coordination for humans, external agents and explicitly configured workers. SQLite is authoritative. UI language Spanish; source/docs English. Default host 127.0.0.1:8787. Root owns integration, HTTP, MCP, adapters, docs and packaging; execution specialist owns execution.py/test_execution.py; frontend owner owns static/*.

## HTTP

- GET /api/state -> {tickets: Ticket[], profiles: Profile[], events: Event[], stats: object}. Events newest first, max 100.
- GET /api/tickets/{id}/context -> {ticket, parent, dependencies, children, events, instructions, profile, profiles}. Includes evidence/checkpoint, blocked readiness, recommended target profile (or null) and the profile catalog for help routing in the same read transaction. Recommendations are not execution attestations.
- POST /api/actions -> {action: string, actor: string, data: object}; returns {result: object, state: State}. actor defaults human in UI. Action errors HTTP 400 (validation), 404, 409 (conflict). JSON error {error: string}. All mutations via this endpoint. UI sends expected_revision on update and lifecycle actions.
- GET /api/export -> complete versioned JSON export.
- GET /api/health -> {status: 'ok', version: '0.4.0'}.
- GET /api/workspaces -> {workspaces:[{id,name,database,demo}],default_workspace_id}. Trusted startup registry only; no browser path input or registry mutation. Multi-project state/context/export/actions require X-AgentRelay-Workspace with a registered ID; missing is 400 and unknown is 404. Single-project requests remain compatible without it. State, context and HTTP export include workspace identity.
- State also contains `demo`, `version`, and `execution: {enabled, workers, runs}`. Run and ticket statuses are read in one SQLite snapshot. Workers expose only id/name/model/effort/profile_ids/timeout_seconds. Run fields: id/ticket_id/worker_id/status/started_at/finished_at/summary/error/model/effort, newest 100.
- POST actions `start_run {ticket_id,worker_id,expected_revision}` and `cancel_run {run_id}` require startup `--workers`. Normal result/state envelope applies. Execution protocol and failure statuses are in [EXECUTION.md](EXECUTION.md).

## Ticket fields

id string AR-0001, title string, description string, type enum objective|task|bug|research|review|help, status enum backlog|queued|in_progress|blocked|review|done|cancelled, priority enum urgent|high|normal|low, parent_id string|null, depends_on string[], profile_id string|null, acceptance string[], checkpoint string, evidence [{kind:string,label:string,uri:string}], assignee string|null, actual_model string|null, actual_effort string|null, blocked_reason string, revision integer, created_at/updated_at UTC ISO strings. Derived ready boolean and blockers string[] returned on tickets.

## Profile fields

id string, name string, role string, provider string, model string, effort string, capabilities string[], preference enum quality|balanced|speed, description string. Model and effort are recommendations, not proof of availability. Default profiles Astra coordinator gpt-6-astra high; Sol complex implementation gpt-6-sol high; Terra bounded implementation gpt-5.6-terra medium; Luna extraction gpt-6-luna medium. Coordinator model may not silently downgrade. No availability/connected indicators without execution evidence.

## Actions and data

- create_ticket: title required; all editable fields optional. Defaults task/queued/normal; no arbitrary initial completed status. acceptance recommended.
- create_plan: exact envelope `{request_id,tickets}`; request_id nonempty <=128 characters, tickets 1..64 entries. Each entry has unique `key` <=64 characters, create_ticket fields, optional `parent_key`, `depends_on_keys`, and `status` (backlog default or queued). Local references may point forward. `parent_key` and `parent_id` are mutually exclusive; external `depends_on` may combine with local keys, without duplicates. Identifiers reject surrounding whitespace. Returns `{request_id,key_to_id,tickets}`. One transaction creates the entire validated graph and audit events; any failure rolls everything back. Same ID/actor/canonical JSON payload returns the original receipt, even after restart, without new events. Different actor/payload conflicts (409). The receipt is not current ticket context. No execution or automatic review. See [plans and freshness](PLANS_AND_FRESHNESS.md).
- update_ticket: id, expected_revision required, any title, description, type, priority, parent_id, depends_on, profile_id, acceptance, checkpoint. State changes use transition/claim/submit/complete. Cannot weaken acceptance while in progress/review/done. Completed task must reopen before editing deliverable scope.
- transition: id, expected_revision, status (backlog|queued|blocked|cancelled), reason optional. Reject in_progress/review/done here. blocked needs reason; reopening done requires reason. Clearing assignee on queue/cancel. Dependencies alone should produce derived blockers, not silently erase manual blocked state.
- claim_ticket: id, expected_revision, assignee required, actual_model, actual_effort optional. Only queued ready tickets; atomic; child objective not executable until children resolved. actor agent should match assignee.
- checkpoint: id, expected_revision, checkpoint required. Append activity and increment revision.
- submit_ticket: id, expected_revision, summary string, evidence array required nonempty. Only in_progress, same owner or human. Moves to review and updates checkpoint/evidence. A URI is a reference, not verified proof.
- complete_ticket: id, expected_revision, verification string required, accepted_criteria string[] required matching all acceptance criteria. Only review and dependencies/children complete (cancelled children allowed); actor cannot equal assignee (human actor can review other agents). Meaningful acceptance required. Records reviewer and verification event. No automated truth claim.
- request_help: id, expected_revision, title, description, profile_id optional. Transactionally creates help child, makes parent depend on it, marks parent blocked with reason. Child references parent's context but does not depend on parent (no cycle). On help completion parent remains explicitly blocked until requeued by owner/human.
- split_ticket: id, expected_revision, children array of {title,description?,profile_id?,acceptance?}. Creates queued children, marks original blocked, preserves history. Reject empty children.
- add_comment: id, body string.
- create_profile: profile fields except id; name,role,model required.
- update_profile: id + profile editable fields.

All relations must exist, dependency and parent cycles rejected (including execution deadlocks between hierarchy and dependencies). Audit actor/time/action/ticket_id/details. SQLite transactions, foreign keys/WAL, optimistic revisions. No destructive deletion/reset UI. Events include id, ticket_id nullable, actor, action, details object, created_at.

## Python service

`Store(path)` initializes schema only, no demo by default. `state()`, `context(ticket_id)`, `export()`, `action(action, data, actor='human')`. `DomainError(message, status=400)` has .status. `seed_demo()` explicit idempotent method. Store connections per operation, concurrent safe. Standard-library only.

Demo is clearly labeled fictitious, belongs in separate --demo DB, never automatic user content. At least six meaningful tickets spanning statuses, priorities, nested tasks, help, and evidence. No fake running agents or invented usage metrics.
