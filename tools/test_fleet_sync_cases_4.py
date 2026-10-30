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
    def test_defer_created_during_bootstrap_precedes_installer(self):
        with patch.dict(os.environ, self.env, clear=True):
            _, runner = self.runner()
            command = runner.cmd
            def clone_then_defer(*args, **kwargs):
                result = command(*args, **kwargs)
                if args[0] == "git" and "clone" in args and ".fabrig-install-" in str(args[-1]):
                    put(self.home / ".config/fleet-sync/defer-fabrig", "ops deferred bootstrap\n")
                return result
            with patch.object(runner, "cmd", side_effect=clone_then_defer):
                runner.fabrig()
            self.assertEqual(self.fabrig_item(runner.state)["result"], "deferred")
            self.assertFalse((self.home / "src/fabrig/main").exists())
            self.assertFalse(any("tools/install" in entry for entry in runner.log))

    def test_defer_created_during_links_stops_remaining_checks(self):
        self.sync()
        with patch.dict(os.environ, self.env, clear=True):
            module, runner = self.runner()
            readlink = os.readlink
            seen = []
            def readlink_then_defer(path, *args, **kwargs):
                result = readlink(path, *args, **kwargs)
                if Path(path).parent == self.home / ".local/bin" or "dir_fd" in kwargs:
                    seen.append(str(path))
                    put(self.home / ".config/fleet-sync/defer-fabrig", "ops deferred link checks\n")
                return result
            with patch.object(module.os, "readlink", side_effect=readlink_then_defer):
                runner.fabrig()
            self.assertEqual(len(seen), 1)
            self.assertEqual(self.fabrig_item(runner.state)["result"], "deferred")

    def test_versions_warn_only(self):
        put(self.bin / "codex", "#!/bin/bash\necho codex-cli 0.0.1\n", True)
        state = self.sync()
        self.assertEqual(next(i["result"] for i in state["items"] if i["item"] == "version:codex"), "warn")

    def test_builder_rendering_and_env_host_override(self):
        self.sync("--host", "hetzner6", env={**self.env, "FLEET_HOST": "hel8"})
        self.assertEqual(self.state()["host"], "hetzner6")
        self.assertNotIn("jobs", tomllib.loads((self.home / ".cargo/config.toml").read_text())["build"])
        self.assertEqual((self.home / "src/rust/tmp/machine.env").read_text(),
                         "PLAN_MIN_DISK_GB=40\nKACHE_MAX_GB=50\nKACHE_LOCAL_ONLY=1\nQA_SLOTS=2\nHEAVY_BUILD_SLOTS=3\n"
                         "QA_WALK_KINDS=forgejo=2:chatgpt,claude=2:claude\nQA_WALK_SLOTS=forgejo=8+1,claude=4+3\n"
                         "QA_SLOT_HOST=hetzner6\nQA_CLAIM_OWNER=s/qa\nQA_CLAIM_SSH=free@204.168.210.29\n"
                         "QA_STUCK_TO=s/qa@hel8\n")
        settings = json.loads((self.home / ".claude/settings.json").read_text())
        self.assertNotIn("HEAVY_BUILD_JOBS", settings["env"])
        self.assertNotIn("PATH", settings["env"])
        self.assertTrue(settings["env"]["SKEIN_TEST_CHROMIUM"].startswith(str(self.home)))

    def test_post_machines_check_only_never_written_or_backed_up(self):
        path = self.home / "src/rust/tmp/post/machines"
        put(path, "ops routing\n")
        before = path.stat().st_mtime_ns
        for flags in ((), ("--check",)):
            state = self.sync(*flags)
            item = next(i for i in state["items"] if i["item"] == "src/rust/tmp/post/machines")
            self.assertEqual(item["result"], "warn")
            self.assertIn("names differ:", item["reason"])
            self.assertIn("ops", item["reason"])
            self.assertEqual(path.read_text(), "ops routing\n")
            self.assertEqual(path.stat().st_mtime_ns, before)
            self.assertFalse(path.with_name("machines.pre-fleet-sync").exists())

    def test_policy_write_opt_in_and_matching_check_only(self):
        policy = self.source / "fleet/policy.toml"
        put(policy, '[files]\n"src/rust/tmp/post/machines" = "write"\n')
        self.publish()
        self.sync()
        path = self.home / "src/rust/tmp/post/machines"
        self.assertEqual(path.read_text().splitlines()[0], "hel8 local")
        put(policy, '[files]\n"src/rust/tmp/post/machines" = "check"\n')
        self.publish()
        before = path.stat().st_mtime_ns
        state = self.sync()
        self.assertEqual(next(i["result"] for i in state["items"] if i["item"] == "src/rust/tmp/post/machines"), "ok")
        self.assertEqual(path.stat().st_mtime_ns, before)

    def test_invalid_file_policy_no_writes(self):
        put(self.source / "fleet/policy.toml", '[files]\n"src/rust/tmp/post/machines" = "ignore"\n')
        before = self.snapshot()
        self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--host", "hel8", expected=2)
        self.assertEqual(before, self.snapshot())

    def test_environment_d_plain_values(self):
        self.sync()
        content = (self.home / ".config/environment.d/90-fabrig.conf").read_text()
        self.assertIn(f"SKEIN_TEST_CHROMIUM={self.home}/.local/opt/chromium-147.0.7727.101/bin/chromium\n", content)
        self.assertNotIn('"', content)
        self.assertNotIn("'", content)
        self.assertNotIn("$", content)


if __name__ == "__main__":
    unittest.main()
