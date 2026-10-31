import fcntl
import io
import os
import socket
import subprocess
import threading
import time
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from fab import heavy, log
from fab.sh import Result
from fab.tests.support import FakeRunner, tmp_home


def write(path, text):
    sibling = path.with_name(path.name + ".new")
    sibling.write_text(text)
    sibling.replace(path)


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class DiskTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.available = 40
        self.reclaims = []
        self.messages = []

    def reclaim(self, need):
        self.reclaims.append(need)
        return 999  # A byte count is not a measurement of free space.

    def admit(self, *, reclaim=None, sleep=None, cap=5, poll=2):
        return heavy.admit_disk(100, free=lambda: self.available,
                                reclaim=reclaim or self.reclaim,
                                clock=self.clock.clock, sleep=sleep or self.clock.sleep,
                                cap=cap, poll=poll, say=self.messages.append)

    def test_enough_immediately_does_not_wait_or_reclaim(self):
        for available in (100, 101):
            self.available = available
            self.assertTrue(self.admit())
        self.assertEqual(self.clock.sleeps, [])
        self.assertEqual(self.reclaims, [])
        self.assertEqual(self.messages, [])

    def test_reclaim_frees_enough_without_sleep(self):
        def reclaim(need):
            self.reclaim(need)
            self.available = need
            return 60

        self.assertTrue(self.admit(reclaim=reclaim))
        self.assertEqual(self.reclaims, [100])
        self.assertEqual(self.clock.sleeps, [])
        self.assertEqual(self.messages, ["heavy: disk: waiting: 60 bytes short",
                                         "heavy: disk: ready: 0 bytes short"])

    def test_space_comes_free_while_waiting(self):
        def sleep(seconds):
            self.clock.sleep(seconds)
            self.available += 30

        self.assertTrue(self.admit(sleep=sleep))
        self.assertEqual(self.reclaims, [100, 100])
        self.assertEqual(self.clock.sleeps, [2, 2])
        self.assertEqual(len(self.messages), 2)
        self.assertIn("60 bytes short", self.messages[0])
        self.assertIn("0 bytes short", self.messages[1])

    def test_cap_limits_last_sleep_and_reports_remaining_shortfall(self):
        def sleep(seconds):
            self.clock.sleep(seconds)
            self.available += 10

        self.assertFalse(self.admit(sleep=sleep))
        self.assertEqual(self.clock.sleeps, [2, 2, 1])
        self.assertEqual(self.reclaims, [100, 100, 100])
        self.assertEqual(self.messages, ["heavy: disk: waiting: 60 bytes short",
                                         "heavy: disk: gave up: 30 bytes short"])

    def test_zero_cap_does_not_sleep(self):
        self.assertFalse(self.admit(cap=0))
        self.assertEqual(self.clock.sleeps, [])
        self.assertIn("60 bytes short", self.messages[-1])

    def test_reclaim_time_counts_towards_cap(self):
        def reclaim(need):
            self.reclaim(need)
            self.clock.now += 10

        self.assertFalse(self.admit(reclaim=reclaim))
        self.assertEqual(self.reclaims, [100])
        self.assertEqual(self.clock.sleeps, [])


class LaneTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())

    def worker(self, name, entered, errors):
        try:
            with heavy.lane(name, 2, self.home):
                entered.set()
        except BaseException as error:
            errors.append(error)

    def test_two_build_places_hold_a_third_until_release(self):
        entered, polling = threading.Event(), threading.Event()
        errors = []
        real_sleep = time.sleep

        def sleep(seconds):
            self.assertEqual(seconds, 1)
            polling.set()
            real_sleep(0.002)

        with patch.object(heavy.time, "sleep", side_effect=sleep):
            with heavy.lane("build", 2, self.home):
                with heavy.lane("build", 2, self.home):
                    thread = threading.Thread(target=self.worker, args=("build", entered, errors))
                    thread.start()
                    waiting = polling.wait(0.1)
                    held = not entered.is_set()
                thread.join(0.1)
        self.assertTrue(waiting)
        self.assertTrue(held)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(entered.is_set())
        self.assertEqual(sorted(p.name for p in (self.home / "heavy").iterdir()),
                         ["build-0.lock", "build-1.lock"])

    def test_gate_is_exclusive(self):
        attempted, entered = threading.Event(), threading.Event()
        errors = []
        flock = fcntl.flock

        def observe(file, operation):
            if operation == fcntl.LOCK_EX:
                attempted.set()
            return flock(file, operation)

        with heavy.lane("gate", 2, self.home):
            with patch.object(heavy.fcntl, "flock", side_effect=observe):
                thread = threading.Thread(target=self.worker, args=("gate", entered, errors))
                thread.start()
                waiting = attempted.wait(0.1)
                held = not entered.is_set()
        thread.join(0.1)
        self.assertTrue(waiting)
        self.assertTrue(held)
        self.assertFalse(thread.is_alive())
        self.assertTrue(entered.is_set())
        self.assertEqual(errors, [])

    def test_exception_releases_place(self):
        for name in ("gate", "build"):
            with self.assertRaisesRegex(RuntimeError, "command failed"):
                with heavy.lane(name, 1, self.home):
                    raise RuntimeError("command failed")
            with heavy.lane(name, 1, self.home):
                pass

    def test_invalid_lane_or_capacity_fails(self):
        for name, builds in (("unknown", 2), ("build", 0)):
            with self.assertRaises(ValueError):
                with heavy.lane(name, builds, self.home):
                    self.fail("invalid lane admitted")


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.path = self.home / "hosts.toml"
        write(self.path, '[builder]\nbuilds = 2\nheadroom_gb = 7\n[partial]\nbuilds = 4\n')
        self.enterContext(patch.dict(os.environ, {"FAB_HOST": "builder"}))

    def test_file_and_environment_overrides(self):
        self.assertEqual(heavy.settings(path=self.path),
                         heavy.Settings(builds=2, headroom=7 * heavy.GB))
        self.assertEqual(heavy.settings("partial", path=self.path), heavy.Settings(builds=4))
        self.assertIsInstance(heavy.settings("partial", path=self.path).headroom, int)

    def test_live_overrides_apply_and_a_bad_file_is_left_out(self):
        local = self.home / "fab" / heavy.hosts.LOCAL
        local.parent.mkdir(parents=True, exist_ok=True)
        write(local, "[builder]\nbuilds = 1\n")
        self.assertEqual(heavy.settings(path=self.path), heavy.Settings(builds=1, headroom=7 * heavy.GB))
        write(local, "[builder]\nssh = 'z'\n")
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(heavy.settings(path=self.path).builds, 2)
        self.assertIn("heavy: ignoring", stderr.getvalue())

    def test_unknown_and_missing_host_keep_defaults(self):
        self.assertEqual(heavy.settings("unknown", path=self.path), heavy.Settings())
        self.assertEqual(heavy.settings("", path=self.path), heavy.Settings())
        os.environ.pop("FAB_HOST")
        self.assertEqual(heavy.settings(path=self.path), heavy.Settings())

    def test_without_fab_host_this_machine_is_found_by_hostname(self):
        os.environ.pop("FAB_HOST")
        write(self.path, f'[mine]\nhostname = "{socket.gethostname()}"\nbuilds = 5\n')
        self.assertEqual(heavy.settings(path=self.path).builds, 5)


class WrapTest(unittest.TestCase):
    def test_without_systemd_preserves_arguments(self):
        argv = ("sh", "-c", "printf '%s' 'a b'")
        self.assertEqual(heavy.wrap(argv, "build", systemd=False), list(argv))

    def test_systemd_uses_lane_weight_and_argument_boundary(self):
        for name, weight in (("build", 1000), ("gate", 10000)):
            self.assertEqual(heavy.wrap(["true", "a b"], name, systemd=True),
                             ["systemd-run", "--user", "--scope", "--quiet", "-p",
                              f"CPUWeight={weight}", "--", "true", "a b"])


class MainTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.enterContext(patch.dict(os.environ, {"FAB_HOST": "", "XDG_RUNTIME_DIR": ""}))
        self.free = self.enterContext(patch.object(heavy.slots, "free_bytes", return_value=100 * heavy.GB))
        self.reclaim = self.enterContext(patch.object(heavy.slots, "reclaim", return_value=0))
        self.config = self.enterContext(patch.object(heavy, "settings", return_value=heavy.Settings()))
        self.err = self.enterContext(redirect_stderr(io.StringIO()))
        self.path = self.home / "fab" / "heavy.jsonl"

    def fake_commands(self, fake):
        def run(argv):
            return subprocess.CompletedProcess(argv, fake(argv).code)

        return self.enterContext(patch.object(heavy.subprocess, "run", side_effect=run))

    def test_usage_without_command(self):
        for argv in ([], ["--"], ["--gate"], ["--gate", "--"]):
            self.assertEqual(heavy.main(argv), 2)
        self.assertIn("usage: heavy", self.err.getvalue())
        self.assertFalse(self.path.exists())
        self.free.assert_not_called()

    def test_cargo_fmt_bypasses_admission_and_scope(self):
        fake = FakeRunner().on(["cargo", "fmt"], Result(3))
        run = self.fake_commands(fake)
        with patch.object(heavy, "lane") as lane, patch.object(heavy, "wrap") as wrap:
            self.assertEqual(heavy.main(["--gate", "--", "cargo", "fmt", "--check"]), 3)
        run.assert_called_once_with(["cargo", "fmt", "--check"])
        lane.assert_not_called()
        wrap.assert_not_called()
        self.config.assert_not_called()
        self.free.assert_not_called()
        record, = log.read(self.path)
        self.assertEqual((record["argv0"], record["code"], record["lane_wait"], record["disk_wait"]),
                         ("cargo", 3, 0, 0))

    def test_real_command_codes_and_records_without_systemd(self):
        self.assertEqual(heavy.main(["--", "true"]), 0)
        self.assertEqual(heavy.main(["--gate", "sh", "-c", "exit 3"]), 3)
        records = log.read(self.path)
        self.assertEqual([r["ev"] for r in records], ["heavy", "heavy"])
        self.assertEqual([r["code"] for r in records], [0, 3])
        self.assertEqual([r["lane"] for r in records], ["build", "gate"])
        self.assertEqual([r["argv0"] for r in records], ["true", "sh"])
        for record in records:
            self.assertGreaterEqual(record["lane_wait"], 0)
            self.assertGreaterEqual(record["disk_wait"], 0)
            self.assertGreaterEqual(record["seconds"], record["lane_wait"] + record["disk_wait"])
        self.reclaim.assert_not_called()

    def test_disk_cap_returns_tempfail_reports_infra_and_logs(self):
        self.free.return_value = 0
        self.config.return_value = heavy.Settings(cap=2, poll=1)
        clock = Clock()
        with patch.object(heavy.time, "monotonic", side_effect=clock.clock), \
                patch.object(heavy.time, "sleep", side_effect=clock.sleep), \
                patch.object(heavy.subprocess, "run") as run:
            self.assertEqual(heavy.main(["true"]), heavy.EX_TEMPFAIL)
        run.assert_not_called()
        self.assertEqual(clock.sleeps, [1, 1])
        self.assertEqual(self.reclaim.call_count, 2)
        self.reclaim.assert_called_with(20 * heavy.GB)
        self.assertIn("heavy: Infra: disk:", self.err.getvalue())
        self.assertEqual(len(self.err.getvalue().splitlines()), 3)
        record, = log.read(self.path)
        self.assertEqual(record["code"], 75)
        self.assertEqual(record["disk_wait"], 2)

    def test_wait_measurements_and_custom_disk_requirement(self):
        self.config.return_value = heavy.Settings(builds=2, headroom=3, allowance=4)
        self.fake_commands(FakeRunner())
        with patch.object(heavy.time, "monotonic", side_effect=[10, 10, 12, 13, 15, 20]), \
                patch.object(heavy, "admit_disk", wraps=heavy.admit_disk) as admit, \
                patch.object(heavy, "lane", wraps=heavy.lane) as lane:
            self.assertEqual(heavy.main(["true"]), 0)
        self.assertEqual(admit.call_args.args, (7,))
        lane.assert_called_once_with("build", 2, self.home / "fab")
        record, = log.read(self.path)
        self.assertEqual((record["lane_wait"], record["disk_wait"], record["seconds"]), (2, 3, 10))

    def test_systemd_requires_executable_and_runtime_directory(self):
        for runtime, executable in (("", "/fake/systemd-run"), ("/fake/runtime", None),
                                    ("/fake/runtime", "/fake/systemd-run")):
            with self.subTest(runtime=runtime, executable=executable), \
                    patch.dict(os.environ, {"XDG_RUNTIME_DIR": runtime}), \
                    patch.object(heavy.shutil, "which", return_value=executable):
                fake = FakeRunner()
                self.fake_commands(fake)
                self.assertEqual(heavy.main(["--gate", "true"]), 0)
                self.assertEqual(fake.argvs(),
                                 [heavy.wrap(["true"], "gate", systemd=bool(runtime and executable))])


class UmaskTest(unittest.TestCase):
    def test_commands_run_with_a_private_umask(self):
        with tmp_home() as home:
            out = home / "umask.txt"
            saved = os.umask(0o022)
            try:
                with patch.dict(os.environ, {"FAB_HOST": "", "XDG_RUNTIME_DIR": ""}), \
                        patch.object(heavy.slots, "free_bytes", return_value=10**15):
                    self.assertEqual(heavy.main(["sh", "-c", f"umask > {out}"]), 0)
            finally:
                os.umask(saved)
            self.assertEqual(out.read_text().strip(), "0077")
