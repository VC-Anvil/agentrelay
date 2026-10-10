# Architecture and boundaries

```mermaid
flowchart LR
  Human[Local browser] --> HTTP[Loopback HTTP service]
  Agent[External agent host] --> MCP[MCP stdio server]
  HTTP --> Domain[Store: validated state transitions]
  HTTP --> Runner[Explicit execution manager]
  CLI[Bounded queue CLI] --> Runner
  Runner --> Worker[Trusted configured process]
  Worker --> Result[Validated JSON result]
  Result --> Domain
  MCP --> Domain
  Domain --> SQLite[(SQLite + audit events)]
  Skill[Companion skill] -. workflow guidance .-> Agent
```

Hosts can connect via MCP, or the user can enable a trusted worker configuration at startup. The execution manager claims one ticket, launches a fixed argv without a shell, bounds its duration/output and applies its result through the same domain rules. A profile is a recommendation; an assignment is ownership; a running process is not evidence of provider availability. Actual-model declarations are not measured telemetry.

## State and concurrency

Each command opens its own SQLite connection. Mutations use `BEGIN IMMEDIATE`; all fields and audit records for help/split are committed atomically. Readers use a snapshot transaction. Ticket writes compare `expected_revision`; a conflict requires rereading and reconciling context. Claiming requires a queued, ready ticket. Ownership remains on blocked work so another worker cannot edit a paused owner's task.

Parent-to-child edges and explicit dependency edges form one execution graph for cycle validation. A parent waits for unfinished children and cannot be claimed until they resolve. An explicit dependency requires `done`; a cancelled dependency does not qualify. A cancelled child can be excluded from parent completion. A manually blocked ticket stays blocked after its dependencies finish until explicitly requeued. Closing all children never closes the parent automatically.

Submission records evidence and enters review. Completion needs all criteria explicitly accepted, dependencies resolved, and a reviewer identity different from the assignee. These rules protect workflow integrity; they do not prove an artifact is correct or establish cryptographic identity.

Child membership cannot be added to or removed from a closed parent without
explicitly reopening that parent. Both ends of a move are checked in the child's
transaction. This does not freeze historical child/dependency status: reopening
existing work retains the parent's earlier acceptance. Revisions protect each
addressed ticket, not the entire derived context graph. Acceptance adds a required
token of the context actually presented to the reviewer: the ticket, immediate
children/dependencies and direct source-check observations. Its comparison occurs
in the completion transaction, so a covered difference from the reviewed context produces a
conflict. It does not recurse, verify external evidence or prove that a reviewer
understood what was presented. See [acceptance context](ACCEPTANCE_CONTEXT.md).

Plan imports validate and create the full graph in the same write transaction.
`plan_requests` stores the actor, canonical payload hash and original result;
retries return that receipt without generating more tickets or events. SQLite
backup includes these receipts. A creation receipt is not a current context read.

`apply_ticket_action` wraps eligible ticket mutations in the same dispatcher and
write transaction as legacy actions. `action_requests` stores the normalized
actor, action, bounded canonical intent and its hash, original result and commit
time. Exact retries retrieve that receipt before current-state validation; they
do not execute another mutation. Conflicting key reuse is rejected. Intent and
result serialization failures roll back the action as well as the receipt.
Plans, scoped claims, source checks and ticket actions share the project key
namespace through symmetric guards. The source-check path checks again after its
external comparison to close the intervening write race. Every writer must be
upgraded for these guards to hold across all operations. See
[ticket action receipts](ACTION_RECEIPTS.md) for limits and transport examples.

`get_action_receipt` reads one actor-scoped ticket-action receipt in a SQLite
snapshot without dispatching an action. Result size is checked before its body
is loaded; invalid stored data fails with a controlled error. The response omits
the write API's `replayed` flag and does not combine an old result with current
ticket state. A read that sees no receipt can precede the original writer's
commit. Clients must not turn that observation into an automatic retry. Opening
the project still follows the usual initialization/migration contract; this is
not a new filesystem read-only mode. See [lookup semantics](ACTION_RECEIPT_LOOKUP.md).

## Projects and captured inputs

A trusted startup registry maps project IDs to existing databases and optional
worker configurations. Each request selects its own workspace; the server has no
shared mutable selected-project state. The browser ignores responses belonging to
an earlier project or stale request generation. Cross-project source-file locking
and dependencies are not provided.

Explicit input snapshots preserve selected files and an unsigned hash manifest
outside their source tree. Adapters can receive verified snapshot text when
explicitly configured, without expanding provider file permissions. Freshness
comparison reads an explicitly supplied current root; manifest provenance never
selects that root. Neither operation executes source text or automatically changes
ticket acceptance. File reads are bounded and checked individually, not atomic
across a changing project. See [pilot workflow](PROJECT_PILOTS.md).

## Trust model

Single trusted local OS user. HTTP uses loopback only, a Host allowlist, same-origin checks, a required custom mutation header and a static asset allowlist. No public serving, CORS or arbitrary file-reading endpoint. Execution requests choose an existing configured worker, never a command. The browser always acts as `human`; MCP identity comes from its command-line configuration. Another program with access to the database can bypass application rules, so this is not a security boundary against the local user or a malicious installed agent.

Evidence paths are inert references. No server-side fetching, uploads or inference keys in the web API. Worker commands are trusted code with local OS permissions; the manager is not a sandbox. Codex adds its own configured sandbox, while the Ollama adapter only generates a written report. Do not treat ticket text as authority to expand permissions. The companion skill preserves host permissions and user scope.

## Execution consistency

Claim and run creation commit together. One OS lock and a partial unique SQLite index prevent simultaneous managers/runs on the same database. Result application checks the original claim revision and owner before a transaction changes the ticket and run. Human/MCP edits are never overwritten. Ticket and run statuses in HTTP snapshots share one read transaction. Export and SQLite backup preserve run history without serializing executable configuration or credentials.

Cancel/timeout stop the owned process tree; errors block only the unchanged owned ticket. Restart recovers unfinished runs as interrupted and never retries automatically. A hard manager crash can leave OS children alive, so recovery requires inspection before a manual retry. Process lifetime isolation across crashes and across separate project databases is not claimed.

## Distribution

Python standard-library core; optional official MCP SDK 1.30.0; vanilla HTML/CSS/JS packaged as static resources. One database per project. Demo data and real data have separate default paths. SQLite files, environments, logs and local exports remain outside Git.

## Scope

The shipped core is ticket coordination, MCP, explicit worker execution, bounded queue dispatch and independent review. Provider usage metering, unattended scheduling, GitHub Issues synchronization and multi-user hosting are outside this release. See [execution protocol and operation](EXECUTION.md).
