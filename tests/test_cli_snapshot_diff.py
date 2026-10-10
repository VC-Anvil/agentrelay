"""Subprocess coverage for the local, database-free snapshot diff CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from agentrelay.snapshots import create_snapshot


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CliSnapshotDiffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrelay-snapshot-diff-cli-")
        self.root = Path(self.temp.name)
        self.before_root = self.root / "fuente-antes"
        self.after_root = self.root / "fuente-después"
        self.before_root.mkdir()
        self.after_root.mkdir()
        self.before_dir = self.root / "captura-antes"
        self.after_dir = self.root / "captura-después"

        before = {
            "igual.txt": "igual\n".encode(),
            "cambio.txt": "cabecera\nlínea antigua\nfinal\n".encode("utf-8"),
            "retirado.txt": b"retirado\n",
        }
        after = {
            "igual.txt": "igual\n".encode(),
            "cambio.txt": "cabecera\nlínea nueva\nfinal\n".encode("utf-8"),
            "añadido.txt": "añadido\n".encode("utf-8"),
        }
        self.before_manifest = self.make_snapshot(
            self.before_root, self.before_dir, before)
        self.after_manifest = self.make_snapshot(
            self.after_root, self.after_dir, after)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def make_snapshot(source: Path, destination: Path, files: dict[str, bytes]) -> dict:
        for relative, content in files.items():
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return create_snapshot(source, list(files), destination)

    def command(self, *extra: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        current_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (str(PROJECT_ROOT) if not current_path else
                                      str(PROJECT_ROOT) + os.pathsep + current_path)
        arguments = [
            sys.executable, "-m", "agentrelay", "diff-snapshots",
            "--before", str(self.before_dir),
            "--after", str(self.after_dir),
            "--expected-before-id", self.before_manifest["snapshot_id"],
            "--expected-after-id", self.after_manifest["snapshot_id"],
            *extra,
        ]
        return subprocess.run(
            arguments, cwd=self.root, env=environment, capture_output=True,
            text=True, encoding="utf-8", timeout=20)

    def assert_no_database(self):
        self.assertFalse((self.root / ".agentrelay").exists())
        self.assertFalse(any(self.root.rglob("*.sqlite")))

    def snapshot_bytes(self):
        return {
            str(path.relative_to(self.root)): path.read_bytes()
            for directory in (self.before_dir, self.after_dir)
            for path in directory.rglob("*") if path.is_file()
        }

    def test_union_reports_structured_changes_exit_two_without_database(self):
        snapshots_before = self.snapshot_bytes()
        process = self.command()

        self.assertEqual(process.returncode, 2, process.stderr)
        self.assertFalse(process.stderr)
        report = json.loads(process.stdout)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["before_snapshot_id"], self.before_manifest["snapshot_id"])
        self.assertEqual(report["after_snapshot_id"], self.after_manifest["snapshot_id"])
        self.assertEqual(report["summary"]["total"], 4)
        by_path = {entry["path"]: entry for entry in report["files"]}
        self.assertEqual(list(by_path), sorted(by_path))
        self.assertEqual(by_path["igual.txt"]["status"], "unchanged")
        self.assertEqual(by_path["retirado.txt"]["status"], "removed")
        self.assertEqual(by_path["añadido.txt"]["status"], "added")
        changed = by_path["cambio.txt"]
        self.assertEqual(changed["status"], "modified")
        self.assertEqual(changed["diff"]["status"], "available")
        self.assertTrue(changed["diff"]["hunks"])
        kinds = {line["kind"] for hunk in changed["diff"]["hunks"]
                 for line in hunk["lines"]}
        self.assertTrue({"removed", "added"}.issubset(kinds))
        self.assertEqual(self.snapshot_bytes(), snapshots_before)
        self.assert_no_database()

    def test_explicit_unchanged_selection_exits_zero_and_preserves_utf8(self):
        process = self.command("--file", "igual.txt")

        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertFalse(process.stderr)
        report = json.loads(process.stdout)
        self.assertEqual(report["summary"], {
            "total": 1,
            "unchanged": 1,
            "modified": 0,
            "added": 0,
            "removed": 0,
            "diff_available": 0,
            "diff_omitted": 0,
        })
        self.assertEqual(report["files"][0]["path"], "igual.txt")
        self.assertEqual(report["files"][0]["diff"], {
            "status": "not_needed", "reason": None, "hunks": []})
        self.assert_no_database()

    def test_service_errors_are_concise_and_emit_no_success_json(self):
        unknown = self.command("--file", "desconocido.txt")
        self.assertEqual(unknown.returncode, 1)
        self.assertFalse(unknown.stdout)
        self.assertIn("Snapshot diff failed:", unknown.stderr)
        self.assertNotIn("Traceback", unknown.stderr)

        wrong_id = "sha256:" + "0" * 64
        mismatch = self.command("--expected-after-id", wrong_id)
        # The repeated option overrides the earlier argparse value.
        self.assertEqual(mismatch.returncode, 1)
        self.assertFalse(mismatch.stdout)
        self.assertIn("Snapshot diff failed:", mismatch.stderr)
        self.assertNotIn("Traceback", mismatch.stderr)

        (self.after_dir / "files" / "igual.txt").write_bytes(b"corrupt")
        corrupt = self.command()
        self.assertEqual(corrupt.returncode, 1)
        self.assertFalse(corrupt.stdout)
        self.assertIn("Snapshot diff failed:", corrupt.stderr)
        self.assertNotIn("Traceback", corrupt.stderr)
        self.assert_no_database()

    def test_malformed_usage_exits_two_before_filesystem_or_database(self):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(PROJECT_ROOT)
        snapshots_before = self.snapshot_bytes()
        cases = (
            ["--before", "missing-before", "--after", "missing-after",
             "--expected-before-id", "not-a-snapshot-id",
             "--expected-after-id", "sha256:" + "1" * 64],
            ["--before", "missing-before", "--after", "missing-after",
             "--expected-before-id", "sha256:" + "0" * 64],
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                process = subprocess.run([
                    sys.executable, "-m", "agentrelay", "diff-snapshots", *arguments,
                ], cwd=self.root, env=environment, capture_output=True, text=True,
                    encoding="utf-8", timeout=20)

                self.assertEqual(process.returncode, 2)
                self.assertFalse(process.stdout)
                self.assertIn("usage:", process.stderr.lower())
                self.assertNotIn("Traceback", process.stderr)
        self.assertEqual(self.snapshot_bytes(), snapshots_before)
        self.assert_no_database()


if __name__ == "__main__":
    unittest.main()
