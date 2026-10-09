# AgentRelay 0.11 — report integrity

Date: 2026-10-10 (Europe/Madrid). Windows, Python 3.12.14, MCP SDK 1.30.0.
Previous release: [execution discovery](VALIDATION_0_10.md).

## Evidence and change

The historical Dirt Riot delivery links its report, but its adjacent old receipt
has no `report_sha256`. Inspection of the other documentary pilots found the same
limitation. The current adapter already writes report hashes for new outputs;
without an input snapshot, however, it did not attach the receipt to its evidence.

New deliveries always expose the host receipt. The explicit local `verify-report`
command compares the two fixed artifact files and distinguishes unchanged,
modified, missing and uncheckable. It does not repair old receipts, select a path
from their metadata or change ticket state. A separately retained receipt hash
can detect replacement of that receipt before the report is read.

## Verification

The final suite ran **146 tests: 143 passed, three Windows symlink tests skipped**,
in 45.684 seconds. New service tests exercise the four states, optional anchors,
size limits, directory identities, nonregular/link/reparse paths, receipt changes,
malformed and deeply nested JSON, and unchanged files. A real symlink test could
not run on this Windows host; a separate injected reparse case tests rejection.

Four CLI subprocess tests cover Unicode, JSON states, exit codes, invalid
selection, external paths in metadata and absence of a default database. The
root adapter-to-CLI integration uses a mocked provider, writes a real Unicode
report and receipt without a snapshot, detects a changed report, and detects a
replaced receipt against its separately preserved original hash. No model call
is claimed by those fixtures.

The first full suite had one failure: an older test assumed the first evidence
entry was the report. It now selects by kind, still checks the report's exact
content and additionally checks its receipt hash. The original failed log was
preserved; the final full rerun passed. A separate reproduction showed that a
small receipt with 5,000 nested JSON arrays could raise `RecursionError`; this
now returns uncheckable and is covered by a regression test.

The local CLI inspected six historical artifact pairs across LEVIATHAN, Dirt Riot,
Valley of Rains and Cartógrafo Imposible. All six correctly returned uncheckable
because their receipts lack a report hash. Their bytes and all 33 pilot tickets,
profiles, events and run records remained unchanged. No historical baseline was
invented, no game source was changed and no game worker was relaunched.

Independent review corrected an example's `reason` value and checked the service,
interfaces, adapter change and stronger existing test. A Windows path assertion
checks an absolute path to the same directory rather than a particular short-name
alias. The companion skill passed its structural validator. Reports:
[service](report-integrity-service-report.md),
[interfaces](report-integrity-interface-report.md).

## Package and limits

Local wheel/source archive verification compares packaged files to working source
bytes. An isolated wheel installation exercises report/receipt delivery, unchanged
verification and subsequent modification detection alongside the existing worker
flow. Artifact hashes and logs remain with the local release artifacts. CI must
be checked for the exact published commit separately.

Equality with an unsigned receipt establishes relative byte consistency. It does
not prove authorship, provider/model execution, report quality or acceptance.
The checker uses bounded stable reads and rechecks directory/receipt state; it
does not provide an atomic filesystem snapshot or a complete defense against a
hostile concurrent process. There is no new MCP filesystem tool and no claimed
token saving or fresh browser visual QA.

Earlier acceptance requests for AR-0018/AR-0019 remain pending following their
automatic execution-policy rejection; those tickets and their parent are unchanged.
