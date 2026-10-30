"""Gate smoke: syntax, public help and one fake-Codex happy path."""

import ast
import os
from pathlib import Path
import shutil
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

    def test_release_helpers_via_symlink_and_no_fabrig_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            kit = home / "release/tools/codex-run"
            kit.mkdir(parents=True)
            shutil.copy2(KIT / "codex-run", kit / "codex-run")
            slots = kit.parent / "slots"
            slots.mkdir()
            helper = slots / "lifetime.py"
            helper.write_text("import sys\nassert sys.argv[1] == 'root'\nprint(sys.argv[2])\n")
            legacy = home / "src/fabrig/main/tools/slots"
            legacy.mkdir(parents=True)
            marker = home / "legacy-helper-ran"
            (legacy / "lifetime.py").write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
            link = home / "codex-run"
            link.symlink_to(kit / "codex-run")
            env = dict(os.environ, HOME=directory, DEV_ROOT=directory)
            result = subprocess.run([str(link), "stale"], env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            helper.unlink()
            result = subprocess.run([str(link), "stale"], env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(str(helper), result.stderr)
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
