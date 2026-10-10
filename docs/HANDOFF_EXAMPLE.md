# Reproducible local handoff example

This example exercises a complete help and review handoff with the real
`Store` and `ExecutionManager`. Its workers are deterministic Python fixtures:
they do not call a model, provider, network service or game, and their reports
identify the run as a simulation. It complements the real pilot evidence; it
does not replace or validate it.

## Run it from a checkout

Install the checkout into the same Python environment that will run the
example:

```console
python -m pip install -e .
```

Choose a path that does not exist, then run:

```console
python examples/handoff_demo.py --output ./handoff-demo-output
```

`--output` is mandatory. The example refuses an existing file or directory
before creating or modifying anything. It keeps its database, configuration,
report, result, backup and execution logs under the new output directory. It
does not modify checkout sources or other projects, use their databases, start
a live server, or read environment configuration or credentials. It does execute
the example script and installed package from this checkout. Importing the
module does not start the example; invoking it without the required arguments
produces the normal command help/error.

The controller is a local fixture orchestrator. It is not an LLM identity or a
human reviewer. It simulates separate author, owner and reviewer audit identities
and checks fixed expected responses so the lifecycle is reproducible; this does
not constitute independent judgment. Its worker configuration uses an explicit
Python argv without a shell, the profile model `fixture-python` and effort
`none`. The worker declares those same values; the example does not invent a
provider or Astra claim.

## What the handoff demonstrates

The deterministic sequence uses current ticket revisions at every write:

1. A parent task owned by the fixture requests a specific piece of help. The
   created help ticket inherits the parent's urgent priority, and the parent is
   blocked on that child.
2. `ExecutionManager` starts the helper fixture. Its first report says
   `La cifra de ejemplo es 23. Falta la unidad.` and enters review.
3. The controller uses a distinct reviewer audit identity to return the helper
   delivery with the exact reason
   `Añade la unidad MHz junto a 23 y señala que el dato es una simulación.` The
   controller first retrieves and compares the retained draft with its fixed
   expected text. The ticket returns to its queue without starting a worker or
   changing its existing evidence.
4. A second helper run submits `La cifra de ejemplo es 23 MHz. No es una
   medición real.` The controller retrieves and compares the corrected retained
   report, then explicitly calls `complete_ticket` with the distinct reviewer
   identity and all acceptance criteria.
5. Completing the child resolves the dependency but does not silently resume
   the parent. Its owner explicitly requeues the still-blocked parent.
6. The resumed parent receives current context, checks the accepted child and
   its corrected checkpoint, submits its own summary, and the controller again
   checks the fixed response before an explicit `complete_ticket` call from the
   reviewer identity.
7. The example creates an online SQLite backup after the workflow. Both original
   and backup retain the three run proposals, exact inline fixture reports,
   review feedback and audit history.

`ExecutionManager` never accepts a delivery. The example controller automates
explicit review actions so the demonstration is repeatable: every acceptance is
a `complete_ticket` call under an identity different from the submitting owner,
after checking the fixed fixture response and supplying the complete criteria.
It does not reopen completed work, launch another agent or modify files outside
the output directory. See [returning a delivery for corrections](REVIEW_CHANGES.md)
for the review operation and [inline reports](INLINE_REPORTS.md) for the
retained-report boundary.

## Output

The program prints a concise human-readable summary and retains these principal
files:

| Path under the output directory | Purpose |
|---|---|
| `workspace.sqlite` | Original AgentRelay database with tickets, audit events and execution history. |
| `workers.json` | Trusted deterministic worker configuration used by the example. |
| `backup.sqlite` | Online backup created after the accepted handoff. |
| `report.md` | Human-readable summary of the simulated workflow. |
| `result.json` | Machine-readable identifiers, terminal states, paths and report hashes. |
| `runs/<run-id>/stdout.json` and `runs/<run-id>/stderr.log` | Local worker diagnostics retained by `ExecutionManager`. |

`result.json` has this stable top-level shape:

```json
{
  "schema_version": 1,
  "simulation": true,
  "paths": {
    "database": "/absolute/output/workspace.sqlite",
    "workers": "/absolute/output/workers.json",
    "backup": "/absolute/output/backup.sqlite",
    "report": "/absolute/output/report.md",
    "result": "/absolute/output/result.json"
  },
  "tickets": {
    "parent": {"id": "<parent-ticket-id>", "status": "done"},
    "help": {"id": "<help-ticket-id>", "status": "done", "priority": "urgent"}
  },
  "runs": {
    "help_initial": {"id": "<run-id>", "status": "submitted", "report_sha256": "<sha256>"},
    "help_corrected": {"id": "<run-id>", "status": "submitted", "report_sha256": "<sha256>"},
    "parent": {"id": "<run-id>", "status": "submitted", "report_sha256": "<sha256>"}
  },
  "review": {
    "reviewer": "agent:independent-reviewer",
    "reason": "Añade la unidad MHz junto a 23 y señala que el dato es una simulación.",
    "feedback_event_id": 17,
    "parent_requeued_by": "agent:parent-owner"
  }
}
```

IDs and hashes above are illustrative; read the generated values. Paths in the
actual file are absolute. `report.md` summarizes the example, while the three
complete worker reports live in each retained run proposal as
`result.artifact_markdown`. They are also preserved in `backup.sqlite`; they are
not duplicated as separate report files.

Inspect one explicitly selected report without following its evidence URI:

```console
agentrelay run-result --db ./handoff-demo-output/workspace.sqlite --run RUN_ID
```

Use the corresponding ID from `result.json`. The returned
`result.artifact_markdown` is exact worker-supplied text, not proof that its
claims are correct. Ticket context and history remain the source for current
state and review decisions.

## Failure and reruns

Runs use bounded waits, and the example closes its execution manager even when
a step fails. It does not delete partial diagnostic output after a failure, so
inspect that new directory before choosing a different new output path for a
rerun. Repeating the command with the same output path is intentionally refused
without changing the existing bytes.

The fixture proves the AgentRelay handoff mechanics under deterministic local
inputs. Its separate audit identities do not prove independent human or model
review. It does not prove provider behavior, inference quality, authentication,
game correctness, or product approval. The worker
configuration is executable local configuration and should still be inspected
before use.
