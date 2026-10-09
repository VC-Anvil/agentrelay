"""Adapter deliveries expose their receipt; local checking never rewrites evidence."""

import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from agentrelay import adapters


class ReportDeliveryTests(unittest.TestCase):
    def test_adapter_without_snapshot_exposes_receipt_and_cli_detects_later_changes(self):
        with tempfile.TemporaryDirectory(prefix="agentrelay-report-delivery-") as directory:
            root = Path(directory).resolve()
            packet = {"protocol": "agentrelay.worker.v1",
                      "worker": {"model": "fixture-model", "effort": "none"},
                      "context": {"ticket": {"id": "AR-0001"}}}
            supplied = {"outcome": "submit", "summary": "Fixture delivery",
                        "artifact_markdown": "# Informe ñ\n\nPreparado para revisión.\n",
                        "evidence": []}
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.object(adapters, "read_input", return_value=packet), \
                 patch.object(adapters, "ollama", return_value=copy.deepcopy(supplied)), \
                 contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = adapters.main(["ollama", "--artifacts-dir", str(root / "outputs")])
            self.assertEqual(code, 0, stderr.getvalue())
            delivery = json.loads(stdout.getvalue())
            self.assertEqual([entry["kind"] for entry in delivery["evidence"]], ["receipt", "report"])
            receipt_path = Path(delivery["evidence"][0]["uri"])
            report_path = Path(delivery["evidence"][1]["uri"])
            self.assertEqual(receipt_path.parent, report_path.parent)
            receipt_bytes = receipt_path.read_bytes()
            report_bytes = report_path.read_bytes()
            receipt = json.loads(receipt_bytes)
            self.assertNotIn("snapshot_id", receipt)
            self.assertEqual(receipt["report_sha256"], hashlib.sha256(report_bytes).hexdigest())
            anchor = hashlib.sha256(receipt_bytes).hexdigest()

            def verify():
                process = subprocess.run([
                    sys.executable, "-m", "agentrelay", "verify-report", str(report_path.parent),
                    "--receipt-sha256", anchor,
                ], cwd=Path(__file__).resolve().parents[1], capture_output=True,
                    text=True, encoding="utf-8", timeout=10)
                self.assertIn(process.returncode, (0, 2), process.stderr)
                return process.returncode, json.loads(process.stdout)

            code, result = verify()
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "unchanged")
            self.assertTrue(result["receipt_matches_expected"])

            report_path.write_bytes(report_bytes + b"\nChanged fixture output.\n")
            code, result = verify()
            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "modified")
            self.assertEqual(receipt_path.read_bytes(), receipt_bytes)

            # A replaced receipt cannot establish the original captured baseline.
            receipt["report_sha256"] = hashlib.sha256(report_path.read_bytes()).hexdigest()
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            replaced = receipt_path.read_bytes()
            code, result = verify()
            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "uncheckable")
            self.assertFalse(result["receipt_matches_expected"])
            self.assertIsNone(result["actual_report_sha256"])
            self.assertEqual(receipt_path.read_bytes(), replaced)
            self.assertEqual(report_path.read_bytes(), report_bytes + b"\nChanged fixture output.\n")


if __name__ == "__main__":
    unittest.main()
