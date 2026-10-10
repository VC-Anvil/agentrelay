# AgentRelay API contract

Local-first ticket coordination for humans, external agents and explicitly configured workers. SQLite is authoritative. UI language Spanish; source/docs English. Default host 127.0.0.1:8787. Root owns integration, HTTP, MCP, adapters, docs and packaging; execution specialist owns execution.py/test_execution.py; frontend owner owns static/*.

## HTTP

- GET /api/state -> {tickets: Ticket[], profiles: Profile[], events: Event[], stats: object}. Events newest first, max 100.
- GET /api/tickets/{id}/context -> {ticket, parent, dependencies, children, events, instructions, profile, profiles}. Includes evidence/checkpoint, blocked readiness, recommended target profile (or null) and the profile catalog for help routing in the same read transaction. Recommendations are not execution attestations.
- POST /api/actions -> {action: string, actor: string, data: object}; returns {result: object, state: State}. actor defaults human in UI. Action errors HTTP 400 (validation), 404, 409 (conflict). JSON error {error: string}. All mutations via this endpoint. UI sends expected_revision on update and lifecycle actions.
- GET /api/export -> complete versioned JSON export.
- GET /api/health -> {status: 'ok', version: string}. Version is the installed package version.
- GET /api/workspaces -> {workspaces:[{id,name,database,demo}],default_workspace_id}. Trusted startup registry only; no browser path input or registry mutation. Multi-project state/context/export/actions require X-AgentRelay-Workspace with a registered ID; missing is 400 and unknown is 404. Single-project requests remain compatible without it. State, context and HTTP export include workspace identity.
- State also contains `demo`, `version`, and `execution: {enabled, workers, runs}`. Run and ticket statuses are read in one SQLite snapshot. Workers expose only id/name/model/effort/profile_ids/timeout_seconds. Run fields: id/ticket_id/worker_id/status/started_at/finished_at/summary/error/model/effort, newest 100.
- POST actions `start_run {ticket_id,worker_id,expected_revision}` and `cancel_run {run_id}` require startup `--workers`. Normal result/state envelope applies. Execution protocol and failure statuses are in [EXECUTION.md](EXECUTION.md).

Early rejected POST requests discard a single declared body of at most 1 MiB,
with a one-second total deadline, before sending the error. This preserves error
delivery for complete small bodies sent after their headers without interpreting
their contents. Ambiguous, oversized or incomplete framing is not drained without
bound, so those peers may receive a closed connection instead of a full response.

## Ticket fields

id string AR-0001, title string, description string, type enum objective|task|bug|research|review|help, status enum backlog|queued|in_progress|blocked|review|done|cancelled, priority enum urgent|high|normal|low, parent_id string|null, depends_on string[], profile_id string|null, acceptance string[], checkpoint string, evidence [{kind:string,label:string,uri:string}], assignee string|null, actual_model string|null, actual_effort string|null, blocked_reason string, revision integer, created_at/updated_at UTC ISO strings. Derived ready boolean and blockers string[] returned on tickets.

## Profile fields

id string, name string, role string, provider string, model string, effort string, capabilities string[], preference enum quality|balanced|speed, description string. Model and effort are recommendations, not proof of availability. Default profiles Astra coordinator gpt-6-astra high; Sol complex implementation gpt-6-sol high; Terra bounded implementation gpt-5.6-terra medium; Luna extraction gpt-6-luna medium. Coordinator model may not silently downgrade. No availability/connected indicators without execution evidence.

## Actions and data

- create_ticket: title required; all editable fields optional. Defaults task/queued/normal; no arbitrary initial completed status. acceptance recommended.
- create_plan: exact envelope `{request_id,tickets}`; request_id nonempty <=128 characters, tickets 1..64 entries. Each entry has unique `key` <=64 characters, create_ticket fields, optional `parent_key`, `depends_on_keys`, and `status` (backlog default or queued). Local references may point forward. `parent_key` and `parent_id` are mutually exclusive; external `depends_on` may combine with local keys, without duplicates. Identifiers reject surrounding whitespace. Returns `{request_id,key_to_id,tickets}`. One transaction creates the entire validated graph and audit events; any failure rolls everything back. Same ID/actor/canonical JSON payload returns the original receipt, even after restart, without new events. Different actor/payload conflicts (409). The receipt is not current ticket context. No execution or automatic review. See [plans and freshness](PLANS_AND_FRESHNESS.md).
- update_ticket: id, expected_revision required, any title, description, type, priority, parent_id, depends_on, profile_id, acceptance, checkpoint. State changes use transition/claim/submit/complete. Cannot weaken acceptance while in progress, review, or blocked with an assigned owner. Completed task must reopen before editing deliverable scope.
- transition: id, expected_revision, status (backlog|queued|blocked|cancelled), reason optional. Reject in_progress/review/done here. blocked needs reason; reopening done requires reason. Clearing assignee on queue/cancel. Dependencies alone should produce derived blockers, not silently erase manual blocked state.
- claim_ticket: id, expected_revision, assignee required, actual_model, actual_effort optional. Only queued ready tickets; atomic; child objective not executable until children resolved. actor agent should match assignee.
- claim_next_ticket: exact `{request_id,candidates,assignee,actual_model,actual_effort}`. Candidates are 1..64 unique `{ticket_id,expected_revision}` entries whose full context the caller has reviewed. Identifiers and declarations are nonempty strings up to 128 characters without surrounding whitespace; revisions are positive integers, never booleans. Unknown ticket IDs fail the whole request (404). Stale revisions, non-ready tickets, empty acceptance and incompatible Astra declarations are skipped; eligible candidates sort by priority, creation time, then ID. Returns `{request_id,ticket,skipped}` with one claimed ticket or null. Only supplied IDs can be claimed. The agent actor must match assignee; MCP binds it to the connection. Same request ID/actor/exact canonical payload recovers its original historical receipt, including idle outcomes, without another claim or event. Changed actor/payload conflicts (409). SQLite backup preserves receipts; bulk export does not include them. See [scoped claims](CLAIM_NEXT.md). No model execution or automatic acceptance.
- checkpoint: id, expected_revision, checkpoint required. Append activity and increment revision.
- submit_ticket: id, expected_revision, summary string, evidence array required nonempty. Only in_progress, same owner or human. Moves to review and updates checkpoint/evidence. A URI is a reference, not verified proof.
- complete_ticket: id, expected_revision, expected_acceptance_context_token, verification string required, accepted_criteria string[] required matching all acceptance criteria. Obtain the required token from the context actually reviewed. Missing/malformed token is 400; a changed immediate acceptance context is 409 with no writes. Only review and dependencies/children complete (cancelled children allowed); actor cannot equal assignee (human actor can review other agents). Meaningful acceptance required. Records reviewer, verification and validated context token. No automated truth claim. See [acceptance context](ACCEPTANCE_CONTEXT.md).
- request_help: id, expected_revision, title, description, profile_id optional. Transactionally creates a help child inheriting the current parent priority, makes the parent depend on it, and marks the parent blocked with a reason. Later priority changes do not propagate between tickets. Child references parent's context but does not depend on parent (no cycle). On help completion parent remains explicitly blocked until requeued by owner/human.
- split_ticket: id, expected_revision, children array of {title,description?,profile_id?,acceptance?}. Creates queued children, marks original blocked, preserves history. Reject empty children.
- add_comment: id, body string.
- create_profile: profile fields except id; name,role,model required.
- update_profile: id + profile editable fields.

All relations must exist, dependency and parent cycles rejected (including execution deadlocks between hierarchy and dependencies). Audit actor/time/action/ticket_id/details. SQLite transactions, foreign keys/WAL, optimistic revisions. No destructive deletion/reset UI. Events include id, ticket_id nullable, actor, action, details object, created_at.

Changing a child's `parent_id` requires both the old and new parents, when
present, to be open: `done` and `cancelled` parents must be explicitly reopened
before adding, detaching or moving child scope. A rejected operation returns 409
without changing fields, relations, revisions or events. Existing validation also
rejects an explicitly supplied unchanged `parent_id` pointing to a closed parent;
omit that field when updating unrelated child fields.

Reopening a child or dependency while retaining its relationships does not
automatically reopen or invalidate a previously accepted parent. Acceptance is a
historical decision. `expected_revision` versions the addressed ticket, not every
derived item in its context. Since 0.18, acceptance additionally requires the
`acceptance_context.token` returned in the context the reviewer inspected. That
token covers immediate children/dependencies and direct source checks, not the
recursive graph. Completion compares it and checks current blockers within its
write transaction.

Cycle validation uses an iterative O(V+E) graph traversal. Valid deep hierarchies
do not depend on Python's recursion limit. This is not a performance guarantee
for rendering, listing or executing large boards.

## MCP listing

`list_tickets(status?,priority?,profile_id?,ready_only=false,assignee?,limit=20,offset=0,include_details=false)`
filters first, then orders by priority/created_at/id and paginates. Integers and
booleans are strict; limit is 1..100, offset >=0. Unknown status/priority/profile
filters and empty/nonexact owner identities fail rather than silently returning
unfiltered data. Owner matching uses the exact stored assignee string.

Returns `{tickets,actor,count,total,offset,limit,next_offset}`. `count` is the page
size; `total` counts matching tickets; `next_offset` is null on the final page.
Default summaries contain `id,title,type,status,priority,parent_id,profile_id,
assignee,revision,ready,blockers`. `include_details=true` returns full ticket
objects for the page. The 0.5 defaults differ from the unpaginated full objects in
0.4; clients must handle this change. Fetch current context before mutations.

Each call uses one Store snapshot. Offset pages do not share a snapshot across
calls; concurrent changes can shift positions. This bounds ticket count and field
selection, not string lengths, bytes, model tokens, quota or SQL work. The service
still reads the full local Store state before filtering; no query performance
improvement is claimed.

## Audit context

`create_plan` and `claim_next_ticket` share a request-ID namespace within one
database. An ID already recorded by one cannot be used by the other (409),
including idle claim receipts. Their exact legitimate retries remain historical
and do not mutate current tickets. Different project databases remain independent.

MCP `get_ticket_context(ticket_id,event_limit=20)` returns current context plus
`events_page:{total,count,limit,next_before_id}` and that page in `events`.
`list_ticket_events(ticket_id,limit=20,before_id=null)` returns
`{ticket_id,events,total,count,limit,before_id,next_before_id}`. Both are read-only;
limits are strict integers 1..100 and cursor IDs are positive integers <=2**63-1.
Events are ordered newest first and scoped to the ticket. A cursor excludes its
own ID; null next cursor indicates the final page. Total counts all current
ticket events, not just those older than the cursor. Each response is one SQLite
snapshot. [History semantics and CLI](HISTORY.md).

Worker packets use the recent 20-event context and explicitly identify older
history. CLI context defaults to 20 (`--event-limit` changes it, `--all-events`
restores full history); CLI `history` provides cursor access. Python
`Store.context(ticket_id, event_limit=None)` and HTTP context keep complete history
by default. Python `Store.ticket_events(ticket_id, limit=20, before_id=None)` is
the read-only service behind cursor pages. Export and backup retain full history.

## Python service

CLI `overview --workspaces REGISTRY --limit 5` and Python
`project_overview(config_path, limit=5)` return a versioned multi-project summary:
`{schema_version:1,default_workspace_id,count,limit,projects}`. Each project has
`id,name,database,demo,stats,urgent_open,ready,review,blocked`. Urgent open is an
integer excluding closed tickets. Each of the other three categories contains
`{total,tickets}` with up to 1–20 summaries (default 5), ordered by priority,
creation time and ID. Blocked includes manual blocks and queued tickets with
derived blockers; review is a status, not an approval guarantee.

Overview reads one Store snapshot per project and does not initialize execution
managers, read worker configs, recover runs or claim work. The workspace loader
accepts `enable_execution=False` for this path; its existing default is unchanged.
Store migrations on recognized databases remain possible. There is no global
cross-project snapshot or claimed SQL/token optimization. See [overview](OVERVIEW.md).

CLI `run-result --db DATABASE --run RUN_ID`, MCP `get_run_result(run_id)` and Python
`agentrelay.run_results.get_run_result(store, run_id)` read one retained worker
proposal. The response is `{schema_version:1,run,result,current_ticket}`. Run adds
`claim_revision` and `actor` to the ordinary public run fields; current ticket
contains `id,revision,status,assignee`. The proposal and metadata come from one
SQLite read transaction. A missing run returns 404; an empty/non-string ID is 400.

The execution manager captures normalized protocol output before applying it,
in a separate transaction, so conflicts and domain rejection retain the proposal.
Capture requires the run to remain running. A cancellation or crash after capture
can leave an unapplied proposal. Earlier interruption, invalid output and older
runs can return null. Retrieval starts no worker or execution manager and does
not apply or approve anything. Read full current context and evaluate relevance
before any authorized mutation. SQLite backup includes proposals; bulk run
history and JSON export omit their bodies. [Full contract](RUN_RESULTS.md).

Worker protocol results may include `artifact_markdown`: exact nonblank text,
strict UTF-8, at most 262144 encoded bytes. Future adapter reports retain that
field in the captured proposal and write matching UTF-8 bytes to the report file.
Retrieval does not follow evidence paths. Older proposals without the field stay
unchanged; no artifact is imported or inferred. Existing total output/storage
limits still apply. The provider's structured schema remains distinct from this
optional worker-protocol extension. [Inline reports](INLINE_REPORTS.md).

CLI `runs`, MCP `list_runs` and Python `agentrelay.run_history.list_runs` discover
executions without fetching proposal bodies. Filters `ticket_id` and `status` are
optional, limit is a strict integer 1..100 (default 20), and `before_id` is an
exclusive run-ID cursor. Returns `{runs,ticket_id,status,total,count,limit,
before_id,next_before_id}` with ordinary public run fields plus `has_result`.
Order is `started_at DESC,id DESC`; total counts all filter matches, ignoring the
cursor. A next cursor is present only when more matching rows remain.

Each call uses one SQLite read transaction. The cursor must identify an existing
run in the selected ticket when that filter is supplied; its status may have
changed since the preceding page. Pages do not share a snapshot: changes of
status can alter membership, and totals describe the current call. Legacy runs
without a retained-proposal column have `has_result:false`. Listing starts no
worker or manager and modifies no domain state. [Usage and errors](RUN_HISTORY.md).

CLI `context`, `history`, `runs`, `run-result`, `export`, `backup`, `run` and
non-creation actions require an existing recognized AgentRelay database before
calling `Store`. Missing paths fail without creating directories or backup output.
`serve`, `mcp` and the actions `create_ticket`, `create_plan`, `create_profile` may
initialize a new path. The action envelope and MCP actor are validated first.

Direct `Store(path)` may initialize a nonexistent path. Every existing file must
pass the shared base-schema check before WAL setup, migrations or default profiles.
Empty, corrupt, unrelated and incomplete files, directories and dangling file
symlinks are rejected. A valid symlink remains supported; the normalized path
inspected is the path used for connections. Recognized legacy databases still
receive normal migrations. This is neither database authentication nor protection
against hostile concurrent filesystem replacement, and opening a valid project
is not a filesystem-level read-only session. [Selection rules](DATABASES.md).

`Store.context` also returns `source_checks` (the latest three compact receipts)
and `source_checks_page: {total,count,limit:3,next_before_id}` in the same read
transaction as the ticket. Context receipts add `ticket_revision_matches_now`;
this compares ticket revisions only and does not attest current file contents.
Source checks are historical advisory observations and never reopen, accept or
execute work. Full per-file reports stay out of bulk state/export and worker
context. SQLite backup preserves the complete history and reports.

Local `check-sources` requires explicit existing `--db`, ticket/revision, snapshot,
expected snapshot identity, current root, actor and request ID. It measures using
the local comparison function, stores a bounded canonical UTF-8 report and its
SHA-256, then records a compact event without changing ticket fields or revision.
An exact request replay returns the original receipt before reading source paths;
a new measurement needs a new ID. Its request namespace is shared with plans and
scoped claims. Revision/collision failures insert nothing. Successful record or
replay exits 0 regardless of advisory findings. CLI `source-checks` and
`source-check` and MCP `list_source_checks` / `get_source_check` read stored data
only. There is no HTTP/MCP write action that accepts a source path or report.
See [full source-check contract](SOURCE_CHECKS.md).

An independent reviewer can use action `request_changes` with exactly
`{id,expected_revision,reason}` to return a review ticket to queued. The revision
must match and the stripped reason must contain 1–4000 characters. Self-review
is rejected with the same identity rule as completion. The author's checkpoint,
evidence, acceptance and dependencies are preserved; the assignee is released.
No worker starts. MCP `request_ticket_changes` binds the reviewer to its server
identity. Context includes the latest `review_feedback` independently of the
recent-event page; its later-submission/completion flags are historical facts,
not inferred review quality. [Exact correction workflow](REVIEW_CHANGES.md).

Python `agentrelay.snapshot_diff.diff_snapshots(before, after, *,
expected_before_id, expected_after_id, paths=None)` compares two explicitly
identified, verified captures without opening a database or following their
historical source roots. The local `diff-snapshots` CLI exposes the same operation;
it is not an HTTP/MCP filesystem tool. File states are unchanged, modified, added
and removed; structured hunks preserve text and line endings with zero-based line
indices. Computational and output limits omit an entire file's text explicitly,
while retaining its byte comparison. A report is review context, not a patch or
an automatic task update. See [exact fields, bounds and exits](SNAPSHOT_DIFF.md).

`Store(path)` initializes schema only, no demo by default. `state()`, `context(ticket_id)`, `export()`, `action(action, data, actor='human')`. `DomainError(message, status=400)` has .status. `seed_demo()` explicit idempotent method. Store connections per operation, concurrent safe. Standard-library only.

CLI `verify-report DIRECTORY [--receipt-sha256 HASH]` and Python
`agentrelay.report_integrity.verify_report(directory, receipt_sha256=None)` compare
fixed `receipt.json` and `report.md` files within an explicitly selected directory.
Each file is limited to 1 MiB. Only regular files are read; link/reparse paths and
changes detected during reading are rejected. Receipt metadata never chooses a
path. The command bypasses database initialization and has no MCP equivalent.

Returns `{schema_version:1,directory,status,reason,expected_report_sha256,
actual_report_sha256,receipt_sha256,expected_receipt_sha256,receipt_matches_expected}`.
Unknown values are null. States are `unchanged`, `modified`, `missing` and
`uncheckable`; CLI exits 0 for unchanged, 2 for other result states, 1 for invalid
directory selection or malformed anchor. Argparse usage failures remain 2 without
result JSON. Optional receipt hash mismatch stops before reading the report.
Legacy receipts without a report hash remain uncheckable; no baseline is invented.
The receipt is reread after the report and directory identities checked; this is
not an atomic filesystem snapshot or authentication. [Details](REPORT_INTEGRITY.md).

Demo is clearly labeled fictitious, belongs in separate --demo DB, never automatic user content. At least six meaningful tickets spanning statuses, priorities, nested tasks, help, and evidence. No fake running agents or invented usage metrics.
