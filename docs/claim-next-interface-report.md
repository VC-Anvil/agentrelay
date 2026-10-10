# Scoped claim interfaces

## MCP integration

`claim_next_ticket(request_id, candidates, actual_model, actual_effort)` binds `assignee` to the MCP actor and sends exactly the five backend data fields. It uses a dedicated `ToolAnnotations` instance with `idempotentHint=True`; ordinary write tools keep their existing non-idempotent annotation. The tool documentation requires reviewed, authorized contexts for every candidate, preserves ordinary `claim_ticket` for a user-selected task and treats exact replay as a historical receipt that requires fresh context.

No CLI parser command was added. The existing bounded JSON `action` envelope reaches the same Store action and keeps its explicit database and actor boundary.

## Tests

`tests/test_cli_claim_next.py` exercises the installed-style generic CLI envelope. It verifies priority ordering, every skip reason, exact replay, one durable receipt and one claim event, explicit scope, unknown-ticket rollback, actor/payload conflicts, strict revision types and the shared request-ID namespace with `create_plan` in both directions. After the cross-action guard was integrated, the final run completed with **3/3 tests passing in 7.013 s**.

`tests/test_mcp_claim_next.py` opens two real SDK/stdio MCP connections with distinct actors and request IDs against one database. Both connections fetch current context for both candidates before concurrent claims. The calls must claim distinct tickets, leave an urgent out-of-scope ticket untouched and emit only two claim events; the second transaction reports the first claimed candidate as `stale_revision` because claiming increments its revision. The test also checks the dedicated idempotent annotation, exact historical replay, actor/payload conflicts and invalid revisions.

No SDK mock, worker, provider, browser or network call is used. My local MCP run stalled in the sandbox's stdio transport and was interrupted after 30 seconds, so it is not recorded as passing. The integrator ran it with the real SDK/stdio transport in the normal environment: **1/1 test passing in 2.002 s** (`.agentrelay/v012-mcp-focused.log`).
