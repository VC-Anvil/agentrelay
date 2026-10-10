# AgentRelay 0.17.1 — reproducible local handoff

Date: 2026-10-10. Windows, Python 3.12.14. This patch adds an executable checkout
example and corrects documentation; it changes no ticket or worker runtime
behavior beyond the package version. The preceding
[real-provider validation](VALIDATION_0_17.md) remains separate evidence.

## What changed

The execution guide described split children as accepting normal ticket fields.
The actual validator accepts only `title`, `description`, `profile_id` and
`acceptance`; the guide now names them exactly. The API contract also showed an
outdated health version. It now describes that value as the installed version.

The new [handoff example](HANDOFF_EXAMPLE.md) makes help, explicit review and
resumption reproducible without connecting a model. It uses actual Store actions,
three ExecutionManager subprocesses and retained SQLite state. Its responses,
logical author/reviewer identities and review decisions are deterministic fixtures.
This is an executable illustration of workflow mechanics, not another LLM pilot
or independent human/model quality review.

## Executed checks

The focused subprocess suite passed **2/2 tests in 1.342 seconds**. It checks:

- An urgent help child blocks its parent and inherits its priority and profile.
- Separate logical reviewer actions return the first report for a missing unit,
  then accept the corrected report after checking its exact captured text.
- Child completion precedes an explicit parent requeue by its owner; the parent
  process receives the accepted child's current checkpoint before submission.
- Three original report texts, their hashes, feedback and audit history survive
  online backup. All recorded runs remain submitted; ticket acceptance is separate.
- Repeating the same output path fails and preserves every existing output byte.
- Missing `--output` fails without creating default state in the process cwd.

A separate direct invocation retained a complete example directory for inspection,
with both tickets done, three submitted runs, `result.json`, `report.md`, the
original database and backup. Its generated worker configuration uses explicit
Python argv, `fixture-python` and effort `none`; no inference was performed.

Review identified two weaknesses before closure. The controller originally
checked only report presence before approval; it now compares actual captured
helper reports and the final parent report with the fixture's expected values.
The initial negative test inspected a temporary directory while starting the
process in the checkout; it now starts in the directory being inspected. The
final focused run above includes both corrections. An earlier focused run passed
in 1.373 seconds before the cwd-test correction; it is not the final evidence.

Both packages received independent static review. Specialist temporary SQLite
restrictions prevented their local fixture execution; the runs above belong to
the root's normal environment. The unchanged runtime had already passed the
0.17 full suite. Exact-head CI runs the expanded suite on Windows/Linux and
Python 3.11/3.12; its final result is recorded at publication.

Distribution verification checks that the source archive includes the Python
example and that package, example, documentation and skill bytes match source.
The retained walkthrough is also exercised against an isolated wheel installation.
The wheel supplies the library; the example script comes from the checkout/source
distribution, as the guide states.

## Limits

The example's controller simulates both author and reviewer identities and checks
fixed text. AgentRelay's distinct-identity rule does not establish independent
people, cryptographic identity, semantic correctness or model quality. The fixture
does not validate any game, provider, browser UI or live project. Output directories
are retained, including on failure, and are never silently reused or deleted.

Author reports: [example](handoff-example-author-report.md),
[guide](handoff-example-interface-report.md).
