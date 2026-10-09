# Report integrity CLI interface

## Implementation

`verify-report DIRECTORY [--receipt-sha256 HASH]` is parsed and dispatched before default database resolution or `Store` initialization. It delegates to `agentrelay.report_integrity.verify_report`, prints the complete UTF-8 JSON response and maps `unchanged` to exit 0 and every other machine-readable state to exit 2. Invalid selection and malformed anchors return exit 1 with a concise diagnostic.

No MCP tool was added. The existing ticket MCP server therefore gains no new path-selection or filesystem-reading authority.

## Safety and interpretation

The backend reads only `receipt.json` and `report.md` under the explicit directory and ignores paths embedded in receipt metadata. A mismatched optional receipt anchor stops before reading the report. The anchor must be a previously trusted value kept outside the candidate receipt; deriving it from that same file would add no replacement detection.

Legacy receipts without a historical `report_sha256` remain `uncheckable`; neither the service nor CLI updates them or invents a baseline. A matching unsigned receipt and report establish byte consistency only. They do not attest author, model, provider, factual quality or acceptance.

## Verification

`tests/test_cli_report_integrity.py` exercises UTF-8 output, all four states, optional anchor success and mismatch, exit codes, legacy, malformed and missing receipts, absent reports, invalid directory/anchor/usage, ignored external metadata and an unchanged file tree. Every subprocess runs from a directory without a default AgentRelay database and verifies that `.agentrelay` is not created. The final run completed with **4/4 tests passing in 1.954 s**.

The sandbox's ordinary system TEMP denied fixture writes. The successful run changed only `TEMP` and `TMP` for that command to `tests/.tmp-report-integrity`; the test source still uses `tempfile.TemporaryDirectory()` without a fixed directory, and the temporary tree was removed afterward. No database, MCP server, worker, provider, browser or network call belongs to this package.

The integrator's final normal-environment suite completed with **146 tests: 143 passing and 3 Windows symlink skips in 45.684 s**. The final log is `.agentrelay/v011-tests.log`. The retained first-run log documents one obsolete positional-evidence expectation, corrected by selecting evidence by kind while preserving exact-content checks and adding receipt-hash verification.
