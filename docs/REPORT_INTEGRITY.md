# Verify a saved worker report

AgentRelay can compare the bytes of a saved `report.md` with the SHA-256 recorded by its adjacent `receipt.json`:

```sh
agentrelay verify-report /absolute/artifact-directory
agentrelay verify-report /absolute/artifact-directory \
  --receipt-sha256 PREVIOUSLY_TRUSTED_RECEIPT_SHA256
```

The directory is explicit. The verifier reads only the fixed names `receipt.json` and `report.md` inside it. Paths such as `cwd`, `artifacts_dir`, evidence URIs or other metadata in the receipt are never followed. The command does not select a project database, create `.agentrelay`, start a worker, use the network or mutate either file.

The optional `--receipt-sha256` is useful only when its value was obtained earlier through a trusted channel and retained separately. Do not calculate it from the same receipt whose replacement you are trying to detect. Without that external anchor, a matching report and receipt show internal byte consistency, but coordinated replacement of both files is not detectable.

The JSON response has this shape:

```json
{
  "schema_version": 1,
  "directory": "/absolute/artifact-directory",
  "status": "unchanged",
  "reason": null,
  "expected_report_sha256": "...",
  "actual_report_sha256": "...",
  "receipt_sha256": "...",
  "expected_receipt_sha256": "...",
  "receipt_matches_expected": true
}
```

Values that cannot be established are `null`. Status means:

- `unchanged`: the current report bytes match the hash stored in the receipt, and the optional receipt anchor also matches when supplied.
- `modified`: both report hashes are known and differ.
- `missing`: a readable receipt contains the historical report hash, but local `report.md` is absent.
- `uncheckable`: the receipt is absent or unreadable, has no usable historical report hash, the optional receipt anchor differs, or safe reading cannot complete.

Exit code 0 is reserved for `unchanged`. `modified`, `missing` and `uncheckable` return 2 with the JSON response. Invalid directory selection or a malformed receipt anchor returns 1 with a diagnostic and no traceback. Argparse usage errors, such as omitting the directory, retain argparse's exit code 2 and do not emit result JSON.

Old receipts without `report_sha256` remain `uncheckable`. The verifier does not hash the current report and write that value into historical evidence, and it does not reconstruct a baseline from ticket text, logs or adjacent indices. Preserve the original files for independent review.

SHA-256 comparison establishes only whether the checked bytes match the recorded bytes. An unsigned receipt does not prove author identity, provider execution, declared model, report correctness, evidence quality or acceptance. Do not automatically follow report or receipt URIs found in tickets; select and authorize the local directory explicitly. AgentRelay intentionally exposes no MCP tool for this operation because the ticket server should not gain general filesystem selection authority.
