"""Bounded structured differences use frozen snapshot files only."""

import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agentrelay import snapshot_diff as service
from agentrelay.snapshots import SnapshotError, create_snapshot


class SnapshotDiffTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="agentrelay-snapshot-diff-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sequence = 0

    def capture(self, files):
        self.sequence += 1
        source = self.root / f"source-{self.sequence}"
        source.mkdir()
        for name, data in files.items():
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        snapshot = self.root / f"snapshot-{self.sequence}"
        manifest = create_snapshot(source, list(files), snapshot)
        return source, snapshot, manifest

    def compare(self, before, after, paths=None):
        return service.diff_snapshots(before[1], after[1],
            expected_before_id=before[2]["snapshot_id"],
            expected_after_id=after[2]["snapshot_id"], paths=paths)

    def test_real_long_shared_tail_short_insertion_and_exact_indices(self):
        original = [f"line {index:04d}" for index in range(2000)]
        changed = original[:900] + ["línea nueva"] + original[900:]
        before = self.capture({"notes.txt": ("\n".join(original) + "\n").encode()})
        after = self.capture({"notes.txt": ("\n".join(changed) + "\n").encode()})
        result = self.compare(before, after)
        self.assertEqual(result, self.compare(before, after))
        self.assertEqual(set(result), {"schema_version", "before_snapshot_id",
                                       "after_snapshot_id", "files", "summary"})
        self.assertEqual(result["summary"]["modified"], 1)
        difference = result["files"][0]["diff"]
        self.assertEqual(difference["status"], "available")
        self.assertIsNone(difference["reason"])
        self.assertEqual(len(difference["hunks"]), 1)
        hunk = difference["hunks"][0]
        self.assertEqual((hunk["before_start"], hunk["before_count"],
                          hunk["after_start"], hunk["after_count"]), (897, 6, 897, 7))
        self.assertEqual([line["kind"] for line in hunk["lines"]],
                         ["context"] * 3 + ["added"] + ["context"] * 3)
        self.assertEqual(hunk["lines"][3], {"kind": "added", "text": "línea nueva", "eol": "lf"})

    def test_union_add_remove_rename_and_empty_files(self):
        before = self.capture({"same.txt": b"same\n", "old.txt": b"old\n",
                               "empty.txt": b"", "rename-old.txt": b"renamed\n"})
        after = self.capture({"same.txt": b"same\n", "new.txt": b"new\n",
                              "empty.txt": b"", "added-empty.txt": b"",
                              "rename-new.txt": b"renamed\n"})
        report = self.compare(before, after)
        entries = {entry["path"]: entry for entry in report["files"]}
        self.assertEqual(list(entries), sorted(entries))
        self.assertEqual(report["summary"], {"total": 7, "unchanged": 2,
            "modified": 0, "added": 3, "removed": 2, "diff_available": 5,
            "diff_omitted": 0})
        self.assertEqual(entries["same.txt"]["diff"],
                         {"status": "not_needed", "reason": None, "hunks": []})
        self.assertIsNone(entries["new.txt"]["before"])
        self.assertIsNone(entries["old.txt"]["after"])
        self.assertEqual(entries["added-empty.txt"]["diff"],
                         {"status": "available", "reason": None, "hunks": []})
        self.assertEqual(entries["rename-old.txt"]["status"], "removed")
        self.assertEqual(entries["rename-new.txt"]["status"], "added")

    def test_eof_newline_crlf_and_bom_are_not_normalized(self):
        before = self.capture({"eof.txt": b"a", "crlf.txt": b"a\n",
                               "bom.txt": "a\n".encode("utf-8"), "lone.txt": b"a\r"})
        after = self.capture({"eof.txt": b"a\n", "crlf.txt": b"a\r\n",
                              "bom.txt": b"\xef\xbb\xbfa\n", "lone.txt": b"a\r\n"})
        entries = {entry["path"]: entry for entry in self.compare(before, after)["files"]}
        self.assertEqual({entry["status"] for entry in entries.values()}, {"modified"})
        eof = entries["eof.txt"]["diff"]["hunks"][0]
        self.assertEqual(eof["lines"], [{"kind": "removed", "text": "a", "eol": "none"},
                                        {"kind": "added", "text": "a", "eol": "lf"}])
        self.assertEqual(entries["crlf.txt"]["diff"]["hunks"][0]["lines"][-1]["eol"], "crlf")
        self.assertEqual(entries["bom.txt"]["diff"]["hunks"][0]["lines"][-1]["text"], "\ufeffa")
        self.assertEqual(entries["lone.txt"]["diff"]["hunks"][0]["lines"][0]["text"], "a\r")

    def test_binary_and_invalid_utf8_are_explicitly_omitted(self):
        before = self.capture({"bytes.bin": b"plain", "utf8.txt": b"text"})
        after = self.capture({"bytes.bin": b"zero\x00byte", "utf8.txt": b"\xff"})
        entries = {entry["path"]: entry for entry in self.compare(before, after)["files"]}
        self.assertEqual(entries["bytes.bin"]["diff"],
                         {"status": "omitted", "reason": "binary", "hunks": []})
        self.assertEqual(entries["utf8.txt"]["diff"],
                         {"status": "omitted", "reason": "invalid_utf8", "hunks": []})
        self.assertEqual(self.compare(before, after)["summary"]["diff_omitted"], 2)

    def test_ids_and_selectors_are_validated_before_any_snapshot_io(self):
        before = self.capture({"folder/a.txt": b"a"})
        after = self.capture({"folder/a.txt": b"b"})
        invalid = (
            {"expected_before_id": "sha256:" + "A" * 64},
            {"expected_after_id": None},
            {"paths": []}, {"paths": ["../escape"]}, {"paths": [42]},
            {"paths": ["folder/a.txt", "folder\\a.txt"]},
        )
        baseline = {"expected_before_id": before[2]["snapshot_id"],
                    "expected_after_id": after[2]["snapshot_id"]}
        with patch("agentrelay.snapshot_diff._verified_manifest",
                   side_effect=AssertionError("snapshot I/O began")):
            for change in invalid:
                with self.subTest(change=change), self.assertRaises(SnapshotError):
                    service.diff_snapshots(before[1], after[1], **{**baseline, **change})
        with self.assertRaises(SnapshotError):
            self.compare(before, after, paths=["unknown.txt"])
        self.assertEqual([item["path"] for item in self.compare(before, after,
                         paths=["folder\\a.txt"])["files"]], ["folder/a.txt"])

    def test_corruption_on_either_side_and_identity_mismatch_fail_closed(self):
        before = self.capture({"a.txt": b"before"})
        after = self.capture({"a.txt": b"after"})
        with self.assertRaises(SnapshotError):
            service.diff_snapshots(before[1], after[1], expected_before_id="sha256:" + "0" * 64,
                                   expected_after_id=after[2]["snapshot_id"])
        (before[1] / "files" / "a.txt").write_bytes(b"corrupt")
        with self.assertRaises(SnapshotError):
            self.compare(before, after)
        before = self.capture({"a.txt": b"before"})
        (after[1] / "files" / "a.txt").write_bytes(b"corrupt")
        with self.assertRaises(SnapshotError):
            self.compare(before, after)

    def test_mutation_during_selected_stable_read_is_not_partial_report(self):
        before = self.capture({"a.txt": b"old"})
        after = self.capture({"a.txt": b"new"})
        real_read = service._read_file
        mutated = False

        def change(path, before_info, limit):
            nonlocal mutated
            if not mutated:
                mutated = True
                path.write_bytes(b"changed during read")
            return real_read(path, before_info, limit)

        with patch("agentrelay.snapshot_diff._read_file", side_effect=change):
            with self.assertRaises(SnapshotError):
                self.compare(before, after)
        self.assertTrue(mutated)

    def test_never_reads_source_root_after_capture(self):
        before = self.capture({"a.txt": b"old"})
        after = self.capture({"a.txt": b"new"})
        before[0].rename(self.root / "moved-source-before")
        after[0].rename(self.root / "moved-source-after")
        self.assertEqual(self.compare(before, after)["summary"]["modified"], 1)

    def test_line_and_comparison_limits_omit_whole_file(self):
        before = self.capture({"a.txt": b"a\nb\nc\n"})
        after = self.capture({"a.txt": b"a\nx\nc\n"})
        with patch.object(service, "MAX_LINES", 2):
            entry = self.compare(before, after)["files"][0]
            self.assertEqual(service._lines(b"a\nb\nc\n"), (None, "line_limit"))
        self.assertEqual(entry["diff"], {"status": "omitted", "reason": "line_limit", "hunks": []})
        with patch.object(service, "MAX_COMPARISON_PRODUCT", 1):
            entry = self.compare(before, after)["files"][0]
        self.assertEqual(entry["diff"],
                         {"status": "omitted", "reason": "comparison_limit", "hunks": []})

    def test_case_only_path_change_is_removal_plus_addition(self):
        before = self.capture({"Foo.txt": b"same"})
        after = self.capture({"foo.txt": b"same"})
        entries = self.compare(before, after, paths=["Foo.txt", "foo.txt"])["files"]
        self.assertEqual([(entry["path"], entry["status"]) for entry in entries],
                         [("Foo.txt", "removed"), ("foo.txt", "added")])

    def test_output_limits_omit_whole_file_and_later_small_one_can_fit(self):
        before = self.capture({"a.txt": b"large old line", "b.txt": b"x"})
        after = self.capture({"a.txt": b"large new line", "b.txt": b"y"})
        large = len(service._canonical_bytes(service._hunks(
            [("large old line", "none")], [("large new line", "none")])[0]))
        small = len(service._canonical_bytes(service._hunks(
            [("x", "none")], [("y", "none")])[0]))
        self.assertLess(small, large)
        with patch.object(service, "MAX_HUNKS_BYTES", small):
            entries = self.compare(before, after)["files"]
        self.assertEqual(entries[0]["diff"]["reason"], "output_limit")
        self.assertEqual(entries[1]["diff"]["status"], "available")
        with patch.object(service, "MAX_TOTAL_HUNKS_BYTES", small):
            entries = self.compare(before, after)["files"]
        self.assertEqual(entries[0]["diff"]["reason"], "output_limit")
        self.assertEqual(entries[1]["diff"]["status"], "available")
        with patch.object(service, "MAX_REPORT_BYTES", 100):
            with self.assertRaisesRegex(SnapshotError, "select fewer --file"):
                self.compare(before, after)

    def test_snapshot_symlink_is_rejected_when_available(self):
        before = self.capture({"a.txt": b"old"})
        after = self.capture({"a.txt": b"new"})
        target = before[1] / "files" / "a.txt"
        alias = before[1] / "files" / "alias.txt"
        try:
            os.symlink(target, alias)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable on this host")
        # An extra unlisted symlink is ignored by the snapshot verifier. Replace
        # the selected file itself to exercise the selected-path safety rule.
        target.unlink()
        try:
            os.symlink(after[1] / "files" / "a.txt", target)
        except (OSError, NotImplementedError):
            self.skipTest("symlink replacement unavailable on this host")
        with self.assertRaises(SnapshotError):
            self.compare(before, after)


if __name__ == "__main__":
    unittest.main()
