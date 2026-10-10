# Review changes interface report

## Delivered MCP surface

`request_ticket_changes(ticket_id, expected_revision: StrictInt, reason)` binds
the reviewer to the MCP server actor and forwards exactly `id`,
`expected_revision` and `reason` to Store action `request_changes`. It uses the
existing non-idempotent write annotation. Its description states that an
independent reviewer returns a delivered ticket to queue with explicit
corrections; it does not execute, claim, accept or implicitly reopen work.

The server and current-context instructions direct resumed workers to read the
latest feedback and make clear that later-submission/completion booleans are
historical event facts rather than proof of correction or acceptance.

## Interface coverage

`tests/test_mcp_review_changes.py` uses two real SDK/stdio sessions with fixed
author and reviewer identities. Both read current context. It verifies tool
annotations and the strict integer schema, rejects self-review and invalid
revision types, returns the reviewed ticket once, preserves checkpoint,
evidence, acceptance and declared settings, reads the projected feedback from
fresh bounded context, and confirms that no execution run or second return event
was created.

The same module invokes the existing CLI `action` command as a real subprocess
with the exact JSON envelope. It checks successful requeue, reviewer feedback,
preserved historical delivery fields and an empty execution history.

The root integrator ran the final service plus MCP/CLI modules with the real SDK
and subprocess surface: **8/8 tests passed in 3.003 s**, recorded in
`.agentrelay/v016-focused-final.log`. A separate real-worker/service fixture also
passed **7/7 in 1.207 s** and confirmed that feedback remains available outside
more than 20 recent events. These are root results rather than executions in the
specialist sandbox. The specialist did not change TEMP or claim a local protocol
pass.

Root also exercised two real MCP review returns in isolated pilots: each AR-0009
moved from `review` revision 3 to `queued` revision 4 while retaining evidence
and checkpoint, with other tickets and runs unchanged. Subsequent correction
work remains a separate workflow and is not implied by that return result.

## Preserved limits

Reason length, lifecycle, CAS, identity independence and atomic state invariants
remain service-authoritative. The interface does not add a browser, UI or HTTP
control claim and does not mutate report files. A queued result can remain
blocked by its graph and still requires an authorized ordinary claim before
work resumes.
