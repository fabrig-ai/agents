"""The gate discovers nested tests and propagates failures in disposable trees."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

GATE = Path(__file__).with_name("check.sh")


class GateTests(unittest.TestCase):
    def run_gate(self, sources):
        with tempfile.TemporaryDirectory(prefix="gate-test-") as temp:
            root = Path(temp)
            home = root / "home"
            home.mkdir()
            tools = root / "tools"
            tools.mkdir()
            (tools / "check.sh").write_bytes(GATE.read_bytes())
            for name, content in sources.items():
                path = tools / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            result = subprocess.run(["bash", str(tools / "check.sh")],
                                    env=dict(os.environ, HOME=str(home)),
                                    capture_output=True, text=True)
            self.assertFalse(list(root.rglob("__pycache__")))
            return result

    def test_nested_files_and_repeated_basenames(self):
        source = "import unittest\nclass T(unittest.TestCase):\n def test_ok(self): pass\n"
        result = self.run_gate({name: source for name in
                               ("test_same.py", "records/test_same.py", "session/deep/test_same.py")})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Ran 3 tests", result.stderr)

    def test_nested_failure_fails_gate(self):
        result = self.run_gate({"records/deep/test_bad.py":
                               "import unittest\nclass T(unittest.TestCase):\n def test_bad(self): self.fail('nested failure')\n"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("nested failure", result.stderr)

    def test_import_failure_fails_gate(self):
        result = self.run_gate({"session/test_bad.py": "raise RuntimeError('broken import')\n"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("broken import", result.stderr)


if __name__ == "__main__":
    unittest.main()
