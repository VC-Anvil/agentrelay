# Closed parent scope implementation report

The host reproduction allowed a cancelled child to be detached from a completed
parent. The parent remained accepted at the same revision while its current
context lost that child.

`Store._update_ticket` now checks the normalized `parent_id` before writing. If
the relationship changes and the old parent is `done` or `cancelled`, the action
returns 409 without changing fields, dependencies or audit events. This covers
both detaching and moving to another parent. Existing destination validation is
unchanged, including its rejection of an explicitly unchanged closed-parent ID.

Open parents can still be reorganized, and explicitly reopening the old parent
permits a later membership change. Other edits to an editable child remain
possible when `parent_id` is omitted. A child can be reopened while retaining
its relationship to an accepted parent; later detaching it is still rejected.
This patch adds neither parent revision propagation nor automatic invalidation
of historical acceptance when child or dependency status evolves.

`tests/test_closed_parent_scope.py` contains seven domain tests: closed-source
detach/move with rollback, open-source moves, explicit parent reopening,
unrelated edits, historical child reopening, unchanged destination protection
and stale child revision rejection.

The author's first attempt to execute six initial cases could not open SQLite
under its restricted temporary directory; cleanup also received a permission
error. No functional assertions ran there, and no alternative location was
used to bypass the restriction. The host subsequently ran the final seven domain
tests and two protocol tests successfully. The integrator's measured results
and release limits are recorded in [validation](VALIDATION_CLOSED_PARENT_SCOPE.md).
