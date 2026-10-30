#!/usr/bin/env python3
"""Lifecycle hook checks with a temporary HOME and fake services only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HOOK = Path(__file__).with_name("reap-hook")
IDENTITY = "63cf764d-1df5-478f-92de-5aeb424fda12"


class HookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.bin = self.home / "bin"
        self.bin.mkdir()
        self.log = self.home / "calls.jsonl"
        self.env = dict(HOME=str(self.home), PATH=str(self.bin), LOG=str(self.log))
        for name in ("reap", "systemctl"):
            path = self.bin / name
            path.write_text(f"#!{sys.executable}\n" + '''import json, os, pathlib, sys, time
with open(os.environ['LOG'], 'a') as stream:
    stream.write(json.dumps([pathlib.Path(sys.argv[0]).name, *sys.argv[1:]]) + '\\n')
if os.environ.get('HANG') == '1':
    time.sleep(10)
print('unwanted stdout')
print('unwanted stderr', file=sys.stderr)
sys.exit(int(os.environ.get('FAIL', '0')))
''')
            path.chmod(0o755)

    def run_hook(self, event="SessionStart", identity=IDENTITY, raw=None):
        result = subprocess.run([sys.executable, "-I", "-B", str(HOOK), "lead/q/temper"],
                                input=raw if raw is not None else json.dumps(dict(
                                    hook_event_name=event, session_id=identity)),
                                capture_output=True, text=True, env=self.env)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_start_uses_cached_name_and_short_jobs_path_without_lookup(self):
        state = self.home / "cache"
        state.mkdir()
        (state / "names.json").write_text(json.dumps({IDENTITY[:8]: "cached-session"}))
        self.env["SESSION_CONTEXT_STATE"] = str(state)
        self.assertEqual(self.run_hook(), [["reap", "record", "start", "--kind", "claude-session",
            "--owner", "cached-session", "--id", IDENTITY, "--path", str(self.home / ".claude/jobs/63cf764d")]])

    def test_name_fallback_for_missing_bad_and_ambiguous_cache(self):
        state = self.home / ".local/state/session-context"
        state.mkdir(parents=True)
        for cache in (None, '{', '[]', json.dumps({IDENTITY: "a", IDENTITY[:8]: "b"})):
            with self.subTest(cache=cache):
                if cache is not None:
                    (state / "names.json").write_text(cache)
                calls = self.run_hook()
                self.assertEqual(calls[-1][calls[-1].index("--owner") + 1], "lead/q/temper")

    def test_end_records_and_starts_service(self):
        self.assertEqual(self.run_hook("SessionEnd"), [
            ["reap", "record", "end", "--kind", "claude-session", "--id", IDENTITY],
            ["systemctl", "--user", "start", "--no-block", "reap.service"]])

    def test_absent_reap_is_silent_even_on_end(self):
        (self.bin / "reap").unlink()
        self.assertEqual(self.run_hook(), [])
        self.assertEqual(self.run_hook("SessionEnd"), [])

    def test_failures_and_timeouts_are_silent_and_end_still_wakes_service(self):
        for key in ("FAIL", "HANG"):
            with self.subTest(key=key):
                self.env[key] = "1"
                self.run_hook()
                calls = self.run_hook("SessionEnd")
                self.assertEqual(calls[-1][0], "systemctl")
                del self.env[key]

    def test_bad_events_are_silent(self):
        for raw in ("{", "[]", "null", '{}', '{"session_id":"../../oops","hook_event_name":"SessionStart"}'):
            self.assertEqual(self.run_hook(raw=raw), [])
        self.assertEqual(self.run_hook("Stop"), [])


if __name__ == "__main__":
    unittest.main()
