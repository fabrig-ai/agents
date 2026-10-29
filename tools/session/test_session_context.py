#!/usr/bin/env python3
"""Offline tests for session-context: a fixture HOME holding a session transcript."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

TOOL = Path(__file__).resolve().parent / "session-context"


def call(tokens, ts="2026-10-29T09:00:00.000Z"):
    return {"type": "assistant", "timestamp": ts,
            "message": {"role": "assistant", "usage": {
                "input_tokens": tokens[0], "cache_read_input_tokens": tokens[1],
                "cache_creation_input_tokens": tokens[2], "output_tokens": tokens[3]}}}


class SessionContext(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.home = self.base / "home"
        self.cwd = self.base / "work.dir"
        self.cwd.mkdir(parents=True)
        self.project = self.home / ".claude/projects" / str(self.cwd).replace("/", "-").replace(".", "-")
        self.project.mkdir(parents=True)

    def transcript(self, name, calls):
        path = self.project / f"{name}.jsonl"
        path.write_text("".join(json.dumps(c) + "\n" for c in calls) + "not json\n")
        return path

    def run_tool(self, *args):
        env = dict(os.environ, HOME=str(self.home))
        return subprocess.run(["python3", "-I", str(TOOL), *args], cwd=self.cwd, env=env,
                              text=True, capture_output=True, stdin=subprocess.DEVNULL)

    def test_latest_call_below_threshold(self):
        self.transcript("aaaa1111-x", [call((10, 100, 0, 5)), call((1_000, 400_000, 2_000, 500))])
        result = self.run_tool()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("aaaa1111: 403,500 of 1,000,000 tokens (40%)", result.stdout)
        self.assertIn("2 calls", result.stdout)
        self.assertNotIn("REACHED", result.stdout)

    def test_threshold_exits_three(self):
        self.transcript("bbbb2222-x", [call((0, 760_000, 0, 0))])
        result = self.run_tool()
        self.assertEqual(result.returncode, 3)
        self.assertIn("REACHED: hand over now", result.stdout)
        self.assertEqual(self.run_tool("--window", "2000000").returncode, 0)
        self.assertEqual(self.run_tool("--threshold", "0.8").returncode, 0)

    def test_session_by_prefix_and_newest_by_default(self):
        old = self.transcript("cccc3333-old", [call((0, 1_000, 0, 0))])
        self.transcript("dddd4444-new", [call((0, 2_000, 0, 0))])
        os.utime(old, (1, 1))
        self.assertIn("dddd4444: 2,000", self.run_tool().stdout)
        self.assertIn("cccc3333: 1,000", self.run_tool("cccc").stdout)

    def test_compactions_are_counted(self):
        self.transcript("ffff6666-x", [call((0, 900_000, 0, 0)),
                                       {"type": "system", "subtype": "compact_boundary"},
                                       call((0, 50_000, 0, 0))])
        result = self.run_tool()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("50,000 of 1,000,000 tokens (5%)", result.stdout)
        self.assertIn("1 compaction(s)", result.stdout)

    def hook(self, event):
        env = dict(os.environ, HOME=str(self.home))
        return subprocess.run(["python3", "-I", str(TOOL), "--hook"], cwd=self.cwd, env=env,
                              input=json.dumps(event), text=True, capture_output=True)

    def test_hook_asks_for_a_handover_once(self):
        path = self.transcript("gggg7777-x", [call((0, 800_000, 0, 0))])
        result = self.hook({"transcript_path": str(path), "stop_hook_active": False})
        self.assertEqual(result.returncode, 0, result.stderr)
        answer = json.loads(result.stdout)
        self.assertEqual(answer["decision"], "block")
        self.assertIn("80%", answer["reason"])
        again = self.hook({"transcript_path": str(path), "stop_hook_active": True})
        self.assertEqual((again.returncode, again.stdout), (0, ""))

    def test_hook_is_silent_below_the_threshold(self):
        path = self.transcript("hhhh8888-x", [call((0, 100_000, 0, 0))])
        result = self.hook({"transcript_path": str(path), "stop_hook_active": False})
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def codex_rollout(self, thread, used, window, compactions=0):
        day = self.home / ".codex/sessions/2026/10/29"
        day.mkdir(parents=True, exist_ok=True)
        rows = [{"type": "session_meta", "payload": {"id": thread}}]
        rows += [{"type": "compacted", "payload": {}}] * compactions
        rows.append({"timestamp": "2026-10-29T09:59:00.000Z", "type": "event_msg", "payload": {
            "type": "token_count", "info": {"last_token_usage": {"total_tokens": used},
                                            "model_context_window": window}}})
        (day / f"rollout-2026-10-29T01-00-00-{thread}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows))

    def test_codex_thread_and_owner(self):
        thread = "01a10000-0000-7000-8000-000000000001"
        self.codex_rollout(thread, 380_000, 475_000, compactions=2)
        result = self.run_tool("--codex", thread)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("380,000 of 475,000 tokens (80%)", result.stdout)
        self.assertIn("2 compaction(s)", result.stdout)
        owner = self.base / "dev/tmp/owners/ops/codex"
        owner.mkdir(parents=True)
        (owner / "events.jsonl").write_text(json.dumps(
            {"type": "thread.started", "thread_id": thread}) + "\n")
        env = dict(os.environ, HOME=str(self.home), DEV_ROOT=str(self.base / "dev"))
        by_owner = subprocess.run(["python3", "-I", str(TOOL), "--owner", "ops"], cwd=self.cwd,
                                  env=env, text=True, capture_output=True)
        self.assertEqual(by_owner.stdout, result.stdout)

    def test_no_transcript_is_refused(self):
        result = self.run_tool("eeee")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no transcript", result.stderr)


if __name__ == "__main__":
    unittest.main()
