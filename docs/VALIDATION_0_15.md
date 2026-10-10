# AgentRelay 0.15 — explaining changes between captured inputs

Date: 2026-10-10 (Europe/Madrid). Windows, Python 3.12.14.
Previous release: [historical source checks](VALIDATION_0_14.md).

## Real use and resulting change

The previous release recorded that original documents in Dirt Riot and Cartógrafo
Imposible had changed. Reading the changed passages showed why hashes alone were
insufficient for the next handoff: Dirt Riot's new preface declares its musical
integration technically complete while preserving human/hardware review gates;
Cartógrafo labels the earlier continuity document historical. Those statements
are documentary evidence, not a new verification of either game.

AgentRelay now compares two explicitly identified frozen snapshots and returns
per-file byte identities plus bounded structured text hunks. The local
`diff-snapshots` command can select specific paths. It does not read historical
source roots or follow links, initialize a database, change a ticket or launch a
worker. [Fields, examples and limits](SNAPSHOT_DIFF.md).

## Actual documentary exercise

New captures preserved the same three explicitly selected original documents in
each affected project. Their originals and earlier derived selections were kept.
Actual CLI subprocesses compared each old/new pair, selected the changed file
separately and repeated the full comparison. Selected entries matched exactly;
repeated output was identical. All capture bytes remained unchanged.

| Project | Unchanged files | Modified files | Available hunks | Added lines | Canonical report bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Dirt Riot | 2 | 1 | 1 | 10 | 3,698 |
| Cartógrafo Imposible | 2 | 1 | 1 | 3 | 2,007 |

Neither report omitted text. Dirt Riot's long document was handled by removing
its shared prefix/suffix from the matching window while retaining context and
original line indices. UTF-8 content and exact LF/CRLF/unterminated endings were
preserved. These byte counts describe output only; no token or quota saving was
measured.

Read-only checks confirmed every row in all four pilot databases remained equal
during comparison. Afterwards, the integrator added one explicit documentary
review comment to each affected AR-0002, referencing both snapshot identities and
the saved report's hash. Only those two audit events were appended. All 33 pilot
tickets, revisions, acceptance, ownership, dependencies and executions remained
unchanged; LEVIATHAN and Valley received no writes. No game source was edited and
no game work was reopened or run. The Cartógrafo reference was not followed.

## Verification and review

Service tests cover exact indices, additions/removals, case-only renames, empty
files, UTF-8/BOM, binary data, line endings and EOF, corrupt snapshots, identity
mismatch, unsafe selectors, concurrent read mutation, ignored source roots,
determinism and computation/output limits. Actual CLI subprocess tests cover
required arguments, selected paths, meaningful exit codes, concise errors,
snapshot preservation and absence of any default database.

The first focused run exposed an invalid Windows fixture name, `nul.bin`; it
failed before exercising the binary-data case. The fixture was renamed. Root
review also found overly broad case-folded selector deduplication and a line
limit applied after allocating the full list. Those were corrected, with
regressions for selecting both sides of a case-only rename and checking the line
count before splitting. The final focused service/CLI run completed **16 tests:
15 passed, one Windows symlink test skipped**, in 1.879 seconds.

An independent consumer test reconstructs the exact after-capture bytes from
structured hunks for 36 deterministic examples. It checks line indices, context,
counts, repeated lines, insertions/removals/replacements, UTF-8 and line endings
without using the matching algorithm to derive expected results.

The complete local suite finished **219 tests: 212 passed and seven Windows
symlink tests were skipped**, in 65.246 seconds. The release check compares wheel
package/skill bytes and source-archive contents with the working tree, then
exercises the snapshot-diff API and existing persistence/worker boundaries from
an isolated wheel installation. Exact-commit CI covers Windows/Linux with Python
3.11/3.12; the pushed run is reported separately.

Both specialist packages received independent cross-review. A specialist sandbox
denied temporary fixture creation; that attempt was inconclusive, not a product
failure or a passing test. Executed fixture results above are from the root's
ordinary local environment. The companion skill passed structural validation.
Author reports: [service](snapshot-diff-service-report.md),
[interfaces](snapshot-diff-interface-report.md).

## Limits

The output is historical review context, not an applicable patch, a semantic
decision or a new source-check record. A changed original does not prove that an
earlier derived excerpt changed. Empty file additions/removals have file metadata
changes and may have no text hunk. Renames are shown as removal plus addition.

The tool verifies both full snapshots before comparing selected file bytes, so
`--file` narrows the diff output, not snapshot integrity validation. Unsigned
hashes do not authenticate authorship. Each capture was made file by file, not
as an atomic project-wide filesystem view. Unavailable text is explicitly omitted
for binary/UTF-8, line, comparison or output limits; it is never silently clipped.

No browser control or MCP filesystem tool was added. Browser access remains
pending; no fresh visual QA or provider inference is claimed for this release.
