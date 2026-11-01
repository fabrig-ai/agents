import copy
import io
import json
import os
import re
import tempfile
import threading
import unittest
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from fab import calls, channel, cli, log, serve
from fab.tests.support import tmp_home

NOW = datetime(2026, 11, 1, 0, 30, tzinfo=timezone.utc)


def event(kind, age=0, **fields):
    return {"ev": kind, "ts": (NOW - timedelta(seconds=age)).isoformat(), **fields}


def write(path, text):
    sibling = path.with_name(path.name + ".new")
    sibling.write_text(text)
    sibling.replace(path)


class SnapshotTest(unittest.TestCase):
    def test_serve_empty_and_invalid_timestamps(self):
        empty = serve.snapshot([], NOW, [])
        self.assertEqual(empty["updated"], "2026-11-01T00:30:00.000Z")
        self.assertEqual(empty["log"], "ok")
        self.assertIsNone(empty["last_event_age_s"])
        self.assertEqual(empty["waiting_on_user"], {
            "asks": 0, "by_kind": {"call": 0, "parked": 0}, "oldest_age_s": None,
        })
        self.assertEqual(empty["runs_in_flight"], {"total": 0, "by_host": {}})
        self.assertEqual(empty["calls_in_flight"], {"total": 0, "by_role": {}})
        self.assertEqual(empty["drafts"], {})
        self.assertEqual(empty["overlaps"], [])
        for stamp in (None, "bad", "2026-11-01", "2026-11-01T00:00:00", 1, [],
                      "0001-01-01T00:00:00+23:00"):
            with self.subTest(stamp=stamp):
                self.assertEqual(serve.snapshot([{"ev": "branch.landed", "ts": stamp}], NOW, []), empty)
        self.assertEqual(serve.snapshot([event("branch.landed", -1)], NOW, []), empty)

    def test_serve_pairs_ids_and_bounds_runs_to_24_hours_calls_to_timeout(self):
        events = [
            event("run.started", 86401, run="stale", task="stale/t", host="builder"),
            event("run.started", 86400, run="edge", task="edge/t", host="builder"),
            event("run.started", 80000, run="ended", task="ended/t", host="builder"),
            event("run.ended", 70000, run="ended", outcome="done"),
            event("run.ended", 60000, run="before", outcome="done"),
            event("run.started", 50000, run="before", task="ended/t", host="builder"),
            event("run.started", 20, run="active", task="active/t", host="private-host"),
            event("run.started", 20, run="active", task="active/t", host="private-host"),
            event("run.started", 15, task="missing/t", host="builder"),
            event("call.started", calls.TIMEOUT + 1, call="stale", role="review"),
            event("call.started", calls.TIMEOUT, call="edge", role="review"),
            event("call.started", 500, call="ended", role="answer"),
            event("call.ended", 400, call="ended"),
            event("call.ended", 300, call="before"),
            event("call.started", 200, call="before", role="answer"),
            event("call.started", 42, call="active", role="private-role"),
            event("call.started", 42, call="active", role="private-role"),
        ]
        before = copy.deepcopy(events)
        current = serve.snapshot(events, NOW, ["builder"])
        self.assertEqual(events, before)
        self.assertEqual(current["last_event_age_s"], 42)
        self.assertEqual(current["runs_in_flight"], {"total": 2, "by_host": {"builder": 1, "other": 1}})
        self.assertEqual(current["calls_in_flight"], {"total": 2, "by_role": {"review": 1, "other": 1}})
        self.assertEqual(current["drafts"], {
            "active": {"runs_in_flight": 1, "landed_today": 0, "merged_today": 0},
            "edge": {"runs_in_flight": 1, "landed_today": 0, "merged_today": 0},
        })

    def test_serve_waiting_matches_the_user_channel_log_asks(self):
        events = [
            event("question.asked", 90000, task="foreman/t"),
            event("call.ended", 80000, call="answered", subject="closed", outcome="question"),
            event("call.parked", 70000, call="parked-closed", subject="closed", reason="review"),
            event("call.answered", 60000, subject="closed"),
            event("call.ended", 50000, call="designed", subject="designed", outcome="question"),
            event("call.ended", 40000, call="design", subject="designed", outcome="done"),
            event("call.parked", 30000, call="finished", subject="finished", reason="review"),
            event("call.finished", 20000, call="finished"),
            event("call.ended", 10000, call="first", subject="open", outcome="question"),
            event("call.ended", 9000, call="second", subject="open", outcome="question"),
            event("call.parked", 8000, call="parked-open", subject="open", reason="review"),
            event("question.answered", 7000, task="open"),
            event("call.parked", 6000),
            event("call.ended", 5000, outcome="question"),
            {"ev": "call.answered", "ts": "bad", "subject": "open"},
            event("call.answered", -1, subject="open"),
        ]
        before = copy.deepcopy(events)
        current = serve.snapshot(events, NOW, [])
        self.assertEqual(events, before)
        self.assertEqual(current["waiting_on_user"], {
            "asks": 2, "by_kind": {"call": 1, "parked": 1}, "oldest_age_s": 9000,
        })
        asks = channel.asks((), events[:-2])
        self.assertEqual(current["waiting_on_user"]["asks"], len(asks))
        events.append(event("call.answered", subject="open"))
        self.assertEqual(serve.snapshot(events, NOW, [])["waiting_on_user"], {
            "asks": 0, "by_kind": {"call": 0, "parked": 0}, "oldest_age_s": None,
        })

    def test_serve_waiting_has_no_expiry_and_invalid_endings_do_not_pair(self):
        events = [
            event("call.ended", 172800, call="old", subject="old", outcome="question"),
            event("call.parked", 90000, call="older", subject="older-call", reason="review"),
            event("run.started", 100, run="r", task="draft/t", host="builder"),
            event("call.started", 100, call="c", role="cut"),
            {"ev": "run.ended", "ts": "bad", "run": "r"},
            {"ev": "call.ended", "call": "c"},
        ]
        current = serve.snapshot(events, NOW, ["builder"])
        self.assertEqual(current["waiting_on_user"], {
            "asks": 2, "by_kind": {"call": 1, "parked": 1}, "oldest_age_s": 172800,
        })
        self.assertEqual(current["runs_in_flight"]["total"], 1)
        self.assertEqual(current["calls_in_flight"]["by_role"], {"cut": 1})

    def test_serve_today_hour_outcomes_and_weights(self):
        events = [
            event("run.started", 90000, run="old", task="today/old"),
            event("branch.landed", 3601, task="old/t"),
            event("branch.landed", 3600, task="hour/t"),
            event("branch.landed", 1801, task="yesterday/t"),
            event("branch.landed", 1800, task="today/one"),
            {"ev": "branch.landed", "ts": "2026-10-31T20:15:00-04:00", "task": "today/two"},
            event("branch.landed", -86400, task="tomorrow/t"),
            event("branch.rejected", 1801), event("branch.rejected", 1800),
            event("run.ended", 1801, outcome="done", tokens="9000000/0/0"),
            event("call.ended", 1801, tokens="9000000/0/0"),
            event("run.ended", 1800, outcome="done", tokens="2000000/1000000/100000"),
            event("run.ended", 1700, outcome="question", tokens="bad"),
            event("run.ended", 1600, outcome="infra"),
            event("run.ended", 1500, outcome="failed"),
            event("run.ended", 1400, outcome="private-outcome"),
            event("run.ended", 1300),
            event("call.ended", 1200, tokens="1000000/1000000/100000", cache_write=400000),
            event("call.ended", 1100, tokens="bad"),
            event("call.ended", 1000),
        ]
        local_now = NOW.astimezone(timezone(timedelta(hours=5)))
        current = serve.snapshot(events, local_now, [])
        self.assertEqual(current["updated"], "2026-11-01T00:30:00.000Z")
        self.assertEqual(current["landed"], {"last_hour": 4, "today": 2})
        self.assertEqual(current["rejected_today"], 1)
        self.assertEqual(current["runs_ended_today"], {
            "done": 1, "question": 1, "infra": 1, "failed": 1, "other": 2,
        })
        self.assertEqual(current["weight_today"], {"codex_m": 1.9, "claude_m": 2.1, "ratio": 0.9})
        self.assertEqual(current["merged"], {"last_hour": 0, "today": 0})
        self.assertEqual(current["drafts"], {
            "today": {"runs_in_flight": 0, "landed_today": 2, "merged_today": 0},
        })

    def test_serve_weight_ratio_uses_unrounded_totals_and_zero_denominator(self):
        for events, expected in (
            ([], {"codex_m": 0.0, "claude_m": 0.0, "ratio": None}),
            ([event("run.ended", tokens="1240000/0/0")],
             {"codex_m": 1.2, "claude_m": 0.0, "ratio": None}),
            ([event("run.ended", tokens="1240000/0/0"),
              event("call.ended", tokens="0/0/0")],
             {"codex_m": 1.2, "claude_m": 0.0, "ratio": None}),
            ([event("run.ended", tokens="1240000/0/0"),
              event("call.ended", tokens="140000/0/0")],
             {"codex_m": 1.2, "claude_m": 0.1, "ratio": 8.9}),
            ([event("run.ended", tokens="1240000/0/0"),
              event("call.ended", tokens="14000/0/0")],
             {"codex_m": 1.2, "claude_m": 0.0, "ratio": 88.6}),
            ([event("call.ended", tokens="140000/0/0")],
             {"codex_m": 0.0, "claude_m": 0.1, "ratio": 0.0}),
        ):
            with self.subTest(expected=expected):
                current = serve.snapshot(events, NOW, [])
                self.assertEqual(current["weight_today"], expected)

    def test_serve_merges_belong_to_trunks_and_only_run_drafts_appear(self):
        events = [
            event("branch.landed", 3601, task="calls/old", into="draft/integration"),
            event("branch.landed", 3600, task="answers/hour", into="draft/integration"),
            event("branch.landed", 1801, task="repairs/yesterday", into="draft/integration"),
            event("branch.landed", 1800, task="calls/today", into="draft/integration"),
            event("branch.landed", 0, task="answers/now", into="draft/integration"),
            event("branch.landed", -1, task="calls/future", into="draft/integration"),
            event("branch.landed", task="repairs/today", into="unknown/integration"),
            event("branch.landed", task="draft/main"),
            event("branch.landed", task="never-run/main"),
            event("run.started", 90000, run="old", task="draft/old"),
            event("run.started", 100, run="active", task="draft/active"),
            event("run.started", 90000, run="inactive", task="inactive/old"),
            event("run.started", -1, run="future", task="never-run/future"),
            {"ev": "run.started", "ts": "bad", "task": "unknown/t"},
        ]
        current = serve.snapshot(events, NOW, [])
        self.assertEqual(current["landed"], {"last_hour": 2, "today": 2})
        self.assertEqual(current["merged"], {"last_hour": 5, "today": 3})
        self.assertEqual(current["drafts"], {
            "by-hand": {"runs_in_flight": 0, "landed_today": 1, "merged_today": 0},
            "draft": {"runs_in_flight": 1, "landed_today": 1, "merged_today": 2},
        })
        page = serve.render(current)
        self.assertIn('<div class="label">Landed on main today</div><div class="value">2</div>', page)
        self.assertIn('<div class="label">Merged into a trunk today</div><div class="value">3</div>', page)
        self.assertIn('<td class="num">1</td><td class="num">2</td><td class="num">1</td>', page)

    def test_serve_taskless_main_landings_are_by_hand_without_run_start(self):
        events = [event("branch.landed"), event("branch.landed", task=None),
                  event("branch.landed", 1801), event("branch.landed", -1),
                  event("branch.landed", into="unknown/integration")]
        current = serve.snapshot(events, NOW, [])
        self.assertEqual(current["drafts"], {
            "by-hand": {"runs_in_flight": 0, "landed_today": 2, "merged_today": 0},
        })
        self.assertEqual(current["landed"], {"last_hour": 3, "today": 2})
        self.assertIn('<tr><td>by-hand</td>', serve.render(current))
        self.assertNotIn('"other"', json.dumps(current["drafts"]))

    def test_serve_main_landings_without_known_drafts_are_by_hand(self):
        tasks = [{}, {"task": None}, {"task": ""}, {"task": "-"},
                 {"task": "draft"}, {"task": "fab/live-unit"}, {"task": "al/fab-cpu"},
                 {"task": "unseen<secret>/private"}]
        for fields in tasks:
            with self.subTest(fields=fields):
                events = [event("run.started", 90000, task="draft/old"),
                          event("run.started", 90000, task="-"),
                          event("branch.landed", branch="fl/triage-shell-kind", **fields)]
                current = serve.snapshot(events, NOW, [])
                self.assertEqual(current["drafts"], {
                    "by-hand": {"runs_in_flight": 0, "landed_today": 1, "merged_today": 0},
                })
                self.assertEqual(current["landed"], {"last_hour": 1, "today": 1})
                self.assertIn('<tr><td>by-hand</td>', serve.render(current))

    def test_serve_drafts_are_bounded_public_names(self):
        valid = ["a", "release-1.2", "a" * 64, "other"]
        invalid = ["a" * 65, "Upper", "-dash", "path<secret>", "", "../hidden"]
        events = [event("run.started", 90000, run=str(index), task=name + "/private-task")
                  for index, name in enumerate(valid + invalid)]
        events += [event("branch.landed", task=name + "/private-task") for name in valid + invalid]
        events += [event("branch.landed", task="calls/private", into=name + "/integration")
                   for name in valid + invalid]
        events += [event("branch.landed"), event("branch.landed", task=["bad"]),
                   event("branch.landed", task="private-call-id"),
                   event("branch.landed", task="unseen<secret>/private")]
        current = serve.snapshot(events, NOW, [])
        self.assertEqual(current["drafts"]["other"], {
            "runs_in_flight": 0, "landed_today": 7, "merged_today": 7,
        })
        self.assertEqual(current["drafts"]["by-hand"], {
            "runs_in_flight": 0, "landed_today": 4, "merged_today": 0,
        })
        for name in valid[:-1]:
            self.assertEqual(current["drafts"][name], {
                "runs_in_flight": 0, "landed_today": 1, "merged_today": 1,
            })

    def test_serve_privacy_in_json_and_html(self):
        private = {
            "run": "secret-run-id", "call": "secret-call-id", "login": "secret-login-id",
            "task": "<secret-draft>/secret-task-id", "branch": "secret-branch", "sha": "secret-sha",
            "path": "/secret/path", "text": "secret question text", "answer": "secret answer text",
            "reason": "secret reason", "into": "<secret-draft>/secret-integration",
            "notes": "secret notes", "report": "/secret/report", "holder": "secret holder",
            "subject": "secret-subject", "host": "secret-host", "role": "secret-role",
            "outcome": "secret-outcome",
        }
        events = [event(kind, **private) for kind in (
            "run.started", "call.started", "question.asked", "call.parked", "branch.landed",
            "branch.rejected", "note",
        )]
        events.append(event("call.ended", **{**private, "call": "another-secret-call", "outcome": "question"}))
        events.append(event("run.ended", **{**private, "run": "another-secret-run"}))
        events.append(event("run.started", run="review-run", task="private-call-id"))
        current = serve.snapshot(events, NOW, ["builder"])
        for output in (json.dumps(current), serve.render(current)):
            for secret in private.values():
                self.assertNotIn(secret, output)
            self.assertNotIn("another-secret-run", output)
            self.assertNotIn("another-secret-call", output)
            self.assertNotIn("private-call-id", output)
            self.assertNotIn("review-run", output)
        self.assertEqual(current["runs_in_flight"]["by_host"], {"other": 2})
        self.assertEqual(current["calls_in_flight"]["by_role"], {"other": 1})
        self.assertEqual(current["runs_ended_today"]["other"], 1)
        self.assertEqual(current["waiting_on_user"], {
            "asks": 2, "by_kind": {"call": 1, "parked": 1}, "oldest_age_s": 0,
        })

    def test_serve_render_escapes_text_and_formats_ages(self):
        label = '<host & "name">'
        current = serve.snapshot([event("run.started", 42, run="r", task="draft/t", host=label)], NOW, [label])
        page = serve.render(current)
        self.assertNotIn(label, page)
        self.assertIn("&lt;host &amp; &quot;name&quot;&gt;", page)
        self.assertIn('<title>fab status</title>', page)
        self.assertIn('<meta http-equiv="refresh" content="30">', page)
        self.assertIn("prefers-color-scheme:dark", page)
        self.assertIn("width=device-width", page)
        self.assertNotIn("<script", page)
        for title in ("Drafts", "Today", "In flight", "Waiting on the user"):
            self.assertIn(f"<h2>{title}</h2>", page)
        for age, expected in ((42, "42 s"), (420, "7 min"), (10800, "3 h"), (None, "none")):
            current["last_event_age_s"] = age
            current["waiting_on_user"]["oldest_age_s"] = age
            rendered = serve.render(current)
            last_event = f"last event {expected} ago" if age is not None else "no events yet"
            self.assertIn(f'Updated 00:30 UTC · {last_event}</span>', rendered)
            self.assertIn(f'<div class="sub">oldest {expected}</div>', rendered)
            self.assertIn(f'<p class="facts">Oldest: {expected}</p>', rendered)
        failure = serve.render({"updated": "now", "log": "unreadable"})
        self.assertIn('<p class="empty">The event log is unreadable.</p>', failure)
        self.assertNotIn("Runs in flight", failure)


class OverlapsTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(tmp_home())

    def test_serve_overlaps_latest_count_and_panel_after_drafts(self):
        events = [event("run.started", 100000, task=name + "/task") for name in ("alpha", "beta")]
        events += [event("trunks.overlap", 95000, drafts=["alpha", "beta"], tips=["a" * 40, "b" * 40],
                         files=["private/old"], more=0, reason="probe"),
                   event("trunks.overlap", 90000, drafts=["alpha", "beta"], tips=["c" * 40, "d" * 40],
                         files=[f"private/file-{index}" for index in range(40)], more=3, reason="probe")]
        before = copy.deepcopy(events)
        current = serve.snapshot(events, NOW, [])
        self.assertEqual(events, before)
        self.assertEqual(current["overlaps"], [{"drafts": ["alpha", "beta"], "count": 43}])
        self.assertEqual(current["drafts"], {})
        page = serve.render(current)
        self.assertIn('<h2>Overlaps</h2><div class="panel"><div class="scroll"><table><thead><tr>'
                      '<th>Drafts</th><th class="num">Files</th></tr></thead><tbody>'
                      '<tr><td>alpha · beta</td><td class="num">43</td></tr>', page)
        self.assertLess(page.index('<h2>Drafts</h2>'), page.index('<h2>Overlaps</h2>'))
        self.assertLess(page.index('<h2>Overlaps</h2>'), page.index('<h2>Today</h2>'))
        for output in (json.dumps(current), page):
            for record in events[2:]:
                for private in record["files"] + record["tips"]:
                    self.assertNotIn(private, output)

    def test_serve_overlaps_closed_pairs_disappear(self):
        for reason in ("probe", "gone"):
            with self.subTest(reason=reason):
                events = [event("run.started", 30, task=name + "/task") for name in ("alpha", "beta")]
                events += [event("trunks.overlap", 20, drafts=["alpha", "beta"], tips=["a" * 40, "b" * 40],
                                 files=["private/path"], more=3, reason="probe"),
                           event("trunks.overlap", 10, drafts=["alpha", "beta"], tips=["c" * 40, "d" * 40],
                                 files=[], more=0, reason=reason)]
                current = serve.snapshot(events, NOW, [])
                self.assertEqual(current["overlaps"], [])
                page = serve.render(current)
                self.assertIn('<h2>Overlaps</h2><div class="panel">'
                              '<p class="empty">No drafts overlap.</p></div>', page)
                self.assertNotIn('alpha · beta', page)
                for output in (json.dumps(current), page):
                    self.assertNotIn('private/path', output)
                    for tip in ("a" * 40, "b" * 40, "c" * 40, "d" * 40):
                        self.assertNotIn(tip, output)

    def test_serve_overlaps_unknown_and_invalid_drafts_are_other(self):
        for name, known in (("unseen", False), ("Upper", True), ("<private>", True),
                            ("a" * 65, True), ("../private", False)):
            with self.subTest(name=name, known=known):
                events = [event("run.started", 90000, task="zulu/task")]
                if known:
                    events.append(event("run.started", 90000, task=name + "/task"))
                events.append(event("trunks.overlap", drafts=[name, "zulu"], tips=["a" * 40, "b" * 40],
                                    files=["private/path"], more=0, reason="probe"))
                current = serve.snapshot(events, NOW, [])
                self.assertEqual(current["overlaps"], [{"drafts": ["other", "zulu"], "count": 1}])
                page = serve.render(current)
                self.assertIn('<tr><td>other · zulu</td><td class="num">1</td></tr>', page)
                for output in (json.dumps(current), page):
                    self.assertNotIn(name, output)

    def test_serve_overlaps_sorted_by_public_labels_keep_each_pair(self):
        events = [event("run.started", 90000, task=name + "/task") for name in ("alpha", "zulu")]
        for pair, more in ((["alpha", "zulu"], 1), (["Upper", "zulu"], 2),
                           (["Upper", "alpha"], 3), (["unseen", "zulu"], 4)):
            events.append(event("trunks.overlap", drafts=pair, tips=["a" * 40, "b" * 40],
                                files=["private/path"], more=more, reason="probe"))
        current = serve.snapshot(events, NOW, [])
        self.assertEqual(current["overlaps"], [
            {"drafts": ["alpha", "other"], "count": 4},
            {"drafts": ["alpha", "zulu"], "count": 2},
            {"drafts": ["other", "zulu"], "count": 3},
            {"drafts": ["other", "zulu"], "count": 5},
        ])
        page = serve.render(current)
        self.assertLess(page.index('alpha · other'), page.index('alpha · zulu'))
        self.assertLess(page.index('alpha · zulu'), page.index('other · zulu'))
        self.assertEqual(page.count('<td>other · zulu</td>'), 2)

    def test_serve_overlaps_skip_invalid_and_future_events(self):
        opened = event("trunks.overlap", 20, drafts=["alpha", "beta"], tips=["a" * 40, "b" * 40],
                       files=["private/path"], more=0, reason="probe")
        closed = {**opened, "files": [], "more": 0}
        events = [opened, {**closed, "ts": "invalid"}, {**closed, "ts": event("note", -1)["ts"]},
                  {**event("run.started", task="alpha/task"), "ts": "invalid"},
                  event("run.started", -1, task="beta/task")]
        self.assertEqual(serve.snapshot(events, NOW, [])["overlaps"], [
            {"drafts": ["other", "other"], "count": 1},
        ])
        for stamp in (None, "invalid", event("note", -1)["ts"]):
            with self.subTest(stamp=stamp):
                self.assertEqual(serve.snapshot([{**opened, "ts": stamp}], NOW, [])["overlaps"], [])
        events.append({**closed, "ts": event("note", 30)["ts"]})
        self.assertEqual(serve.snapshot(events, NOW, [])["overlaps"], [])


class SubscriptionsTest(unittest.TestCase):
    def added(self, name="codex-1", kind="codex"):
        return {**event("login.added", 200000, id=name, origin="private-host:/private/path", sha="private-sha"),
                "kind": kind}

    def checked(self, age=0, *, name="codex-1", plan="pro", limits=None, **fields):
        if limits is None:
            limits = [("week", 80, NOW.timestamp() + 7200)]
        return event("login.checked", age, id=name, plan=plan,
                     limit_names=[limit[0] for limit in limits], limit_used=[limit[1] for limit in limits],
                     limit_resets=[limit[2] for limit in limits],
                     **{"email": name + "@example.invalid", **fields})

    def test_subscriptions_mask_email_cases(self):
        for email, masked in (("free@ekanayaka.io", "f***e@ekanayaka.io"),
                              ("free.ekanayaka@gmail.com", "f***a@gmail.com"),
                              ("F@EXAMPLE.invalid", "F***@example.invalid"),
                              ("Ab@example.invalid", "A***@example.invalid"),
                              ("FrEe@ExAmPlE.invalid", "F***e@example.invalid"),
                              ("Éloïse@EXAMPLE.invalid", "É***e@example.invalid"),
                              ("missing-at", "***"), ("a@b@c", "***"),
                              ("@example.invalid", "***"), ("local@", "***"), ("@", "***")):
            with self.subTest(email=email):
                current = serve.snapshot([self.added(), self.checked(email=email)], NOW, [])
                self.assertEqual(current["subscriptions"][0]["subscription"], masked)
                encoded = json.dumps(current, ensure_ascii=False)
                self.assertNotIn(email, encoded)
                self.assertIn(masked, encoded)
                self.assertIn(masked, serve.render(current))

    def test_subscriptions_same_mask_keeps_accounts_and_page_sign_in_counts(self):
        emails = ("free.ekanayaka@gmail.com", "flora@gmail.com")
        events = []
        for index in range(1, 6):
            name = f"claude-{index}"
            events += [self.added(name, "claude"),
                       self.checked(name=name, email=emails[1] if index == 5 else emails[0],
                                    plan="max", limits=[])]
        current = serve.snapshot(events, NOW, [])
        self.assertEqual(len(current["subscriptions"]), 2)
        self.assertEqual([s["subscription"] for s in current["subscriptions"]], ["f***a@gmail.com"] * 2)
        self.assertEqual([s["logins"] for s in current["subscriptions"]], [4, 1])
        page = serve.render(current)
        self.assertEqual(page.count('<td>Claude · max · f***a@gmail.com · 4 sign-ins</td>'), 1)
        self.assertEqual(page.count('<td>Claude · max · f***a@gmail.com · 1 sign-in</td>'), 1)
        for output in (json.dumps(current), page):
            for email in emails:
                self.assertNotIn(email, output)
            self.assertIn("f***a@gmail.com", output)

    def test_subscriptions_masked_email_is_escaped_on_page(self):
        current = serve.snapshot([self.added(), self.checked(email="<ab&>@EXAMPLE.invalid")], NOW, [])
        self.assertEqual(current["subscriptions"][0]["subscription"], "<***>@example.invalid")
        page = serve.render(current)
        self.assertIn("&lt;***&gt;@example.invalid", page)
        self.assertNotIn("<***>", page)
        current["subscriptions"][0].update(held=1, held_by=['<host & "quoted">'])
        page = serve.render(current)
        self.assertIn('<span title="&lt;host &amp; &quot;quoted&quot;&gt;">1</span>', page)
        self.assertNotIn('<host & "quoted">', page)

    def test_subscriptions_latest_recent_check_retirement_sorting_and_public_plan(self):
        events = [self.added(), self.checked(3600, plan="old"), self.checked(60),
                  self.checked(-1, plan="future"), self.added("claude-7", "claude"),
                  self.checked(86400, name="claude-7", plan="max"),
                  self.added("codex-2"), self.checked(86401, name="codex-2"),
                  self.added("codex-3"), self.checked(name="codex-3"),
                  event("login.retired", 10, id="codex-3", reason="private reason"),
                  self.added("claude-8", "claude"), self.checked(name="claude-8", plan="private@example.invalid"),
                  self.added("codex-10"), self.checked(name="codex-10", plan="x" * 41),
                  self.added("codex-11"), self.checked(name="codex-11", plan="max_5"),
                  self.checked(name="codex-12"), self.added("private-id", "claude"),
                  self.checked(name="private-id")]
        before = copy.deepcopy(events)
        # The latest check is chosen by its timestamp, even when the input is out of order.
        subscriptions = serve.snapshot(list(reversed(events)), NOW, [])["subscriptions"]
        self.assertEqual(events, before)
        expected = [("claude", "c***7@example.invalid", "max", 86400),
                    ("claude", "c***8@example.invalid", "", 0),
                    ("codex", "c***0@example.invalid", "", 0),
                    ("codex", "c***1@example.invalid", "pro", 60),
                    ("codex", "c***1@example.invalid", "max_5", 0)]
        self.assertEqual([(s["kind"], s["subscription"], s["plan"], s["checked_age_s"])
                          for s in subscriptions], expected)
        self.assertTrue(all(s["logins"] == 1 for s in subscriptions))

    def test_subscriptions_group_account_uses_newest_limits_and_plan(self):
        reset = NOW.timestamp() + 7200
        events = [self.added(), self.checked(600, limits=[("week", 40, reset)]),
                  self.added("codex-2"), self.checked(60, name="codex-2", plan="max",
                                                   email="codex-1@example.invalid")]
        current = serve.snapshot(list(reversed(events)), NOW, [])
        self.assertEqual(current["subscriptions"], [{
            "subscription": "c***1@example.invalid", "kind": "codex", "plan": "max", "logins": 2,
            "held": 0, "held_by": [],
            "checked_age_s": 60, "limits": [{"name": "week", "used": 80, "resets": reset,
                                           "rate_per_h": None, "full_at": None, "at_reset": None}],
        }])
        page = serve.render(current)
        self.assertIn("Codex · max · c***1@example.invalid · 2 sign-ins", page)
        self.assertIn('<div class="sub">1 subscriptions</div>', page)

    def test_subscriptions_claude_box_alone_is_a_claude_row(self):
        name = "claude-box-1"
        current = serve.snapshot([self.added(name, "claude-box"),
                                  self.checked(name=name, plan="max")], NOW, [])
        self.assertEqual(current["subscriptions"], [{
            "subscription": "c***1@example.invalid", "kind": "claude", "plan": "max", "logins": 1,
            "held": 0, "held_by": [],
            "checked_age_s": 0, "limits": [{"name": "week", "used": 80,
                                          "resets": NOW.timestamp() + 7200,
                                          "rate_per_h": None, "full_at": None, "at_reset": None}],
        }])
        page = serve.render(current)
        self.assertIn("Claude · max · c***1@example.invalid · 1 sign-in", page)
        self.assertIn('<div class="sub">1 subscriptions</div>', page)

    def test_subscriptions_claude_box_and_claude_share_account_and_pace(self):
        reset = NOW.timestamp() + 7200
        email = "shared@example.invalid"
        for latest, earlier in (("claude-box-1", "claude-1"), ("claude-1", "claude-box-1")):
            with self.subTest(latest=latest):
                events = [self.added("claude-1", "claude"), self.added("claude-box-1", "claude-box"),
                          self.checked(3600, name=earlier, email=email, limits=[("week", 70, reset)]),
                          self.checked(name=latest, email=email, plan="max")]
                current = serve.snapshot(list(reversed(events)), NOW, [])
                self.assertEqual(current["subscriptions"], [{
                    "subscription": "s***d@example.invalid", "kind": "claude", "plan": "max", "logins": 2,
                    "held": 0, "held_by": [],
                    "checked_age_s": 0, "limits": [{"name": "week", "used": 80, "resets": reset,
                                                  "rate_per_h": 10, "full_at": None, "at_reset": 100}],
                }])
                page = serve.render(current)
                self.assertEqual(page.count("Claude · max · s***d@example.invalid · 2 sign-ins"), 1)
                self.assertIn('<div class="sub">1 subscriptions</div>', page)

    def test_subscriptions_latest_account_moves_login_to_new_group(self):
        events = [self.added(), self.added("codex-2"),
                  self.checked(3600), self.checked(1800, name="codex-2", email="codex-1@example.invalid")]
        events += [event("login.lent", 2000, id="codex-1", holder="walk/private-run", host="hel8", at="/private"),
                   event("login.lent", 2000, id="codex-2", holder="hel8", host="hel8", at=".codex/auth.json")]
        grouped = serve.snapshot(events, NOW, ["hel8"])["subscriptions"][0]
        self.assertEqual((grouped["logins"], grouped["held"], grouped["held_by"]), (2, 2, ["QA walk", "hel8"]))
        events.append(self.checked(email="codex-2@example.invalid"))
        subscriptions = serve.snapshot(events, NOW, [])["subscriptions"]
        self.assertEqual(len(subscriptions), 2)
        self.assertTrue(all(s["logins"] == 1 and s["held"] == 1 for s in subscriptions))
        previous = next(s for s in subscriptions if s["subscription"] == "c***1@example.invalid")
        self.assertEqual(previous["checked_age_s"], 1800)

    def test_subscriptions_failed_or_missing_latest_account_leaves_login_out(self):
        for fields in ({"error": "private failure"}, {"email": None}, {"email": ""},
                       {"email": ["invalid"]}):
            with self.subTest(fields=fields):
                events = [self.added(), self.checked(3600), self.checked(**fields)]
                self.assertEqual(serve.snapshot(events, NOW, [])["subscriptions"], [])
                events += [self.added("codex-2"), self.checked(name="codex-2", email="codex-1@example.invalid")]
                self.assertEqual(serve.snapshot(events, NOW, [])["subscriptions"][0]["logins"], 1)
        missing = self.checked()
        del missing["email"]
        self.assertEqual(serve.snapshot([self.added(), self.checked(3600), missing], NOW, [])["subscriptions"], [])

    def test_subscriptions_pace_uses_oldest_sample_across_account_logins(self):
        reset = NOW.timestamp() + 7200
        events = [self.added(), self.added("codex-2"),
                  self.checked(7200, name="codex-2", email="codex-1@example.invalid",
                               limits=[("week", 60, reset)]),
                  self.checked(3600, limits=[("week", 75, reset)]), self.checked()]
        subscription = serve.snapshot(list(reversed(events)), NOW, [])["subscriptions"][0]
        self.assertEqual(subscription["logins"], 2)
        self.assertEqual(subscription["limits"][0]["rate_per_h"], 10)
        self.assertEqual(subscription["limits"][0]["at_reset"], 100)
        events.insert(2, self.checked(10800, email="another@example.invalid", limits=[("week", 0, reset)]))
        self.assertEqual(serve.snapshot(events, NOW, [])["subscriptions"][0]["limits"], subscription["limits"])

    def test_subscriptions_label_stable_across_login_ids_and_separate_by_kind(self):
        for name in ("codex-1", "codex-19"):
            events = [self.added(name), self.checked(name=name, email="codex-1@example.invalid")]
            self.assertEqual(serve.snapshot(events, NOW, [])["subscriptions"][0]["subscription"], "c***1@example.invalid")
        events += [self.added("claude-7", "claude"),
                   self.checked(name="claude-7", email="codex-1@example.invalid")]
        subscriptions = serve.snapshot(events, NOW, [])["subscriptions"]
        self.assertEqual([s["kind"] for s in subscriptions], ["claude", "codex"])
        self.assertEqual(subscriptions[0]["subscription"], subscriptions[1]["subscription"])

    def test_subscriptions_rate_full_at_and_at_reset_from_same_window(self):
        reset = NOW.timestamp() + 7200
        before = [("week", 70, reset), ("other 1 d", 8, reset), ("other 2 d", 40, reset)]
        latest = [("week", 80, reset), ("other 1 d", 10, reset), ("other 2 d", 40, reset)]
        events = [self.added(), self.checked(4200, limits=before), self.checked(600, limits=latest)]
        limits = serve.snapshot(events, NOW, [])["subscriptions"][0]["limits"]
        self.assertEqual(limits[0], {"name": "week", "used": 80, "resets": reset, "rate_per_h": 10,
                                     "full_at": NOW.timestamp() + 6600, "at_reset": None})
        self.assertEqual(limits[1], {"name": "other 1 d", "used": 10, "resets": reset, "rate_per_h": 2,
                                     "full_at": None, "at_reset": 14.3})
        self.assertEqual(limits[2]["rate_per_h"], 0)
        self.assertEqual(limits[2]["at_reset"], 40)
        # An older, sufficiently spaced sample wins over a more recent one.
        events.insert(2, self.checked(2400, limits=[("week", 79, reset)]))
        self.assertEqual(serve.snapshot(events, NOW, [])["subscriptions"][0]["limits"][0]["rate_per_h"], 10)

    def test_subscriptions_no_pace_across_resets_short_samples_or_other_logins(self):
        reset = NOW.timestamp() + 7200
        for earlier in (self.checked(3600, limits=[("week", 20, reset - 86400)]),
                        self.checked(1199, limits=[("week", 20, reset)]),
                        self.checked(3600, name="codex-2"),
                        self.checked(3600, limits=[("week", 90, reset)]),
                        self.checked(3600, error="private failure"),
                        self.checked(3600, limits=[("other week", 20, reset)])):
            with self.subTest(earlier=earlier):
                limits = serve.snapshot([self.added(), earlier, self.checked()], NOW, [])["subscriptions"][0]["limits"]
                for field in ("rate_per_h", "full_at", "at_reset"):
                    self.assertIsNone(limits[0][field])
        for resets in (None, NOW.timestamp() - 1):
            events = [self.added(), self.checked(3600, limits=[("week", 20, resets)]),
                      self.checked(limits=[("week", 80, resets)])]
            self.assertIsNone(serve.snapshot(events, NOW, [])["subscriptions"][0]["limits"][0]["rate_per_h"])
        events = [self.added(), self.checked(1200, limits=[("week", 78, reset)]), self.checked()]
        self.assertEqual(serve.snapshot(events, NOW, [])["subscriptions"][0]["limits"][0]["rate_per_h"], 6)

    def test_subscriptions_short_window_only_over_80_and_bad_columns_ignored(self):
        for used, kept in ((None, False), (0, False), (80, False), (80.1, True), (100, True)):
            with self.subTest(used=used):
                events = [self.added(), self.checked(limits=[("5 h", used, None), ("week", 80, None)])]
                limits = serve.snapshot(events, NOW, [])["subscriptions"][0]["limits"]
                self.assertEqual([limit["name"] for limit in limits], ["5 h", "week"] if kept else ["week"])
        for fields in ({"limit_names": "week"}, {"limit_used": []}, {"limit_resets": None}):
            events = [self.added(), {**self.checked(), **fields}]
            self.assertEqual(serve.snapshot(events, NOW, [])["subscriptions"][0]["limits"], [])
        events = [self.added(), self.checked(limits=[("week", float("inf"), float("nan")),
                                                   ("Fable", 20, None)])]
        limit = serve.snapshot(events, NOW, [])["subscriptions"][0]["limits"][0]
        self.assertIsNone(limit["used"])
        self.assertIsNone(limit["resets"])

    def test_subscriptions_held_groups_machines_and_run_labels_without_custody_details(self):
        email = "private-account@example.invalid"
        uses = [("claude-1", "claude", "hel8", ".claude/.credentials.json"),
                ("claude-2", "claude", "hetzner6", ".claude/.credentials.json"),
                ("claude-box-1", "claude-box", "walk/private-walk", "/private/walk"),
                ("claude-box-2", "claude-box", "walk/second-private-walk", "/private/walk-2"),
                ("claude-3", "claude", "after-landing/private-tip/pair", "/private/pair"),
                ("claude-4", "claude", "check/private-login", "/private/check"),
                ("claude-5", "claude", "private-holder", "/private/other"),
                ("claude-6", "claude", None, None),
                ("codex-1", "codex", "hel8", ".codex/auth.json")]
        events = []
        for name, kind, holder, path in uses:
            events += [self.added(name, kind),
                       self.checked(name=name, email=email,
                                    limits=[("week", 40, None), ("5 h", 92, None)])]
            if holder is not None:
                events.append(event("login.lent", 100, id=name, holder=holder,
                                    host="private-host", at=path, sha="private-sha"))
        before = copy.deepcopy(events)
        current = serve.snapshot(list(reversed(events)), NOW, ["hetzner6", "hel8"])
        self.assertEqual(events, before)
        claude, codex = current["subscriptions"]
        labels = ["QA walk", "QA walk", "after-landing", "check", "hel8", "hetzner6", "other"]
        self.assertEqual((claude["logins"], claude["held"], claude["held_by"]), (8, 7, labels))
        self.assertEqual((codex["logins"], codex["held"], codex["held_by"]), (1, 1, ["hel8"]))
        page = serve.render(current)
        self.assertEqual(page.count('<span title="' + " · ".join(labels) + '">7</span>'), 1)
        self.assertEqual(page.count('<span title="hel8">1</span>'), 1)
        self.assertIn('92% <small>· 5 h</small>', page)
        for output in (json.dumps(current), page):
            for secret in (email, "private-host", "private-sha", "private-host:/private/path",
                           *(name for name, _, _, _ in uses),
                           *(path for _, _, _, path in uses if path),
                           *(holder for _, _, holder, _ in uses if holder and holder not in ("hel8", "hetzner6"))):
                self.assertNotIn(secret, output)

    def test_subscriptions_held_host_label_requires_the_kinds_machine_path(self):
        for kind, path, expected in (("codex", ".codex/auth.json", "hel8"),
                                     ("claude", ".claude/.credentials.json", "hel8"),
                                     ("codex", ".claude/.credentials.json", "other"),
                                     ("claude", ".codex/auth.json", "other"),
                                     ("codex", "/private/.codex/auth.json", "other"),
                                     ("claude-box", "", "other")):
            with self.subTest(kind=kind, path=path):
                name = kind + "-1"
                events = [self.added(name, kind), self.checked(name=name),
                          event("login.lent", 100, id=name, holder="hel8", host="hel8", at=path)]
                subscription = serve.snapshot(events, NOW, ["hel8"])["subscriptions"][0]
                self.assertEqual((subscription["held"], subscription["held_by"]), (1, [expected]))
                self.assertEqual(serve.snapshot(events, NOW, [])["subscriptions"][0]["held_by"], ["other"])

    def test_subscriptions_held_returns_retirement_and_relending_follow_the_fold(self):
        events = []
        for index in range(1, 4):
            name = f"codex-{index}"
            events += [self.added(name), self.checked(name=name, email="shared@example.invalid"),
                       event("login.lent", 100, id=name, holder="hel8", host="hel8", at=".codex/auth.json")]
        events += [event("login.returned", 30, id="codex-1", sha="returned-sha"),
                   event("login.retired", 20, id="codex-3", reason="private-reason"),
                   event("login.lent", -1, id="codex-1", holder="private-future", host="private", at="/private"),
                   {**event("login.returned", id="codex-2", sha="invalid-sha"), "ts": "invalid"}]
        current = serve.snapshot(list(reversed(events)), NOW, ["hel8"])
        subscription = current["subscriptions"][0]
        self.assertEqual((subscription["logins"], subscription["held"], subscription["held_by"]),
                         (2, 1, ["hel8"]))
        events.append(event("login.returned", 10, id="codex-2", sha="returned-sha"))
        current = serve.snapshot(events, NOW, ["hel8"])
        self.assertEqual(current["subscriptions"][0]["held"], 0)
        self.assertEqual(current["subscriptions"][0]["held_by"], [])
        self.assertIn('<span title="none">0</span>', serve.render(current))
        events.append(event("login.lent", id="codex-1", holder="check/private-id", host="hel8", at="/private"))
        subscription = serve.snapshot(events, NOW, ["hel8"])["subscriptions"][0]
        self.assertEqual((subscription["held"], subscription["held_by"]), (1, ["check"]))

    def test_subscriptions_private_account_and_custody_fields_never_leave_fold(self):
        private = {"email": "private@example.invalid", "holder": "private-holder", "host": "private-host",
                   "path": "/private/path", "plan": "private@example.invalid"}
        for name, kind in (("codex-1", "codex"), ("claude-1", "claude"), ("claude-box-1", "claude-box")):
            with self.subTest(kind=kind):
                events = [self.added(name, kind), event("login.lent", 100, id=name, at="/private/path", **private),
                          self.checked(3600, name=name, error="private failure", **private),
                          self.checked(name=name, **private)]
                current = serve.snapshot(events, NOW, [])
                self.assertEqual(current["subscriptions"][0]["subscription"], "p***e@example.invalid")
                for output in (json.dumps(current), serve.render(current)):
                    for secret in (*private.values(), "private-sha", "private-host:/private/path",
                                   "private failure", name):
                        self.assertNotIn(secret, output)
                    self.assertIn("p***e@example.invalid", output)

    def test_subscriptions_table_meters_resets_pace_and_tile(self):
        reset = NOW.timestamp() + 11340
        events = [self.added("claude-7", "claude"),
                  self.checked(3600, name="claude-7", plan="max",
                               limits=[("week", 76.4, reset), ("5 h", 94, reset), ("other 1 d", 12, reset)]),
                  self.checked(name="claude-7", plan="max",
                               limits=[("week", 80, reset), ("5 h", 95, reset), ("other 1 d", 14, reset)]),
                  self.added(), self.checked(limits=[("week", 4, None)])]
        current = serve.snapshot(events, NOW, [])
        page = serve.render(current)
        self.assertIn('<h2>Subscriptions</h2><div class="panel"><div class="scroll"><table>', page)
        self.assertIn('<th>Subscription</th><th>Held</th><th>Used</th><th>Resets</th>'
                      '<th>Rate</th><th>At this pace</th>', page)
        self.assertEqual(page.count("Claude · max · c***7@example.invalid · 1 sign-in</td>"), 1)
        self.assertIn('<span class="meter warning"><i style="width:80%"></i></span> 80%', page)
        self.assertIn('<span class="meter critical"><i style="width:95%"></i></span> 95% <small>· 5 h</small>', page)
        self.assertIn('14% <small>· other 1 d</small>', page)
        self.assertNotIn('<th>Limit</th>', page)
        self.assertNotIn('<td>week</td>', page)
        self.assertNotIn('<small>· week</small>', page)
        self.assertEqual(page.count('<span title="none">0</span>'), 2)
        self.assertIn('<tr><td></td><td></td><td><span class="meter critical">', page)
        self.assertIn('<span class="meter"><i style="width:4%"></i></span> 4%', page)
        self.assertIn('<time datetime="2026-11-01T03:39:00Z" title="2026-11-01 03:39 UTC">'
                      'in 3 h 9 min</time>', page)
        self.assertIn('<td>3.6%/h</td><td>lasts, 91.3% at reset</td>', page)
        self.assertIn('<td>–</td><td>–</td><td>–</td>', page)
        self.assertIn('<div class="label">Subscriptions</div><div class="value">80%</div>'
                      '<div class="sub">2 subscriptions</div>', page)
        current["subscriptions"][0]["limits"][0]["full_at"] = NOW.timestamp() + 37 * 3600
        current["subscriptions"][0]["limits"][0]["at_reset"] = None
        self.assertIn("full in 1 d 13 h", serve.render(current))
        self.assertIn('.meter.warning i{background:var(--warning)}', page)
        self.assertIn('.meter.critical i{background:var(--critical)}', page)

    def test_subscriptions_empty_and_legacy_checks(self):
        self.assertIn('<p class="empty">No login checked in the last 24 hours.</p>',
                      serve.render(serve.snapshot([], NOW, [])))
        events = [self.added(), event("login.checked", id="codex-1", email="codex-1@example.invalid",
                                      plan="pro", used=72, resets=123)]
        current = serve.snapshot(events, NOW, [])
        self.assertEqual(current["subscriptions"][0]["limits"], [])
        self.assertIn("Codex · pro · c***1@example.invalid · 1 sign-in", serve.render(current))


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.current = serve.snapshot([], NOW, [])
        self.current.update({
            "last_event_age_s": 420,
            "runs_in_flight": {"total": 5, "by_host": {"hetzner6": 2, "hetzner9": 3}},
            "calls_in_flight": {"total": 4, "by_role": {"answer": 1, "review": 3}},
            "waiting_on_user": {"asks": 3, "by_kind": {"call": 1, "parked": 2}, "oldest_age_s": 10800},
            "landed": {"last_hour": 2, "today": 7},
            "merged": {"last_hour": 3, "today": 9},
            "rejected_today": 4,
            "runs_ended_today": {"done": 11, "question": 2, "infra": 3, "failed": 4, "other": 5},
            "weight_today": {"codex_m": 12.3, "claude_m": 4.0, "ratio": 3.1},
            "drafts": {
                "active": {"runs_in_flight": 5, "merged_today": 6, "landed_today": 3},
                "idle": {"runs_in_flight": 0, "merged_today": 3, "landed_today": 4},
            },
        })

    def test_serve_render_layout_tiles_and_header(self):
        before = copy.deepcopy(self.current)
        page = serve.render(self.current)
        self.assertEqual(self.current, before)
        self.assertIn('<body><main><header><h1>Fabrig status</h1>', page)
        self.assertIn('<span class="meta">Updated 00:30 UTC · last event 7 min ago</span></header>', page)
        self.assertEqual(re.findall(r'<h2>(.*?)</h2>', page),
                         ["Waiting on the user", "Subscriptions", "Drafts", "Overlaps", "Today", "In flight"])
        self.assertLess(page.index('<header>'), page.index('<div class="tiles">'))
        self.assertIn('</div></div><h2>Waiting on the user</h2>', page)
        self.assertEqual(page.count('<div class="panel">'), 4)
        self.assertEqual(page.count('<div class="cards">'), 2)
        self.assertEqual(page.count('<div class="card">'), 5)
        self.assertEqual(page.count('<div class="scroll"><table>'), 7)
        self.assertEqual(re.findall(r'<(?:div|a) class="tile"[^>]*>(.*?)</div></(?:div|a)>', page), [
            '<div class="label">Runs in flight</div><div class="value">5</div>'
            '<div class="sub">hetzner6 2 · hetzner9 3',
            '<div class="label">Calls in flight</div><div class="value">4</div>'
            '<div class="sub">answer 1 · review 3',
            '<div class="label">Waiting on the user</div><div class="value">3</div>'
            '<div class="sub">oldest 3 h',
            '<div class="label">Landed on main today</div><div class="value">7</div>'
            '<div class="sub">last hour 2',
            '<div class="label">Merged into a trunk today</div><div class="value">9</div>'
            '<div class="sub">last hour 3',
            '<div class="label">Weight today · Codex/Claude</div><div class="value">3.1×</div>'
            '<div class="sub">Codex 12.3M · Claude 4.0M',
            '<div class="label">Subscriptions</div><div class="value">–</div><div class="sub">0 subscriptions',
        ])
        self.assertIn('main{max-width:1280px;', page)
        self.assertIn('<style>' + serve.STYLE + '</style>', page)
        self.assertTrue(page.endswith('</footer></main></body></html>'))
        self.assertIn("<footer>From fab's event log on hel8; refreshes every 30 s. "
                      'Release page: <a href="/v0.1.0.html">v0.1.0</a>.</footer>', page)

    def test_serve_render_weight_ratio_zero_cases(self):
        for codex, claude, ratio, value in ((12.3, 0.0, None, "–"),
                                         (0.0, 0.0, None, "–"),
                                         (0.0, 4.0, 0.0, "0.0×")):
            with self.subTest(codex=codex, claude=claude):
                self.current["weight_today"] = {"codex_m": codex, "claude_m": claude, "ratio": ratio}
                page = serve.render(self.current)
                self.assertIn('<div class="label">Weight today · Codex/Claude</div>'
                              f'<div class="value">{value}</div>'
                              f'<div class="sub">Codex {codex:.1f}M · Claude {claude:.1f}M</div>', page)
                self.assertNotIn("Weight today, Codex", page)
                self.assertNotIn("Weight today, Claude", page)

    def test_serve_render_waiting_links_to_open_questions(self):
        issues = "https://git.fabrig.ai/fabrig-ai/agents/issues?state=open&amp;labels=1"
        for current in (self.current, serve.snapshot([], NOW, [])):
            with self.subTest(asks=current["waiting_on_user"]["asks"]):
                page = serve.render(current)
                self.assertIn(f'<a class="tile" href="{issues}"><div class="label">'
                              'Waiting on the user</div>'
                              f'<div class="value">{current["waiting_on_user"]["asks"]}</div>', page)
                for label, kind in (("Call questions", "call"), ("Parked chains", "parked")):
                    count = current["waiting_on_user"]["by_kind"][kind]
                    self.assertIn(f'<tr><td><a href="{issues}">{label}</a></td>'
                                  f'<td class="num">{count}</td></tr>', page)
                self.assertIn(f'</p><p><a href="{issues}">Open the questions</a></p></div>'
                              '<h2>Subscriptions</h2>', page)
                self.assertEqual(page.count(f'href="{issues}"'), 4)
                self.assertIn('a{color:var(--info)}', page)
                self.assertIn('a.tile{color:inherit;text-decoration:none;display:block}', page)

    def test_serve_render_drafts_and_outcome_badges(self):
        page = serve.render(self.current)
        self.assertIn('<h2>Drafts</h2><div class="panel"><div class="scroll"><table><thead><tr>'
                      '<th>Draft</th><th>State</th><th class="num">Runs in flight</th>'
                      '<th class="num">Merged today</th><th class="num">Landed today</th>', page)
        self.assertIn('<tr><td>active</td><td><span class="badge info"><i></i>running</span></td>'
                      '<td class="num">5</td><td class="num">6</td><td class="num">3</td></tr>', page)
        self.assertIn('<tr><td>idle</td><td><span class="badge neutral"><i></i>idle</span></td>'
                      '<td class="num">0</td><td class="num">3</td><td class="num">4</td></tr>', page)
        for outcome, state, count in (("done", "good", 11), ("question", "warning", 2),
                                      ("infra", "neutral", 3), ("failed", "critical", 4),
                                      ("other", "neutral", 5)):
            with self.subTest(outcome=outcome):
                self.assertIn(f'<tr><td><span class="badge {state}"><i></i>{outcome}</span></td>'
                              f'<td class="num">{count}</td></tr>', page)

    def test_serve_render_tables_keep_counts_and_numeric_columns(self):
        page = serve.render(self.current)
        self.assertIn('<h3>Landings</h3><div class="scroll"><table><thead><tr><th></th>'
                      '<th class="num">Last hour</th><th class="num">Today</th>', page)
        for label, hour, today in (("Landed on main", 2, 7), ("Merged into a trunk", 3, 9),
                                   ("Rejected", "–", 4)):
            self.assertIn(f'<tr><td>{label}</td><td class="num">{hour}</td>'
                          f'<td class="num">{today}</td></tr>', page)
        for title, first, second in (("Weight", "", "Millions"),
                                     ("Codex runs by host", "Host", "Runs"),
                                     ("Claude calls by role", "Role", "Calls")):
            self.assertIn(f'<h3>{title}</h3><div class="scroll"><table><thead><tr><th>{first}</th>'
                          f'<th class="num">{second}</th>', page)
        self.assertIn('<h2>Waiting on the user</h2><div class="panel"><div class="scroll"><table>'
                      '<thead><tr><th>Kind</th><th class="num">Open</th>', page)
        for label, value in (("Codex", "12.3"), ("Claude", "4.0"), ("hetzner6", 2), ("hetzner9", 3),
                             ("answer", 1), ("review", 3)):
            self.assertIn(f'<tr><td>{label}</td><td class="num">{value}</td></tr>', page)
        self.assertIn('<p class="facts">Oldest: 3 h</p>', page)

    def test_serve_render_empty_states(self):
        page = serve.render(serve.snapshot([], NOW, []))
        self.assertIn('Updated 00:30 UTC · no events yet</span>', page)
        self.assertIn('<h2>Drafts</h2><div class="panel">'
                      '<p class="empty">No draft active today.</p></div>', page)
        self.assertIn('<h2>Overlaps</h2><div class="panel">'
                      '<p class="empty">No drafts overlap.</p></div>', page)
        for title in ("Codex runs by host", "Claude calls by role"):
            self.assertIn(f'<div class="card"><h3>{title}</h3><p class="empty">None.</p></div>', page)
        self.assertIn('<div class="label">Runs in flight</div><div class="value">0</div></div>', page)
        self.assertIn('<div class="label">Calls in flight</div><div class="value">0</div></div>', page)
        self.assertIn('<div class="sub">oldest none</div>', page)
        self.assertIn('<p class="facts">Oldest: none</p>', page)
        self.assertEqual(page.count('<span class="badge '), 5)

    def test_serve_render_unreadable_log_keeps_header_and_footer(self):
        page = serve.render({"updated": "2026-11-01T00:30:00.000Z", "log": "unreadable"})
        self.assertIn('<header><h1>Fabrig status</h1><span class="meta">Updated 00:30 UTC · '
                      'no events yet</span></header><p class="empty">The event log is unreadable.</p>'
                      '<footer>', page)
        self.assertIn('<a href="/v0.1.0.html">v0.1.0</a>', page)
        self.assertIn('<meta http-equiv="refresh" content="30">', page)
        for markup in ('<div class="tiles">', '<h2>', '<table>', '<div class="card">'):
            self.assertNotIn(markup, page)

    def test_serve_render_escapes_all_snapshot_labels(self):
        label = '<label & "quoted">'
        self.current["runs_in_flight"]["by_host"] = {label: 5}
        self.current["calls_in_flight"]["by_role"] = {label: 4}
        self.current["drafts"] = {label: {"runs_in_flight": 1, "merged_today": 2, "landed_today": 3}}
        self.current["overlaps"] = [{"drafts": [label, "zulu"], "count": 2}]
        page = serve.render(self.current)
        self.assertNotIn(label, page)
        self.assertEqual(page.count('&lt;label &amp; &quot;quoted&quot;&gt;'), 6)
        failure = serve.render({"updated": label, "log": "unreadable"})
        self.assertNotIn(label, failure)
        self.assertIn('&lt;label &amp; &quot;quoted&quot;&gt;', failure)


class ServerTest(unittest.TestCase):
    @contextmanager
    def running(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {"HOME": directory, "FAB_HOME": directory}), \
                patch.object(serve.machines, "load", return_value={"builder": None}), \
                ThreadingHTTPServer(("127.0.0.1", 0), serve._Request) as server:
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
            thread.start()
            try:
                yield server.server_port, Path(directory) / "log.jsonl"
            finally:
                server.shutdown()
                thread.join(timeout=2)
                self.assertFalse(thread.is_alive())

    def request(self, port, path, method="GET"):
        connection = HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            connection.request(method, path)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read().decode()
        finally:
            connection.close()

    def test_serve_routes_query_strings_fresh_reads_and_no_writes(self):
        with self.running() as (port, path):
            with patch.object(serve.log, "read", wraps=log.read) as reads:
                code, headers, body = self.request(port, "/?ignored=private")
                self.assertEqual(code, 200)
                self.assertTrue(headers["Content-Type"].startswith("text/html"))
                self.assertIn("fab status", body)
                self.assertFalse(path.exists())
                code, headers, body = self.request(port, "/api/status?ignored=yes")
                self.assertEqual(code, 200)
                self.assertTrue(headers["Content-Type"].startswith("application/json"))
                self.assertEqual(json.loads(body)["runs_in_flight"]["total"], 0)
                line = json.dumps({"ts": log.now(), "ev": "run.started", "run": "r",
                                   "task": "draft/t", "host": "builder"}) + '\n{"torn":'
                write(path, line)
                code, _, body = self.request(port, "/api/status")
                self.assertEqual(code, 200)
                self.assertEqual(json.loads(body)["runs_in_flight"], {"total": 1, "by_host": {"builder": 1}})
                self.assertEqual(self.request(port, "/healthz?ignored=yes")[::2], (200, "ok"))
                self.assertEqual(self.request(port, "/unknown?secret")[::2], (404, "not found"))
                self.assertEqual(reads.call_count, 5)
                self.assertEqual(path.read_text(), line)
                self.assertEqual(sorted(p.name for p in path.parent.iterdir()), ["log.jsonl"])

    def test_serve_all_other_methods_are_405(self):
        with self.running() as (port, path):
            for method in ("POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE", "CONNECT", "UNKNOWN"):
                with self.subTest(method=method):
                    code, headers, body = self.request(port, "/api/status", method)
                    self.assertEqual(code, 405)
                    self.assertEqual(headers["Allow"], "GET")
                    self.assertEqual(body, "" if method == "HEAD" else "method not allowed")
            self.assertFalse(path.exists())

    def test_serve_unreadable_log_returns_fixed_failure_and_no_figures(self):
        with self.running() as (port, path):
            path.mkdir()  # An unreadable log even when tests run as root.
            code, _, body = self.request(port, "/api/status")
            self.assertEqual(code, 200)
            current = json.loads(body)
            self.assertEqual(set(current), {"updated", "log"})
            self.assertEqual(current["log"], "unreadable")
            code, _, body = self.request(port, "/")
            self.assertEqual(code, 200)
            self.assertIn("The event log is unreadable.", body)
            self.assertNotIn(str(path), body)
            self.assertEqual(self.request(port, "/healthz")[::2], (200, "ok"))

    def test_serve_host_failure_classifies_unknown_hosts(self):
        with self.running() as (port, path):
            write(path, json.dumps({"ts": log.now(), "ev": "run.started", "run": "r",
                                   "host": "private", "task": "draft/t"}) + "\n")
            with patch.object(serve.machines, "load", side_effect=ValueError("private reason")):
                code, _, body = self.request(port, "/api/status")
            self.assertEqual(code, 200)
            self.assertNotIn("private", body)
            self.assertEqual(json.loads(body)["runs_in_flight"]["by_host"], {"other": 1})

    def test_serve_command_registration_defaults_and_bound_port(self):
        self.assertEqual(cli.COMMANDS["serve"], ("fab.serve", "the public status page, live from the log"))
        for args, address in (([], ("127.0.0.1", 8370)),
                              (["--bind", "0.0.0.0", "--port", "0"], ("0.0.0.0", 0))):
            out = io.StringIO()
            with patch.object(serve, "ThreadingHTTPServer") as factory, redirect_stdout(out):
                server = factory.return_value.__enter__.return_value
                server.server_port = 12345
                server.serve_forever.side_effect = KeyboardInterrupt
                self.assertEqual(cli.main(["serve", *args]), 0)
                factory.assert_called_once_with(address, serve._Request)
                factory.return_value.__exit__.assert_called_once()
            self.assertEqual(out.getvalue(), f"serving on http://{address[0]}:12345\n")
