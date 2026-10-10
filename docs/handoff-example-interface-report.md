# Reproducible handoff documentation report

## Scope

This package documents the deterministic checkout example implemented in
`examples/handoff_demo.py`. It changes documentation only: no runtime, test,
database, version, browser, provider or game file was modified by this package.

## Delivered documentation

- `HANDOFF_EXAMPLE.md` gives the exact editable-install and
  `python examples/handoff_demo.py --output NEW_DIRECTORY` invocation. It states
  that the output must not exist and that the example confines its database,
  worker configuration, diagnostics, summary, result and backup to that new
  directory.
- The guide follows the implemented deterministic flow: a local controller
  requests help through `Store`; urgent priority is inherited; the first helper
  report omits `MHz` from the simulated value `23`; a distinct simulated reviewer
  identity returns it with the exact reason; the controller compares each
  retained report with fixed expected content before its review action; the
  corrected child is explicitly completed; the parent remains blocked until its
  owner requeues it; the parent worker checks accepted child context; a final
  explicit review completes it; and an online backup preserves all three
  retained inline reports.
- The documented `result.json` shape matches the implementation:
  `schema_version`, `simulation`, five absolute paths, terminal parent/help
  ticket records, three run IDs/statuses/report hashes, and review metadata.
  It distinguishes the overall `report.md` from the exact worker reports held in
  SQLite `result_json` and recovered through `run-result`/`get_run_result`.
- `EXECUTION.md` now limits split children to `title` plus optional
  `description`, `profile_id` and `acceptance`, notes inherited priority, links
  to the deterministic handoff example, and links retained
  `artifact_markdown` to the inline-report contract.

## Review against the implementation

The final documentation was checked statically against the handoff contract,
`Store` help/review/transition behavior, `ExecutionManager` protocol handling,
the example's fixed worker reports and its `result.json` construction. The guide
does not call the fixture's audit identities independent humans or models:
the same local controller simulates them and verifies fixed responses. It also
states that `ExecutionManager` does not approve work; the demonstration makes
explicit `complete_ticket` calls under a different audit identity with all
acceptance criteria.

No subprocess fixture or full suite was run by this documentation author. The
root integrator later reported both focused tests passing (2/2 in 1.373 seconds)
and a successful direct invocation retained under
`.agentrelay/handoff-example-v0171/`. Inspection of its readable `result.json`
and `report.md` confirmed the documented schema, terminal states, actor strings,
three submitted runs, exact review reason and report hashes. Execution and timing
are attributed to the root integrator.

## Limits

This example demonstrates local AgentRelay mechanics under fixed inputs. It is
not inference, provider attestation, a second reviewer, game evidence or product
approval. Its online backup contains database state and retained proposals, not
external configuration or diagnostic files. Existing output paths are preserved
by refusal rather than overwritten or cleaned up.
