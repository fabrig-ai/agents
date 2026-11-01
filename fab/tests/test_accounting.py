"""Usage accounting over plain log records (docs/design/fab-reports.md, 3)."""

import unittest
from unittest.mock import patch

from fab import accounting as counts
from fab import atomic
from fab.report import Window
from fab.tests.support import tmp_home


def event(ev="call.ended", minute="10", **fields):
    return {"ev": ev, "ts": f"2026-10-31T12:{minute}:00.000Z", **fields}


WINDOW = Window("2026-10-31T12:00:00.000Z", "2026-10-31T13:00:00.000Z")


class AccountingTest(unittest.TestCase):
    def test_accounting_token_counts(self):
        self.assertEqual(counts.token_counts("10/3/4"), (10, 3, 4))
        for value in (None, 42, "1/2", "1/2/3/4", "1/oops/3", "-1/2/3", "", "1/2/3\n"):
            with self.subTest(value=value):
                self.assertIsNone(counts.token_counts(value))

    def test_accounting_weights_preserve_cache_meanings(self):
        self.assertAlmostEqual(counts.call_weight({"tokens": "10/3/4"}), 30.3)
        self.assertAlmostEqual(counts.call_weight({"tokens": "10/3/4", "cache_write": 8}), 40.3)
        for value in (None, "8", -1, True, 1.5):
            with self.subTest(cache_write=value):
                self.assertAlmostEqual(counts.call_weight({"tokens": "10/3/4", "cache_write": value}), 30.3)
        self.assertEqual(counts.run_weight({"tokens": "10/3/4"}), 39.3)
        self.assertEqual(counts.run_weight({"tokens": "2/3/4"}), 32.3)
        for weight in (counts.call_weight, counts.run_weight):
            self.assertIsNone(weight({}))
            self.assertIsNone(weight({"tokens": "bad"}))

    def test_accounting_draft_calls_use_subject_boundaries(self):
        records = [event(subject=subject) for subject in
                   ("demo", "demo/core", "demo/review", "demo/core/decision", "demo2/x", "elsewhere")]
        records += [event("call.started", subject="demo"), event(), event(subject=None)]
        self.assertEqual(counts.draft_calls("demo", iter(records)), records[:4])

    def test_accounting_draft_runs_find_review_call_even_later_in_log(self):
        records = [event("run.ended", task=task) for task in
                   ("demo/core", "demo/core/foreman", "review-root", "demo2/core", "other-root")]
        records += [event("call.started", subject="demo/core/decision", call="review-root"),
                    event("call.started", subject="elsewhere", call="other-root"),
                    event("run.started", task="demo/core")]
        self.assertEqual(counts.draft_runs("demo", iter(records)), records[:3])

    def test_accounting_figures_each_count_once_and_window_edges(self):
        records = [event(minute="00", subject="demo", tokens="10/3/4", cache_write=8,
                         minutes="2.5", peak=counts.TARGET + 1),
                   event(subject="demo/core", tokens="5/7/9", minutes=3, peak=counts.TARGET),
                   event(subject="demo/review"),
                   event(subject="demo/core/decision", tokens="bad", peak=-1),
                   event(subject="demo/core", peak=True),
                   event(subject="demo/core", peak="999999"),
                   event(subject="demo2/core", tokens="999/999/999", peak=9999999),
                   event("run.ended", task="demo/core", tokens="10/3/4"),
                   event("run.ended", task="review-root", tokens="2/3/4"),
                   event("run.ended", task="demo/core/foreman"),
                   event("run.ended", task="elsewhere/core", tokens="999/999/999"),
                   {**event(subject="demo", tokens="999/999/999"), "ts": WINDOW.end},
                   {**event("call.started", subject="demo/review", call="review-root"),
                    "ts": "2026-10-31T11:00:00.000Z"}]
        result = counts.figures("demo", records, WINDOW)
        expected = {"calls": 6, "call_minutes": 5.5, "input_tokens": 33, "output_tokens": 13,
                    "codex_input_tokens": 12, "codex_output_tokens": 8,
                    "claude_weight": 91 / counts.MILLION, "codex_weight": 71.6 / counts.MILLION,
                    "weight_ratio": 91 / 71.6, "peak_context": counts.TARGET + 1, "over_target": 1}
        self.assertEqual(set(result), {key for key, _ in counts.FIGURES})
        for key, value in expected.items():
            with self.subTest(key=key):
                self.assertIs(type(result[key]), type(value))
                self.assertAlmostEqual(result[key], value)

    def test_accounting_figures_without_runs_or_measured_peaks(self):
        result = counts.figures("demo", [event(subject="demo", tokens="10/3/4")], WINDOW)
        self.assertIsNone(result["weight_ratio"])
        self.assertIsNone(result["peak_context"])
        self.assertEqual(result["over_target"], 0)
        empty = counts.figures("demo", [], WINDOW)
        self.assertEqual(empty["claude_weight"], 0.0)
        self.assertEqual(empty["codex_weight"], 0.0)
        self.assertIs(type(empty["call_minutes"]), float)

    def test_accounting_call_rows_measured_and_historical(self):
        records = [event(subject="demo/core", call="measured", role="skeleton", minutes="2.5",
                         turns=4, peak=counts.TARGET + 1, tokens="10/3/4", cache_write=8),
                   event(subject="demo"),
                   event(subject="demo/review", turns=True, peak="bad"),
                   event(subject="demo/core", turns=1, peak=counts.TARGET),
                   {**event(subject="demo"), "ts": WINDOW.end}]
        self.assertEqual(counts.call_rows("demo", records, WINDOW), [
            ("measured", "skeleton", "demo/core", 2.5, 4, counts.TARGET + 1, 40.3 / counts.MILLION, "yes"),
            ("", "", "demo", 0.0, None, None, None, "-"),
            ("", "", "demo/review", 0.0, None, None, None, "-"),
            ("", "", "demo/core", 0.0, 1, counts.TARGET, None, "no"),
        ])


class HandUsageTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.projects = self.home / "transcripts"
        self.manifest = self.home / "fab/hand-sessions"
        self.transcript = self.projects / "project/session.jsonl"

    def test_accounting_hand_requests_and_subagents_count_once(self):
        atomic.write(self.manifest, "# hand sessions\n\n session demo # a draft\nsession demo\nother demo2\n")
        atomic.write(self.transcript, '\n'.join([
            '{"type":"assistant","requestId":"one","message":{"usage":{"input_tokens":10,"cache_creation_input_tokens":8,"cache_read_input_tokens":3,"output_tokens":4}}}',
            '{"type":"assistant","requestId":"one","message":{"usage":{"input_tokens":10,"cache_creation_input_tokens":8,"cache_read_input_tokens":3,"output_tokens":4}}}',
            '{"type":"assistant","requestId":"two","message":{"usage":{"input_tokens":5,"cache_read_input_tokens":7,"output_tokens":9}}}',
            '{"type":"user","requestId":"ignored","message":{"usage":{"input_tokens":999}}}',
            '{torn', '[]']))
        subagent = self.projects / "project/session/subagents/agent.jsonl"
        atomic.write(subagent, '{"type":"assistant","requestId":"three","message":{"usage":{"input_tokens":2,"cache_creation_input_tokens":4,"cache_read_input_tokens":1,"output_tokens":3}}}\n')
        # A duplicate request in another file is still the same request.
        atomic.write(self.projects / "copy/session.jsonl", self.transcript.read_text())
        result, notes = counts.hand_usage("demo", projects=self.projects)
        self.assertEqual(notes, [])
        self.assertEqual(result["hand_input_tokens"], 40)
        self.assertEqual(result["hand_output_tokens"], 16)
        self.assertAlmostEqual(result["hand_weight"], 113.1 / counts.MILLION)
        self.assertEqual(counts.hand_usage("unlisted", projects=self.projects), ({}, []))

    def test_accounting_hand_missing_manifest_and_missing_transcript(self):
        self.assertEqual(counts.hand_usage("demo", projects=self.projects), ({}, []))
        atomic.write(self.manifest, "missing demo\n")
        result, notes = counts.hand_usage("demo", projects=self.projects)
        self.assertEqual(result["hand_weight"], 0.0)
        self.assertEqual(len(notes), 1)
        self.assertIn("missing", notes[0])

    def test_accounting_hand_unreadable_transcript_is_a_note(self):
        atomic.write(self.manifest, "session demo\n")
        self.transcript.mkdir(parents=True)
        result, notes = counts.hand_usage("demo", projects=self.projects)
        self.assertEqual(result["hand_input_tokens"], 0)
        self.assertEqual(len(notes), 1)
        self.assertIn(str(self.transcript), notes[0])

    def test_accounting_hand_invalid_counts_and_usage_are_skipped(self):
        atomic.write(self.manifest, "session demo\n../outside demo\nmalformed\n")
        atomic.write(self.transcript, '\n'.join([
            '{"type":"assistant","requestId":"one","message":null}',
            '{"type":"assistant","requestId":"one","message":{"usage":{"input_tokens":5,"output_tokens":true,"cache_creation_input_tokens":-1,"cache_read_input_tokens":"8"}}}',
            '{"type":"assistant","message":{"usage":{"input_tokens":999}}}',
            '{"type":"assistant","requestId":[],"message":{"usage":{}}}']))
        result, notes = counts.hand_usage("demo", projects=self.projects)
        self.assertEqual(result["hand_input_tokens"], 5)
        self.assertEqual(result["hand_output_tokens"], 0)
        self.assertEqual(len(notes), 2)

    def test_accounting_hand_unreadable_manifest_is_a_note(self):
        self.manifest.mkdir(parents=True)
        result, notes = counts.hand_usage("demo", projects=self.projects)
        self.assertEqual(result, {})
        self.assertEqual(len(notes), 1)
        self.assertIn(str(self.manifest), notes[0])

    def test_accounting_hand_unreadable_projects_is_a_note(self):
        atomic.write(self.manifest, "session demo\n")
        with patch.object(type(self.projects), "glob", side_effect=PermissionError("unreadable")):
            result, notes = counts.hand_usage("demo", projects=self.projects)
        self.assertEqual(result["hand_weight"], 0.0)
        self.assertIn("unreadable", notes[0])
