# Comparing two input snapshots

`diff-snapshots` compares two already captured AgentRelay snapshots. It reads
only the fixed files referenced by their verified manifests. It does not read a
live project, follow `source_root` or links in captured documents, open a ticket
database, contact a worker, or change acceptance state.

Both expected identities are mandatory:

```console
agentrelay diff-snapshots \
  --before .agentrelay/snapshots/plan-inputs \
  --after .agentrelay/snapshots/current-inputs \
  --expected-before-id sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --expected-after-id sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
```

The default selection is the sorted union of manifest paths. Repeat `--file`
to request a nonempty subset explicitly:

```console
agentrelay diff-snapshots \
  --before snapshots/old --after snapshots/new \
  --expected-before-id sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --expected-after-id sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb \
  --file docs/plan.md --file config/profiles.json
```

The example IDs use exactly 64 lowercase hexadecimal characters and must be
replaced with the identities from the two manifests. Selectors are canonical
relative manifest paths. A focused request contains 1 to 128 unique paths.
Unknown, unsafe or duplicate selectors fail instead of broadening the comparison.

## Result and exit status

The exact top-level keys are `schema_version`, `before_snapshot_id`,
`after_snapshot_id`, `files` and `summary`. Summary contains `total`,
`unchanged`, `modified`, `added`, `removed`, `diff_available` and
`diff_omitted`. Each sorted file entry is classified as `unchanged`, `modified`,
`added` or `removed`; a rename therefore appears as one removal and one addition.
Its `before` and `after` values contain the captured size and SHA-256, or `null`
when that side does not exist.

Exit status is:

- `0` when every selected entry is unchanged.
- `2` when at least one entry is modified, added or removed. The complete JSON
  report is still written to standard output.
- `1` for a controlled verification, selection, integrity, size or filesystem
  error. The CLI writes a concise diagnostic to standard error and no success
  JSON.
- `2` is also argparse's malformed-command status; in that case standard error
  begins with usage information and there is no report.

The command runs before any Store or default database initialization. It accepts
no database, current project root, actor, ticket, MCP or HTTP option.

## Structured text differences

Text files use strict UTF-8 and preserve their original line endings. Each hunk
has zero-based `before_start` and `after_start` indices, counts for both sides,
and complete line items with `kind` (`context`, `removed` or `added`), `text`,
and `eol` (`lf`, `crlf` or `none`). Three unchanged lines on each side of a
change provide context; a grouped hunk can therefore contain context around
more than one nearby edit. These hunks describe captured bytes for review; they
are not a directly applicable patch.

`diff.status` is `not_needed` for unchanged content, `available` for a complete
structured difference, or `omitted` with a reason and no hunks. Omission is
explicit for binary data, invalid UTF-8, line/comparison limits or output limits.
AgentRelay never returns a truncated hunk that looks complete. A narrower
`--file` selection can be used if the full report exceeds its overall bound.

The service allows at most 50,000 lines on either side. After removing the
common prefix and suffix while retaining context, the product of the two window
lengths may not exceed 1,000,000. Canonical JSON for one available hunk list is
limited to 32,768 bytes and all available hunk lists together to 131,072 bytes;
the complete canonical report is limited to 1,048,576 bytes. A file that exceeds
a hunk limit is wholly `omitted`, while a report above its bound fails and asks
for a narrower selection. Existing snapshot bounds also remain in force: at
most 64 files, 1,048,576 bytes per file and 8,388,608 bytes total.

## Interpretation and limits

The result is a historical comparison between two frozen input bundles. A hash
or textual change does not decide whether a proposed ticket is stale, reopen a
ticket, reserve work, or approve an implementation. Reviewers must interpret
the exact input that the earlier work used. For example, a modified raw source
does not prove that an independently captured derived excerpt changed.

Snapshot manifests and hashes detect accidental mismatch or corruption. They
are unsigned and do not authenticate authorship, review quality or the host.
Each snapshot was captured file by file rather than as one atomic multi-file
filesystem view. The comparison does not reopen either source project or follow
provenance paths to compensate for those limits.
