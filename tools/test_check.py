"""The gate discovers nested tests and propagates failures in disposable trees."""
import fcntl
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

GATE = Path(__file__).with_name("check.sh")


class GateTests(unittest.TestCase):
    def run_gate(self, sources, *files):
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
            result = subprocess.run(["bash", str(tools / "check.sh"), *files],
                                    env={k: v for k, v in dict(os.environ, HOME=str(home)).items()
                                         if k not in ("AGENTS_GATE_HELD", "AGENTS_GATE_LOCK")},
                                    capture_output=True, text=True)
            self.assertFalse(list(root.rglob("__pycache__")))
            return result

    def test_nested_files_and_repeated_basenames(self):
        source = "import unittest\nclass T(unittest.TestCase):\n def test_ok(self): pass\n"
        result = self.run_gate({name: source for name in
                               ("test_same.py", "records/test_same.py", "session/deep/test_same.py")})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr.count("Ran 1 test"), 3)
        self.assertIn("Checked 3 files", result.stderr)

    def test_focused_files_are_sorted_and_deduplicated(self):
        source = "import unittest\nclass T(unittest.TestCase):\n def test_ok(self): pass\n"
        result = self.run_gate({"test_z.py": source, "test_a.py": source,
                                "test_unselected.py": "raise RuntimeError('unselected')"},
                               "tools/test_z.py", "tools/test_a.py", "tools/test_z.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Checked 2 files", result.stderr)
        self.assertLess(result.stderr.index("=== tools/test_a.py"),
                        result.stderr.index("=== tools/test_z.py"))
        self.assertNotIn("unselected", result.stderr)

    def test_invalid_focused_file_fails_before_running_tests(self):
        for path in ("tools/missing.py", "tools/helper.py", "../test_outside.py"):
            with self.subTest(path=path):
                result = self.run_gate({"test_valid.py": "raise RuntimeError('should not run')",
                                        "helper.py": ""}, path)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("expected a tools/test_*.py file", result.stderr)
                self.assertNotIn("should not run", result.stderr)

    @unittest.skipIf((os.cpu_count() or 1) < 2, "parallelism needs two CPUs")
    def test_files_overlap_with_separate_homes_and_temp_roots(self):
        # Both imports must reach a barrier before either can complete. The
        # marker directory belongs to run_gate's disposable fixture tree.
        source = r'''import os
from pathlib import Path
import tempfile
import time
import unittest
root = Path(__file__).parent
name = Path(__file__).stem
home, temp = Path.home(), Path(tempfile.gettempdir())
assert home.parent == temp and home.is_dir()
marker = root / (name + ".ready")
sibling = marker.with_suffix(".new")
sibling.write_text(str(home))
sibling.replace(marker)
deadline = time.monotonic() + 10
while len(list(root.glob("*.ready"))) != 2:
    assert time.monotonic() < deadline, "files did not overlap"
    time.sleep(0.01)
assert len({p.read_text() for p in root.glob("*.ready")}) == 2
class T(unittest.TestCase):
    def test_ok(self): pass
'''
        result = self.run_gate({"test_first.py": source, "test_second.py": source})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_output_is_grouped_and_sorted_after_early_failure(self):
        result = self.run_gate({"test_a.py": "raise RuntimeError('first failed')",
                                "test_z.py": "print('last still ran')"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("last still ran", result.stderr)
        self.assertLess(result.stderr.index("first failed"), result.stderr.index("last still ran"))
        self.assertIn("1 failed", result.stderr)

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


class GateLockTests(unittest.TestCase):
    def test_a_second_gate_waits_for_the_host_lock(self):
        source = "import unittest\nclass T(unittest.TestCase):\n def test_ok(self): pass\n"
        with tempfile.TemporaryDirectory(prefix="gate-lock-") as temp:
            root = Path(temp)
            (root / "home").mkdir()
            tools = root / "tools"
            tools.mkdir()
            (tools / "check.sh").write_bytes(GATE.read_bytes())
            (tools / "test_ok.py").write_text(source)
            lock = root / "gate.lock"
            env = {k: v for k, v in os.environ.items() if k != "AGENTS_GATE_HELD"}
            env.update(HOME=str(root / "home"), AGENTS_GATE_LOCK=str(lock))
            with open(lock, "w") as held:
                fcntl.flock(held, fcntl.LOCK_EX)
                gate = subprocess.Popen(["bash", str(tools / "check.sh")], env=env, text=True,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertIn("waiting for another agents gate", gate.stderr.readline())
                self.assertIsNone(gate.poll())
            out, err = gate.communicate(timeout=120)
            self.assertEqual(gate.returncode, 0, err)
            self.assertIn("Checked 1 files", err)

    def test_a_parent_lock_override_does_not_reach_the_fixture(self):
        source = "import unittest\nclass T(unittest.TestCase):\n def test_ok(self): pass\n"
        with tempfile.TemporaryDirectory(prefix="gate-parent-") as temp:
            lock = Path(temp) / "parent.lock"
            with open(lock, "w") as held:
                fcntl.flock(held, fcntl.LOCK_EX)
                previous = os.environ.get("AGENTS_GATE_LOCK")
                os.environ["AGENTS_GATE_LOCK"] = str(lock)
                try:
                    result = GateTests.run_gate(self, {"test_ok.py": source})
                finally:
                    if previous is None:
                        os.environ.pop("AGENTS_GATE_LOCK")
                    else:
                        os.environ["AGENTS_GATE_LOCK"] = previous
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invoked_from_tools_by_relative_name(self):
        source = "import unittest\nclass T(unittest.TestCase):\n def test_ok(self): pass\n"
        with tempfile.TemporaryDirectory(prefix="gate-relative-") as temp:
            root = Path(temp)
            (root / "home").mkdir()
            tools = root / "tools"
            tools.mkdir()
            (tools / "check.sh").write_bytes(GATE.read_bytes())
            (tools / "test_ok.py").write_text(source)
            env = {k: v for k, v in os.environ.items() if k != "AGENTS_GATE_HELD"}
            env.update(HOME=str(root / "home"), AGENTS_GATE_LOCK=str(root / "gate.lock"))
            result = subprocess.run(["bash", "check.sh"], cwd=tools, env=env,
                                    capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Checked 1 files", result.stderr)
