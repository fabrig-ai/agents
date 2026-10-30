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
    def test_never_touches_coordination_heavy_or_spools(self):
        protected = ["src/fabrig/claims", "src/fabrig/leases", "src/fabrig/queue", "src/fabrig/slots",
                     ".local/state/heavy", ".local/state/agents-heavy", ".local/state/fabrig/heavy",
                     "src/rust/tmp/heavy", "src/rust/tmp/codex-run", "src/rust/tmp/owners",
                     "src/rust/tmp/logins",
                     "src/rust/tmp/post/inbox", "src/rust/tmp/post/outbox", "src/rust/tmp/post/sent",
                     "src/rust/tmp/post/arbitrary-spool"]
        units = [".config/systemd/user/agents-heavy-reconcile.service",
                 ".config/systemd/user/agents-heavy-reconcile.timer",
                 ".config/systemd/user/heavy.service"]
        for directory in protected:
            put(self.home / directory / "sentinel", "opaque state\n")
        for unit in units:
            put(self.home / unit, "[Unit]\nDescription=Never touch\n")
        snapshots = {p: self.snapshot(root=self.home / p) for p in protected + units}
        self.sync()
        self.sync("--check")
        self.assertEqual(snapshots, {p: self.snapshot(root=self.home / p) for p in protected + units})
        self.assertFalse(any(any("heavy" in arg for arg in argv) for argv in self.calls()))

    def test_shell_outside_bytes_preserved(self):
        outside = "# keep CRLF\r\n# outside\r\n"
        put(self.home / ".profile", outside)
        put(self.home / ".bashrc", outside)
        self.sync()
        self.assertTrue((self.home / ".profile").read_bytes().decode().startswith(outside))
        self.assertTrue((self.home / ".bashrc").read_bytes().decode().endswith(outside))

    def test_full_sha_pin_rolls_back_current(self):
        self.sync()
        put(self.source / "fleet/env", (self.source / "fleet/env").read_text() + "NEW_VALUE=1\n")
        self.publish()
        self.sync()
        put(self.home / ".config/fleet-sync/pin", self.sha + "\n")
        state = self.sync(script=self.current() / "tools/fleet-sync")
        self.assertEqual(self.current().name, "agents-" + self.sha)
        self.assertEqual(state["agents_sha"], self.sha)
        self.assertNotIn("NEW_VALUE", (self.home / ".config/fabrig/env.sh").read_text())

    def test_timer_age_and_history_pruning(self):
        self.sync("--timer")
        stamp = self.state()["last_timer_end"]
        history = self.home / ".local/state/fleet-sync/runs.jsonl"
        stale = {"end": (dt.datetime.now(dt.UTC) - dt.timedelta(days=8)).isoformat()}
        put(history, json.dumps(stale) + "\n" + history.read_text())
        self.sync()
        self.assertEqual(self.state()["last_timer_end"], stamp)
        self.assertEqual(len(history.read_text().splitlines()), 1)
        self.assertEqual(self.sync("--check")["last_timer_end"], stamp)

    def test_status_unreachable(self):
        self.sync("--timer")
        state = self.sync("status", expected=1)
        self.assertEqual(len(state["hosts"]), HOST_COUNT)
        self.assertIn("unreachable", next(h for h in state["hosts"] if h["host"] == "hetzner3"))
        self.assertTrue(next(h for h in state["hosts"] if h["host"] == "hel8")["last_timer_end"])
        calls = [json.loads(line) for line in (self.home / "ssh.log").read_text().splitlines()]
        self.assertEqual(len(calls), HOST_COUNT - 1)
        self.assertTrue(all("StrictHostKeyChecking=yes" in c and "BatchMode=yes" in c for c in calls))

    def test_release_retention(self):
        self.sync()
        directory = self.home / "src/fabrig/releases"
        for n in range(12):
            path = directory / f"agents-{n:040x}"
            path.mkdir()
            os.utime(path, (n + 1, n + 1))
        self.sync()
        self.assertEqual(len(list(directory.glob("agents-*"))), 10)
        self.assertTrue(self.current().is_dir())

    def test_invalid_declaration_changes_nothing(self):
        put(self.source / "fleet/unparsed.txt", "surprise\n")
        before = self.snapshot()
        self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--host", "hel8", expected=2)
        self.assertEqual(before, self.snapshot())


if __name__ == "__main__":
    unittest.main()
