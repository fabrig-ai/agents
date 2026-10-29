#!/usr/bin/env python3
"""Offline tests for session-context: a fixture HOME holding a session transcript."""

import json
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import sys
from unittest.mock import patch

TOOL = Path(__file__).resolve().parent / "session-context"
loader = importlib.machinery.SourceFileLoader("session_context", str(TOOL))
spec = importlib.util.spec_from_loader(loader.name, loader)
context = importlib.util.module_from_spec(spec)
loader.exec_module(context)


def call(tokens, ts="2026-10-29T09:00:00.000Z"):
    return {"type": "assistant", "timestamp": ts,
            "message": {"role": "assistant", "usage": {
                "input_tokens": tokens[0], "cache_read_input_tokens": tokens[1],
                "cache_creation_input_tokens": tokens[2], "output_tokens": tokens[3]}}}


class SessionContext(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.home = self.base / "home"
        self.cwd = self.base / "work.dir"
        self.cwd.mkdir(parents=True)
        self.project = self.home / ".claude/projects" / str(self.cwd).replace("/", "-").replace(".", "-")
        self.project.mkdir(parents=True)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        fake = self.bin / "claude"
        fake.write_text(f"#!{sys.executable}\n" + '''import json, os, sys
with open(os.environ["FAKE_LOG"], "a") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\\n")
print(os.environ.get("FAKE_AGENTS", "[]"))
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
''')
        fake.chmod(0o755)
        self.state = self.base / "state"
        self.log = self.base / "calls.jsonl"
        self.env = dict(os.environ, HOME=str(self.home), PATH=str(self.bin),
                        SESSION_CONTEXT_STATE=str(self.state), FAKE_LOG=str(self.log))

    def transcript(self, name, calls):
        path = self.project / f"{name}.jsonl"
        path.write_text("".join(json.dumps(c) + "\n" for c in calls) + "not json\n")
        return path

    def run_tool(self, *args):
        return subprocess.run([sys.executable, "-I", str(TOOL), *args], cwd=self.cwd, env=self.env,
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

    def hook(self, event, *args):
        event = {"hook_event_name": "Stop", **event}
        return subprocess.run([sys.executable, "-I", str(TOOL), "--hook", *args], cwd=self.cwd, env=self.env,
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
        env = dict(self.env, DEV_ROOT=str(self.base / "dev"))
        by_owner = subprocess.run([sys.executable, "-I", str(TOOL), "--owner", "ops"], cwd=self.cwd,
                                  env=env, text=True, capture_output=True)
        self.assertEqual(by_owner.stdout, result.stdout)

    def test_no_transcript_is_refused(self):
        result = self.run_tool("eeee")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no transcript", result.stderr)

    def test_capabilities_and_existing_by_name_mode(self):
        self.assertEqual(self.run_tool("--capabilities").stdout, "hook-gating\n")
        self.transcript("named-session", [call((0, 300_000, 0, 0))])
        self.env["FAKE_AGENTS"] = json.dumps([{"name": "lead/jig", "sessionId": "named-session", "cwd": str(self.cwd)}])
        result = self.run_tool("--name", "lead/jig")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("300,000", result.stdout)

    def test_name_gate_caches_prefix_lookup_with_private_permissions(self):
        path = self.transcript("gate-id", [call((0, 750_000, 0, 0))])
        event = {"session_id": "gate", "transcript_path": str(path)}
        self.env["FAKE_AGENTS"] = json.dumps([{"sessionId": "gate-id", "name": "lead/jig"}])
        for _ in range(2):
            result = self.hook(event, "--name", "wrong", "--name", "lead/jig", "--role", "lead", "--coordinator", "s/draft@hel8")
            self.assertEqual(result.returncode, 0, result.stderr)
            message = json.loads(result.stdout)["reason"]
            self.assertIn("End now, as agents/lead.md 4 says", message)
            self.assertIn("post `files current` to s/draft@hel8", message)
        cache = self.state / "names.json"
        self.assertEqual(json.loads(cache.read_text()), {"gate": "lead/jig"})
        self.assertEqual(cache.stat().st_mode & 0o777, 0o600)
        self.assertEqual(len(self.log.read_text().splitlines()), 1)
        self.assertEqual([p.name for p in self.state.iterdir()], ["names.json"])

    def test_name_prefix_and_mismatch(self):
        path = self.transcript("coord-id", [call((0, 800_000, 0, 0))])
        event = {"session_id": "coord-id", "transcript_path": str(path)}
        self.env["FAKE_AGENTS"] = '[{"sessionId":"coord-id","name":"coordinator/dm/20261029T1200Z"}]'
        result = self.hook(event, "--name-prefix", "other/", "--name-prefix", "coordinator/dm/", "--role", "coordinator", "--handle", "dm", "--handover", "/a handover.md")
        message = json.loads(result.stdout)["reason"]
        self.assertIn("bring /a handover.md current", message)
        self.assertIn("tools/session/start coordinator dm --next", message)
        self.assertIn("If your handover is already under way", message)
        mismatch = self.hook(event, "--name", "wrong", "--name-prefix", "coordinator/ab/")
        self.assertEqual((mismatch.returncode, mismatch.stdout, mismatch.stderr), (0, "", ""))

    def test_failed_lookup_is_silent_and_does_not_cache(self):
        path = self.transcript("gate-id", [call((0, 800_000, 0, 0))])
        event = {"session_id": "gate", "transcript_path": str(path)}
        for output, code in (("invalid json", "0"), ("[]", "0"), ('[{"sessionId":"gate-id","name":"lead/jig"}]', "1")):
            self.env.update(FAKE_AGENTS=output, FAKE_EXIT=code)
            result = self.hook(event, "--name", "lead/jig")
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
            self.assertFalse(self.state.exists())
        with patch.dict(os.environ, self.env), patch.object(context.subprocess, "run", side_effect=subprocess.TimeoutExpired("claude", 10)) as run:
            self.assertIsNone(context.hook_name("gate"))
            self.assertEqual(run.call_args.kwargs["timeout"], 10)
        self.assertFalse(self.state.exists())

    def test_compaction_triggers_even_below_threshold_or_without_a_call(self):
        for rows in (
            [call((0, 900_000, 0, 0)), {"type": "system", "subtype": "compact_boundary"}, call((0, 10_000, 0, 0))],
            [{"type": "system", "subtype": "compact_boundary"}],
        ):
            path = self.transcript("compacted-id", rows)
            result = self.hook({"transcript_path": str(path)})
            self.assertEqual(json.loads(result.stdout)["decision"], "block")
            self.assertIn("compaction detected", result.stdout)

    def test_session_start_compact_is_gated_and_adds_context(self):
        path = self.transcript("start-id", [call((0, 20_000, 0, 0))])
        self.env["FAKE_AGENTS"] = '[{"sessionId":"start-id","name":"coord-next"}]'
        event = {"hook_event_name": "SessionStart", "source": "compact", "session_id": "start-id", "transcript_path": str(path)}
        result = self.hook(event, "--name", "coord-next", "--role", "coordinator", "--handle", "dm", "--handover", "/handover.md")
        answer = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(answer["hookEventName"], "SessionStart")
        self.assertIn("20,000", answer["additionalContext"])
        self.assertIn("Hand over now", answer["additionalContext"])
        self.assertEqual(self.hook(event, "--name", "wrong").stdout, "")
        event.pop("transcript_path")
        self.assertIn("usage unavailable", self.hook(event, "--name", "coord-next").stdout)

    def test_other_events_and_active_stop_do_not_even_look_up_names(self):
        for event in (
            {"hook_event_name": "Notification"},
            {"hook_event_name": "SessionStart", "source": "startup"},
            {"stop_hook_active": True},
        ):
            result = self.hook(event, "--name", "lead/jig")
            self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertFalse(self.log.exists())

    def test_usage_reads_tail_and_compaction_scan_covers_old_records(self):
        path = self.transcript("long-id", [{"type": "system", "subtype": "compact_boundary"}])
        with path.open("a") as stream:
            stream.write(json.dumps({"padding": "x" * (context.TAIL + 100)}) + "\n")
            stream.write(json.dumps(call((0, 100, 0, 0))) + "\n")
        result = self.hook({"transcript_path": str(path)})
        self.assertIn("compaction detected", result.stdout)
        self.assertIn("100 of 1,000,000", result.stdout)
        with patch.object(context, "records", wraps=context.records) as records:
            context.claude_usage(path, 1_000_000, counts=False, tail_only=True)
            self.assertEqual(records.call_count, 1)
            self.assertEqual(records.call_args.args, (path, True))

    def test_hook_always_exits_zero_on_bad_input(self):
        for payload, args in (("not json", []), ("[]", []), ("{}", ["--window", "bad"]), ("{}", ["--role", "bad"]), ("{}", ["--name"])):
            result = subprocess.run([sys.executable, "-I", str(TOOL), "--hook", *args],
                                    env=self.env, cwd=self.cwd, input=payload, text=True, capture_output=True)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))


if __name__ == "__main__":
    unittest.main()
