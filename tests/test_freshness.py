"""Read-only freshness comparison tests; no provider, server, or database."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agentrelay import freshness
from agentrelay.freshness import compare_snapshot
from agentrelay.snapshots import SnapshotError, create_snapshot, verify_snapshot


class FreshnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-freshness-")
        self.base = Path(self.temp.name)
        self.original = self.base / "original"
        self.current = self.base / "current"
        self.snapshots = self.base / "snapshots"
        self.original.mkdir()
        self.current.mkdir()
        self.snapshots.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def write(self, root: Path, relative: str, data: bytes) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def snapshot(self, files: dict[str, bytes], name: str = "one") -> tuple[Path, dict]:
        for relative, data in files.items():
            self.write(self.original, relative, data)
            self.write(self.current, relative, data)
        directory = self.snapshots / name
        manifest = create_snapshot(self.original, list(files), directory)
        return directory, manifest

    def by_path(self, result: dict) -> dict[str, dict]:
        return {entry["path"]: entry for entry in result["files"]}

    def test_classifies_unchanged_modified_missing_and_same_size_change(self):
        directory, manifest = self.snapshot({
            "same.txt": b"same",
            "changed.txt": b"short",
            "same-size.bin": b"abcde",
            "missing.txt": b"gone",
        })
        self.write(self.current, "changed.txt", b"a longer current value")
        self.write(self.current, "same-size.bin", b"edcba")
        (self.current / "missing.txt").unlink()

        result = compare_snapshot(directory, self.current)
        entries = self.by_path(result)
        self.assertEqual(result["snapshot_id"], manifest["snapshot_id"])
        self.assertEqual(Path(result["root"]), self.current.resolve())
        self.assertEqual(entries["same.txt"]["status"], "unchanged")
        self.assertEqual(entries["changed.txt"]["status"], "modified")
        self.assertEqual(entries["same-size.bin"]["status"], "modified")
        self.assertEqual(entries["same-size.bin"]["current"]["size"], entries["same-size.bin"]["expected"]["size"])
        self.assertNotEqual(entries["same-size.bin"]["current"]["sha256"], entries["same-size.bin"]["expected"]["sha256"])
        self.assertEqual(entries["missing.txt"]["status"], "missing")
        self.assertEqual(entries["missing.txt"]["current"], {"size": None, "sha256": None})
        self.assertEqual(result["summary"], {"total": 4, "unchanged": 1, "modified": 2, "missing": 1, "uncheckable": 0})

    def test_invalid_snapshot_fails_before_current_root_is_inspected(self):
        directory, _ = self.snapshot({"file.txt": b"captured"})
        (directory / "files/file.txt").write_bytes(b"corrupt")
        self.assertFalse(verify_snapshot(directory)["valid"])
        with patch("agentrelay.freshness._prepare_current_root") as prepare:
            with self.assertRaisesRegex(SnapshotError, "invalid snapshot"):
                compare_snapshot(directory, self.current)
        prepare.assert_not_called()

    def test_traversal_manifest_is_invalid_before_root_access(self):
        directory, _ = self.snapshot({"safe.txt": b"safe"}, "traversal")
        manifest_path = directory / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"][0]["path"] = "../outside.txt"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with patch("agentrelay.freshness._prepare_current_root") as prepare:
            with self.assertRaisesRegex(SnapshotError, "invalid snapshot"):
                compare_snapshot(directory, self.current)
        prepare.assert_not_called()

    def test_explicit_root_is_used_and_manifest_source_root_is_never_read(self):
        directory, manifest = self.snapshot({"data.txt": b"captured"}, "explicit-root")
        manifest_path = directory / "manifest.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["source_root"] = str(self.base / "must-not-be-read")
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")
        self.write(self.current, "data.txt", b"current!")
        shutil.rmtree(self.original)

        result = compare_snapshot(directory, self.current)
        self.assertEqual(result["snapshot_id"], manifest["snapshot_id"])
        self.assertEqual(result["files"][0]["status"], "modified")
        self.assertEqual(Path(result["root"]), self.current.resolve())

    def test_unstable_current_read_is_uncheckable_not_missing(self):
        directory, _ = self.snapshot({"moving.txt": b"before"}, "unstable")
        with patch("agentrelay.freshness._read_current_file", side_effect=SnapshotError("file changed while reading")):
            result = compare_snapshot(directory, self.current)
        entry = result["files"][0]
        self.assertEqual(entry["status"], "uncheckable")
        self.assertIn("changed while reading", entry["reason"])
        self.assertEqual(result["summary"]["missing"], 0)

    def test_io_error_is_reported_per_file_and_other_files_are_compared(self):
        directory, _ = self.snapshot({"a.txt": b"first", "b.txt": b"second"}, "io-error")
        read_file = freshness._read_current_file

        def interrupted_read(path, before, limit):
            if path.name == "a.txt":
                raise OSError("device read failed")
            return read_file(path, before, limit)

        with patch("agentrelay.freshness._read_current_file", side_effect=interrupted_read):
            result = compare_snapshot(directory, self.current)
        entries = self.by_path(result)
        self.assertEqual(entries["a.txt"]["status"], "uncheckable")
        self.assertIn("device read failed", entries["a.txt"]["reason"])
        self.assertEqual(entries["b.txt"]["status"], "unchanged")
        self.assertEqual(result["summary"]["missing"], 0)

    def test_snapshot_identity_change_around_manifest_is_rejected(self):
        directory, manifest = self.snapshot({"stable.txt": b"stable"}, "identity")
        valid = {"valid": True, "errors": [], "snapshot_id": manifest["snapshot_id"]}
        changed = {"valid": True, "errors": [], "snapshot_id": "sha256:" + "0" * 64}
        with patch("agentrelay.freshness._snapshots.verify_snapshot", side_effect=[valid, changed]):
            with patch("agentrelay.freshness._prepare_current_root") as prepare:
                with self.assertRaisesRegex(SnapshotError, "identity changed"):
                    compare_snapshot(directory, self.current)
        prepare.assert_not_called()

    def test_unsafe_current_component_and_non_regular_file_are_uncheckable(self):
        directory, _ = self.snapshot({"unsafe.txt": b"safe", "folder.txt": b"file"}, "unsafe")
        (self.current / "folder.txt").unlink()
        (self.current / "folder.txt").mkdir()
        real_is_link = freshness._is_link

        def mark_one_unsafe(info, path):
            return Path(path).name == "unsafe.txt" or real_is_link(info, path)

        with patch("agentrelay.freshness._is_link", side_effect=mark_one_unsafe):
            result = compare_snapshot(directory, self.current)
        entries = self.by_path(result)
        self.assertEqual(entries["unsafe.txt"]["status"], "uncheckable")
        self.assertIn("reparse", entries["unsafe.txt"]["reason"])
        self.assertEqual(entries["folder.txt"]["status"], "uncheckable")
        self.assertIn("regular file", entries["folder.txt"]["reason"])
        self.assertEqual(result["summary"]["missing"], 0)

    def test_current_symlink_is_uncheckable_when_supported(self):
        directory, _ = self.snapshot({"link.txt": b"captured"}, "symlink")
        outside = self.base / "outside.txt"
        outside.write_bytes(b"outside")
        link = self.current / "link.txt"
        link.unlink()
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks unavailable: {exc}")
        result = compare_snapshot(directory, self.current)
        self.assertEqual(result["files"][0]["status"], "uncheckable")
        self.assertEqual(result["summary"]["missing"], 0)

    def test_current_file_and_total_read_limits_produce_uncheckable(self):
        directory, _ = self.snapshot({"a.bin": b"aa", "b.bin": b"bb"}, "limits")
        with patch("agentrelay.freshness.MAX_FILE_BYTES", 1):
            per_file = compare_snapshot(directory, self.current)
        self.assertEqual(per_file["summary"]["uncheckable"], 2)
        self.assertTrue(all("exceeds" in entry["reason"] for entry in per_file["files"]))

        with patch("agentrelay.freshness.MAX_TOTAL_BYTES", 3):
            total = compare_snapshot(directory, self.current)
        self.assertEqual(total["summary"]["unchanged"], 1)
        self.assertEqual(total["summary"]["uncheckable"], 1)
        self.assertTrue(any("comparison would exceed" in entry["reason"] for entry in total["files"]))

    def test_failed_reads_reserve_total_budget_before_later_attempts(self):
        directory, _ = self.snapshot({"a.bin": b"aa", "b.bin": b"bb", "c.bin": b"cc"}, "failed-budget")
        with patch("agentrelay.freshness.MAX_TOTAL_BYTES", 4):
            with patch("agentrelay.freshness._read_current_file", side_effect=SnapshotError("racing read")) as reader:
                result = compare_snapshot(directory, self.current)
        self.assertEqual(reader.call_count, 2)
        self.assertEqual(result["summary"]["uncheckable"], 3)
        self.assertIn("comparison would exceed", self.by_path(result)["c.bin"]["reason"])


if __name__ == "__main__":
    unittest.main()
