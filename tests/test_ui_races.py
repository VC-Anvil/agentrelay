from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


NODE = shutil.which("node")


class UiRaceNodeTests(unittest.TestCase):
    @unittest.skipUnless(NODE, "Node.js no está disponible; se omite el arnés JavaScript de carreras UI")
    def test_real_app_javascript_race_guards(self) -> None:
        script = Path(__file__).with_suffix(".js")
        result = subprocess.run(
            [NODE, str(script)],
            cwd=script.parents[1],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
        details = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
        self.assertEqual(result.returncode, 0, details or "El arnés Node terminó sin diagnóstico")
        self.assertIn("4 pruebas de carreras UI superadas", result.stdout)


if __name__ == "__main__":
    unittest.main()
