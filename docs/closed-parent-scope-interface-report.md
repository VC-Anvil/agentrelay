# Closed parent scope interface report

## Scope

This package adds protocol-level regression coverage for the 0.17.2 rule that an
explicit `parent_id` change cannot detach or move a child from a `done` or
`cancelled` source parent. It changes no Store, CLI, MCP, public contract,
database or product file.

The rule is deliberately narrow. It does not add state propagation, invalidate
historical acceptance, block reopening a child that keeps the same association,
change dependency semantics, or define new behavior for an explicitly identical
`parent_id`.

## Coverage

`tests/test_mcp_closed_parent_scope.py` builds deterministic temporary databases
with separate fixture author and reviewer audit identities. Each fixture has a
completed parent, a cancelled child still associated with it, and another open
parent.

- The generic CLI action test attempts both `parent_id: null` and a move to the
  open parent. Each must exit 1 with a concise closed-parent diagnostic, no
  traceback or success JSON, and no change to tickets, profiles, events, runs or
  the demo marker. It then explicitly reopens the source parent to `queued` with
  a reason, reads the child's fresh revision, and moves the child successfully.
- The real MCP SDK test performs the same detach and move attempts through
  `update_ticket`. Each response must have `isError` set, expose the 409
  closed-parent error and leave domain state unchanged. It then reads fresh
  context, calls `transition_ticket` with a reason, rereads the child and confirms
  that the move succeeds.

The tests assert the public surfaces rather than duplicating Store internals.
They use ordinary optimistic revisions and verify that the failed operation does
not append an audit event or partially alter either hierarchy.

## Validation and limits

The test module was checked statically against the existing CLI action envelope,
MCP tool signatures and fixture lifecycle. It was not executed by this author
because the task reserves normal temporary SQLite/MCP execution for the host; a
later result must be attributed to the integrator that runs it.

Audit actor separation in these fixtures is not authentication or evidence of an
independent human/model review. The tests do not cover hostile database
replacement, HTTP, UI, child reopening, no-op parent assignments, parent revision
propagation, dependency evolution or any live database.
