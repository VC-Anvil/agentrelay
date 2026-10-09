"""Adapter CLI artifacts stay outside the provider's working directory when requested."""

import contextlib
import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agentrelay import adapters


PACKET = {
    "protocol": "agentrelay.worker.v1",
    "context": {"ticket": {"id": "AR-9001", "title": "Auditar proyecto"}},
    "worker": {"id": "fixture", "model": "local-fixture", "effort": "none"},
}

RESULT = {
    "outcome": "submit", "summary": "Informe local preparado", "artifact_markdown": "# Informe\n\nSin cambios en el proyecto.\n",
    "evidence": [], "title": "", "description": "", "profile_id": None, "children": [],
}

FAKE_CODEX = r'''
import json, pathlib, sys
args = sys.argv[1:]
assert "--sandbox" in args and args[args.index("--sandbox")+1] == "read-only"
assert "--model" in args and args[args.index("--model")+1] == "gpt-6-sol"
assert "--output-schema" in args
schema = pathlib.Path(args[args.index("--output-schema")+1])
assert schema.is_file()
prompt = sys.stdin.read()
assert "Auditar proyecto" in prompt
output = pathlib.Path(args[args.index("--output-last-message")+1])
result = {"outcome":"submit","summary":"Revisión simulada","artifact_markdown":"# Reporte\n\nPrueba simulada.\n",
          "evidence":[],"title":"","description":"","profile_id":None,"children":[]}
output.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
'''


class AdapterArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="agentrelay-adapter-")
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / "existing.txt").write_text("unchanged", encoding="utf-8")
        self.packet = dict(PACKET)
    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, adapter, *args, packet=None):
        return subprocess.run([sys.executable, "-m", "agentrelay.adapters", adapter, *map(str, args)],
                              input=json.dumps(packet or self.packet, ensure_ascii=False).encode("utf-8"),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=self.project,
                              env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                                   "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
                              timeout=10, check=False)

    def cli_ollama(self, *args):
        """Exercise CLI parsing and persistence with a fixed provider response."""
        stdout, stderr = io.StringIO(), io.StringIO()
        previous = Path.cwd()
        try:
            os.chdir(self.project)
            with patch.object(adapters, "read_input", return_value=self.packet), \
                 patch.object(adapters, "ollama", return_value=copy.deepcopy(RESULT)), \
                 contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = adapters.main(["ollama", *map(str, args)])
        finally:
            os.chdir(previous)
        return SimpleNamespace(returncode=code, stdout=stdout.getvalue().encode("utf-8"),
                               stderr=stderr.getvalue().encode("utf-8"))

    def assert_receipt(self, base, cli_result, provider):
        self.assertEqual(cli_result.returncode, 0, cli_result.stderr.decode("utf-8", "replace"))
        result = json.loads(cli_result.stdout)
        children = [path for path in base.iterdir() if path.is_dir()]
        self.assertEqual(len(children), 1)
        artifacts = children[0]
        receipt = json.loads((artifacts / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["provider"], provider)
        self.assertEqual(receipt["cwd"], str(self.project.resolve()))
        self.assertEqual(receipt["artifacts_dir"], str(artifacts.resolve()))
        self.assertEqual(receipt["ticket_id"], "AR-9001")
        self.assertEqual(result["evidence"][-1]["uri"], str(artifacts / "report.md"))
        self.assertIn("#", (artifacts / "report.md").read_text(encoding="utf-8"))
        return artifacts

    def test_ollama_relative_base_is_outside_project_and_reusable(self):
        base = self.root / "audit-output"
        original = sorted(str(path.relative_to(self.project)) for path in self.project.rglob("*"))
        first = self.cli_ollama("--artifacts-dir", "../audit-output")
        first_dir = self.assert_receipt(base, first, "ollama")
        second = self.cli_ollama("--artifacts-dir", "../audit-output")
        self.assertEqual(second.returncode, 0, second.stderr.decode("utf-8", "replace"))
        children = [path for path in base.iterdir() if path.is_dir()]
        self.assertEqual(len(children), 2)
        self.assertTrue((first_dir / "report.md").is_file())
        self.assertEqual(original, sorted(str(path.relative_to(self.project)) for path in self.project.rglob("*")))

    def test_codex_absolute_base_preserves_cwd_and_sandbox(self):
        (self.project / "exec").write_text(FAKE_CODEX, encoding="utf-8")
        original = sorted(str(path.relative_to(self.project)) for path in self.project.rglob("*"))
        base = self.root / "codex-artifacts"
        packet = {**self.packet, "worker": {**self.packet["worker"], "model": "gpt-6-sol", "effort": "high"}}
        result = self.cli("codex", "--executable", sys.executable, "--artifacts-dir", base, packet=packet)
        artifacts = self.assert_receipt(base, result, "codex")
        self.assertTrue((artifacts / "schema.json").is_file())
        self.assertTrue((artifacts / "response.json").is_file())
        self.assertEqual(original, sorted(str(path.relative_to(self.project)) for path in self.project.rglob("*")))

    def test_invalid_artifact_base_is_error_without_project_writes(self):
        blocker = self.root / "not-a-directory"
        blocker.write_text("keep", encoding="utf-8")
        original = sorted(str(path.relative_to(self.project)) for path in self.project.rglob("*"))
        result = self.cli("ollama", "--artifacts-dir", blocker)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Adapter failed", result.stderr.decode("utf-8", "replace"))
        self.assertEqual(blocker.read_text(encoding="utf-8"), "keep")
        self.assertEqual(original, sorted(str(path.relative_to(self.project)) for path in self.project.rglob("*")))

    def test_default_artifact_base_is_unchanged(self):
        result = self.cli_ollama()
        self.assert_receipt(self.project / ".agentrelay" / "artifacts", result, "ollama")


if __name__ == "__main__":
    unittest.main()
