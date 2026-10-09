# Import plans and check input freshness

An agent can propose a full task graph before anyone starts it. Import the
[example plan](../examples/plan.json) through the same service used by MCP and HTTP:

```sh
python -m agentrelay action --db /absolute/project.sqlite --actor agent:planner --input examples/plan.json
```

Each entry has a temporary `key`, plus normal ticket fields such as title,
description, priority, profile and acceptance. `parent_key` and `depends_on_keys`
refer to other entries in this request, including entries appearing later in the
array. Existing relations use `parent_id` and `depends_on`. The service validates
the complete graph and creates all tickets in one transaction. An invalid profile,
unknown reference or cycle leaves no partial tickets or audit events behind.

Entries default to **backlog**. An explicit `status: "queued"` makes an entry
eligible for later claiming when its dependencies permit. Import never launches a
worker, changes existing tasks or approves a result. A plan supports up to 64
entries. The example's parent and two children all remain proposals.

Keep the same `request_id`, payload and actor when retrying after a lost response.
AgentRelay returns the original result without duplicating the plan. Reusing that
ID for a different payload or actor is a conflict; use a new ID for a different
plan. The original result is a creation receipt: fetch current ticket context
before editing or claiming, because revisions may have changed since import.

MCP exposes `create_plan(request_id, tickets)`. HTTP clients send the equivalent
`create_plan` action to `/api/actions` with the selected workspace header.

## Check whether a captured source is still current

```sh
python -m agentrelay compare-snapshot /absolute/captured-inputs --root /absolute/current-project
```

The command verifies the captured bundle, then compares only the listed relative
paths under the root you explicitly provide. The manifest's historical
`source_root` is descriptive metadata; it never chooses a directory to read.
The JSON result contains the snapshot ID, current root, per-file expected/current
size and SHA-256, a reason, and counts for:

- `unchanged`: current bytes match the captured bytes.
- `modified`: current bytes differ.
- `missing`: the listed path is absent.
- `uncheckable`: the file could not be safely compared, including permissions,
  links, limits or changes during the read. This does not mean unchanged.

Exit codes are **0** when every file matches, **2** when any file differs, is
missing or cannot be checked, and **1** for an invalid snapshot or unusable root.
Usage errors also use argparse's exit code 2; distinguish them by the absence of
a comparison JSON result and the diagnostic on stderr.

A comparison is read-only and limited to the selected files. It does not detect
new unlisted files, guarantee a simultaneous view of a changing project, establish
authenticity of an unsigned manifest or prove the source is correct. Comparing a
derived excerpt against its staging directory only checks that excerpt; compare
the original capture with the live project to assess source drift.

A changed source does not erase an earlier review. Attach the comparison to the
ticket, decide which conclusions it affects, and recapture/review only the needed
inputs. Nothing automatically reopens completed tickets or restarts workers.
