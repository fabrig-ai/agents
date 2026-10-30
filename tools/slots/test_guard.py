"""Disk pressure policy with disposable slots, fake systemd, and real trim."""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True

DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parent.parent
guard = type(sys)("guard")
guard.__dict__.update(runpy.run_path(str(DIRECTORY / "guard")))
GB = 1_000_000_000

FAKE = '''#!/usr/bin/python3
import json, os
from pathlib import Path
import sys
root = Path(os.environ["GUARD_FIXTURE"])
with (root / "calls").open("a") as out:
    out.write(json.dumps([Path(sys.argv[0]).name, *sys.argv[1:]]) + "\\n")
state = json.loads((root / "systemd.json").read_text())
if state.get("fail"):
    sys.exit("fixture systemd unavailable")
if Path(sys.argv[0]).name == "systemctl":
    args = sys.argv[1:]
    if "list-units" in args:
        for name, properties in state.get("units", {}).items():
            print(name, "loaded", properties.get("ActiveState", "active"), "running", "fixture")
    elif "show" in args:
        if "LoadState" not in state["units"][args[-1]]:
            print("LoadState=loaded")
        for key, value in state["units"][args[-1]].items():
            print(key + "=" + value)
'''


class GuardTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=ROOT.parent, prefix=".guard-test-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.slots = self.home / "src/fabrig/slots"
        self.slots.mkdir(parents=True)
        self.log = self.home / "src/fabrig/notes/slot-guard.log"
        self.bin = self.home / "bin"
        self.bin.mkdir()
        for name in ("systemctl", "systemd-run"):
            path = self.bin / name
            path.write_text(FAKE)
            path.chmod(0o700)
        self.state()
        self.environment = {**os.environ, "HOME": str(self.home),
                            "GUARD_FIXTURE": str(self.home),
                            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"]}
        environment = patch.dict(os.environ, self.environment)
        environment.start()
        self.addCleanup(environment.stop)

    def state(self, **values):
        (self.home / "systemd.json").write_text(json.dumps(values))

    def executable(self, slot, size=4096):
        path = self.slots / slot / "target/debug/deps/test-bin"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        path.chmod(0o700)
        return path

    def cli(self, *args, free=60):
        usage = lambda path: shutil._ntuple_diskusage(1000 * GB, 0, int(
            (free() if callable(free) else free) * GB))
        with patch.object(sys, "argv", ["guard", *args]), \
                patch.object(guard.shutil, "disk_usage", side_effect=usage), \
                redirect_stdout(io.StringIO()) as output:
            code = guard.main()
        return code, output.getvalue()

    def calls(self):
        path = self.home / "calls"
        return [json.loads(row) for row in path.read_text().splitlines()] if path.exists() else []

    def test_above_threshold_does_not_inspect_units_or_trim(self):
        path = self.executable("1")
        code, output = self.cli(free=90)
        self.assertEqual(code, 0)
        self.assertTrue(path.exists())
        self.assertEqual(self.calls(), [])
        self.assertIn("before=90.000 after=90.000; ok", output)

    def test_largest_slot_first_and_stop_after_recovery_margin(self):
        small = self.executable("1")
        large = self.executable("2", size=16384)
        middle = self.executable("3", size=8192)
        free = lambda: 60 + (40 if not large.exists() else 0) + (25 if not middle.exists() else 0)
        code, output = self.cli(free=free)
        self.assertEqual(code, 0)
        self.assertFalse(large.exists())
        self.assertFalse(middle.exists())
        self.assertTrue(small.exists())
        self.assertLess(output.index("slot 2:"), output.index("slot 3:"))
        self.assertNotIn("slot 1:", output)
        self.assertIn("after=125.000", output)

    def test_active_and_activating_heavy_subdirectories_are_busy(self):
        for state in ("active", "activating"):
            with self.subTest(state=state):
                path = self.executable("1")
                self.state(units={"job-heavy-build.service": {
                    "WorkingDirectory": str(path.parent), "ActiveState": state}})
                code, output = self.cli()
                self.assertEqual(code, 2)
                self.assertTrue(path.exists())
                self.assertIn("slot 1: skipped (busy)", output)
        self.assertIn(["systemctl", "--user", "show", "-p",
                       "WorkingDirectory,ActiveState,LoadState", "job-heavy-build.service"], self.calls())

    def test_exact_slot_directory_is_busy(self):
        self.executable("1")
        self.state(units={"job-heavy-build.service": {
            "WorkingDirectory": str(self.slots / "1"), "ActiveState": "active"}})
        self.assertTrue(guard.busy(self.slots / "1"))

    def test_nonheavy_inactive_and_sibling_paths_do_not_block(self):
        path = self.executable("1")
        self.state(units={
            "codex-run.service": {"WorkingDirectory": str(path.parent), "ActiveState": "active"},
            "job-heavy-old.service": {"WorkingDirectory": str(path.parent), "ActiveState": "inactive"},
            "job-heavy-other.service": {"WorkingDirectory": str(self.slots / "10"),
                                         "ActiveState": "active"}})
        code, output = self.cli()
        self.assertEqual(code, 2)
        self.assertFalse(path.exists())
        self.assertIn("trimmed 1 executables", output)

    def test_busy_is_rechecked_before_trim(self):
        path = self.executable("1")
        with patch.dict(guard.sweep.__globals__, busy=unittest.mock.Mock(side_effect=[False, True])):
            code, output = self.cli()
        self.assertEqual(code, 2)
        self.assertTrue(path.exists())
        self.assertIn("skipped (busy)", output)

    def test_nonnumeric_slot_names_are_ignored(self):
        path = self.executable("scratch")
        self.executable("1")
        code, output = self.cli()
        self.assertEqual(code, 2)
        self.assertTrue(path.exists())
        self.assertNotIn("scratch", output)

    def test_no_slots_is_nothing_to_do(self):
        code, _ = self.cli()
        self.assertEqual(code, 0)

    def test_still_below_trims_every_idle_slot_and_exits_two(self):
        paths = [self.executable(str(n)) for n in (1, 2, 3)]
        code, output = self.cli()
        self.assertEqual(code, 2)
        self.assertTrue(all(not path.exists() for path in paths))
        self.assertIn("still below 80 GB", output)

    def test_dry_run_preserves_files_and_reports_eligible_count(self):
        path = self.executable("1")
        (path.parent / "lib.so").write_bytes(b"library")
        code, output = self.cli("--dry-run")
        self.assertEqual(code, 2)
        self.assertTrue(path.exists())
        self.assertIn("dry-run", output)
        self.assertIn("would trim 1 executables", output)

    def test_open_descriptor_is_protected_in_dry_run_and_real_run(self):
        path = self.executable("1")
        with path.open("rb"):
            for args in (("--dry-run",), ()):
                code, output = self.cli(*args)
                self.assertEqual(code, 2)
                self.assertTrue(path.exists())
                self.assertIn("0 executables", output)

    def test_log_matches_single_stdout_line_and_repairs_private_mode(self):
        self.log.parent.mkdir(parents=True)
        self.log.write_text("earlier\n")
        self.log.chmod(0o644)
        code, output = self.cli(free=90)
        self.assertEqual(code, 0)
        self.assertEqual(len(output.splitlines()), 1)
        self.assertRegex(output, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ ")
        self.assertEqual(self.log.read_text(), "earlier\n" + output)
        self.assertEqual(self.log.stat().st_mode & 0o777, 0o600)

    def test_log_creation_is_private(self):
        self.cli(free=90)
        self.assertEqual(self.log.stat().st_mode & 0o777, 0o600)

    def test_systemctl_error_fails_without_deleting(self):
        path = self.executable("1")
        self.state(fail=True)
        code, output = self.cli()
        self.assertEqual(code, 1)
        self.assertTrue(path.exists())
        self.assertIn("fixture systemd unavailable", output)

    def test_missing_unit_properties_fail_without_deleting(self):
        path = self.executable("1")
        self.state(units={"job-heavy-build.service": {"ActiveState": "active"}})
        code, output = self.cli()
        self.assertEqual(code, 1)
        self.assertTrue(path.exists())
        self.assertIn("missing heavy unit properties", output)

    def test_heavy_timer_without_working_directory_does_not_block_pressure_recovery(self):
        path = self.executable("1")
        self.state(units={
            "skein-heavy-queue-reconcile.timer": {"ActiveState": "active"},
            "skein-heavy-queue-reconcile.service": {"WorkingDirectory": "", "ActiveState": "active"}})
        code, output = self.cli()
        self.assertEqual(code, 2)
        self.assertFalse(path.exists())
        self.assertNotIn("error:", output)
        listed = [call for call in self.calls() if "list-units" in call]
        self.assertTrue(all("--type=service" in call for call in listed))
        self.assertFalse(any("show" in call and call[-1].endswith(".timer") for call in self.calls()))

    def test_symlink_slot_is_refused(self):
        path = self.executable("scratch")
        (self.slots / "1").symlink_to(self.slots / "scratch", target_is_directory=True)
        code, output = self.cli()
        self.assertEqual(code, 1)
        self.assertTrue(path.exists())
        self.assertIn("symlink slot", output)

    def test_custom_threshold(self):
        path = self.executable("1")
        code, output = self.cli("--below", "50", free=60)
        self.assertEqual(code, 0)
        self.assertTrue(path.exists())
        self.assertIn("ok", output)

    def test_timer_replaces_existing_units_and_uses_resolved_path(self):
        self.state(units={"fabrig-slot-guard.timer": {}, "fabrig-slot-guard.service": {}})
        code, _ = self.cli("--timer")
        self.assertEqual(code, 0)
        self.assertIn(["systemctl", "--user", "stop", "fabrig-slot-guard.timer",
                       "fabrig-slot-guard.service"], self.calls())
        self.assertEqual(self.calls()[-1], [
            "systemd-run", "--user", "--collect", "--unit", "fabrig-slot-guard",
            "--on-calendar", "*:0/5", "bash", "-lc", 'exec "$0" "$@"',
            str(DIRECTORY / "guard"), "--below", "80"])

    def test_timer_stop_never_launches(self):
        self.state(units={"fabrig-slot-guard.timer": {}})
        code, _ = self.cli("--timer", "--stop")
        self.assertEqual(code, 0)
        self.assertEqual(self.calls()[-1], ["systemctl", "--user", "stop", "fabrig-slot-guard.timer"])
        self.assertTrue(all(call[0] != "systemd-run" for call in self.calls()))

    def test_timer_invoked_via_symlink_uses_source_and_custom_threshold(self):
        link = self.home / "guard link"
        link.symlink_to(DIRECTORY / "guard")
        result = subprocess.run([sys.executable, "-I", "-B", str(link), "--timer", "--below", "90"],
                                env=self.environment, stdin=subprocess.DEVNULL,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls()[-1][-3:], [str(DIRECTORY / "guard"), "--below", "90.0"])

    def test_log_failure_is_an_error(self):
        self.log.parent.mkdir(parents=True)
        target = self.home / "keep-log"
        target.write_text("keep\n")
        self.log.symlink_to(target)
        code, output = self.cli(free=90)
        self.assertEqual(code, 1)
        self.assertIn("log error:", output)
        self.assertEqual(target.read_text(), "keep\n")

    def test_isolated_cli_loads_sibling_trim_from_another_directory(self):
        path = self.executable("1")
        result = subprocess.run([sys.executable, "-I", "-B", str(DIRECTORY / "guard"),
                                 "--below", "1000000", "--dry-run"], cwd=self.home,
                                env=self.environment, stdin=subprocess.DEVNULL,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertTrue(path.exists())
        self.assertIn("would trim 1 executables", result.stdout)


if __name__ == "__main__":
    unittest.main()
