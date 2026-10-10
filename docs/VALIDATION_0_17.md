# AgentRelay 0.17 — report review through the database connection

Date: 2026-10-10 (Europe/Madrid). Windows, Python 3.12.14, MCP SDK 1.30.0.
Previous release: [independent correction requests](VALIDATION_0_16.md).

## Observed need and change

The actual documentary reviews in 0.16 exposed a report URI through MCP, but
not the report text. A reviewer without access to the worker's artifact directory
could retrieve the proposal yet could not read its delivered report through
that connection. The new optional `artifact_markdown` field retains future
worker report text in the existing captured result.

Text is exact strict UTF-8, nonblank and bounded to 262144 bytes. The adapter
writes matching bytes to its report file, avoiding Windows newline conversion;
the receipt hash covers those bytes. Existing total stdout, storage and nesting
limits remain. No new filesystem tool, table, migration, report backfill or
implicit execution was added. [Protocol and retrieval](INLINE_REPORTS.md).

## Local verification

The full suite ran **237 tests: 230 passed, seven Windows symlink tests skipped**,
in 70.994 seconds. Service tests cover Unicode and newline fidelity, exact byte
limits, invalid persisted text, real subprocess capture, conflict retention,
backup and successful retrieval after removing the external report artifact.
Actual SDK sessions and CLI subprocesses verify exact text, absent legacy fields,
legacy null proposals and unchanged ticket/execution tables.

The first focused run had three fixture failures: a worker helper unpacked five
arguments into four variables. Correcting the fixture restored all seven service
tests (1.482 seconds); its two SDK/CLI tests had already passed. Independent review
then found the oversize fixture failed early for missing evidence. It now supplies
valid evidence and asserts the specific report-size rejection; the corrected
focused case passed in 0.319 seconds and is included in the final full suite.
Neither fixture issue was presented as a product success or hidden by omission.

Both packages received independent static review. A suggested removal of the
provider schema's required field was rejected: its structured-output contract is
separate from the optional normalized worker field and already required report
text for submission. Specialist sandbox restrictions prevented their temporary
SQLite fixtures; the executed results above belong to the root's normal local
environment. The companion skill passed structural validation.

## Real Valley documentary delivery

A configured Codex worker (`gpt-6-sol`, `high`, declared settings rather than
provider attestation) received only an authorized frozen bundle: two historical
Valley documents, historical backlog proposals and provenance. No current game
source was consulted or changed. The worker produced a 4548-byte report in
37.779 seconds and submitted it for independent documentary review.

An actual reviewer SDK connection retrieved the complete text through
`get_run_result`. A separate host integrity check confirmed it matched the file
and receipt SHA-256:
`ae1feaf280c6a3f48ff078593e3228e53a80685dc34eea1f24110e86a2f0d1ff`.
The online database backup returned an identical complete result. Reading did not
mutate state; all pre-existing tickets and execution records remained unchanged.
The distinction matters: database retrieval and separate filesystem integrity
checking are different operations and neither alone establishes report quality.

An independent reviewer then checked the MCP-returned text against the four
frozen inputs and all acceptance criteria. It found no documentary defects:
the six proposals, exact snapshot IDs, attributed figures, historical scope and
single conditional next step were supported. A separate reviewer MCP session
accepted the documentary ticket at revision 4, preserving other tickets and all
execution records. This does not approve the game or reactivate its proposals.

The live five-project server restarted with all database rows preserved and no
active workers. Package verification compares archive/source/skill bytes and
exercises report retention from an isolated wheel installation. Exact-head CI
covers Windows/Linux and Python 3.11/3.12; publication records its result.
Author reports: [service](inline-reports-service-report.md),
[interfaces](inline-reports-interface-report.md).

## Limits

Inline reports are untrusted worker-supplied evidence, not instructions or proof
of correctness. Review still needs current ticket context and independent
acceptance. Text describes the captured delivery; the external file can change
later. Legacy responses remain unchanged and do not imply an empty report.
No claim of token savings, current game verification, ROM approval, hardware
validation, audio review or fresh browser visual QA is made.
