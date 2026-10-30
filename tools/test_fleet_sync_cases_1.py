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
    def test_blocks_and_conflicts(self):
        outside = '# personal\nexport DISABLE_AUTOUPDATER=0\ncase $- in *i*) ;; *) return;; esac\n'
        put(self.home / ".bashrc", outside)
        put(self.home / ".profile", "# profile\n")
        put(self.home / ".config/plan/environment.sh", "export TEMPER_FORGEJO=/wrong\n")
        state = self.sync()
        self.assertTrue(any(i["item"].startswith("conflict:") for i in state["items"]))
        bashrc = self.home / ".bashrc"
        self.assertTrue(bashrc.read_text().endswith(outside))
        self.assertTrue(bashrc.read_text().startswith("# >>> fleet-sync >>>\n"))
        before = bashrc.read_text()
        self.sync()
        self.assertEqual(bashrc.read_text(), before)
        # Update an obsolete block, retaining every byte outside it.
        put(bashrc, before.replace('[ ! -f "$HOME/.config/fabrig/env.sh" ] || . "$HOME/.config/fabrig/env.sh"', "# obsolete source"))
        self.sync()
        self.assertEqual(bashrc.read_text(), before)

    def test_codex_preserves_project_bytes(self):
        suffix = '[projects."/tmp/a"]\ntrust_level = "trusted" # keep\n\n[projects."/tmp/b"]\ntrust_level = "untrusted"\n'
        put(self.home / ".codex/config.toml", '# keep comment\nmodel = "old"\npersonality = "friendly"\n' + suffix)
        self.sync()
        content = (self.home / ".codex/config.toml").read_text()
        self.assertTrue(content.endswith(suffix))
        self.assertIn('# keep comment\n', content)
        self.assertIn('personality = "friendly"\n', content)
        self.assertEqual(tomllib.loads(content)["model_reasoning_effort"], "high")

    def test_codex_multiline_and_crlf_preserved(self):
        prefix = '# keep\r\nnotes = """\r\nmodel = "inside a string"\r\n[apparent.header]\r\n"""\r\n'
        suffix = '[projects."/tmp/a"]\r\ntrust_level = "trusted"\r\n'
        path = self.home / ".codex/config.toml"
        put(path, prefix + '"model" = "old"\r\n' + suffix)
        self.sync()
        result = path.read_bytes().decode()
        self.assertTrue(result.startswith(prefix))
        self.assertTrue(result.endswith(suffix))
        self.assertEqual(tomllib.loads(result)["model"], "gpt-6.1-sol")

    def test_json_semantics_and_file_mtime(self):
        self.sync()
        path = self.home / ".claude/settings.json"
        put(path, json.dumps(json.loads(path.read_text()), sort_keys=True))
        before = path.stat().st_mtime_ns
        state = self.sync()
        self.assertEqual(before, path.stat().st_mtime_ns)
        self.assertEqual(next(i["result"] for i in state["items"] if i["item"] == ".claude/settings.json"), "ok")

    def test_check_writes_nothing_empty_and_configured(self):
        before = self.snapshot(exclude_mirror=True)
        self.sync("--check", expected=1)
        self.assertEqual(before, self.snapshot(exclude_mirror=True))
        self.sync()
        put(self.home / ".cargo/config.toml", "# drift\n")
        before = self.snapshot(exclude_mirror=True)
        self.sync("--check", expected=1)
        self.assertEqual(before, self.snapshot(exclude_mirror=True))

    def test_unknown_host_no_writes(self):
        before = self.snapshot()
        result = self.process("python3", "-I", "-B", self.source / "tools/fleet-sync", "--host", "unknown", expected=2)
        self.assertIn("unknown host", result.stderr)
        self.assertEqual(before, self.snapshot())

    def test_timer_lock_is_quiet(self):
        path = self.home / ".local/state/fleet-sync/lock"
        put(path, "")
        with path.open("r") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            before = self.snapshot()
            self.assertIsNone(self.sync("--timer"))
            self.assertEqual(before, self.snapshot())
            self.assertEqual(self.sync("--check")["items"], [
                {"item": "lock", "result": "busy", "reason": "a run is in progress; check again"}])

    def test_units_reload_only_on_change(self):
        self.sync()
        calls = self.calls()
        self.assertEqual(calls.count(["--user", "daemon-reload"]), 1)
        self.sync()
        self.assertEqual(self.calls().count(["--user", "daemon-reload"]), 1)
        self.assertFalse(any("restart" in a or "stop" in a for a in self.calls()))
        self.assertEqual(next(i["result"] for i in self.sync("--check")["items"] if i["item"] == "enabled:fleet-sync.timer"), "ok")


if __name__ == "__main__":
    unittest.main()
