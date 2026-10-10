# Historical source checks

AgentRelay can compare a verified input snapshot with an explicitly selected current project root and attach the observation to an existing ticket. The result is advisory, point-in-time context. It does not reopen, queue, claim, block, complete or accept the ticket, and it does not start a worker.

## Record a local comparison

Run the host-only command with every selection explicit:

```sh
python -m agentrelay check-sources \
  --db /absolute/project.sqlite \
  --ticket AR-0001 \
  --expected-revision 4 \
  --snapshot /absolute/captured-inputs \
  --expected-snapshot-id sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef \
  --root /absolute/current-project \
  --request-id source-check-20261010-01 \
  --actor agent:local-reviewer
```

`--db` must identify an existing recognized AgentRelay database. The command never initializes a database. The ticket must exist at the supplied positive revision. Request ID and actor are exact nonempty declarations up to 128 characters without surrounding whitespace. The expected snapshot ID must be lowercase `sha256:` plus 64 hexadecimal characters.

Snapshot and root selections are expanded and made lexically absolute for the durable intent without resolving links. The existing snapshot verifier and comparator decide whether those paths are safe. The manifest's historical `source_root`, ticket text and evidence URIs never select a path. The expected snapshot ID is checked after snapshot verification and before inspecting the current root.

Success prints one compact receipt:

```json
{
  "schema_version": 1,
  "check_id": 12,
  "request_id": "source-check-20261010-01",
  "ticket_id": "AR-0001",
  "ticket_revision": 4,
  "actor": "agent:local-reviewer",
  "method": "local_compare_snapshot_v1",
  "snapshot_id": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "report_sha256": "89abcdef0123456789abcdef0123456789abcdef0123456789abcdef01234567",
  "summary": {
    "total": 4,
    "unchanged": 3,
    "modified": 1,
    "missing": 0,
    "uncheckable": 0
  },
  "checked_at": "2026-10-10T12:00:00.000Z",
  "recorded_at": "2026-10-10T12:00:00.010Z"
}
```

Exit code **0** means the observation was recorded or an exact historical receipt was recovered. It remains 0 when the summary contains modified, missing or uncheckable files; inspect the counters. Selection, comparison, revision and persistence failures return 1 with a concise diagnostic and no success JSON. Argparse usage errors return 2.

The comparison keeps the existing snapshot limits: at most 64 captured files, 1 MiB per file and 8 MiB total. The complete canonical UTF-8 report is limited to 1 MiB. Its SHA-256 covers the exact stored canonical JSON. No source bytes are stored.

## Retry semantics

The request ID shares one database-wide namespace with plan creation and scoped next-ticket claims. Retry a lost response with the exact same actor, ticket, revision, expected snapshot ID and literal expanded snapshot/root selections. After the database lookup, AgentRelay returns the original receipt before reading the ticket or snapshot/source paths, even if the ticket changed or either path disappeared. It creates no second event or measurement.

Changing any bound intent field, actor or action for an existing request ID returns 409 before comparison. A new measurement always needs a new request ID. If the ticket changes while the comparison runs, the final revision check rolls back the source-check row and event; fetch current context and decide whether to perform a new check with a new ID.

Replay is historical recovery, not a fresh check. The receipt never changes when sources or ticket state change later.

## Read stored observations

List compact receipts for one ticket, newest first:

```sh
python -m agentrelay source-checks --db /absolute/project.sqlite --ticket AR-0001 --limit 20
python -m agentrelay source-checks --db /absolute/project.sqlite --ticket AR-0001 --limit 20 --before-id 12
```

The result has exact page fields `checks`, `ticket_id`, `total`, `count`, `limit` and `next_before_id`. A non-null cursor means older records exist. Read one complete stored report explicitly:

```sh
python -m agentrelay source-check --db /absolute/project.sqlite --check-id 12
```

The detail response adds `report` to the receipt. It validates the stored report size, canonical encoding, SHA-256, snapshot ID and summary. Corruption produces a controlled error. Lists, state and export never contain full reports. SQLite backup preserves the complete source-check table and reports.

MCP exposes only `list_source_checks(ticket_id, limit, before_id)` and `get_source_check(check_id)`. Both are read-only and accept IDs/cursors, never filesystem paths or supplied reports. They read records already stored by the local command and cannot run a comparison. `get_ticket_context` includes up to three newest compact receipts and a page descriptor. Its derived `ticket_revision_matches_now` flag only compares ticket revisions; it says nothing about current source bytes.

## Review meaning

An unchanged result establishes byte equality only at `checked_at`. A finding asks a reviewer to determine which conclusion, if any, depended on that file. Missing and uncheckable never mean unchanged. Earlier acceptance and evidence remain historical facts.

For example, a changed Dirt Riot raw document does not prove that a derived `focused-v2` excerpt delivered earlier changed. The raw snapshot and the derived selection are different inputs. Review or regenerate the exact derived input only when that distinction matters; never silently substitute the raw bundle or reopen work automatically.

The comparison is not a watcher, an atomic multi-file filesystem snapshot, proof of authorship or proof of correctness. Normal Store migrations may occur when a recognized database opens. The path checks reduce accidental unsafe reads but do not defend against a hostile process replacing paths concurrently.
