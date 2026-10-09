"""The report-integrity CLI is machine-readable and never bootstraps project state."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CliReportIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-report-integrity-cli-")
        self.root = Path(self.temp.name)
        self.directory = self.root / "entrega-á"
        self.directory.mkdir()
        self.report = self.directory / "report.md"
        self.receipt = self.directory / "receipt.json"
        self.report.write_text("# Informe\n\nRevisión íntegra: ñ.\n", encoding="utf-8")
        self.write_receipt()

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def write_receipt(self, **changes):
        data = {
            "provider": "fixture",
            "ticket_id": "AR-0001",
            "artifacts_dir": "Z:/metadata/must-not-be-followed",
            "report_uri": "Z:/outside/report.md",
            "report_sha256": self.digest(self.report),
        }
        data.update(changes)
        self.receipt.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def command(self, directory=None, *args):
        environment = os.environ.copy()
        current_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (str(PROJECT_ROOT) if not current_path else
                                      str(PROJECT_ROOT) + os.pathsep + current_path)
        return subprocess.run([
            sys.executable, "-m", "agentrelay", "verify-report",
            str(self.directory if directory is None else directory), *map(str, args),
        ], cwd=self.root, env=environment, capture_output=True, text=True,
            encoding="utf-8", timeout=20)

    def read(self, directory=None, *args):
        process = self.command(directory, *args)
        self.assertTrue(process.stdout, process.stderr)
        return process, json.loads(process.stdout)

    def tree_bytes(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()}

    def test_unchanged_with_optional_receipt_anchor_is_utf8_and_read_only(self):
        before = self.tree_bytes()
        anchor = self.digest(self.receipt)

        process, result = self.read(None, "--receipt-sha256", anchor)

        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("entrega-á", process.stdout)
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(result["expected_report_sha256"], self.digest(self.report))
        self.assertEqual(result["actual_report_sha256"], self.digest(self.report))
        self.assertEqual(result["receipt_sha256"], anchor)
        self.assertEqual(result["expected_receipt_sha256"], anchor)
        self.assertTrue(result["receipt_matches_expected"])
        self.assertEqual(self.tree_bytes(), before)
        self.assertFalse((self.root / ".agentrelay").exists())

    def test_modified_missing_and_uncheckable_states_exit_two(self):
        self.report.write_text("# Informe modificado\n", encoding="utf-8")
        modified_process, modified = self.read()
        self.assertEqual(modified_process.returncode, 2, modified_process.stderr)
        self.assertEqual(modified["status"], "modified")
        self.assertNotEqual(modified["actual_report_sha256"], modified["expected_report_sha256"])

        self.report.unlink()
        missing_process, missing = self.read()
        self.assertEqual(missing_process.returncode, 2, missing_process.stderr)
        self.assertEqual(missing["status"], "missing")
        self.assertIsNone(missing["actual_report_sha256"])

        self.report.write_text("restored", encoding="utf-8")
        self.receipt.write_text(json.dumps({"ticket_id": "legacy"}), encoding="utf-8")
        legacy_process, legacy = self.read()
        self.assertEqual(legacy_process.returncode, 2, legacy_process.stderr)
        self.assertEqual(legacy["status"], "uncheckable")
        self.assertIsNone(legacy["expected_report_sha256"])

        self.receipt.write_text("{not valid JSON", encoding="utf-8")
        unreadable_process, unreadable = self.read()
        self.assertEqual(unreadable_process.returncode, 2, unreadable_process.stderr)
        self.assertEqual(unreadable["status"], "uncheckable")

        self.receipt.unlink()
        absent_process, absent = self.read()
        self.assertEqual(absent_process.returncode, 2, absent_process.stderr)
        self.assertEqual(absent["status"], "uncheckable")

    def test_wrong_receipt_anchor_stops_before_report_and_external_metadata_is_ignored(self):
        outside = self.root / "outside-report.md"
        outside.write_text("outside bytes", encoding="utf-8")
        self.write_receipt(artifacts_dir=str(outside.parent), report_uri=str(outside))
        correct_anchor = self.digest(self.receipt)
        before = self.tree_bytes()

        mismatch_process, mismatch = self.read(
            None, "--receipt-sha256", "0" * 64)
        self.assertEqual(mismatch_process.returncode, 2, mismatch_process.stderr)
        self.assertEqual(mismatch["status"], "uncheckable")
        self.assertFalse(mismatch["receipt_matches_expected"])
        self.assertIsNone(mismatch["actual_report_sha256"])

        unchanged_process, unchanged = self.read(
            None, "--receipt-sha256", correct_anchor)
        self.assertEqual(unchanged_process.returncode, 0, unchanged_process.stderr)
        self.assertEqual(unchanged["status"], "unchanged")
        self.assertEqual(unchanged["actual_report_sha256"], self.digest(self.report))
        self.assertEqual(self.tree_bytes(), before)

    def test_invalid_directory_anchor_and_usage_exit_without_traceback_or_writes(self):
        before = self.tree_bytes()
        invalid_cases = (
            self.command(self.root / "missing"),
            self.command(self.report),
            self.command(None, "--receipt-sha256", "not-a-sha256"),
        )
        for process in invalid_cases:
            with self.subTest(stderr=process.stderr):
                self.assertEqual(process.returncode, 1)
                self.assertFalse(process.stdout)
                self.assertIn("Report verification failed:", process.stderr)
                self.assertNotIn("Traceback", process.stderr)

        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(PROJECT_ROOT)
        usage = subprocess.run([sys.executable, "-m", "agentrelay", "verify-report"],
                               cwd=self.root, env=environment, capture_output=True,
                               text=True, encoding="utf-8", timeout=20)
        self.assertEqual(usage.returncode, 2)
        self.assertIn("usage:", usage.stderr.lower())
        self.assertNotIn("Traceback", usage.stderr)
        self.assertEqual(self.tree_bytes(), before)
        self.assertFalse((self.root / ".agentrelay").exists())


if __name__ == "__main__":
    unittest.main()
