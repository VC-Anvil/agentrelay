"""Deterministic local AgentRelay handoff example; no model or network calls.

After an editable install: python examples/handoff_demo.py --output NEW_DIRECTORY
The private worker mode is invoked only by the fixed local worker configuration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

from agentrelay.execution import ExecutionManager
from agentrelay.run_results import get_run_result
from agentrelay.store import Store


ACCEPT_HELP = "El informe corregido indica la unidad MHz junto a 23."
ACCEPT_PARENT = "El informe final usa la ayuda aceptada y distingue la simulación de la aceptación."
REVIEW_REASON = "Añade la unidad MHz junto a 23 y señala que el dato es una simulación."
REVIEWER = "agent:independent-reviewer"
PARENT_OWNER = "agent:parent-owner"
REPORTS = {
    "help-initial": "# Ayuda simulada — primer borrador\n\nLa cifra de ejemplo es 23. Falta la unidad.\n",
    "help-corrected": "# Ayuda simulada — corrección\n\nLa cifra de ejemplo es 23 MHz. No es una medición real.\n",
}
SUMMARIES = {
    "help-initial": "Borrador simulado: 23 sin unidad.",
    "help-corrected": "Ayuda simulada corregida: 23 MHz, sin medición real.",
}


def fixture_worker(mode: str) -> int:
    """Emit one fixed JSON proposal; parent checks the accepted child in context."""
    if mode not in {"help-initial", "help-corrected", "parent"}:
        raise ValueError("unknown private fixture mode")
    raw = sys.stdin.buffer.read(1_048_577)
    if len(raw) > 1_048_576:
        raise ValueError("fixture context exceeds 1 MiB")
    request = json.loads(raw.decode("utf-8", errors="strict"))
    if request.get("protocol") != "agentrelay.worker.v1":
        raise ValueError("unexpected worker protocol")
    context = request["context"]
    if mode == "parent":
        children = [child for child in context["children"] if child["type"] == "help"]
        if len(children) != 1 or children[0]["status"] != "done" or "23 MHz" not in children[0]["checkpoint"]:
            raise ValueError("accepted corrected child context is required")
        child = children[0]
        report = ("# Cierre simulado del padre\n\n"
                  f"Leí el contexto del hijo aceptado {child['id']}: {child['checkpoint']}\n"
                  "Uso la ayuda corregida, 23 MHz, sólo como ejemplo; no hay medición real.\n")
        summary = f"Resumen simulado basado en el hijo aceptado {child['id']}: 23 MHz."
    else:
        report = REPORTS[mode]
        summary = SUMMARIES[mode]
    proposal = {
        "outcome": "submit", "summary": summary,
        "artifact_markdown": report,
        "evidence": [{"kind": "fixture", "label": "Texto simulado por Python determinista",
                      "uri": f"fixture://handoff/{mode}"}],
    }
    sys.stdout.write(json.dumps(proposal, ensure_ascii=False) + "\n")
    return 0


def _act(store: Store, action: str, ticket: dict, actor: str, **fields) -> dict:
    return store.action(action, {"id": ticket["id"], "expected_revision": ticket["revision"],
                                 **fields}, actor)


def _wait_run(manager: ExecutionManager, run_id: str, *, timeout: float = 8.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = next((item for item in manager.snapshot()["runs"] if item["id"] == run_id), None)
        if run is not None and run["status"] != "running":
            return run
        time.sleep(0.05)
    manager.cancel(run_id)
    raise TimeoutError(f"fixture run {run_id} did not finish within {timeout:g} seconds")


def _run_fixture(manager: ExecutionManager, store: Store, ticket: dict, worker_id: str) -> tuple[dict, dict, str]:
    started = manager.start(ticket["id"], worker_id, ticket["revision"])
    run = _wait_run(manager, started["id"])
    if run["status"] != "submitted":
        raise RuntimeError(f"fixture worker {worker_id} ended as {run['status']}: {run['error']}")
    result = get_run_result(store, run["id"])
    if result["result"] is None or not isinstance(result["result"].get("artifact_markdown"), str):
        raise RuntimeError(f"fixture worker {worker_id} did not retain its report")
    report = result["result"]["artifact_markdown"]
    return result["current_ticket"], {
        "id": run["id"], "status": run["status"],
        "report_sha256": hashlib.sha256(report.encode("utf-8")).hexdigest(),
    }, report


def _workers_config(output: Path, profile_id: str) -> Path:
    script = Path(__file__).resolve()
    workers = []
    for worker_id in ("help-initial", "help-corrected", "parent"):
        workers.append({
            "id": worker_id, "name": f"Deterministic fixture: {worker_id}",
            "command": [sys.executable, str(script), "--fixture-worker", worker_id],
            "cwd": str(output), "model": "fixture-python", "effort": "none",
            "profile_ids": [profile_id], "timeout_seconds": 5,
        })
    path = output / "workers.json"
    path.write_text(json.dumps({"workers": workers}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def run_example(output: Path) -> dict:
    """Create a wholly new retained fixture directory and run the review cycle."""
    output = output.expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"output directory already exists: {output}")
    if not output.parent.is_dir():
        raise ValueError(f"output parent directory does not exist: {output.parent}")
    output.mkdir(exist_ok=False)
    database = output / "workspace.sqlite"
    store = Store(database)
    profile = store.action("create_profile", {
        "name": "Deterministic Python fixture", "role": "local example worker",
        "provider": "Python fixture", "model": "fixture-python", "effort": "none",
        "description": "Scripted output; no LLM, provider or network call.",
    }, "human")
    workers_path = _workers_config(output, profile["id"])
    manager = ExecutionManager(store, workers_path)
    try:
        parent = store.action("create_ticket", {
            "title": "Integrar un ejemplo documental con ayuda corregida",
            "description": "Simulación local de entrega, devolución y aceptación independiente.",
            "priority": "urgent", "profile_id": profile["id"],
            "acceptance": [ACCEPT_PARENT],
        }, "human")
        parent = _act(store, "claim_ticket", parent, PARENT_OWNER,
                      assignee="parent-owner", actual_model="fixture-python", actual_effort="none")
        requested = _act(store, "request_help", parent, PARENT_OWNER,
                         title="Aclarar unidad de la cifra simulada",
                         description="El informe debe especificar MHz y declarar que es una simulación.",
                         profile_id=profile["id"])
        parent, child = requested["parent"], requested["child"]
        if child["priority"] != "urgent" or parent["status"] != "blocked":
            raise RuntimeError("fixture help did not inherit urgent priority or block parent")
        child = _act(store, "update_ticket", child, "human", acceptance=[ACCEPT_HELP])

        child, initial_run, initial_report = _run_fixture(manager, store, child, "help-initial")
        if initial_report != REPORTS["help-initial"] or "23 MHz" in initial_report:
            raise RuntimeError("first fixture report did not match the expected missing-unit draft")
        child = _act(store, "request_changes", child, REVIEWER, reason=REVIEW_REASON)
        feedback = store.context(child["id"], event_limit=1)["review_feedback"]
        if feedback is None or feedback["reason"] != REVIEW_REASON:
            raise RuntimeError("fixture review feedback was not retained")
        child, corrected_run, corrected_report = _run_fixture(manager, store, child, "help-corrected")
        child_review_context = store.context(child["id"])
        if corrected_report != REPORTS["help-corrected"] or "23 MHz" not in corrected_report:
            raise RuntimeError("corrected fixture report did not address the review reason")
        child = _act(store, "complete_ticket", child, REVIEWER,
                     expected_acceptance_context_token=child_review_context["acceptance_context"]["token"],
                     verification="El informe simulado corregido incluye MHz y distingue el ejemplo de una medición.",
                     accepted_criteria=[ACCEPT_HELP])
        accepted_child_context = store.context(child["id"])
        if accepted_child_context["ticket"]["status"] != "done":
            raise RuntimeError("corrected child was not independently accepted")
        parent = store.context(parent["id"])["ticket"]
        if parent["status"] != "blocked":
            raise RuntimeError("parent resumed implicitly")
        parent = _act(store, "transition", parent, PARENT_OWNER, status="queued")
        parent, parent_run, parent_report = _run_fixture(manager, store, parent, "parent")
        parent_review_context = store.context(parent["id"])
        if (child["id"] not in parent_report or "23 MHz" not in parent_report
                or "simulad" not in parent_report.lower() or "no hay medición real" not in parent_report):
            raise RuntimeError("parent fixture report did not use accepted child context and simulation limits")
        parent = _act(store, "complete_ticket", parent, REVIEWER,
                      expected_acceptance_context_token=parent_review_context["acceptance_context"]["token"],
                      verification="El informe final simulado usa el hijo aceptado y explicita los límites.",
                      accepted_criteria=[ACCEPT_PARENT])
    finally:
        manager.close()

    runs = {"help_initial": initial_run, "help_corrected": corrected_run, "parent": parent_run}
    backup_path = output / "backup.sqlite"
    store.backup(backup_path)
    backup = Store(backup_path)
    for run in runs.values():
        captured = get_run_result(store, run["id"])["result"]["artifact_markdown"]
        restored = get_run_result(backup, run["id"])["result"]["artifact_markdown"]
        if captured != restored:
            raise RuntimeError(f"backup lost report for {run['id']}")
    paths = {name: str(output / filename) for name, filename in (
        ("database", "workspace.sqlite"), ("workers", "workers.json"),
        ("backup", "backup.sqlite"), ("report", "report.md"), ("result", "result.json"))}
    result = {
        "schema_version": 1, "simulation": True, "paths": paths,
        "tickets": {"parent": {"id": parent["id"], "status": parent["status"]},
                    "help": {"id": child["id"], "status": child["status"],
                             "priority": child["priority"]}},
        "runs": runs,
        "review": {"reviewer": REVIEWER, "reason": REVIEW_REASON,
                   "feedback_event_id": feedback["event_id"],
                   "parent_requeued_by": PARENT_OWNER},
    }
    (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# AgentRelay: traspaso local simulado",
        "", "Tres trabajadores Python deterministas; ninguna inferencia ni conexión de red.",
        f"Ayuda {child['id']} (urgente): borrador devuelto por {REVIEWER} para añadir MHz; corrección aceptada.",
        f"Padre {parent['id']}: permaneció bloqueado hasta que {PARENT_OWNER} lo reencoló; entrega final aceptada.",
        "", "Los informes originales están en result_json de la base y del backup;",
        "get_run_result recupera cada texto por ID aun sin archivo de informe local.",
        "El texto es una simulación y cada aceptación fue una decisión explícita del revisor fixture.",
        "", "Runs y SHA-256 del texto exacto:",
    ]
    lines.extend(f"- {name}: {run['id']} · {run['report_sha256']}" for name, run in runs.items())
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main(argv=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "--fixture-worker":
        if len(arguments) != 2:
            raise ValueError("private fixture worker requires one fixed mode")
        return fixture_worker(arguments[1])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path,
                        help="New directory for isolated SQLite, worker config, report and backup")
    args = parser.parse_args(arguments)
    try:
        result = run_example(args.output)
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        parser.exit(1, f"Handoff example failed: {exc}\n")
    tickets = result["tickets"]
    print(f"Simulación completada: ayuda {tickets['help']['id']}={tickets['help']['status']}; "
          f"padre {tickets['parent']['id']}={tickets['parent']['status']}.")
    print(f"Resumen: {result['paths']['report']}")
    print(f"Resultados: {result['paths']['result']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
