# Connect an existing agent through MCP

AgentRelay exposes tickets to an agent hosted by an MCP-compatible application.
Your host runs the agent; the AgentRelay MCP process supplies tools and persistent
context. Configuring MCP does not configure or launch an AgentRelay worker.

## Install in a chosen Python environment

Use Python 3.11 or newer. From the root of this repository, install the package
and its optional MCP dependency in the environment your host will use:

```sh
python -m pip install -e ".[mcp]"
```

Here `python` must be that environment's interpreter. You can use an existing
environment or create a new virtual environment first. No global client settings
are changed by this command. The examples below use placeholder absolute paths;
replace them with your own interpreter and project database.

## Choose the project database

For a project already open in the board, use that board's exact database path.
Take it from the server's `--db` argument or its workspace registry; the ticket
context itself does not return that filesystem path.
Each database is a separate project. Connecting to another path can give the agent
an empty board even though your web board contains tickets.

To start a new project explicitly, run the installed package from your terminal:

```sh
python -m agentrelay serve --db /absolute/project/.agentrelay/workspace.sqlite
```

The normal address is `http://127.0.0.1:8787`. If a server already manages the
chosen project, keep using it; a second web server is unnecessary for MCP. The
MCP connection uses the SQLite database directly, not the web server's port.
Use the demo database only when you intentionally want fictional tickets.

Both `serve` and `mcp` can initialize a new database path. Check the path before
connecting. Existing unrelated or corrupt SQLite files are rejected; recognized
AgentRelay databases follow normal migrations. See [database selection](DATABASES.md).

## Add a stdio entry to your host

This is an example for hosts whose configuration uses `mcpServers`. Other hosts
have their own configuration format. Add it explicitly through your chosen host:

```json
{
  "mcpServers": {
    "agentrelay": {
      "command": "/absolute/venv/bin/python",
      "args": [
        "-X", "utf8", "-m", "agentrelay", "mcp",
        "--db", "/absolute/project/.agentrelay/workspace.sqlite",
        "--actor", "agent:worker-01"
      ]
    }
  }
}
```

On Windows, use the environment's absolute `Scripts/python.exe` path, for example
`C:/path/to/venv/Scripts/python.exe`, and a database path such as
`D:/path/to/project/.agentrelay/workspace.sqlite`. Forward slashes are valid in
these JSON strings. Installing the package in that environment means no `cwd`
entry is needed. An uninstalled source checkout instead requires that the host
start Python in the repository directory; not every host supports a `cwd` option.

Give each worker or reviewer connection a different stable `agent:<name>` actor.
The actor is fixed at process startup. It is an audit identity for trusted local
collaborators, not authentication against someone who can access the database.
Reviewer and author identities must differ for acceptance.

## Verify the connection before changing work

1. Let the host discover the server's tools. The server name is `AgentRelay`.
2. Call `list_tickets` with `{"limit": 5}`. An empty list is valid for a new project.
3. For an ID returned by that call, use `get_ticket_context` with
   `{"ticket_id": "AR-0001"}`, substituting the actual ID.
4. Confirm that the title and current revision match the board you meant to
   connect, and that its selected database matches the configured `--db` path.
   Read the acceptance criteria and dependencies before any mutation.

These checks do not claim tickets or start workers. For a first demonstration,
create a small ticket in the chosen board with a concrete output and acceptance
criteria, then let the connected agent read it. Model and effort recommendations
do not establish which model your host is actually running.

The agent can then claim authorized ready work, save checkpoints, request help
and submit evidence. A separate reviewer checks the result and accepts it or
requests changes. Delivery is not acceptance. The [companion skill](../skills/agentrelay-work/SKILL.md)
describes this workflow; it is not installed into your host automatically.

For a complete reproducible example without a model, run the
[deterministic handoff](HANDOFF_EXAMPLE.md). To let AgentRelay launch a process
itself, use the separate [worker setup](EXECUTION.md).

## Common configuration mistakes

| Symptom | Check |
|---|---|
| `No module named agentrelay` | Install the checkout with the same interpreter named in `command`. |
| Missing MCP dependency | Install `.[mcp]` in that interpreter's environment. |
| Unexpected empty board | Compare the absolute `--db` path with the board's selected project. |
| No tasks can be claimed | Read their status, dependencies and acceptance; backlog is still a proposal. |
| An action conflicts | Read fresh context before deciding a new action; do not silently overwrite it. |

Keep stdio reserved for MCP messages; do not add shell commands that print banners
before starting the process. Ticket lists are paginated and context includes a
bounded recent history. See the [API contract](CONTRACT.md), [history](HISTORY.md)
and [uncertain-action recovery](ACTION_RECEIPT_LOOKUP.md) before building a client
that automates mutations.
