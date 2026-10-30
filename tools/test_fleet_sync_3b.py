"""Busy checks and system-command collision regressions in disposable HOME."""

import datetime as dt
import fcntl
import json
import unittest

import test_fleet_sync as fixture


BUSY = {"item": "lock", "result": "busy", "reason": "a run is in progress; check again"}


class FleetSync3bTest(fixture.FleetFixture):
    def test_busy_check_reports_one_item_without_altering_backoff(self):
        self.sync()
        saved = self.state()
        saved.update(consecutive_failures=2, last_failure=dt.datetime.now(dt.UTC).isoformat())
        fixture.put(self.home / ".local/state/fleet-sync/state.json", json.dumps(saved))
        fixture.put(self.home / ".config/fleet-sync/retry", "operator\n")
        with (self.home / ".local/state/fleet-sync/lock").open("rb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            before = self.snapshot()
            for options in (("--check",), ("--check", "--timer")):
                with self.subTest(options=options):
                    state = self.sync(*options)
                    self.assertEqual(state["items"], [BUSY])
                    self.assertEqual(state["consecutive_failures"], 2)
                    self.assertEqual(state["last_failure"], saved["last_failure"])
                    self.assertIsNotNone(state["end"])
            text = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync",
                                "--host", "hel8", "--check").stdout
            self.assertIn("busy", text)
            self.assertIn("a run is in progress; check again", text)
            self.assertIn("hel8: 1 busy", text)
            self.assertIsNone(self.sync("--timer"))
            self.assertEqual(self.snapshot(), before)

    def test_status_treats_local_and_remote_busy_as_nonfailures(self):
        self.sync()
        fixture.put(self.bin / "ssh", '''#!/usr/bin/env python3
import json, os, sys
host = json.loads(os.environ["FAKE_SSH_HOSTS"])[sys.argv[-2]]
items = [{"item": "lock", "result": "busy", "reason": "a run is in progress; check again"}]
if os.environ.get("FAKE_REMOTE_DRIFT") and host == "hetzner3":
    items = [{"item": "agents", "result": "drift", "reason": "release differs"}]
print(json.dumps({"host": host, "items": items}))
''', True)
        with (self.home / ".local/state/fleet-sync/lock").open("rb") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            before = self.snapshot()
            status = self.sync("status")
            for row in status["hosts"]:
                self.assertEqual(row["items"], [BUSY])
            text = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync",
                                "status", "--host", "hel8").stdout
            self.assertEqual(text.count("busy lock: a run is in progress; check again"), len(status["hosts"]))
            self.sync("status", expected=1, env={**self.env, "FAKE_REMOTE_DRIFT": "1"})
            self.assertEqual(self.snapshot(), before)

    def test_system_executable_names_fail_self_check_and_block_promotion(self):
        self.sync()
        current = self.current()
        manifest = self.source / "tools/installed"
        original = manifest.read_text()
        for name, directory in zip(("reserved-a", "reserved-b"), self.system_bins):
            with self.subTest(directory=directory):
                fixture.put(directory / name, "#!/bin/sh\nexit 0\n", True)
                fixture.put(manifest, original + f"{name} fleet-sync\n")
                checked = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync",
                                       "--host", "hel8", "--self-check", expected=2)
                self.assertIn(f"shadows system command: {name}", checked.stderr)
                self.publish()
                state = self.sync(script=current / "tools/fleet-sync", expected=1)
                self.assertEqual(self.current(), current)
                self.assertTrue(any(i["item"] == "agents" and i["result"] == "failed" for i in state["items"]))

    def test_collision_guard_ignores_noncommands_and_refuses_executable_symlinks(self):
        fixture.put(self.system_bins[0] / "nonexec", "not executable\n")
        (self.system_bins[1] / "directory-tool").mkdir()
        fixture.put(self.bin / "local-command", "#!/bin/sh\nexit 0\n", True)
        manifest = self.source / "tools/installed"
        allowed = manifest.read_text() + "nonexec fleet-sync\ndirectory-tool fleet-sync\nlocal-command fleet-sync\n"
        fixture.put(manifest, allowed)
        self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--host", "hel8", "--self-check")
        (self.system_bins[1] / "linked-command").symlink_to(self.bin / "local-command")
        for name in ("linked-command", "watch"):
            with self.subTest(name=name):
                fixture.put(manifest, allowed + f"{name} fleet-sync\n")
                self.process("python3", "-I", "-B", self.source / "tools/fleet-sync",
                             "--host", "hel8", "--self-check", expected=2)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(FleetSync3bTest(name) for name in FleetSync3bTest.__dict__ if name.startswith("test_"))
