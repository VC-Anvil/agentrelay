# Ticket action receipt validation — 0.19

The motivating isolated HTTP reproduction against 0.18.3 committed a child
ticket and then failed while constructing the response. Repeating the unkeyed
request produced two children. The equivalent comment reproduction produced two
events. This is permitted for unkeyed operations; matching text alone cannot
identify an intended retry.

The new wrapper lets the caller identify one logical operation before its first
send. Its guarantee is one committed ticket mutation per retained key and exact
intent in the selected SQLite database, not atomic external execution or automatic
recovery. See the [contract and examples](ACTION_RECEIPTS.md).

## Reproducible checks

From an installed checkout with the optional MCP dependency:

```sh
python -m unittest tests.test_action_receipts tests.test_action_receipt_protocols -v
python examples/action_receipt_demo.py --output .agentrelay/new-receipt-example
python -m unittest discover -s tests -v
```

Domain tests cover a single child and comment after exact replay, concurrent
Store connections, conflicting key reuse, historical results after later edits,
reopening the database, SQLite backup, export exclusions and rollback of action,
events and ID allocation when receipt serialization or size checks fail. Help and
split retries do not duplicate children. Completion replays preserve a historical
decision without adding another acceptance event or using a new token.

Namespace tests cover both directions between ticket receipts and plan, scoped
claim and source-check receipts. A controlled race lets a ticket action reserve
the key while the source comparison is in progress; the second source-check guard
rejects it without persisting a contradictory receipt.

Protocol tests use real subprocess CLI commands, an isolated loopback HTTP server
and two official SDK MCP stdio clients. They inject a response-construction error
after a real HTTP write has committed, then retry the exact wrapper. One child or
comment remains. A later edit demonstrates that HTTP's current state and the
receipt's historical result can differ. The CLI validates wrapper structure before
database selection and only allows the wrapped creation case to bootstrap. MCP
tests cover schema annotations, concurrent clients, actor binding, self-review
rejection and required execution declarations.

The runnable example discards the first committed return value deliberately;
that is a simulation, not a network fault. It then explicitly recovers the
receipt, distinguishes current context, rejects changed intent and verifies
backup replay. Its output directory must be new, preserving earlier results.

## Findings closed before publication

Review found that an optional key added to an ordinary `add_comment` could be
silently ignored by an older writer. A pinned 0.18.3 Store reproduction confirmed
two comments with that approach, while the explicit new action name rejected
before writing. The shipped contract therefore requires the new wrapper.

Review also found that a generic MCP data object could omit model/effort
declarations required by the specific claim tool. Wrapped claims now require
nonempty declarations; missing, null and empty values cannot claim an Astra task.
The existing locked-profile checks reject incompatible declarations. This does
not turn declarations into measured execution telemetry.

Canonicalization now executes a detached JSON value, so later mutation of the
caller's Python object cannot change the action after its intent was recorded.
Invalid Unicode and non-JSON Python types produce controlled errors. Depth is
bounded explicitly rather than relying on an interpreter's recursion limit.
The first domain run also exposed an incorrect test expectation for an unknown
profile: the existing domain returns 404, and the fixture was corrected.
The first CI run on Python 3.11 found that rendering the deeply nested fixture
inside a subtest label raised `RecursionError` before reaching the validator.
The label now uses a case index, preserving the deep input and actual assertion.

## Real project use and limits

The integrator's final Python 3.12 run discovered 286 tests: 279 passed and seven
Windows symlink cases were skipped by their existing capability checks, in
87.892 seconds. The focused domain run passed 11 tests and the CLI/HTTP/MCP run
passed five. The companion skill also passed its structural validator; that
check alone does not establish correct agent behavior. The repository's CI
matrix separately exercises Python 3.11 and 3.12 on Windows and Ubuntu.

The integrator used the new CLI against AgentRelay's own development ticket. Two
explicit sends of one retained comment request returned first-write and replay
receipts and left one event. No response failure was injected in that project;
the post-commit failure evidence comes from isolated HTTP fixtures. The comment
did not accept the task, start a worker or change another project's source.

Independent source review is separate from the integrator's executable checks.
Specialist fixture execution blocked by its environment is not counted as a
passing run. The integrator runs fixtures in its normal runtime and retains the
logs. Package verification compares source, wheel and installed files and runs
the example using the isolated installed package.

This release does not add browser retries, receipt lookup, automatic acceptance
or worker/process idempotence. No fresh browser QA or live pilot-server upgrade
is claimed. A historical receipt does not establish current state or evidence
quality. Every writer needs upgrading for the new cross-operation namespace
guards; an older running process cannot enforce guards it does not know.
