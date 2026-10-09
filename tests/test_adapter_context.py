"""Snapshot context tests use fixed provider replies; no model is contacted."""

import contextlib
import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentrelay import adapters
from agentrelay.snapshots import create_snapshot


PACKET = {
    "protocol": "agentrelay.worker.v1",
    "context": {"ticket": {"id": "AR-0900", "title": "Auditar lectura"}, "dependencies": []},
    "worker": {"id": "fixture", "model": "fixture-model", "effort": "none"},
}

RESULT = {
    "outcome": "submit", "summary": "Informe simulado", "artifact_markdown": "# Informe\n\nFuente leída.\n",
    "evidence": [], "title": "", "description": "", "profile_id": None, "children": [],
}


class AdapterContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="agentrelay-context-")
        self.root = Path(self.tmp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.snapshots = self.root / "snapshots"
        self.snapshots.mkdir()
        self.artifacts = self.root / "artifacts"
        self.packet = copy.deepcopy(PACKET)

    def tearDown(self):
        self.tmp.cleanup()

    def snapshot(self, name="one", payload=b"Secci\xc3\xb3n: ni\xc3\xb1o y acci\xc3\xb3n.\n"):
        source_file = self.source / "notes.txt"
        source_file.write_bytes(payload)
        directory = self.snapshots / name
        manifest = create_snapshot(self.source, ["notes.txt"], directory)
        return directory, manifest

    def main_with_provider(self, adapter, directory, *, packet=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        supplied = packet or self.packet
        with patch.object(adapters, "read_input", return_value=supplied), \
             patch.object(adapters, "codex", return_value=copy.deepcopy(RESULT)) as codex_provider, \
             patch.object(adapters, "ollama", return_value=copy.deepcopy(RESULT)) as ollama_provider, \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = adapters.main([adapter, "--input-snapshot", str(directory),
                                  "--artifacts-dir", str(self.artifacts)])
        return code, stdout.getvalue(), stderr.getvalue(), codex_provider, ollama_provider

    def test_exact_unicode_context_deep_copy_and_receipt_for_both_adapters(self):
        directory, manifest = self.snapshot()
        (self.source / "notes.txt").unlink()  # Source is no longer needed after capture.
        original = copy.deepcopy(self.packet)
        for adapter in ("codex", "ollama"):
            with self.subTest(adapter=adapter):
                code, stdout, stderr, codex_provider, ollama_provider = self.main_with_provider(adapter, directory)
                self.assertEqual(code, 0, stderr)
                selected = codex_provider if adapter == "codex" else ollama_provider
                other = ollama_provider if adapter == "codex" else codex_provider
                selected.assert_called_once()
                other.assert_not_called()
                self.assertTrue(selected.call_args.kwargs["snapshot_verified"])
                delivered = selected.call_args.args[0]
                included = delivered["context"]["input_snapshot"]
                self.assertEqual(included["snapshot_id"], manifest["snapshot_id"])
                self.assertEqual(included["captured_at"], manifest["captured_at"])
                self.assertEqual(included["source_root"], manifest["source_root"])
                self.assertEqual(included["files"], [{"path": "notes.txt", "sha256": manifest["files"][0]["sha256"],
                                                       "size": manifest["files"][0]["size"],
                                                       "text": "Sección: niño y acción.\n"}])
                self.assertEqual(self.packet, original)
                result = json.loads(stdout)
                report = Path(result["evidence"][-1]["uri"])
                receipt = json.loads(report.with_name("receipt.json").read_text(encoding="utf-8"))
                self.assertEqual(result["evidence"][0]["kind"], "receipt")
                self.assertEqual(Path(result["evidence"][0]["uri"]), report.with_name("receipt.json"))
                self.assertEqual(receipt["report_sha256"], hashlib.sha256(report.read_bytes()).hexdigest())
                self.assertEqual(receipt["snapshot_id"], manifest["snapshot_id"])
                self.assertEqual(receipt["manifest_sha256"],
                                 hashlib.sha256((directory / "manifest.json").read_bytes()).hexdigest())

    def test_corrupted_snapshot_rejected_before_provider_or_artifacts(self):
        directory, _ = self.snapshot()
        (directory / "files" / "notes.txt").write_text("changed", encoding="utf-8")
        for adapter in ("codex", "ollama"):
            code, _, stderr, codex_provider, ollama_provider = self.main_with_provider(adapter, directory)
            self.assertEqual(code, 1)
            self.assertIn("Invalid input snapshot", stderr)
            codex_provider.assert_not_called()
            ollama_provider.assert_not_called()
        self.assertFalse(self.artifacts.exists())

    def test_binary_utf8_and_oversize_text_rejected_before_provider(self):
        for name, payload in (("binary", b"\x00\xff"), ("controls", b"abc\x00def"),
                              ("oversize", b"a" * 600_000)):
            with self.subTest(name=name):
                directory, _ = self.snapshot(name, payload)
                code, _, stderr, codex_provider, ollama_provider = self.main_with_provider("codex", directory)
                self.assertEqual(code, 1)
                self.assertIn("Adapter failed", stderr)
                codex_provider.assert_not_called()
                ollama_provider.assert_not_called()
        self.assertFalse(self.artifacts.exists())

    def test_invalid_snapshot_directory_rejected(self):
        missing = self.snapshots / "missing"
        code, _, stderr, codex_provider, ollama_provider = self.main_with_provider("ollama", missing)
        self.assertEqual(code, 1)
        self.assertIn("Invalid input snapshot", stderr)
        codex_provider.assert_not_called()
        ollama_provider.assert_not_called()

    def test_without_flag_packet_and_receipt_keep_existing_shape(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        original = copy.deepcopy(self.packet)
        with patch.object(adapters, "read_input", return_value=self.packet), \
             patch.object(adapters, "ollama", return_value=copy.deepcopy(RESULT)) as provider, \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = adapters.main(["ollama", "--artifacts-dir", str(self.artifacts)])
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(provider.call_args.args[0], original)
        self.assertFalse(provider.call_args.kwargs["snapshot_verified"])
        report = Path(json.loads(stdout.getvalue())["evidence"][-1]["uri"])
        receipt = json.loads(report.with_name("receipt.json").read_text(encoding="utf-8"))
        self.assertNotIn("snapshot_id", receipt)
        self.assertNotIn("manifest_sha256", receipt)


if __name__ == "__main__":
    unittest.main()
