# Inline reports interface report

## Interface behavior

The existing `get_run_result(run_id)` MCP tool and `run-result --db ... --run ...`
CLI command expose `result.artifact_markdown` exactly as persisted by the v0.17
backend. No command, tool, envelope, schema table, filesystem reader or execution
surface was added by this interface package.

Absence remains backward compatible: a retained result created without the key
does not gain one, while a legacy run with no captured proposal remains
`result: null`. Reading either shape does not infer or backfill report content.

## Interface coverage

`tests/test_mcp_inline_reports.py` creates a recognized database fixture with an
exact persisted report containing Unicode, mixed CRLF/LF, significant spaces and
no final newline. It deletes the source report before reading. A real SDK/stdio
session retrieves the exact text with the existing read-only `get_run_result`,
and a real CLI subprocess retrieves the same bytes after JSON decoding. Both
paths also verify a result object without the key and a legacy null result.

The test compares all ticket, profile, dependency, event, metadata and execution
rows before and after both readers. It confirms the deleted report path remains
absent, so success depends on persisted JSON rather than URI or artifact access.
It also confirms that no new MCP inline-report tool is exposed.

## Verification status and limits

The tests require Python temporary directories and the optional MCP SDK. The
specialist sandbox has previously denied fixture creation under its virtual TEMP;
the package does not redirect TEMP to bypass that restriction. The root
integrator ran both interface tests in its normal environment as part of the
first nine-test focal run: the real MCP SDK and CLI subprocess cases both passed
and returned exact text after the report file was removed. Three simultaneous
backend fixture failures in that initial run were unrelated to these two cases
and are not presented here as interface passes. A later corrected backend
oversize case passed 1/1. The root's final integration run completed 237 tests:
230 passed and seven Windows symlink cases were skipped, in 70.994 seconds.

Validation of the 262,144-byte boundary, malformed stored values, adapter file
and receipt parity, backup, conflicts and the real custom worker subprocess
belongs to the backend service suite. These interface tests establish exact
exposure and read isolation; they do not claim report truth, provider identity,
independent acceptance, browser control or filesystem sandboxing beyond the
selected database query.
