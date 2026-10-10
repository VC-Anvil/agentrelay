# CLI database guard interface report

## Result

The CLI now separates commands that explicitly initialize a new project from commands that require an existing recognized AgentRelay database. `serve` and `mcp` may initialize a missing path. `action` may do so only for `create_ticket`, `create_plan` and `create_profile`. `run`, unknown actions and all other actions use the existing read-side preflight before any parent directory or `Store` is created.

MCP actor validation moved ahead of database selection. Action JSON and its nonempty actor declaration remain bounded and validated before database selection, including excessive parser nesting. Cross-review initially found that a whitespace-only action actor reached `Store` and initialized a new database before domain validation; the final CLI applies Store's existing nonempty rule first, without imposing any additional actor format. The CLI no longer resolves a path or creates its parent before the central guard: home expansion, read preflight, `Store` construction and explicit demo seeding share one diagnostic boundary for `DomainError`, `OSError`, `RuntimeError` and `sqlite3.Error`, producing a concise `Database:` error without a traceback. Existing query and backup behavior remains unchanged.

## Reproduction and validation

The supplied isolated reproduction `.agentrelay/foreign-action-repro.json` records the original failure: an action against a SQLite file containing only `sentinel` exited on a missing ticket only after adding the AgentRelay schema. Its database SHA-256 changed from `b28baa4c…` to `20b97bbb…`; the sentinel row survived but the foreign file was still mutated.

`tests/test_cli_database_guard.py` exercises the corrected command boundary through subprocesses. It covers foreign, zero-byte and corrupt files for `action`, `run`, `serve` and `mcp`; compares the foreign file hash and complete `sqlite_master` rows; checks concise errors; verifies that missing claim, unknown action and run paths create neither parent nor database; and proves that the three allowed creation actions initialize distinct new projects. It also verifies action-envelope and MCP-actor ordering, excessive JSON nesting and unavailable home expansion. In-process mocks stop `serve` and MCP immediately after initialization to confirm their authorized bootstrap without opening sockets, launching workers or contacting providers.

After the backend database guard and the actor-ordering correction were integrated, the final focused module completed with **7 tests passing and 1 symlink test skipped in 10.854 s**. The skip records Windows error 1314 because this account lacks symbolic-link creation privilege; it is not counted as a successful symlink check. Python compilation and `git diff --check` also completed without findings. The run used only disposable fixtures; its `TEMP`/`TMP` override selected a repository-local test directory because the sandbox does not grant general writes to the host temporary directory.

A targeted regression run of `tests.test_cli` and `tests.test_cli_readonly` completed **9 tests successfully**. The unrelated snapshot case failed while creating its source fixture with Windows error 5 inside the repository-local temporary override; no snapshot assertion or database behavior ran in that case, so it is recorded as an environmental failure rather than a pass.

## Limits

Recognized legacy databases still pass through normal `Store` initialization and migrations. The preflight does not make operational commands filesystem-read-only, authenticate database contents or close a hostile path-replacement race. No worker, provider, browser or network service was used by this package.
