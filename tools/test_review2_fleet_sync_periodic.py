"""Installer signal hardening sweep for the periodic tier."""
from test_review2_fleet_sync import *


class PeriodicReview2Test(Review2Test):
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
    return unittest.TestSuite([PeriodicReview2Test("test_interrupt_waits_for_installer_group_before_unlock")])
