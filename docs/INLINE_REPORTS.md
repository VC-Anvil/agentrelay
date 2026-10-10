# Inline reports in retained worker results

Worker protocol `agentrelay.worker.v1` can optionally include the exact report
text in `artifact_markdown`. This lets an authorized MCP reviewer inspect one
captured delivery through its existing database connection when it has no access
to the worker's local artifact directory.

This is an additive field in the retained proposal:

```json
{
  "outcome": "submit",
  "summary": "Document review delivered",
  "evidence": [
    {"kind": "report", "label": "Review report", "uri": "local://report.md"}
  ],
  "artifact_markdown": "# Review\n\nExact bounded report text.\n"
}
```

When present, `artifact_markdown` is a string that is nonempty after a whitespace
check and at most 262,144 bytes when encoded as strict UTF-8. AgentRelay preserves
the exact text, including Unicode, line endings, leading/trailing whitespace and
the presence or absence of a final newline. It does not trim or normalize the
stored content. Oversized or invalid content fails explicitly; it is never
truncated or silently omitted.

Provider adapters write the same UTF-8 bytes to their report artifact and retain
the exact text in the normalized proposal. The adjacent receipt's
`report_sha256` covers those exact written bytes. A receipt hash is integrity
metadata rather than proof of authorship or review quality.

## Reading the report

No new command or MCP tool is needed. Read one explicitly selected retained
proposal with the existing CLI:

```console
agentrelay run-result --db .agentrelay/workspace.sqlite --run RUN_ID
```

Or call the existing read-only MCP tool:

```json
{
  "name": "get_run_result",
  "arguments": {"run_id": "RUN_ID"}
}
```

Both surfaces return the existing run-result envelope. When the captured
proposal supplied a report, its exact text is at
`result.artifact_markdown`. The reader uses only the persisted database value:
it does not open the report URI, worker directory, logs or any other filesystem
path, and it does not construct an `ExecutionManager` or relaunch the worker.

Runs captured before this extension, or results whose protocol output omitted
the key, remain unchanged: an existing result object has no
`artifact_markdown` key, and a legacy run without a retained proposal still has
`result: null`. AgentRelay does not infer text from `summary` or `evidence`,
dereference a URI, or backfill historical rows.

`list_runs`, ticket context, state and bulk export do not include inline report
content. This keeps normal coordination responses bounded. Reviewers explicitly
select a run ID with `get_run_result` or `run-result` before receiving the full
bounded proposal.

## Review boundary

Inline text is worker-supplied proposal content. It does not prove that cited
files exist, that claims are correct, that the report was independently reviewed,
or that the ticket meets acceptance. A `submit` result still requires evidence,
and an independent reviewer must compare the delivery with current ticket
context and acceptance. Run status and the presence of report text never mean
the proposal was applied or accepted.

Worker stdout remains capped at 1 MiB, normalized strict JSON at 4 MiB and result
nesting at 64 containers. The inline report has its own 256 KiB UTF-8 limit. A
malformed persisted optional field produces a controlled read error rather than
a replacement value. Database reads can still perform normal recognized-schema
migrations through Store; they do not mutate ticket state or execution history.
