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
    def test_role_change_removes_only_owned_units(self):
        roles = self.source / "fleet/units/roles.toml"
        put(roles, roles.read_text() + '"role.service" = ["session"]\n"role.timer" = ["session"]\n')
        put(self.source / "fleet/units/role.service", "[Unit]\nDescription=Role\n[Service]\nType=simple\nExecStart=/bin/true\n")
        put(self.source / "fleet/units/role.timer", "[Unit]\nDescription=Role timer\n[Timer]\nOnCalendar=minutely\n[Install]\nWantedBy=timers.target\n")
        self.publish()
        state = self.sync()
        self.assertTrue(any(i["reason"].startswith("restart pending") for i in state["items"]))
        units = self.home / ".config/systemd/user"
        put(units / "personal.service", "keep\n")
        hosts = self.source / "fleet/hosts.toml"
        put(hosts, hosts.read_text().replace('roles = ["session"]', 'roles = ["builder"]'))
        self.publish()
        self.sync()
        self.assertFalse((units / "role.service").exists())
        self.assertFalse((units / "role.timer").exists())
        self.assertEqual((units / "personal.service").read_text(), "keep\n")
        self.assertIn(["--user", "disable", "--no-reload", "role.service"], self.calls())

    def test_no_bus_fails(self):
        state = self.sync(expected=1, env={**self.env, "FAKE_NO_BUS": "1"})
        self.assertTrue(any(i["item"] == "units" and i["result"] == "failed" for i in state["items"]))
        self.assertTrue(self.state()["unit_reload_pending"])
        self.sync()
        self.assertEqual(self.calls().count(["--user", "daemon-reload"]), 1)
        self.assertFalse(self.state()["unit_reload_pending"])

    def test_status_from_outside_fleet(self):
        script = self.source / "tools/fleet-sync"
        put(script, script.read_text().replace("import socket\n", "import socket\nsocket.gethostname = lambda: 'outside-fleet'\n"), True)
        result = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "status", "--json", expected=1)
        self.assertEqual(len(json.loads(result.stdout)["hosts"]), HOST_COUNT)
        calls = [json.loads(line) for line in (self.home / "ssh.log").read_text().splitlines()]
        self.assertEqual(len(calls), HOST_COUNT)

    def test_fabrig_failure_does_not_skip_files(self):
        self.sync()
        self.git(self.home / "src/fabrig/main", "remote", "set-url", "origin", self.origin)
        (self.home / ".cargo/config.toml").unlink()
        state = self.sync(expected=1)
        self.assertTrue(any(i["item"] == "fabrig" and i["result"] == "failed" for i in state["items"]))
        self.assertTrue((self.home / ".cargo/config.toml").exists())

    def test_fabrig_new_head_and_link_repair(self):
        self.sync()
        put(self.fabrig / "tools/new-file", "new\n")
        self.git(self.fabrig, "add", ".")
        self.git(self.fabrig, "commit", "-qm", "fabrig update")
        self.git(self.fabrig, "push", "origin", "main")
        state = self.sync()
        self.assertEqual(state["fabrig_sha"], self.git(self.fabrig, "rev-parse", "HEAD").strip())
        link = self.home / ".local/bin/claim"
        link.unlink()
        state = self.sync()
        self.assertTrue(link.is_symlink())
        self.assertIn("tools/install", (self.home / ".local/state/fleet-sync/run.log").read_text())

    def test_fabrig_non_tools_landing_leaves_main_untouched(self):
        self.sync()
        clone = self.home / "src/fabrig/main"
        installed = self.git(clone, "rev-parse", "HEAD").strip()
        before = self.snapshot(root=clone)
        put(self.fabrig / "docs/new", "docs only\n")
        self.git(self.fabrig, "add", ".")
        self.git(self.fabrig, "commit", "-qm", "non-tool landing")
        self.git(self.fabrig, "push", "origin", "main")
        remote = self.git(self.fabrig, "rev-parse", "HEAD").strip()
        state = self.sync()
        self.assertEqual(before, self.snapshot(root=clone))
        self.assertEqual(state["fabrig_sha"], installed)
        self.assertEqual(self.fabrig_item(state), {"item": "fabrig", "result": "ok",
            "reason": f"main ahead, tools unchanged ({installed[:7]} -> {remote[:7]})"})
        self.assertNotIn("tools/install", (self.home / ".local/state/fleet-sync/run.log").read_text())
        mirror = self.home / "src/fabrig/.fleet-sync/fabrig.git"
        self.assertEqual(self.git(mirror, "rev-parse", "origin/main").strip(), remote)
        self.assertEqual(self.git(mirror, "rev-parse", "--is-bare-repository").strip(), "true")
        self.assertEqual(self.git(mirror, "config", "--get", "remote.origin.partialclonefilter").strip(), "blob:none")
        self.assertEqual(stat.S_IMODE(mirror.stat().st_mode), 0o700)

    def test_check_fetches_only_existing_mirror(self):
        self.sync()
        put(self.fabrig / "tools/new", "tool change\n")
        self.git(self.fabrig, "add", ".")
        self.git(self.fabrig, "commit", "-qm", "tool landing")
        self.git(self.fabrig, "push", "origin", "main")
        mirror = self.home / "src/fabrig/.fleet-sync/fabrig.git"
        old = self.git(mirror, "rev-parse", "origin/main")
        before = self.snapshot(exclude_mirror=True)
        state = self.sync("--check", expected=1)
        self.assertEqual(before, self.snapshot(exclude_mirror=True))
        self.assertNotEqual(old, self.git(mirror, "rev-parse", "origin/main"))
        self.assertEqual(self.fabrig_item(state)["result"], "drift")

    def test_check_missing_mirror_and_lock_creates_neither(self):
        self.sync()
        mirror = self.home / "src/fabrig/.fleet-sync/fabrig.git"
        lock = self.home / ".local/state/fabrig/install.lock"
        shutil.rmtree(mirror)
        lock.unlink()  # Fixture cleanup only; fleet-sync must never unlink this inode.
        before = self.snapshot()
        self.assertEqual(self.fabrig_item(self.sync("--check"))["result"], "ok")
        self.assertEqual(before, self.snapshot())
        put(self.fabrig / "docs-only", "ahead\n")
        self.git(self.fabrig, "add", ".")
        self.git(self.fabrig, "commit", "-qm", "non-tool landing")
        self.git(self.fabrig, "push", "origin", "main")
        state = self.sync("--check", expected=1)
        self.assertEqual(self.fabrig_item(state)["result"], "drift")
        self.assertEqual(before, self.snapshot())
        self.assertFalse(mirror.exists())
        self.assertFalse(lock.exists())


if __name__ == "__main__":
    unittest.main()
