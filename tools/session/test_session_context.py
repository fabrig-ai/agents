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
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
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
        self.assertEqual(self.run_tool("--capabilities").stdout, "hook-gating\nrole-drift\n")
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


    def prepare_drift(self, text="# Lead\nPreamble.\n\n## 1. First\nOne.\n\n## 2. Tasks\nTwo.\n\n### Detail\nThree.\n"):
        self.role_file = self.base / "lead.md"
        self.role_file.write_text(text)
        self.drift_transcript = self.transcript("drift-id", [call((0, 100_000, 0, 0))])
        self.env["FAKE_AGENTS"] = '[{"sessionId":"drift-id","name":"lead/jig"}]'

    def drift(self, kind="UserPromptSubmit", *args, **extra):
        event = {"hook_event_name": kind, "session_id": "drift-id", "transcript_path": str(self.drift_transcript), **extra}
        return self.hook(event, "--name", "lead/jig", "--role", "lead", "--coordinator", "s/draft@hel8", "--watch", str(self.role_file), *args)

    def drift_index(self):
        return json.loads((self.state / "seen/drift-id/index.json").read_text())

    def test_drift_first_event_baselines_silently(self):
        self.prepare_drift()
        result = self.drift("SessionStart", source="startup")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        digest = hashlib.sha256(self.role_file.read_bytes()).hexdigest()
        self.assertEqual(self.drift_index(), {str(self.role_file): digest})
        copies = list((self.state / "seen/drift-id").glob("*.md"))
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].read_bytes(), self.role_file.read_bytes())

    def test_drift_changed_section_hashes_and_told_once(self):
        self.prepare_drift()
        self.drift("SessionStart", source="startup")
        old = self.drift_index()[str(self.role_file)]
        self.role_file.write_text(self.role_file.read_text().replace("Two.", "New task rule."))
        new = hashlib.sha256(self.role_file.read_bytes()).hexdigest()
        result = self.drift()
        self.assertEqual(result.returncode, 0, result.stderr)
        message = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn(f"{self.role_file} changed since you last read it ({old[:8]} -> {new[:8]})", message)
        self.assertIn("sections 2. Tasks. Re-read those sections before acting.", message)
        self.assertNotIn("1. First", message)
        self.assertEqual(self.drift_index()[str(self.role_file)], new)
        self.assertEqual(len(list((self.state / "seen/drift-id").glob("*.md"))), 1)
        self.assertEqual(self.drift().stdout, "")
        self.assertEqual(self.drift("Stop").stdout, "")

    def test_drift_headings_added_removed_and_level_three_changed(self):
        self.prepare_drift()
        self.drift()
        self.role_file.write_text(self.role_file.read_text().replace("## 1. First\nOne.\n\n", "").replace("Three.", "Updated detail.") + "\n## 3. Added\nNew.\n")
        result = self.drift()
        message = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("1. First", message)
        self.assertIn("3. Added", message)
        self.assertIn("Detail", message)
        self.assertNotIn("2. Tasks", message)

    def test_drift_heading_cap(self):
        self.prepare_drift("".join(f"## Section {i}\nOld.\n" for i in range(1, 11)))
        self.drift()
        self.role_file.write_text(self.role_file.read_text().replace("Old.", "New."))
        message = json.loads(self.drift().stdout)["hookSpecificOutput"]["additionalContext"]
        for i in range(1, 9):
            self.assertIn(f"Section {i}", message)
        self.assertNotIn("Section 9", message)
        self.assertNotIn("Section 10", message)
        self.assertIn("and 2 more", message)

    def test_drift_preamble_only(self):
        self.prepare_drift()
        self.drift()
        self.role_file.write_text(self.role_file.read_text().replace("Preamble.", "Revised introduction."))
        self.assertIn("sections none (text before the first heading)", self.drift().stdout)

    def test_drift_missing_files_skipped_and_first_appearance_baselined(self):
        self.prepare_drift()
        text = self.role_file.read_text()
        self.role_file.unlink()
        self.assertEqual(self.drift().stdout, "")
        self.assertEqual(self.drift_index(), {})
        self.role_file.write_text(text)
        self.assertEqual(self.drift().stdout, "")
        digest = self.drift_index()[str(self.role_file)]
        self.role_file.unlink()
        self.assertEqual(self.drift().stdout, "")
        self.assertEqual(self.drift_index()[str(self.role_file)], digest)
        self.role_file.write_text(text.replace("Two.", "A changed rule."))
        self.assertIn("2. Tasks", self.drift().stdout)

    def test_drift_output_shapes_for_each_delivery_event(self):
        self.prepare_drift()
        self.drift()
        for kind, extra in (("UserPromptSubmit", {}), ("Stop", {}),
                            ("SessionStart", {"source": "resume"}), ("SessionStart", {"source": "compact"})):
            with self.subTest(kind=kind, extra=extra):
                self.role_file.write_text(self.role_file.read_text() + "Rule added.\n")
                result = self.drift(kind, **extra)
                self.assertEqual(result.returncode, 0, result.stderr)
                answer = json.loads(result.stdout)
                if kind == "Stop":
                    self.assertEqual(answer["decision"], "block")
                    self.assertIn("changed since", answer["reason"])
                else:
                    self.assertEqual(answer["hookSpecificOutput"]["hookEventName"], kind)
                    self.assertIn("changed since", answer["hookSpecificOutput"]["additionalContext"])

    def test_drift_defers_changes_for_non_delivery_events(self):
        self.prepare_drift()
        self.drift("Notification")  # Any first event can establish the baseline.
        index = self.drift_index()
        self.role_file.write_text(self.role_file.read_text() + "Rule added.\n")
        self.assertEqual(self.drift("Notification").stdout, "")
        self.assertEqual(self.drift("SessionStart", source="startup").stdout, "")
        self.assertEqual(self.drift_index(), index)
        self.assertIn("changed since", self.drift().stdout)

    def test_drift_active_stop_never_delivers_or_consumes_changes(self):
        self.prepare_drift()
        self.assertEqual(self.drift("Stop", stop_hook_active=True).stdout, "")
        index = self.drift_index()
        self.role_file.write_text(self.role_file.read_text() + "Rule added.\n")
        self.assertEqual(self.drift("Stop", stop_hook_active=True).stdout, "")
        self.assertEqual(self.drift_index(), index)
        self.assertIn("changed since", self.drift("Stop").stdout)

    def test_drift_and_handover_combined_in_one_output_handover_first(self):
        self.prepare_drift()
        self.drift()
        self.role_file.write_text(self.role_file.read_text() + "Rule added.\n")
        self.drift_transcript = self.transcript("drift-id", [call((0, 800_000, 0, 0))])
        result = self.drift("Stop")
        self.assertEqual(len(result.stdout.splitlines()), 1)
        message = json.loads(result.stdout)["reason"]
        self.assertLess(message.index("End now"), message.index("changed since"))
        self.assertNotIn("changed since", self.drift("Stop").stdout)

    def test_drift_gating_mismatch_records_no_role_baseline(self):
        self.prepare_drift()
        self.env["FAKE_AGENTS"] = '[{"sessionId":"drift-id","name":"another-session"}]'
        result = self.drift("SessionStart", source="startup")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.assertFalse((self.state / "seen").exists())

    def test_drift_state_permissions_and_no_temporary_files(self):
        self.prepare_drift()
        with patch.dict(os.environ, self.env):
            previous = os.umask(0)
            try:
                context.role_drift("drift-id", [str(self.role_file)], True)
            finally:
                os.umask(previous)
        for path in [self.state, *self.state.rglob("*")]:
            self.assertEqual(path.stat().st_mode & 0o777, 0o700 if path.is_dir() else 0o600, str(path))
            self.assertFalse(path.name.startswith("."))

    def test_drift_cleanup_daily_retains_recent_and_active_sessions(self):
        self.prepare_drift()
        seen = self.state / "seen"
        old, recent = seen / "old-id", seen / "recent-id"
        for path, days in ((old, 8), (recent, 6)):
            path.mkdir(parents=True, mode=0o700)
            (path / "index.json").write_text("{}")
            stamp = time.time() - days * 86400
            os.utime(path, (stamp, stamp))
        self.drift()
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())
        old.mkdir()
        stamp = time.time() - 8 * 86400
        os.utime(old, (stamp, stamp))
        self.drift()
        self.assertTrue(old.exists())  # The day's cleanup already ran.
        marker = self.state / "seen-cleanup.json"
        marker.write_text(json.dumps(time.time() - 86401))
        current = seen / "drift-id"
        os.utime(current, (stamp, stamp))
        self.role_file.write_text(self.role_file.read_text() + "Rule added.\n")
        self.assertIn("changed since", self.drift().stdout)
        self.assertFalse(old.exists())
        self.assertTrue(current.exists())

    def test_drift_concurrent_events_deliver_once(self):
        self.prepare_drift()
        self.drift()
        self.role_file.write_text(self.role_file.read_text() + "Rule added.\n")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.drift(), range(2)))
        self.assertTrue(all(result.returncode == 0 for result in results))
        self.assertEqual(sum(bool(result.stdout) for result in results), 1)

    def test_drift_rejects_relative_paths_and_unsafe_session_ids(self):
        self.prepare_drift()
        result = self.hook({"hook_event_name": "UserPromptSubmit", "session_id": "drift-id"}, "--watch", "relative.md")
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        result = self.drift("UserPromptSubmit", session_id="../../unsafe")
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertFalse(self.state.exists())

    def test_drift_heading_shaped_code_is_not_a_section(self):
        self.prepare_drift("## Actual\n```markdown\n## Fake\nOld.\n```\n")
        self.drift()
        self.role_file.write_text(self.role_file.read_text().replace("Old.", "New."))
        message = json.loads(self.drift().stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("sections Actual.", message)
        self.assertNotIn("Fake", message)

    def test_drift_does_not_require_a_transcript(self):
        self.prepare_drift()
        self.drift()
        self.drift_transcript.unlink()
        self.role_file.write_text(self.role_file.read_text() + "Rule added.\n")
        self.assertIn("changed since", self.drift("Stop").stdout)

    def test_unavailable_drift_store_does_not_suppress_handover(self):
        self.prepare_drift()
        self.drift_transcript = self.transcript("drift-id", [call((0, 800_000, 0, 0))])
        self.state.write_text("Not a directory")
        result = self.drift("Stop")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("End now", json.loads(result.stdout)["reason"])

    def test_director_handover_message_for_current_and_legacy_names(self):
        path = self.transcript("director-id", [call((0, 800_000, 0, 0))])
        expected = ("Hand over now: bring ~/src/rust/tmp/supervise/director/handover.md and state.md current, "
                    "start your successor with `tools/session/start director --next`, then warm-up and takeover. "
                    "If your handover is already under way, carry on with it.")
        for name, kind, extra in (("director/20261029T1200Z", "Stop", {}), ("director", "SessionStart", {"source": "compact"})):
            # Use different session ids so each event exercises its own gate lookup.
            identity = name.replace("/", "-")
            self.env["FAKE_AGENTS"] = json.dumps([{"name": name, "sessionId": identity}])
            result = self.hook({"hook_event_name": kind, "session_id": identity, "transcript_path": str(path), **extra},
                               "--role", "director", "--name-prefix", "director/", "--name", "director")
            self.assertEqual(result.returncode, 0, result.stderr)
            answer = json.loads(result.stdout)
            message = answer["reason"] if kind == "Stop" else answer["hookSpecificOutput"]["additionalContext"]
            self.assertTrue(message.endswith(expected))
            self.assertNotIn("End now", message)

    def test_director_handover_combines_with_role_drift(self):
        self.prepare_drift()
        self.env["FAKE_AGENTS"] = '[{"sessionId":"drift-id","name":"director/20261029T1200Z"}]'
        args = ("--role", "director", "--name-prefix", "director/", "--watch", str(self.role_file))
        event = {"hook_event_name": "SessionStart", "source": "startup", "session_id": "drift-id", "transcript_path": str(self.drift_transcript)}
        self.assertEqual(self.hook(event, *args).stdout, "")
        self.role_file.write_text(self.role_file.read_text() + "Rule added.\n")
        self.transcript("drift-id", [call((0, 800_000, 0, 0))])
        result = self.hook({**event, "hook_event_name": "Stop"}, *args)
        message = json.loads(result.stdout)["reason"]
        self.assertLess(message.index("Hand over now"), message.index("changed since"))
        self.assertIn("tools/session/start director --next", message)

if __name__ == "__main__":
    unittest.main()
