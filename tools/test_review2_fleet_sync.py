"""Second-review regressions; all installers and signals use disposable HOME."""

import fcntl
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import time
import unittest
from unittest.mock import patch

import test_fleet_sync as fixture


def exiting(pid):
    """A pidfd is notified after exit releases memory and inherited pipes.

    PF_EXITING is set at entry to Linux do_exit, before those releases. Check
    that irreversible state when a lock observation beats pidfd notification.
    Only inspect the PIDs announced by this test's fake installer.
    """
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    except FileNotFoundError:
        return True
    return bool(int(fields[6]) & 0x4)  # PF_EXITING


class ExitObservationTests(unittest.TestCase):
    def test_running_descendant_is_not_accepted(self):
        with patch.object(Path, "read_text", return_value="123 (fake child) R 1 2 3 0 -1 4195336"):
            self.assertFalse(exiting(123))

    def test_exit_before_pidfd_notification_is_accepted(self):
        with patch.object(Path, "read_text", return_value="123 (fake child) R 1 2 3 0 -1 4195340"):
            self.assertTrue(exiting(123))
        with patch.object(Path, "read_text", side_effect=FileNotFoundError):
            self.assertTrue(exiting(123))


class Review2Test(fixture.FleetFixture):
    def test_candidate_cannot_exclude_recovery_timer(self):
        self.sync()
        current = self.current()
        roles = self.source / "fleet/units/roles.toml"
        fixture.put(roles, roles.read_text().replace('"fleet-sync.timer" = ["*"]', '"fleet-sync.timer" = ["unused"]'))
        self.publish()
        self.sync(script=current / "tools/fleet-sync", expected=1)
        self.assertEqual(self.current(), current)
        self.assertTrue((self.home / ".config/systemd/user/fleet-sync.timer").exists())
        self.assertFalse(any("disable" in call and "fleet-sync.timer" in call for call in self.calls()))

    def test_recovery_units_require_exact_all_roles_and_cannot_be_removed(self):
        roles = self.source / "fleet/units/roles.toml"
        original = roles.read_text()
        for name in ("fleet-sync.service", "fleet-sync.timer"):
            fixture.put(roles, original.replace(f'"{name}" = ["*"]', f'"{name}" = ["*", "session"]'))
            self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--self-check", "--host", "hel8", expected=2)
        fixture.put(roles, original)
        with patch.dict(os.environ, self.env, clear=True):
            _, runner = self.runner()
            runner.units()
            runner.d.unit_roles["fleet-sync.timer"] = ["unused"]
            calls = self.calls()
            with self.assertRaises(ValueError):
                runner.units()
            self.assertEqual(self.calls(), calls)

    def assert_unsafe_destination_refused(self, bootstrap, parent):
        if not bootstrap:
            self.sync()
        outside = self.directory / "outside-bin"
        destination = self.home / (".local" if parent else ".local/bin")
        if destination.exists():
            destination.rename(outside)
        else:
            outside.mkdir()
            destination.parent.mkdir(parents=True, exist_ok=True)
        destination.symlink_to(outside)
        before = self.snapshot(root=outside)
        with patch.dict(os.environ, self.env, clear=True):
            _, runner = self.runner()
            command = runner.cmd
            def refuse_install(*args, **kwargs):
                if str(args[-1]).endswith("tools/install"):
                    self.fail("installer invoked with unsafe destination")
                return command(*args, **kwargs)
            with patch.object(runner, "cmd", side_effect=refuse_install):
                runner.attempt("fabrig", runner.fabrig)
            self.assertEqual(self.fabrig_item(runner.state)["result"], "failed")
        self.assertEqual(before, self.snapshot(root=outside))

    def test_bootstrap_refuses_symlinked_bin(self):
        self.assert_unsafe_destination_refused(bootstrap=True, parent=False)

    def test_bootstrap_refuses_symlinked_bin_parent(self):
        self.assert_unsafe_destination_refused(bootstrap=True, parent=True)

    def test_repair_refuses_symlinked_bin(self):
        self.assert_unsafe_destination_refused(bootstrap=False, parent=False)

    def test_repair_refuses_symlinked_bin_parent(self):
        self.assert_unsafe_destination_refused(bootstrap=False, parent=True)

    def test_wrong_enablement_link_is_replaced_atomically(self):
        self.sync()
        link = self.home / ".config/systemd/user/timers.target.wants/fleet-sync.timer"
        link.unlink()
        link.symlink_to("/old-release/fleet-sync.timer")
        # The real systemctl refuses this conflict; the fake must do so too.
        self.process(self.bin / "systemctl", "--user", "enable", "--now", "--no-reload", "fleet-sync.timer", expected=1)
        fixture.put(self.home / "systemctl.log", "")
        target = self.home / ".config/systemd/user/fleet-sync.timer"
        unrelated = link.with_name("personal.timer")
        unrelated.symlink_to("/personal/timer")
        with patch.dict(os.environ, self.env, clear=True):
            module, runner = self.runner()
            replace = module.os.replace
            observed = []
            def observe_replace(source, destination, *args, **kwargs):
                if destination == "fleet-sync.timer" and "dst_dir_fd" in kwargs:
                    self.assertEqual(os.readlink(link), "/old-release/fleet-sync.timer")
                    observed.append(True)
                return replace(source, destination, *args, **kwargs)
            with patch.object(module.os, "replace", side_effect=observe_replace):
                runner.units()
            self.assertEqual(observed, [True])
        self.assertEqual(os.readlink(link), str(target))
        self.assertEqual(os.readlink(unrelated), "/personal/timer")
        self.assertIn(["--user", "enable", "--now", "--no-reload", "fleet-sync.timer"], self.calls())
        self.assertFalse(any("--force" in call for call in self.calls()))

    def test_interrupt_waits_for_installer_group_before_unlock(self):
        installer = '''#!/usr/bin/env python3
import json, os, signal, subprocess, sys
for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    signal.signal(sig, signal.SIG_IGN)
code = "import signal; [signal.signal(s,signal.SIG_IGN) for s in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP)]; print('ready',flush=True); signal.pause()"
child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
assert child.stdout.readline().strip() == "ready"
with open(os.environ["SIGNAL_INFO"], "w") as ready:
    ready.write(json.dumps({"group": os.getpgrp(), "pids": [os.getpid(), child.pid]}) + "\\n")
signal.pause()
'''
        fixture.put(self.fabrig / "tools/install", installer, True)
        self.git(self.fabrig, "add", ".")
        self.git(self.fabrig, "commit", "-qm", "fake interruptible install")
        self.git(self.fabrig, "push", "origin", "main")
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signal=sig):
                home = self.directory / f"signal-home-{sig}"
                home.mkdir()
                ready = home / "signal-info"
                os.mkfifo(ready)
                ready_fd = os.open(ready, os.O_RDWR | os.O_NONBLOCK)
                process = subprocess.Popen(["python3", "-I", "-B", str(self.source / "tools/fleet-sync"), "--host", "hel8", "--json"],
                    env={**self.env, "HOME": str(home), "SIGNAL_INFO": str(ready)},
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
                info, descriptors = None, []
                try:
                    readiness = select.poll()
                    readiness.register(ready_fd, select.POLLIN)
                    self.assertTrue(readiness.poll(30_000), "fake installer did not start")
                    info = json.loads(os.read(ready_fd, 4096))
                    for pid in info["pids"]:
                        descriptors.append(os.pidfd_open(pid))
                    poll = select.poll()
                    for descriptor in descriptors:
                        poll.register(descriptor, select.POLLIN)
                    with (home / ".local/state/fabrig/install.lock").open("r") as lock:
                        with self.assertRaises(BlockingIOError):
                            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        process.send_signal(sig)
                        deadline = time.monotonic() + 9
                        while process.poll() is None and time.monotonic() < deadline:
                            try:
                                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            except BlockingIOError:
                                pass
                            else:
                                exited = {fd for fd, _ in poll.poll(0)}
                                for pid, fd in zip(info["pids"], descriptors):
                                    self.assertTrue(fd in exited or exiting(pid),
                                                    "install lock became free while descendants survived")
                                fcntl.flock(lock, fcntl.LOCK_UN)
                            time.sleep(0.01)
                        output, error = process.communicate(timeout=1)
                        self.assertEqual(process.returncode, 130 if sig == signal.SIGINT else 143, output + error)
                        # poll can wake for just one pidfd. Accumulate readiness
                        # until both have exited, rather than sampling a moment.
                        pending = set(descriptors)
                        deadline = time.monotonic() + 5
                        while pending and time.monotonic() < deadline:
                            for fd, _ in poll.poll(100):
                                pending.discard(fd)
                                poll.unregister(fd)
                        self.assertFalse(pending, "installer group survived fleet-sync exit")
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    deadline = time.monotonic() + 2
                    while time.monotonic() < deadline:
                        try:
                            os.killpg(info["group"], 0)
                        except ProcessLookupError:
                            break
                        time.sleep(0.01)
                    else:
                        self.fail("installer process group remains after fleet-sync exit")
                finally:
                    os.close(ready_fd)
                    if info:
                        try:
                            os.killpg(info["group"], signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
                    for descriptor in descriptors:
                        os.close(descriptor)


def load_tests(loader, tests, pattern):
    suite = loader.loadTestsFromTestCase(ExitObservationTests)
    suite.addTests(Review2Test(name) for name in Review2Test.__dict__ if name.startswith("test_"))
    return suite


if __name__ == "__main__":
    unittest.main()
