"""Snapshot tests use only disposable local files and no provider/runtime."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agentrelay import snapshots
from agentrelay.snapshots import SnapshotError, create_snapshot, verify_snapshot


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-snapshot-")
        self.base = Path(self.temp.name)
        self.root = self.base / "project"
        self.root.mkdir()
        self.destinations = self.base / "snapshots"
        self.destinations.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def write(self, relative, data):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_exact_bytes_manifest_hash_and_stable_content_id(self):
        first = self.write("notes/á.txt", "línea\r\nsegunda".encode("utf-8"))
        second = self.write("data.bin", bytes(range(256)))
        manifest = create_snapshot(self.root, ["notes/á.txt", "data.bin"], self.destinations / "one")
        other = create_snapshot(self.root, ["data.bin", "notes/á.txt"], self.destinations / "two")

        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["snapshot_id"], other["snapshot_id"])
        self.assertEqual(manifest["content_sha256"], other["content_sha256"])
        self.assertEqual([entry["path"] for entry in manifest["files"]], ["data.bin", "notes/á.txt"])
        self.assertEqual((self.destinations / "one/files/notes/á.txt").read_bytes(), first.read_bytes())
        self.assertEqual((self.destinations / "one/files/data.bin").read_bytes(), second.read_bytes())
        self.assertEqual(manifest["files"][0]["sha256"], hashlib.sha256(second.read_bytes()).hexdigest())
        self.assertEqual(json.loads((self.destinations / "one/manifest.json").read_text(encoding="utf-8")), manifest)
        verification = verify_snapshot(self.destinations / "one")
        self.assertTrue(verification["valid"], verification)
        self.assertEqual(verification["snapshot_id"], manifest["snapshot_id"])

    def test_rejects_unbounded_ambiguous_and_non_file_sources(self):
        self.write("ok.txt", b"ok")
        (self.root / "folder").mkdir()
        invalid_sets = [
            ["../outside.txt"],
            [str((self.root / "ok.txt").resolve())],
            ["folder/../ok.txt"],
            ["folder//file.txt"],
            ["*.txt"],
            ["ok.txt", "ok.txt"],
            ["ok.txt", "OK.TXT"],
            ["ok.txt:stream"],
            ["CON"],
            ["name."],
            ["name "],
            ["folder"],
            [],
            [f"missing-{index}" for index in range(65)],
        ]
        for index, values in enumerate(invalid_sets):
            with self.subTest(values=values):
                destination = self.destinations / f"invalid-{index}"
                with self.assertRaises((SnapshotError, FileNotFoundError)):
                    create_snapshot(self.root, values, destination)
                self.assertFalse(destination.exists())
        with self.assertRaises(SnapshotError):
            create_snapshot(self.root, ["ok.txt"], self.root / "inside-snapshot")

    def test_preexisting_modified_file_and_windows_ctime_semantics(self):
        source = self.write("existing.txt", b"old content")
        source.write_bytes(b"final content after an earlier modification")
        manifest = create_snapshot(self.root, ["existing.txt"], self.destinations / "existing-file")
        self.assertEqual(
            (self.destinations / "existing-file/files/existing.txt").read_bytes(),
            b"final content after an earlier modification",
        )
        self.assertTrue(verify_snapshot(self.destinations / "existing-file")["valid"])

        path_stat = SimpleNamespace(st_dev=7, st_ino=9, st_size=12, st_mtime_ns=100, st_ctime_ns=20)
        handle_stat = SimpleNamespace(st_dev=7, st_ino=9, st_size=12, st_mtime_ns=100, st_ctime_ns=100)
        with patch("agentrelay.snapshots.os.name", "nt"):
            self.assertEqual(snapshots._signature(path_stat), snapshots._signature(handle_stat))
        with patch("agentrelay.snapshots.os.name", "posix"):
            self.assertNotEqual(snapshots._signature(path_stat), snapshots._signature(handle_stat))

    def test_rejects_file_and_total_size_limits(self):
        too_large = self.write("large.bin", b"x" * (snapshots.MAX_FILE_BYTES + 1))
        with self.assertRaises(SnapshotError):
            create_snapshot(self.root, [too_large.name], self.destinations / "large")

        names = []
        for index in range(9):
            name = f"chunk-{index}.bin"
            path = self.root / name
            with path.open("wb") as stream:
                stream.truncate(snapshots.MAX_FILE_BYTES)
            names.append(name)
        with self.assertRaises(SnapshotError):
            create_snapshot(self.root, names, self.destinations / "total")
        self.assertFalse((self.destinations / "total").exists())

    def test_existing_destination_is_preserved_and_failed_stage_is_removed(self):
        self.write("ok.txt", b"ok")
        existing = self.destinations / "existing"
        existing.mkdir()
        marker = existing / "owned.txt"
        marker.write_text("foreign", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            create_snapshot(self.root, ["ok.txt"], existing)
        self.assertEqual(marker.read_text(encoding="utf-8"), "foreign")

        failed = self.destinations / "failed"
        with patch("agentrelay.snapshots._read_stable_file", side_effect=SnapshotError("fixture failure")):
            with self.assertRaises(SnapshotError):
                create_snapshot(self.root, ["ok.txt"], failed)
        self.assertFalse(failed.exists())
        self.assertEqual(list(self.destinations.glob(".failed.staging-*")), [])

    def test_detects_source_change_during_read(self):
        source = self.write("moving.txt", b"original bytes")
        real_read = os.read
        changed = False

        def read_then_change(descriptor, amount):
            nonlocal changed
            data = real_read(descriptor, amount)
            if not changed:
                changed = True
                source.write_bytes(b"changed while snapshot was reading")
            return data

        with patch("agentrelay.snapshots.os.read", side_effect=read_then_change):
            with self.assertRaisesRegex(SnapshotError, "changed"):
                create_snapshot(self.root, ["moving.txt"], self.destinations / "moving")
        self.assertFalse((self.destinations / "moving").exists())

    def test_verification_reports_corruption_and_hostile_manifest_path(self):
        self.write("safe.txt", b"trusted")
        destination = self.destinations / "verify"
        create_snapshot(self.root, ["safe.txt"], destination)
        copied = destination / "files/safe.txt"
        copied.write_bytes(b"tampered")
        result = verify_snapshot(destination)
        self.assertFalse(result["valid"])
        self.assertTrue(any("mismatch" in error for error in result["errors"]), result)

        destination_two = self.destinations / "traversal"
        create_snapshot(self.root, ["safe.txt"], destination_two)
        manifest_path = destination_two / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"][0]["path"] = "../outside.txt"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        result = verify_snapshot(destination_two)
        self.assertFalse(result["valid"])
        self.assertTrue(any("traversal" in error for error in result["errors"]), result)

    def test_source_and_snapshot_symlinks_are_rejected_when_supported(self):
        outside = self.base / "outside.txt"
        outside.write_bytes(b"outside")
        source_link = self.root / "link.txt"
        try:
            source_link.symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks unavailable: {exc}")
        with self.assertRaisesRegex(SnapshotError, "symlink"):
            create_snapshot(self.root, ["link.txt"], self.destinations / "linked-source")

        self.write("real.txt", b"real")
        destination = self.destinations / "linked-copy"
        create_snapshot(self.root, ["real.txt"], destination)
        copied = destination / "files/real.txt"
        copied.unlink()
        copied.symlink_to(outside)
        result = verify_snapshot(destination)
        self.assertFalse(result["valid"])
        self.assertTrue(any("symlink" in error for error in result["errors"]), result)

    def test_verify_handles_missing_and_invalid_manifests(self):
        missing = self.destinations / "missing"
        missing.mkdir()
        self.assertFalse(verify_snapshot(missing)["valid"])
        invalid = self.destinations / "invalid-json"
        invalid.mkdir()
        (invalid / "manifest.json").write_text("not json", encoding="utf-8")
        self.assertFalse(verify_snapshot(invalid)["valid"])


if __name__ == "__main__":
    unittest.main()
