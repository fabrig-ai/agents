"""Fleet regressions, using the shared disposable fixture without inherited cases."""
import argparse
import datetime as dt
import fcntl
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import patch
import test_fleet_sync as fixture
from test_fleet_sync import put, ROOT, FABRIG_TOOLS, HOST_COUNT


class FleetCases(fixture.FleetFixture):
    def test_installed_head_missing_from_mirror_counts_changed(self):
        self.sync()
        clone = self.home / "src/fabrig/main"
        put(clone / "local-only", "unpublished commit\n")
        self.git(clone, "add", ".")
        self.git(clone, "commit", "-qm", "installed local commit")
        self.assertEqual(self.fabrig_item(self.sync("--check", expected=1))["result"], "drift")

    def test_install_lock_busy_skips_fabrig_and_continues(self):
        self.sync()
        path = self.home / ".local/state/fabrig/install.lock"
        inode = path.stat().st_ino
        link = self.home / ".local/bin/claim"
        link.unlink()
        link.symlink_to("wrong")
        with path.open("r") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            before = self.snapshot()
            self.assertEqual(self.fabrig_item(self.sync("--check")),
                {"item": "fabrig", "result": "held", "reason": "install lock busy"})
            self.assertEqual(before, self.snapshot())
            (self.home / ".cargo/config.toml").unlink()
            state = self.sync()
            self.assertEqual(self.fabrig_item(state)["result"], "held")
            self.assertTrue((self.home / ".cargo/config.toml").exists())
            self.assertEqual(os.readlink(link), "wrong")
        self.assertEqual(path.stat().st_ino, inode)

    def test_install_lock_inode_modes_scope_and_installer_exclusion(self):
        with patch.dict(os.environ, self.env, clear=True):
            module, runner = self.runner()
            command = runner.cmd
            path = self.home / ".local/state/fabrig/install.lock"
            observed = []
            def assert_locked(*args, **kwargs):
                if str(args[-1]).endswith("tools/install"):
                    self.assertEqual(kwargs.get("timeout"), 300)
                    with path.open("r") as stream:
                        with self.assertRaises(BlockingIOError):
                            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    observed.append("installer")
                return command(*args, **kwargs)
            with patch.object(runner, "cmd", side_effect=assert_locked):
                runner.fabrig()
            self.assertEqual(observed, ["installer"])
            inode = path.stat().st_ino
            real_readlink = os.readlink
            def readlink_checked(link, *args, **kwargs):
                if Path(link).parent == self.home / ".local/bin" or "dir_fd" in kwargs:
                    with path.open("r") as stream:
                        with self.assertRaises(BlockingIOError):
                            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    observed.append("link")
                return real_readlink(link, *args, **kwargs)
            with patch.object(module.os, "readlink", side_effect=readlink_checked):
                runner.fabrig()
            self.assertIn("link", observed)
            self.assertEqual(path.stat().st_ino, inode)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            with path.open("r") as stream:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)  # Released at step return.

    def test_install_lock_refuses_symlink_fifo_and_directory(self):
        lock = self.home / ".local/state/fabrig/install.lock"
        lock.parent.mkdir(parents=True)
        target = self.home / "untouched"
        put(target, "never replace or follow\n")
        lock.symlink_to(target)
        self.assertEqual(self.fabrig_item(self.sync(expected=1))["result"], "failed")
        self.assertTrue(lock.is_symlink())
        self.assertEqual(target.read_text(), "never replace or follow\n")
        lock.unlink()
        os.mkfifo(lock, 0o600)
        self.assertIn("not a regular file", self.fabrig_item(self.sync(expected=1))["reason"])
        self.assertTrue(stat.S_ISFIFO(lock.lstat().st_mode))
        lock.unlink()
        lock.mkdir()
        self.assertEqual(self.fabrig_item(self.sync(expected=1))["result"], "failed")
        self.assertTrue(lock.is_dir())

    def test_install_lock_modes_check_read_only_normal_repairs_inode(self):
        self.sync()
        lock = self.home / ".local/state/fabrig/install.lock"
        inode = lock.stat().st_ino
        lock.chmod(0o644)
        lock.parent.chmod(0o755)
        before = self.snapshot()
        self.assertIn("0600", self.fabrig_item(self.sync("--check", expected=1))["reason"])
        self.assertEqual(before, self.snapshot())
        self.sync()
        self.assertEqual(lock.stat().st_ino, inode)
        self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(lock.parent.stat().st_mode), 0o700)

    def test_defer_before_lock_keeps_controls_unchanged(self):
        defer = self.home / ".config/fleet-sync/defer-fabrig"
        put(defer, "ops upgrading\nsecond line\n")
        state = self.sync()
        self.assertEqual(self.fabrig_item(state), {"item": "fabrig", "result": "deferred", "reason": "ops upgrading"})
        self.assertFalse((self.home / ".local/state/fabrig/install.lock").exists())
        self.assertFalse((self.home / "src/fabrig/main").exists())
        self.assertEqual(defer.read_text(), "ops upgrading\nsecond line\n")
        self.assertFalse((defer.parent / "pin").exists())
        self.assertFalse((defer.parent / "hold").exists())
        result = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--host", "hel8")
        self.assertIn("1 deferred", result.stdout)

    def test_defer_created_during_lock_acquisition(self):
        with patch.dict(os.environ, self.env, clear=True):
            module, runner = self.runner()
            real_flock = fcntl.flock
            lock = self.home / ".local/state/fabrig/install.lock"
            def acquire_then_defer(fd, operation):
                real_flock(fd, operation)
                with lock.open("r") as other:
                    with self.assertRaises(BlockingIOError):
                        real_flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                put(self.home / ".config/fleet-sync/defer-fabrig", "raced with ops\n")
            with patch.object(module.fcntl, "flock", side_effect=acquire_then_defer):
                runner.fabrig()
            self.assertEqual(self.fabrig_item(runner.state)["result"], "deferred")
            self.assertFalse(runner.log)  # No git calls or link checks before the second defer check.

    def test_defer_created_during_fetch_precedes_link_check(self):
        self.sync()
        put(self.home / "src/fabrig/main/tools/installed", "malformed manifest to detect a read\n")
        with patch.dict(os.environ, self.env, clear=True):
            _, runner = self.runner()
            command = runner.cmd
            def fetch_then_defer(*args, **kwargs):
                result = command(*args, **kwargs)
                if args[0] == "git" and "fetch" in args and str(args[2]).endswith("fabrig.git"):
                    put(self.home / ".config/fleet-sync/defer-fabrig", "deferred during fetch\n")
                return result
            with patch.object(runner, "cmd", side_effect=fetch_then_defer):
                runner.fabrig()
            self.assertEqual(self.fabrig_item(runner.state)["result"], "deferred")


if __name__ == "__main__":
    unittest.main()
