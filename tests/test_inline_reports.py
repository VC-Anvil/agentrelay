"""Exact bounded worker reports survive protocol capture without artifact reads."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

from agentrelay.adapters import persist_result
from agentrelay.execution import ExecutionManager
from agentrelay.run_results import MAX_REPORT_BYTES, get_run_result, validate_artifact_markdown
from agentrelay.store import DomainError, Store


REPORT = "# Informe ñ\r\n\r\nLínea final á.  \n"
PACKET = {"protocol": "agentrelay.worker.v1",
          "worker": {"id": "fixture", "model": "fixture-model", "effort": "none"},
          "context": {"ticket": {"id": "AR-0001"}}}

WORKER = r'''
import json, pathlib, sys, time
sys.path.insert(0, sys.argv[5])
from agentrelay.adapters import persist_result
packet = json.load(sys.stdin)
assert packet["protocol"] == "agentrelay.worker.v1"
mode, artifact_dir, marker, gate = sys.argv[1:5]
report = "# Informe ñ\r\n\r\nLínea final á.  \n"
result = {"outcome": "submit", "summary": "Entrega de fixture", "evidence": []}
if mode != "legacy":
    result["artifact_markdown"] = report if mode != "oversize" else "ñ" * 131073
if mode == "oversize":
    result["evidence"] = [{"kind": "file", "label": "Valid fixture evidence", "uri": "local://fixture"}]
if mode in ("adapter", "conflict"):
    result = persist_result(result, pathlib.Path(artifact_dir), packet, "fixture")
if mode == "conflict":
    pathlib.Path(marker).write_text("ready", encoding="utf-8")
    while not pathlib.Path(gate).exists():
        time.sleep(0.02)
if mode == "legacy":
    result["evidence"] = [{"kind": "file", "label": "Old fixture", "uri": "local://old"}]
print(json.dumps(result, ensure_ascii=False))
'''


class InlineReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-inline-report-")
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "tickets.sqlite")
        self.script = self.root / "fixture.py"
        self.script.write_text(WORKER, encoding="utf-8")
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        self.marker = self.root / "marker.txt"
        self.gate = self.root / "gate.txt"
        self.managers = []

    def tearDown(self):
        for manager in reversed(self.managers):
            manager.close()
        self.temp.cleanup()

    def manager(self, mode):
        config = self.root / "workers.json"
        config.write_text(json.dumps({"workers": [{
            "id": "fixture", "name": "Fixture", "model": "fixture-model", "effort": "medium",
            "command": [sys.executable, str(self.script), mode, str(self.artifacts),
                        str(self.marker), str(self.gate), str(Path(__file__).resolve().parents[1])],
            "cwd": str(self.root), "profile_ids": [], "timeout_seconds": 5,
        }]}), encoding="utf-8")
        manager = ExecutionManager(self.store, config)
        self.managers.append(manager)
        return manager

    def ticket(self):
        return self.store.action("create_ticket", {
            "title": "Review fixture", "acceptance": ["Report independently checked"],
        })

    def wait_for(self, check, description):
        deadline = time.monotonic() + 7
        while time.monotonic() < deadline:
            value = check()
            if value:
                return value
            time.sleep(0.02)
        self.fail(f"timed out waiting for {description}")

    def finished(self, manager, run_id):
        return self.wait_for(lambda: next((run for run in manager.snapshot()["runs"]
            if run["id"] == run_id and run["status"] != "running"), None), "run finish")

    def test_validation_is_utf8_exact_and_byte_bounded(self):
        self.assertEqual(validate_artifact_markdown(REPORT), REPORT.encode("utf-8"))
        boundary = "ñ" * (MAX_REPORT_BYTES // 2)
        self.assertEqual(len(validate_artifact_markdown(boundary)), MAX_REPORT_BYTES)
        for invalid in (None, 7, "", " \r\n\t", "\ud800", boundary + "ñ"):
            with self.subTest(invalid=repr(invalid)[:30]), self.assertRaises(ValueError):
                validate_artifact_markdown(invalid)

    def test_adapter_returns_exact_text_and_receipt_matches_written_bytes(self):
        supplied = {"outcome": "submit", "summary": "Fixture", "artifact_markdown": REPORT,
                    "evidence": []}
        returned = persist_result(supplied, self.artifacts, PACKET, "fixture")
        self.assertEqual(returned["artifact_markdown"], REPORT)
        report_bytes = (self.artifacts / "report.md").read_bytes()
        self.assertEqual(report_bytes, REPORT.encode("utf-8"))
        receipt = json.loads((self.artifacts / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["report_sha256"], hashlib.sha256(report_bytes).hexdigest())
        self.assertEqual([item["kind"] for item in returned["evidence"]], ["receipt", "report"])

    def test_adapter_rejects_excess_before_report_or_receipt(self):
        supplied = {"outcome": "submit", "summary": "Fixture", "evidence": [],
                    "artifact_markdown": "ñ" * (MAX_REPORT_BYTES // 2 + 1)}
        with self.assertRaises(ValueError):
            persist_result(supplied, self.artifacts, PACKET, "fixture")
        self.assertFalse((self.artifacts / "report.md").exists())
        self.assertFalse((self.artifacts / "receipt.json").exists())
        help_result = persist_result({"outcome": "help", "summary": "Need details",
                                      "artifact_markdown": "  ", "evidence": []},
                                     self.artifacts, PACKET, "fixture")
        self.assertNotIn("artifact_markdown", help_result)
        self.assertFalse((self.artifacts / "report.md").exists())
        with self.assertRaises(ValueError):
            persist_result({"outcome": "submit", "summary": "No content",
                            "artifact_markdown": " \n", "evidence": []},
                           self.artifacts, PACKET, "fixture")

    def test_subprocess_result_and_backup_survive_deleted_artifact(self):
        ticket = self.ticket()
        manager = self.manager("adapter")
        run_id = manager.start(ticket["id"], "fixture", ticket["revision"])["id"]
        self.assertEqual(self.finished(manager, run_id)["status"], "submitted")
        report_path = self.artifacts / "report.md"
        self.assertEqual(report_path.read_bytes(), REPORT.encode("utf-8"))
        report_path.unlink()
        (self.artifacts / "receipt.json").unlink()
        captured = get_run_result(self.store, run_id)
        self.assertEqual(captured["result"]["artifact_markdown"], REPORT)
        self.assertEqual(captured["current_ticket"]["status"], "review")
        self.assertNotIn("artifact_markdown", manager.snapshot()["runs"][0])
        self.assertNotIn("artifact_markdown", self.store.export()["runs"][0])
        self.assertNotIn("artifact_markdown", self.store.context(ticket["id"])["ticket"])
        backup = self.root / "backup.sqlite"
        self.store.backup(backup)
        self.assertEqual(get_run_result(Store(backup), run_id)["result"]["artifact_markdown"], REPORT)

    def test_conflict_retains_inline_report_without_applying_it(self):
        ticket = self.ticket()
        manager = self.manager("conflict")
        run_id = manager.start(ticket["id"], "fixture", ticket["revision"])["id"]
        self.wait_for(self.marker.exists, "worker marker")
        edited = self.store.action("update_ticket", {"id": ticket["id"],
            "expected_revision": 2, "description": "Keep concurrent human edit"})
        self.gate.write_text("go", encoding="utf-8")
        self.assertEqual(self.finished(manager, run_id)["status"], "conflict")
        captured = get_run_result(self.store, run_id)
        self.assertEqual(captured["result"]["artifact_markdown"], REPORT)
        self.assertEqual(captured["current_ticket"]["revision"], edited["revision"])
        self.assertEqual(self.store.context(ticket["id"])["ticket"]["evidence"], [])

    def test_old_result_shape_and_malformed_stored_field(self):
        ticket = self.ticket()
        manager = self.manager("legacy")
        run_id = manager.start(ticket["id"], "fixture", 1)["id"]
        self.assertEqual(self.finished(manager, run_id)["status"], "submitted")
        old = get_run_result(self.store, run_id)["result"]
        self.assertNotIn("artifact_markdown", old)
        with self.store._write() as db:
            original = db.execute("SELECT result_json FROM execution_runs WHERE id=?", (run_id,)).fetchone()[0]
        for invalid in (None, 4, "", " ", "\ud800", "x" * (MAX_REPORT_BYTES + 1)):
            with self.subTest(invalid=repr(invalid)[:30]):
                modified = {**old, "artifact_markdown": invalid}
                with self.store._write() as db:
                    db.execute("UPDATE execution_runs SET result_json=? WHERE id=?",
                               (json.dumps(modified, ensure_ascii=True), run_id))
                with self.assertRaises(DomainError) as caught:
                    get_run_result(self.store, run_id)
                self.assertEqual(caught.exception.status, 500)
        with self.store._write() as db:
            db.execute("UPDATE execution_runs SET result_json=? WHERE id=?", (original, run_id))
        self.assertEqual(get_run_result(self.store, run_id)["result"], old)

    def test_direct_worker_oversize_fails_without_captured_result(self):
        ticket = self.ticket()
        manager = self.manager("oversize")
        run_id = manager.start(ticket["id"], "fixture", 1)["id"]
        self.assertEqual(self.finished(manager, run_id)["status"], "failed")
        manager.close()  # Wait for the diagnostic copy after the terminal DB update.
        stdout_log = self.root / "runs" / run_id / "stdout.json"
        raw = json.loads(stdout_log.read_text(encoding="utf-8"))
        self.assertEqual(raw["evidence"][0]["kind"], "file")
        self.assertGreater(len(raw["artifact_markdown"].encode("utf-8")), MAX_REPORT_BYTES)
        with self.assertRaisesRegex(DomainError, "artifact_markdown exceeds"):
            manager._validate_result(raw)
        self.assertIsNone(get_run_result(self.store, run_id)["result"])
        self.assertEqual(self.store.context(ticket["id"])["ticket"]["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
