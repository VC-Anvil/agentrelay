"""Report integrity checks use only fixed local files and never repair old receipts."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agentrelay import report_integrity
from agentrelay import snapshots
from agentrelay.report_integrity import MAX_ARTIFACT_BYTES, verify_report
from agentrelay.snapshots import SnapshotError


class ReportIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-report-integrity-")
        self.root = Path(self.temp.name)
        self.directory = self.root / "selected"
        self.directory.mkdir()
        self.report = self.directory / "report.md"
        self.receipt = self.directory / "receipt.json"
        self.outside = self.root / "elsewhere"
        self.outside.mkdir()
        (self.outside / "report.md").write_text("Unrelated external report", encoding="utf-8")
        self.report.write_text("Informe íntegro: revisión ñ\n", encoding="utf-8")
        self.write_receipt()

    def tearDown(self):
        self.temp.cleanup()

    def write_receipt(self, **changes):
        data = {"provider": "fixture", "cwd": str(self.outside),
                "artifacts_dir": str(self.outside), "uri": str(self.outside / "report.md"),
                "report_sha256": hashlib.sha256(self.report.read_bytes()).hexdigest()}
        data.update(changes)
        self.receipt.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    def test_unchanged_uses_fixed_files_and_optional_receipt_anchor_without_writes(self):
        before = {path.name: path.read_bytes() for path in self.directory.iterdir()}
        anchor = hashlib.sha256(before["receipt.json"]).hexdigest()
        result = verify_report(self.directory, receipt_sha256=anchor.upper())
        self.assertTrue(Path(result["directory"]).is_absolute())
        self.assertTrue(os.path.samefile(result["directory"], self.directory))
        self.assertEqual({key: value for key, value in result.items() if key != "directory"}, {
            "schema_version": 1,
            "status": "unchanged", "reason": None,
            "expected_report_sha256": hashlib.sha256(before["report.md"]).hexdigest(),
            "actual_report_sha256": hashlib.sha256(before["report.md"]).hexdigest(),
            "receipt_sha256": anchor, "expected_receipt_sha256": anchor,
            "receipt_matches_expected": True})
        self.assertEqual({path.name: path.read_bytes() for path in self.directory.iterdir()}, before)
        self.assertEqual((self.outside / "report.md").read_text(encoding="utf-8"),
                         "Unrelated external report")
        without_anchor = verify_report(self.directory)
        self.assertIsNone(without_anchor["expected_receipt_sha256"])
        self.assertIsNone(without_anchor["receipt_matches_expected"])

    def test_modified_and_missing_report_with_valid_receipt(self):
        expected = self.write_receipt()["report_sha256"]
        self.report.write_text("Informe cambiado\n", encoding="utf-8")
        changed = verify_report(self.directory)
        self.assertEqual(changed["status"], "modified")
        self.assertEqual(changed["expected_report_sha256"], expected)
        self.assertEqual(changed["actual_report_sha256"], hashlib.sha256(self.report.read_bytes()).hexdigest())
        self.report.unlink()
        missing = verify_report(self.directory)
        self.assertEqual(missing["status"], "missing")
        self.assertIsNone(missing["actual_report_sha256"])
        self.assertEqual(missing["expected_report_sha256"], expected)

    def test_uncheckable_receipts_do_not_create_historical_baseline(self):
        cases = (
            ("absent", None),
            ("malformed", b"{not json}"),
            ("legacy", b'{"provider":"old"}'),
            ("bad_hash", b'{"report_sha256":"incorrect"}'),
            ("duplicate", b'{"report_sha256":"x","report_sha256":"y"}'),
            ("oversize", b"x" * (MAX_ARTIFACT_BYTES + 1)),
            ("deeply_nested", b'{"meta":' + b"[" * 5_000 + b"0" + b"]" * 5_000 + b"}"),
        )
        report_before = self.report.read_bytes()
        for name, payload in cases:
            with self.subTest(name=name):
                if payload is None:
                    self.receipt.unlink(missing_ok=True)
                else:
                    self.receipt.write_bytes(payload)
                before = self.receipt.read_bytes() if self.receipt.exists() else None
                result = verify_report(self.directory)
                self.assertEqual(result["status"], "uncheckable")
                self.assertIsNone(result["expected_report_sha256"])
                self.assertIsNone(result["actual_report_sha256"])
                self.assertEqual(self.report.read_bytes(), report_before)
                self.assertEqual(self.receipt.read_bytes() if self.receipt.exists() else None, before)

    def test_anchor_mismatch_skips_report_and_replaced_receipt_is_uncheckable(self):
        original_hash = hashlib.sha256(self.receipt.read_bytes()).hexdigest()
        self.write_receipt(note="replacement")
        original_reader = report_integrity._stable_named_file

        def receipt_only(directory, filename):
            if filename == "report.md":
                raise AssertionError("anchor mismatch must not read report")
            return original_reader(directory, filename)

        with patch.object(report_integrity, "_stable_named_file", side_effect=receipt_only):
            result = verify_report(self.directory, receipt_sha256=original_hash)
        self.assertEqual(result["status"], "uncheckable")
        self.assertIsNone(result["actual_report_sha256"])
        self.assertEqual(result["receipt_matches_expected"], False)
        self.assertEqual(result["expected_receipt_sha256"], original_hash)

    def test_unsafe_report_and_concurrent_change_are_uncheckable(self):
        original_stable = report_integrity._read_stable_file
        def unreadable_receipt(path, before, limit=MAX_ARTIFACT_BYTES):
            if path.name == "receipt.json":
                raise OSError("injected read failure")
            return original_stable(path, before, limit)
        with patch.object(report_integrity, "_read_stable_file", side_effect=unreadable_receipt):
            self.assertEqual(verify_report(self.directory)["status"], "uncheckable")

        self.report.write_bytes(b"x" * (MAX_ARTIFACT_BYTES + 1))
        self.assertEqual(verify_report(self.directory)["status"], "uncheckable")
        self.report.write_text("Restored report", encoding="utf-8")
        self.write_receipt()

        original_reader = report_integrity._stable_named_file

        def mutate_after_report(directory, filename):
            content = original_reader(directory, filename)
            if filename == "report.md":
                self.write_receipt(note="changed during check")
            return content

        with patch.object(report_integrity, "_stable_named_file", side_effect=mutate_after_report):
            changed_receipt = verify_report(self.directory)
        self.assertEqual(changed_receipt["status"], "uncheckable")
        self.assertIn("changed", changed_receipt["reason"])
        self.assertIsNone(changed_receipt["receipt_sha256"])

        def injected_change(path, before, limit=MAX_ARTIFACT_BYTES):
            if path.name == "report.md":
                raise SnapshotError("changed while reading")
            return original_stable(path, before, limit)
        with patch.object(report_integrity, "_read_stable_file", side_effect=injected_change):
            unstable = verify_report(self.directory)
        self.assertEqual(unstable["status"], "uncheckable")

        self.write_receipt()
        def add_entry_after_report(directory, filename):
            content = original_reader(directory, filename)
            if filename == "report.md":
                (self.directory / "concurrent.tmp").write_text("new entry", encoding="utf-8")
            return content
        with patch.object(report_integrity, "_stable_named_file", side_effect=add_entry_after_report):
            changed_directory = verify_report(self.directory)
        self.assertEqual(changed_directory["status"], "uncheckable")
        self.assertEqual(changed_directory["reason"], "directory changed during verification")

    def test_invalid_inputs_are_rejected(self):
        for digest in ("", "0" * 63, "g" * 64, 123, True):
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                verify_report(self.directory, receipt_sha256=digest)
        with self.assertRaises(ValueError):
            verify_report(self.root / "absent")
        with self.assertRaises(ValueError):
            verify_report(self.report)
        with self.assertRaises(ValueError):
            verify_report(None)

    def test_directory_receipt_and_report_links_are_rejected(self):
        linked_directory = self.root / "linked-directory"
        try:
            linked_directory.symlink_to(self.directory, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink creation is unavailable on this Windows host")
        with self.assertRaises(ValueError):
            verify_report(linked_directory)
        self.receipt.unlink()
        self.receipt.symlink_to(self.outside / "report.md")
        self.assertEqual(verify_report(self.directory)["status"], "uncheckable")
        self.receipt.unlink()
        self.write_receipt()
        self.report.unlink()
        self.report.symlink_to(self.outside / "report.md")
        self.assertEqual(verify_report(self.directory)["status"], "uncheckable")

    def test_simulated_reparse_files_are_rejected_without_following(self):
        real_snapshot_link = snapshots._is_link
        def mark_receipt(info, path):
            return path.name == "receipt.json" or real_snapshot_link(info, path)
        with patch.object(snapshots, "_is_link", side_effect=mark_receipt):
            self.assertEqual(verify_report(self.directory)["status"], "uncheckable")

        def mark_report(info, path):
            return path.name == "report.md" or real_snapshot_link(info, path)
        with patch.object(snapshots, "_is_link", side_effect=mark_report):
            self.assertEqual(verify_report(self.directory)["status"], "uncheckable")

        real_directory_link = report_integrity._is_link
        def mark_directory(info, path):
            return path == self.directory or real_directory_link(info, path)
        with patch.object(report_integrity, "_is_link", side_effect=mark_directory):
            with self.assertRaises(ValueError):
                verify_report(self.directory)


if __name__ == "__main__":
    unittest.main()
