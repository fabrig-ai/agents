"""Gate smoke: syntax, public help and one fake-Codex happy path."""

import ast
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from codex_run_fixtures import KIT, run_suite


class LauncherTests(unittest.TestCase):
    def test_syntax(self):
        for name in ("codex-run", "test-codex-run"):
            subprocess.run(["/bin/bash", "-n", str(KIT / name)], check=True)
        for path in KIT.rglob("*.py"):
            ast.parse(path.read_text(), filename=str(path))

    def test_help(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([str(KIT / "codex-run"), "--help"],
                                    env=dict(os.environ, HOME=directory, DEV_ROOT=directory),
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("usage: codex-run", result.stdout)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_fake_codex_happy_path(self):
        run_suite(self, "--smoke")


if __name__ == "__main__":
    unittest.main()
