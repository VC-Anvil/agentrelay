# AgentRelay 0.11 — report integrity

Date: 2026-10-10 (Europe/Madrid). Windows, Python 3.12.14, MCP SDK 1.30.0.
Previous release: [execution discovery](VALIDATION_0_10.md).

## Patch 0.11.2 — portable stored-result depth limit

The first patch passed locally but failed on Linux Python 3.12.15 in CI: that
decoder accepted 5,000 levels, after which the CLI's JSON encoder exceeded its
own recursion limit. The failed run and original artifacts were preserved, and
the development ticket was reopened. Raising the fixture's depth would only
hide the difference between runtimes.

The reader now checks a fixed maximum of 64 object/array containers, with the
root counting as one. An iterative traversal keeps its auxiliary stack bounded
by nesting depth. The execution manager applies the same check before retaining
new normalized proposals or applying them to a ticket. Stored data beyond the
limit is rejected without rewriting it; strings containing brackets remain text.

Regressions preserve the original deep fixture and additionally exercise exactly
64 levels, 65 levels, long bracket-containing text, an unaffected neighboring run,
CLI diagnostics and a real local fixture worker rejected before proposal capture
or submission. These fixtures do not call a model provider.

The full local rerun passed **146 tests with three Windows symlink skips (149
total)** in 47.057 seconds. Independent service/integration review found no
remaining defect in the scoped change. CI must verify this exact patch separately;
the earlier failed 0.11.1 run is not counted as success.

## Patch 0.11.1 — initial decoder exception handling

An isolated SQLite fixture containing 10,013 bytes of deeply nested JSON caused
`get_run_result` to raise an unhandled `RecursionError`; its CLI printed a
traceback. This was synthetic malformed stored data, not a damaged pilot record.
The reader now converts that decoder failure to the existing invalid-result
domain error (500); the CLI exits 1 with a concise diagnostic. It neither repairs
nor replaces the retained bytes.

The service regression and a CLI subprocess regression verify that the selected
data remains unchanged and another valid result is still readable. Independent
root review confirmed the original reproduction now fails cleanly and all its
ticket, profile, event, dependency and run rows remain identical. The full suite
passed **145 tests with three Windows symlink skips (148 total)** in 46.323 seconds.
The earlier 0.11.0 commit passed all four Windows/Linux Python 3.11/3.12 CI jobs;
the patch's subsequent Linux failure is recorded above. No pilot or game data
was modified. The local result alone did not establish cross-platform success.

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
