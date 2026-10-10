# Database selection and initialization

AgentRelay distinguishes an explicit project bootstrap from a command that must target an existing project. This prevents a misspelled path or an unrelated SQLite file from silently acquiring AgentRelay tables.

## Commands that may initialize a path

`serve` and `mcp` may initialize a database only when the selected path does not yet exist. The generic `action` command has the same permission for these explicit creation actions:

- `create_ticket`
- `create_plan`
- `create_profile`
- `apply_ticket_action` only when its validated inner action is `create_ticket`

The wrapper's exact structure, key and bounded JSON intent are checked before
database initialization. Its inner ticket fields are validated by the domain
after opening the selected database. A rejected creation can therefore leave an
initialized database, as with an ordinary creation action. Wrapping a comment or
another non-creation operation cannot bootstrap a project.

The action envelope and its nonempty actor declaration are validated before database selection. An invalid MCP actor is also rejected before resolving or creating its database. Initialization creates the parent directory when needed and installs the normal AgentRelay schema. It does not seed demo content unless `serve --demo` was explicitly selected, launch a worker, or authorize any action contained in a payload.

If the selected path already exists, even these startup commands require it to be a recognizable AgentRelay database. An existing zero-byte file, empty SQLite database, unrelated or incomplete schema, corrupt file, directory, or a set of similarly named views is rejected before AgentRelay schema initialization. A recognizable legacy AgentRelay database remains eligible for the normal idempotent `Store` migrations.

## Commands that require an existing project

`run` and every `action` other than the creation cases above require an existing recognizable AgentRelay database. This includes an unknown action name: it cannot create a project as a side effect before the domain reports the unknown action. A missing database path fails without creating its parent directories.

The query and backup commands keep the same existing-database preflight:

- `context`
- `history`
- `runs`
- `run-result`
- `export`
- `backup`

`backup` does not create its output when selection of the input database fails. Once a recognized database has been selected, commands construct `Store` normally, so idempotent migrations can still occur. This policy is not a filesystem read-only promise.

## Diagnostics and limits

Database selection and opening failures return a concise message on stderr with a nonzero exit code rather than a Python traceback. The CLI catches domain validation failures, filesystem errors and SQLite errors at this boundary.

The check prevents ordinary typo and foreign-file mutations. It does not authenticate a database and is not a defense against a hostile process replacing a path between validation and opening. Use trusted local paths and normal filesystem permissions.
