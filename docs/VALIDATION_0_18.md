# AgentRelay 0.18 — acceptance against inspected context

Date: 2026-10-10. Local checks used Windows and Python 3.12.14.

## Evidence that motivated the change

A real configured Codex worker reviewed AgentRelay's frozen code through its
worker protocol. The host reproduced the reported sequence: read a parent in
review, add and complete a child, then accept the parent using its unchanged
ticket revision. That was allowed by the per-ticket contract in 0.17.2, even
though the reviewer had not seen the new child. The
[previous validation](VALIDATION_CLOSED_PARENT_SCOPE.md) preserves the source
snapshot, report hash, model-configuration limits and separate host reproduction.

This release deliberately strengthens the contract. Completion now requires the
token from the immediate context the reviewer inspected. It compares current
covered material, not every intervening event or the recursive graph. Legacy
completion requests without the token fail; no compatibility fallback bypasses
the new precondition. Included MCP, HTTP, CLI usage, UI, example and companion
skill are updated. See [the contract and migration](ACCEPTANCE_CONTEXT.md).

## Real design review using the new contract

The active AgentRelay design ticket was submitted for independent review. A
reviewer connection retrieved its acceptance token through the real MCP SDK.
The host then recorded a source check of its design and contract documents.
Both files matched the selected frozen capture, but that additional observation
changed the covered context without incrementing the ticket revision.

An MCP acceptance using the earlier token returned **409**, leaving ticket state
and events unchanged. The reviewer retrieved the new context; the host inspected
the new receipt and then explicitly accepted with that saved token in a separate
step. The completion event retained the validated token. Online SQLite backup
preserved the accepted ticket, audit event and source-check receipt exactly.

Frozen design input:
`sha256:bbe2abf9cdb8979b8fbd36c48f214bf5752b2ad0f0b9e79666e68c9167978b33`.
Source-check report SHA-256:
`c4558f17cd1366a920a9f43df226931da2f1ea16683ab4010bb8f9b73ed8f53d`.
This was a real project-document review, not a game validation or new provider
inference. The independent design analysis, host decision and transport checks
have distinct roles; an audit identity alone does not establish human identity.

## Executed checks and review

The first focused run passed **16/16 tests in 5.224 seconds**: thirteen domain
cases and actual CLI, HTTP and MCP integration tests. An additional domain case
then made the transient-state limit explicit: adding, cancelling and detaching a
new child can restore the original material and token; this is not an event
counter. The full suite including that case passed **265 tests in 79.446 seconds:
258 passed and seven Windows symbolic-link tests were skipped**.

Coverage includes source-check insertion/replay and a fourth receipt, child and
dependency reopening/reacceptance, changed membership, irrelevant comments,
history pagination, backup, two concurrent completions, 120 immediate relations,
nonrecursive scope, malformed/missing tokens and transactional conflicts. The
existing author/criteria/blocker tests were migrated to provide valid tokens so
their original negative checks still reach their intended rules.

Independent review found UI issues after the first full run: all completion 409s
were described as context changes, although other domain rules also use 409;
covered relationship and source-check details were insufficiently visible; and
failed context reload needed an explicit recovery path that retained the draft.
A subsequent review reproduced a pending completion overwriting a different or
reopened drawer. Completion now captures a stable drawer generation, ticket and
workspace before the request. Its response can update the board, but can only
refresh or clear the originating drawer instance. A failed-refresh retry also
retains edits made after the failure and disables those inputs during its read.
These findings were fixed. The final host UI run passed **15/15 JavaScript cases**
through its **1/1 passing Python wrapper**. These final UI checks are separate from the
initial full-suite result; the published commit is also checked by CI.

The [domain report](acceptance-context-implementation-report.md) and
[interface report](acceptance-context-interface-report.md) distinguish author
checks, independent review and host execution. Distribution verification compares
package and source-archive bytes, runs the changed acceptance behavior from an
isolated wheel and exercises the migrated handoff example.

## Limits

No browser or visual acceptance is claimed. JavaScript tests exercise the actual
application code through a controlled DOM/fetch harness; they do not establish
layout, focus, screen-reader behavior or pointer usability. Automatic execution
approval previously rejected restarting the existing pilot server; that server
remains at 0.17.1 pending authorization. It was not bypassed with another live
server or alternative rendering. Temporary HTTP servers used by automated
protocol tests are isolated fixtures, not substitutes for the requested reload.

The new token is neither a signature nor proof of evidence quality. It covers
the addressed ticket, immediate child/dependency rows and direct source-check
observations. It excludes external files, deeper graph state, comments and
direct hostile edits of SQLite. Historical acceptance is not automatically
invalidated, and no paused game work was resumed.
