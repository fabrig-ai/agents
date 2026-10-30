"""The gate discovers nested tests and propagates failures in disposable trees."""
import fcntl
import json
import time
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
            (tools / "gate.py").write_bytes(GATE.with_name("gate.py").read_bytes())
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


class BudgetSelectionTests(unittest.TestCase):
    def test_tiers_and_explicit_files(self):
        sources = {'test_gate.py': "print('gate marker')",
                   'test_sweep_periodic.py': "print('periodic marker')"}
        result = GateTests.run_gate(self, sources)
        self.assertIn('gate marker', result.stderr)
        self.assertNotIn('periodic marker', result.stderr)
        result = GateTests.run_gate(self, sources, '--tier', 'periodic')
        self.assertIn('periodic marker', result.stderr)
        self.assertNotIn('gate marker', result.stderr)
        result = GateTests.run_gate(self, sources, 'tools/test_sweep_periodic.py')
        self.assertIn('periodic marker', result.stderr)

    def test_wait4_counts_waited_descendant_cpu_and_enforces_named_budget(self):
        source = """import subprocess,sys
subprocess.run([sys.executable, '-c', 'import time; end=time.process_time()+0.15\\nwhile time.process_time()<end: pass'],check=True)
"""
        config = '[budget]\nfile_cpu_s = 0.01\ntier_cpu_s = 0.01\nenforce = false\n[files."tools/test_cpu.py"]\nowner = "lead/test"\n'
        sources = {'test_cpu.py': source, 'gate.toml': config}
        result = GateTests.run_gate(self, sources)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('budget: REPORT-ONLY (not enforced)', result.stderr)
        self.assertIn('REPORT ONLY: file CPU budget: tools/test_cpu.py (lead/test)', result.stderr)
        self.assertIn('REPORT ONLY: tier CPU budget: gate', result.stderr)
        row = next(line for line in result.stderr.splitlines() if line.startswith('tools/test_cpu.py lead/test '))
        self.assertGreaterEqual(float(row.split()[2]), 0.15)
        sources['gate.toml'] = config.replace('false', 'true')
        result = GateTests.run_gate(self, sources)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('FAIL: file CPU budget', result.stderr)
        self.assertIn('budget: ENFORCED', result.stderr)

    def test_report_only_slow_file_completes_and_enforced_file_is_unobserved(self):
        sources = {'test_slow.py': "import time; time.sleep(0.2); print('completed slow file')",
                   'gate.toml': '[budget]\nfile_wall_s = 0.1\nmerge_wall_s = 0.1\nenforce = false\n'}
        result = GateTests.run_gate(self, sources)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('completed slow file', result.stderr)
        self.assertIn('0 starved/unobserved', result.stderr)
        self.assertIn('OVER (report-only)', result.stderr)
        self.assertIn('file wall budget: tools/test_slow.py', result.stderr)
        sources['gate.toml'] = sources['gate.toml'].replace('false', 'true').replace('merge_wall_s = 0.1', 'merge_wall_s = 60')
        result = GateTests.run_gate(self, sources)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn('completed slow file', result.stderr)
        self.assertIn('1 starved/unobserved', result.stderr)
        self.assertIn('1 failed', result.stderr)

    def test_signal_killed_file_is_unobserved_in_both_modes(self):
        for enforce in ('false', 'true'):
            result = GateTests.run_gate(self, {
                'test_killed.py': 'import os,signal; os.kill(os.getpid(),signal.SIGKILL)',
                'gate.toml': '[budget]\nenforce = ' + enforce + '\n'})
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn('1 starved/unobserved', result.stderr)
            self.assertIn('1 failed', result.stderr)

    def test_detached_descendants_are_drained_and_counted(self):
        result = GateTests.run_gate(self, {'test_detached.py': """import subprocess,sys
child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],start_new_session=True)
print('descendant_pid',child.pid,flush=True)
"""})
        self.assertEqual(result.returncode, 0, result.stderr)
        line = next(line for line in result.stderr.splitlines() if line.startswith('descendant_pid '))
        with self.assertRaises(ProcessLookupError):
            os.kill(int(line.split()[1]), 0)

    def test_priority_and_tier_wall_backstop(self):
        source = """import os,subprocess
assert os.getpriority(os.PRIO_PROCESS, 0) == 19
assert 'idle' in subprocess.check_output(['ionice', '-p', str(os.getpid())], text=True)
"""
        result = GateTests.run_gate(self, {'test_priority.py': source})
        self.assertEqual(result.returncode, 0, result.stderr)
        for mode in ('enforce = true', 'report_hard_wall_s = 0.15'):
            result = GateTests.run_gate(self, {'test_hang.py': 'import time; time.sleep(30)',
                                             'gate.toml': '[budget]\nmerge_wall_s = 0.1\n' + mode + '\n'})
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn('1 starved/unobserved', result.stderr)
            self.assertIn('1 failed', result.stderr)

    def test_selection_mapping_smoke_unknown_and_changed_git_diff(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('gate_selection_fixture', GATE.with_name('gate.py'))
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = ['tools/test_smoke.py', 'tools/a/test_a.py', 'tools/b/test_b.py']
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('')
            config = dict(smoke=[names[0]], select={'tools/a/**': [names[1]]})
            cases = [(['tools/a/code'], names[:2]), (['docs/a.txt'], names[:1]),
                     (['README.md'], names[:1]), (['tools/a/help.md'], names[:1]), (['tools/b/new'], [names[0], names[2]]),
                     (['other'], names), (['tools/empty/new'], names)]
            for changes, expected in cases:
                self.assertEqual(gate.select(root, config, changes), sorted(expected))
            env = dict(os.environ, GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_NOSYSTEM='1',
                       GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@example.invalid',
                       GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@example.invalid')
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=root, env=env, stderr=subprocess.DEVNULL).decode().strip()
            git('init', '-b', 'main')
            git('add', '.')
            git('commit', '-qm', 'base')
            base = git('rev-parse', 'HEAD')
            (root/'README.md').write_text('new')
            git('add', '.')
            git('commit', '-qm', 'doc')
            self.assertEqual(gate.changed_paths(root, base), ['README.md'])


class GateLockTests(unittest.TestCase):
    def test_a_second_gate_waits_for_the_host_lock(self):
        source = "import unittest\nclass T(unittest.TestCase):\n def test_ok(self): pass\n"
        with tempfile.TemporaryDirectory(prefix="gate-lock-") as temp:
            root = Path(temp)
            (root / "home").mkdir()
            tools = root / "tools"
            tools.mkdir()
            (tools / "check.sh").write_bytes(GATE.read_bytes())
            (tools / "gate.py").write_bytes(GATE.with_name("gate.py").read_bytes())
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
            (tools / "gate.py").write_bytes(GATE.with_name("gate.py").read_bytes())
            (tools / "test_ok.py").write_text(source)
            env = {k: v for k, v in os.environ.items() if k != "AGENTS_GATE_HELD"}
            env.update(HOME=str(root / "home"), AGENTS_GATE_LOCK=str(root / "gate.lock"))
            result = subprocess.run(["bash", "check.sh"], cwd=tools, env=env,
                                    capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Checked 1 files", result.stderr)


if __name__ == "__main__":
    unittest.main()
