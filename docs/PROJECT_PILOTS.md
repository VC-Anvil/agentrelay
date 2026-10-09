# Working with active projects

An agent needs the right project, current decisions and the exact evidence being
reviewed. Historical status pages can contain both an old pause and a subsequent
authorization. A report against one candidate cannot certify a different one.

Keep one explicit database per project. Use frozen, bounded inputs for documentary
reviews while another team continues changing the source project. This does not
replace the project's integration owner, native tests or human acceptance.

## Capture and verify inputs

Create the destination's parent directory first. Select individual relative files;
globs and recursive directory copying are deliberately unsupported.

```sh
agentrelay snapshot --root /absolute/source-project --file docs/current-state.md --file docs/candidate-review.md --output /absolute/review-inputs/candidate-01
agentrelay verify-snapshot /absolute/review-inputs/candidate-01
```

The new directory contains exact file bytes under `files/` and a `manifest.json`
with source paths, capture time, byte counts, per-file SHA-256 and a stable content
ID. Existing destinations are refused. Limits are 64 files, 1 MiB per file and
8 MiB total. The destination must be outside the source project. Verification
reads the bundle itself, never the original paths in its manifest.

A capture detects individual file changes during reading; it is not an atomic
multi-file snapshot. For a release requiring atomic provenance, use a frozen
commit/archive first. Hashes detect accidental modification, not authenticity:
someone who can edit the bundle can also replace its manifest.

Point the read-only worker's cwd at this bundle and set `--artifacts-dir` in its
adapter command to an output base outside the bundle. Put the bundle ID, candidate,
task scope and acceptance in the ticket. Ask the worker to distinguish claims in
documents from tests it actually ran. A text review cannot approve gameplay,
artwork, audio or hardware behavior.

For text-only workers or hosts where file tools are unavailable, explicitly add
`--input-snapshot /absolute/review-inputs/candidate-01` to the adapter command.
The host verifies the snapshot before contacting the provider and supplies its
UTF-8 text as `context.input_snapshot`. The enriched context is limited to 512 KiB;
binary data, corruption and excess size fail without a model call. Nothing is
silently truncated. The receipt records the snapshot ID and exact manifest hash.
The model must distinguish host verification from checks it performed itself.
Use this only for inputs authorized for that configured provider. Keep the worker
sandbox unchanged; supplying text does not grant tools additional permissions.

When a source includes a long history or large data payloads, prepare an explicit
selection with original hashes, selected fields/line ranges and omissions recorded.
Keep the original snapshot. Such a selection is a derived document, not a byte-for-byte
copy of the entire source. Smaller text is not evidence of token or quota savings.

## One board, multiple projects

Register existing databases in a trusted local JSON file:

```json
{
  "default_workspace_id": "alpha",
  "workspaces": [
    {"id": "alpha", "name": "Project Alpha", "db": "/absolute/alpha/workspace.sqlite"},
    {"id": "beta", "name": "Project Beta", "db": "/absolute/beta/workspace.sqlite", "workers": "/absolute/beta/workers.json"}
  ]
}
```

```sh
agentrelay serve --workspaces /absolute/workspaces.json --port 8787
```

Windows: `Start-AgentRelay.ps1 -Workspaces /absolute/workspaces.json`.
Relative database/worker paths resolve from the registry file. Up to 16 projects
are supported; duplicate IDs/databases, missing databases and unrelated SQLite
files are rejected. Initialize a new project with the normal single-project CLI
before registering it. Registry mode cannot be mixed with `--db`, `--demo` or
`--workers`; each optional worker config belongs to its own entry.

The board shows the selected project and database. API calls select a registered
ID using `X-AgentRelay-Workspace`; the browser cannot supply a database path.
Selection is explicit for multi-project requests, so the same `AR-0001` in two
databases cannot silently refer to the default project. Switching projects never
launches work; pending mutations block switching and dirty forms require a decision.
Each MCP connection still targets one explicit database. The registry does not add
cross-project dependencies or locks on shared source files.

## Coordinate without an MCP client

The CLI uses the same domain rules and optimistic revisions as the web and MCP.
Save an explicit request as UTF-8 JSON:

```json
{
  "action": "create_ticket",
  "data": {
    "title": "Reconcile candidate acceptance",
    "type": "review",
    "priority": "high",
    "profile_id": "sol",
    "description": "Review the frozen input bundle and distinguish superseded findings from unverified fixes.",
    "acceptance": ["Every open finding cites its input and candidate", "Historical fixes and remaining verification are distinguished"]
  }
}
```

```sh
agentrelay action --db /absolute/pilot.sqlite --actor agent:coordinator --input /absolute/request.json
agentrelay context --db /absolute/pilot.sqlite --ticket AR-0001
```

The input file contains exactly `action` and `data`; the audit identity comes from
the explicit CLI argument. This is a local identity declaration, not authentication.
The command does not execute commands found in the JSON. Use `run` separately to
launch a trusted configured worker. Read its actual report before reviewing the
ticket; creating follow-up tickets does not mean their implementation is done.

## Private pilot data

Use [atomic plan imports and source comparison](PLANS_AND_FRESHNESS.md) when a
review produces several related proposals or the source project continues changing.
Comparisons preserve earlier accepted evidence; they never automatically restart work.

Keep real source bundles, project databases, worker configs and reports under an
ignored local directory such as `.agentrelay/pilots/`. Public product evidence can
describe the workflow and aggregate results without publishing private inputs.
Back up the databases and artifact directories together; database backup alone
does not include the captured files or reports.
