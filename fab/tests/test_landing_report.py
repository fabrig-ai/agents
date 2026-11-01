import unittest
from unittest.mock import patch

from fab import landing_report as landing
from fab.gate import NO_TESTS
from fab.hosts import Host
from fab.report import Signal, Sources, Window
from fab.tests.support import tmp_home


START = "2026-10-29T00:00:00.000Z"
END = "2026-10-29T01:00:00.000Z"
WINDOW = Window(START, END)
RED_COUNTS = {"reds_opened", "reds_foreman", "reds_page", "reds_fix", "reds_none", "reds_left",
              "red_repairs_landed", "reds_closed", "reds_closed_recovered", "reds_closed_absent",
              "reds_closed_cleared", "hand_rejected"}


def ts(time, day="2026-10-29"):
    return f"{day}T{time}:00.000Z"


def batch(time, branches, outcome="green", steps=(), **fields):
    return {"ts": ts(time), "ev": "batch", "branches": branches, "parent": "main-tip",
            "selection": "full", "steps": list(steps), "outcome": outcome,
            "log": "/queue/batch.log", "freed": 0, **fields}


def ready(time, branch, tip, **fields):
    return {"ts": ts(time), "ev": "branch.ready", "task": branch,
            "branch": branch, "tip": tip, **fields}


def landed(time, branch, tip, **fields):
    return {"ts": ts(time), "ev": "landed", "branch": branch, "tip": tip,
            "main": "main-tip", **fields}


def rejected(time, branch, tip, step="build", **fields):
    return {"ts": ts(time), "ev": "rejected", "branch": branch, "tip": tip,
            "step": step, "log": "/queue/batch.log", **fields}


def red_opened(time, identifier, route="foreman", **fields):
    return {"ts": ts(time), "ev": "red.opened", "red": identifier, "tip": "main-tip",
            "keys": [identifier + "-case"], "suspects": ["demo/a"], "tasks": ["demo/a"],
            "draft": "demo", "route": route, "reason": "no suspects" if route == "signal" else "",
            **fields}


def red_decisions(time, identifier, verdict, **fields):
    stamp = fields.get("ts", ts(time))
    return [red_opened(time, identifier, **fields),
            {"ts": stamp, "ev": "run.started", "kind": "foreman", "red": identifier,
             "task": f"demo/{identifier}/foreman", "tip": "main-tip", "run": identifier + "-foreman"},
            {"ts": stamp, "ev": "run.ended", "run": identifier + "-foreman", "outcome": "done"},
            {"ts": stamp, "ev": "red.settled", "red": identifier, "run": identifier + "-foreman",
             "verdict": verdict, "reason": "the tier needs a login"}]


def red_sources():
    events = red_decisions("23:00", "red-old", "fix", ts=ts("23:00", "2026-10-28"))
    for time, identifier, verdict in (("00:00", "red-1", "fix"), ("00:01", "red-2", "none"),
                                       ("00:02", "red-3", "left"), ("00:04", "red-5", "fix")):
        events.extend(red_decisions(time, identifier, verdict))
    events.extend([red_opened("00:03", "red-4", route="signal"),
                   red_opened("00:05", "red-6", route="signal"),
                   red_opened("01:00", "red-future", route="signal")])
    for time, identifier in (("00:06", "red-old"), ("00:07", "red-1"), ("00:08", "red-5")):
        events.append({"ts": ts(time), "ev": "branch.landed", "task": f"demo/{identifier}"})
    events.append({"ts": ts("00:09"), "ev": "tiers.run", "tip": "covering-tip", "faults": [],
                   "branches": ["demo/red-5-r2"], "reds": ["red-5-case"]})
    for time, identifier, reason in (("00:10", "red-2", "absent"), ("00:11", "red-3", "cleared"),
                                      ("00:12", "red-4", "absent"), ("00:20", "red-5", "recovered"),
                                      ("00:30", "red-old", "recovered"), ("00:30", "red-1", "recovered")):
        events.append({"ts": ts(time), "ev": "red.closed", "red": identifier, "reason": reason})
    events.extend([
        {"ts": ts("00:01"), "ev": "queue.rejected", "queue_ts": ts("00:01"),
         "branch": "hand/open", "tip": "open-tip"},
        {"ts": ts("00:02"), "ev": "queue.rejected", "queue_ts": ts("00:02"),
         "branch": "hand/landed", "tip": "landed-tip"},
        {"ts": ts("00:10"), "ev": "queue.landed", "branch": "hand/landed"},
        {"ts": ts("00:03"), "ev": "branch.rejected", "task": "demo/a"},
        {"ts": ts("01:00"), "ev": "queue.rejected", "queue_ts": ts("01:00"),
         "branch": "hand/future", "tip": "future-tip"},
        {"ts": ts("01:00"), "ev": "queue.landed", "branch": "hand/open"},
        {"ts": ts("01:00"), "ev": "red.closed", "red": "red-6", "reason": "cleared"},
    ])
    return Sources(sorted(events, key=lambda event: event["ts"]), [], {})


def metric_sources():
    events = [ready("23:50", "waiting", "waiting-tip", ts=ts("23:50", "2026-10-28")),
              ready("00:00", "a", "a-tip"), ready("00:00", "b", "b-tip"),
              ready("00:00", "x", "x-tip"), ready("00:05", "p", "p-tip"),
              ready("00:20", "x", "new-x-tip"), ready("01:00", "at-end", "at-end-tip")]
    queue = [
        rejected("23:56", "p", "old-p", ts=ts("23:56", "2026-10-28")),
        rejected("23:57", "a", "old-a", ts=ts("23:57", "2026-10-28")),
        rejected("23:59", "a", "a-tip", ts=ts("23:59", "2026-10-28")),
        batch("00:01", ["a", "b"], "red", ["fmt:0:6", "build:1:54"]),
        batch("00:02", ["a"], steps=[f"build:{NO_TESTS}:30", "default:0:30"]),
        landed("00:03", "a", "a-tip"),
        batch("00:03", ["b"], "red", ["build:1:60"]),
        rejected("00:04", "b", "b-tip"),
        batch("00:04", ["x"], "conflict"),
        rejected("00:05", "x", "x-tip", "merge"),
        batch("00:05", ["c"], "error", ["fmt:0:60"], error="push failed"),
        batch("00:06", [], "error", error="fetch failed"),
        landed("00:10", "p", "p-tip"),
        landed("01:00", "outside", "outside-tip"),
        landed("02:00", "b", "b-tip"),
        landed("02:01", "x", "new-x-tip"),
        rejected("02:02", "p", "p-tip"),
    ]
    heavy = {"gate": [{"ts": START, "ev": "heavy", "lane_wait": 120.0, "disk_wait": 60.0},
                      {"ts": END, "ev": "heavy", "lane_wait": 600.0, "disk_wait": 600.0},
                      {"ts": START, "ev": "note", "lane_wait": 600.0, "disk_wait": 600.0}],
             "builder": [{"ts": START, "ev": "heavy", "lane_wait": 600.0, "disk_wait": 600.0}]}
    hosts = {"gate": Host("gate", "fake@gate", ("gate", "builder")),
             "builder": Host("builder", "fake@builder", ("builder",)),
             "missing": Host("missing", "fake@missing", ("gate",))}
    return Sources(events, queue, heavy), hosts


class LandingReportTest(unittest.TestCase):
    def test_landing_report_steps_parse_from_the_right_and_use_gate_verdicts(self):
        record = batch("00:00", ["a"], steps=[
            "tools:python:0:1.25", "bad", "fmt:no:2", "fmt:0:bad", None, 5,
            f"build:{NO_TESTS}:2", f"clippy:{NO_TESTS}:3",
            f"default:{NO_TESTS}:4", f"fuzzy:{NO_TESTS}:5", "build:124:6",
        ])
        self.assertEqual(landing.steps(record), [
            landing.StepRun("tools:python", 0, 1.25, True),
            landing.StepRun("build", NO_TESTS, 2.0, True),
            landing.StepRun("clippy", NO_TESTS, 3.0, False),
            landing.StepRun("default", NO_TESTS, 4.0, True),
            landing.StepRun("fuzzy", NO_TESTS, 5.0, True),
            landing.StepRun("build", 124, 6.0, False),
        ])
        self.assertEqual(landing.busy_seconds(record), 21.25)
        self.assertEqual(landing.steps({}), [])
        self.assertEqual(landing.busy_seconds({}), 0.0)
        self.assertIsInstance(landing.busy_seconds({}), float)

    def test_landing_report_latencies_join_tip_and_latest_ready_before_landing(self):
        events = [ready("23:50", "a", "a1", ts=ts("23:50", "2026-10-28")),
                  ready("00:02", "a", "a1"), ready("00:05", "a", "a2"),
                  ready("00:06", "a", "a1"), ready("00:30", "a", "a1"),
                  ready("00:01", "other", "shared"), ready("00:05", "equal", "e")]
        queue = [landed("00:10", "a", "a1"), landed("00:10", "a", "a2"),
                 landed("00:10", "manual", "shared"), landed("00:05", "equal", "e"),
                 landed("01:00", "a", "a1"),
                 landed("23:55", "a", "a1", ts=ts("23:55", "2026-10-28")),
                 rejected("00:11", "a", "a1")]
        self.assertEqual(landing.latencies(events, queue, WINDOW), [4.0, 5.0, 0.0])
        self.assertEqual(landing.latencies([], queue, WINDOW), [])

    def test_landing_report_waiting_excludes_resolved_tips_and_uses_latest_ready(self):
        events = [ready("00:00", "landed", "l1"), ready("00:00", "rejected", "r1"),
                  ready("00:01", "repaired", "r1"), ready("00:20", "repaired", "r2"),
                  ready("00:25", "repaired", "r2"),
                  ready("23:50", "old", "o1", ts=ts("23:50", "2026-10-28")),
                  ready("00:30", "future-landing", "f1"), ready("01:00", "edge", "e1")]
        queue = [landed("00:05", "landed", "l1"), rejected("00:10", "rejected", "r1"),
                 rejected("00:10", "repaired", "r1"), landed("01:00", "future-landing", "f1")]
        self.assertEqual(landing.waiting(events, queue, WINDOW), [
            landing.Wait("old", "o1", ts("23:50", "2026-10-28"), 70.0),
            landing.Wait("repaired", "r2", ts("00:25"), 35.0),
            landing.Wait("future-landing", "f1", ts("00:30"), 30.0),
        ])
        self.assertEqual(landing.waiting([], queue, WINDOW), [])

    def test_landing_report_bisections_keep_halves_and_quarters_in_one_root(self):
        queue = [batch("00:00", ["a", "b", "c", "d"], "red", ["build:1:600"]),
                 batch("00:01", ["a", "b"], "red", ["build:1:60"]),
                 rejected("00:01", "a", "a1"),
                 batch("00:02", ["a"], "red", ["build:1:30"]),
                 batch("00:03", ["b"], steps=["build:0:90"]),
                 batch("00:04", ["c", "d"], steps=["build:0:120"]),
                 batch("00:05", ["e", "f"], "red", ["build:1:900"]),
                 batch("00:06", ["e"], steps=["build:0:60"]),
                 batch("00:07", ["f"], "red", ["build:1:60"]),
                 batch("00:08", [], "error"),
                 batch("00:09", ["e"], steps=["build:0:600"]),
                 batch("01:00", ["e", "f"], "red")]
        self.assertEqual(landing.bisections(list(reversed(queue)), WINDOW), [
            landing.Bisection(ts("00:00"), 4, 4, 5.0),
            landing.Bisection(ts("00:05"), 2, 2, 2.0),
        ])

    def test_landing_report_bisection_closes_at_window_end(self):
        queue = [batch("00:00", ["a", "b"], "red")]
        self.assertEqual(landing.bisections(queue, WINDOW),
                         [landing.Bisection(START, 2, 0, 0.0)])
        self.assertEqual(landing.bisections([batch("00:00", ["a"], "red")], WINDOW), [])

    def test_landing_report_step_rows_count_failures_timeouts_and_nearest_ranks(self):
        queue = [batch("00:00", ["a"], steps=["fmt:0:1.26", "build:1:20.25"]),
                 batch("00:01", ["b"], steps=["fmt:0:1.24", f"build:{NO_TESTS}:30.26"]),
                 batch("00:02", ["c"], steps=["fmt:124:9.99", "build:124:40.26"]),
                 batch("00:03", ["d"], steps=[f"clippy:{NO_TESTS}:2.26", "broken"]),
                 batch("01:00", ["e"], steps=["fmt:1:1000"])]
        self.assertEqual(landing.step_rows(queue, WINDOW), [
            ("fmt", 3, 1, 1, 1.3, 10.0, 10.0),
            ("build", 3, 2, 1, 30.3, 40.3, 40.3),
            ("clippy", 1, 1, 0, 2.3, 2.3, 2.3),
        ])
        self.assertEqual(landing.step_rows([], WINDOW), [])

    def test_landing_report_figures_compute_every_metric_once(self):
        sources, hosts = metric_sources()
        with (patch.object(landing, "latencies", wraps=landing.latencies) as latency,
              patch.object(landing, "waiting", wraps=landing.waiting) as waits,
              patch.object(landing, "bisections", wraps=landing.bisections) as splits,
              patch.object(landing, "heavy_waits", wraps=landing.heavy_waits) as heavy):
            actual = landing.figures(sources, hosts, WINDOW)
        latency.assert_called_once_with(sources.log, sources.queue, WINDOW)
        waits.assert_called_once_with(sources.log, sources.queue, WINDOW)
        splits.assert_called_once_with(sources.queue, WINDOW)
        heavy.assert_called_once()
        self.assertEqual(actual, {
            "batches": 5, "batches_per_hour": 5.0, "branches_per_batch": 1.2,
            "utilisation": 240 / 3600 * 100,
            "green": 1, "red": 2, "conflict": 1, "error": 2, "red_share": 40.0,
            "landed": 2, "rejected": 2, "collateral": 1, "false_red_rate": 50.0,
            "retried": 0, "reused": 0,
            "latency_median": 3.0, "latency_p90": 5.0, "waiting": 2, "oldest_wait": 70.0,
            "bisections": 1, "bisection_runs": 2, "bisection_minutes": 2.0,
            "repair_rounds": 1.5, "repair_minutes": 4.0, "lane_wait": 2.0, "disk_wait": 1.0,
            "reds_opened": 0, "reds_foreman": 0, "reds_page": 0, "reds_fix": 0, "reds_none": 0,
            "reds_left": 0, "red_repairs_landed": 0, "reds_closed": 0, "reds_closed_recovered": 0,
            "reds_closed_absent": 0, "reds_closed_cleared": 0, "red_recovery_hours": None,
            "hand_rejected": 0,
        })
        self.assertEqual(set(actual), {key for key, _ in landing.FIGURES})
        counts = {"batches", "green", "red", "conflict", "error", "landed", "rejected",
                  "collateral", "retried", "reused", "waiting", "bisections", "bisection_runs"}
        counts |= RED_COUNTS
        for key, value in actual.items():
            with self.subTest(key=key):
                if key == "red_recovery_hours":
                    self.assertIsNone(value)
                else:
                    self.assertIs(type(value), int if key in counts else float)

    def test_landing_report_figures_on_empty_and_zero_length_windows(self):
        sources = Sources([], [], {})
        empty = landing.figures(sources, {}, WINDOW)
        counts = {"batches", "green", "red", "conflict", "error", "landed", "rejected",
                  "collateral", "retried", "reused", "waiting", "bisections", "bisection_runs"}
        absent = {"branches_per_batch", "red_share", "false_red_rate", "latency_median",
                  "latency_p90", "oldest_wait", "repair_rounds", "repair_minutes", "red_recovery_hours"}
        counts |= RED_COUNTS
        for key, _ in landing.FIGURES:
            with self.subTest(key=key):
                if key in absent:
                    self.assertIsNone(empty[key])
                else:
                    self.assertEqual(empty[key], 0)
                    self.assertIs(type(empty[key]), int if key in counts else float)
        self.assertEqual(landing.figures(sources, {}, Window(START, START)), empty)

    def test_landing_report_counts_red_routes_settlements_repairs_and_closures_from_log(self):
        sources = red_sources()
        actual = landing.figures(sources, {}, WINDOW)
        self.assertEqual({key: actual[key] for key in RED_COUNTS | {"red_recovery_hours"}}, {
            "reds_opened": 6, "reds_foreman": 4, "reds_page": 4,
            "reds_fix": 2, "reds_none": 1, "reds_left": 1,
            "red_repairs_landed": 3, "reds_closed": 6, "reds_closed_recovered": 3,
            "reds_closed_absent": 2, "reds_closed_cleared": 1, "red_recovery_hours": 0.5,
            "hand_rejected": 2,
        })
        previous = landing.figures(sources, {}, WINDOW.previous())
        self.assertEqual({key: previous[key] for key in RED_COUNTS if previous[key]},
                         {"reds_opened": 1, "reds_foreman": 1, "reds_fix": 1})
        self.assertIsNone(previous["red_recovery_hours"])
        with tmp_home():
            rendered = landing.render(sources, {}, WINDOW)
        for label, value in (("after-landing reds opened", "6"),
                             ("after-landing reds sent to a foreman", "4"),
                             ("after-landing reds sent to the page", "4"),
                             ("red repairs landed", "3"),
                             ("after-landing reds closed recovered", "3"),
                             ("hours opened to recovered, median", "0.5"),
                             ("hand-pushed rejections", "2")):
            with self.subTest(label=label):
                self.assertIn(f"| {label} | {value} (prev ", rendered)

    def test_landing_report_counts_queue_decisions_on_the_day_they_happened(self):
        yesterday = "2026-10-28"
        today = "2026-10-29"
        tomorrow = "2026-10-30"
        events = []
        for identifier in ("red-1", "red-2", "red-3"):
            events += red_decisions("22:00", identifier, "fix", ts=ts("22:00", yesterday))
        for identifier, imported, occurred in (
                ("red-1", ts("00:01", today), ts("23:59", yesterday)),
                ("red-2", ts("00:01", tomorrow), ts("23:59", today)),
                ("red-3", ts("00:00", today), None)):
            fields = {"queue_ts": occurred} if occurred is not None else {}
            events += [
                {"ev": "branch.landed", "ts": imported, "task": f"demo/{identifier}", **fields},
                {"ev": "queue.rejected", "ts": imported, "branch": f"hand/{identifier}", **fields},
            ]
        sources = Sources(events, [], {})
        for day, end, count in ((yesterday, today, 1), (today, tomorrow, 2),
                                (tomorrow, "2026-10-31", 0)):
            with self.subTest(day=day):
                actual = landing.figures(sources, {}, Window(ts("00:00", day), ts("00:00", end)))
                self.assertEqual((actual["hand_rejected"], actual["red_repairs_landed"]), (count, count))

    def test_landing_report_counts_all_signal_routes_by_transition_even_after_closing(self):
        yesterday = "2026-10-28"
        events = [red_opened("22:00", "red-1", route="signal", ts=ts("22:00", yesterday))]
        events += red_decisions("23:00", "red-2", "left", ts=ts("23:00", yesterday))
        events[-1]["ts"] = ts("00:01")
        events += red_decisions("23:00", "red-3", "fix", ts=ts("23:00", yesterday))
        events += [
            {"ts": ts("23:30", yesterday), "ev": "branch.landed", "task": "demo/red-3"},
            {"ts": ts("00:02"), "ev": "tiers.run", "tip": "unfixed", "faults": [],
             "branches": ["demo/red-3-r2"], "reds": ["red-3-case"]},
        ]
        for identifier in ("red-1", "red-2", "red-3"):
            events.append({"ts": ts("00:30"), "ev": "red.closed", "red": identifier, "reason": "cleared"})
        sources = Sources(sorted(events, key=lambda event: event["ts"]), [], {})
        previous = landing.figures(sources, {}, Window(ts("00:00", yesterday), START))
        current = landing.figures(sources, {}, WINDOW)
        self.assertEqual((previous["reds_page"], current["reds_page"]), (1, 2))
        self.assertEqual(current["reds_closed_cleared"], 3)

    def test_landing_report_signals_show_ownerless_reds_and_rejections_at_window_end(self):
        with tmp_home():
            rendered = landing.render(red_sources(), {}, WINDOW)
        signals = rendered.split("## Signals\n", 1)[1].split("\n\n", 1)[0]
        self.assertIn("**after-landing red red-6 has no owner fab knows:** "
                      "a confirmed red goes to its owner with its evidence; "
                      "see the user's page red-6 (the branch's owner)", signals)
        self.assertIn("**hand-pushed rejection hand/open has no owner fab knows:** "
                      "the precheck learns it (a tool check), not a role's text (a rule); "
                      "see the user's page queue:hand/open (ops)", signals)
        for absent in ("red-1 ", "red-2 ", "red-3 ", "red-4 ", "red-5 ", "red-future", "hand/landed", "hand/future"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, signals)

    def test_landing_report_hand_clears_hide_red_and_queue_signals_before_tick(self):
        events = [red_opened("00:00", "red-1", route="signal"),
                  {"ts": ts("00:01"), "ev": "queue.rejected", "queue_ts": ts("00:01"),
                   "branch": "hand/pushed", "tip": "tip"},
                  {"ts": ts("00:02"), "ev": "signal.cleared", "signal": "red-1"},
                  {"ts": ts("00:03"), "ev": "signal.cleared", "signal": "queue:hand/pushed"},
                  {"ts": ts("00:04"), "ev": "tiers.run", "faults": ["live-temper: exit 4"]}]
        with tmp_home():
            rendered = landing.render(Sources(events, [], {}), {}, WINDOW)
        self.assertIn("## Signals\n- none\n\n", rendered)
        actual = landing.figures(Sources(events, [], {}), {}, WINDOW)
        self.assertEqual((actual["reds_page"], actual["hand_rejected"], actual["reds_closed"]), (1, 1, 0))

    def test_landing_report_counts_unfixed_route_when_opened_and_landed_before_window(self):
        events = red_decisions("23:00", "red-1", "fix", ts=ts("23:00", "2026-10-28"))
        events += [
            {"ts": ts("23:30", "2026-10-28"), "ev": "branch.landed", "task": "demo/red-1"},
            {"ts": ts("23:45", "2026-10-28"), "ev": "tiers.run", "tip": "cover", "faults": [],
             "branches": ["demo/red-1-r2"], "reds": [], "starved": 1},
            {"ts": ts("00:00"), "ev": "tiers.run", "tip": "faulted", "faults": ["p: exit 4"],
             "reds": ["red-1-case"]},
            {"ts": ts("00:10"), "ev": "tiers.run", "tip": "unfixed", "faults": [], "reds": ["red-1-case"]},
            {"ts": ts("00:20"), "ev": "tiers.run", "tip": "standing", "faults": [], "reds": ["red-1-case"]},
            {"ts": ts("00:30"), "ev": "red.closed", "red": "red-1", "reason": "cleared"},
        ]
        actual = landing.figures(Sources(events, [], {}), {}, WINDOW)
        self.assertEqual((actual["reds_opened"], actual["reds_foreman"], actual["red_repairs_landed"]), (0, 0, 0))
        self.assertEqual((actual["reds_page"], actual["reds_closed_cleared"]), (1, 1))

    def test_landing_report_collateral_requires_a_later_landing_of_the_same_tip(self):
        sources = Sources([], [landed("00:01", "a", "a1"), rejected("00:02", "a", "a1"),
                               rejected("00:02", "b", "b1"), landed("02:00", "b", "b2"),
                               rejected("00:03", "c", "shared"),
                               landed("02:00", "other", "shared")], {})
        figures = landing.figures(sources, {}, WINDOW)
        self.assertEqual(figures["collateral"], 0)
        self.assertEqual(figures["false_red_rate"], 0.0)
        self.assertEqual(figures["repair_rounds"], 0.0)
        self.assertIsNone(figures["repair_minutes"])

    def test_landing_report_counts_collateral_records_and_green_receipt_batches_in_window(self):
        queue = [batch("23:59", ["old"], receipt="old", ts=ts("23:59", "2026-10-28")),
                 batch("00:01", ["a", "b"], "collateral"),
                 {"ts": ts("00:01"), "ev": "collateral", "branch": "a", "tip": "a1"},
                 {"ts": ts("00:01"), "ev": "collateral", "branch": "b", "tip": "b1"},
                 batch("00:02", ["a"], receipt="receipt-a"),
                 batch("00:03", ["b"], "red", receipt="receipt-b"),
                 batch("00:04", ["c"], "error", receipt="receipt-c"),
                 batch("00:05", ["d"], "conflict", receipt="receipt-d"),
                 batch("00:06", ["e"]),
                 batch("01:00", ["later"], receipt="later"),
                 {"ts": ts("01:00"), "ev": "collateral", "branch": "later", "tip": "later"}]
        figures = landing.figures(Sources([], queue, {}), {}, WINDOW)
        self.assertEqual((figures["retried"], figures["reused"]), (2, 1))
        self.assertEqual([figures[key] for key in ("batches", "green", "red", "conflict", "error")],
                         [6, 2, 1, 1, 1])
        self.assertEqual(figures["collateral"], 0)
        self.assertEqual(landing.bisections(queue, WINDOW), [])
        keys = [key for key, _ in landing.FIGURES]
        start = keys.index("false_red_rate")
        self.assertEqual(keys[start:start + 3], ["false_red_rate", "retried", "reused"])

    def test_landing_report_retried_signal_absent_at_zero(self):
        self.assertEqual(landing.signals({"retried": 0}, {}, []), [])

    def test_landing_report_signals_in_order_with_actions_and_owners(self):
        current = {"collateral": 2, "retried": 4, "error": 3, "oldest_wait": 90.0, "disk_wait": 1.25}
        self.assertEqual(landing.signals(current, {"oldest_wait": 61.0}, ["queue: offline", "heavy: offline"]), [
            Signal("2 rejections later landed unchanged",
                   "the red's cause found and ledgered; a flake goes to its owner", "ops, the test's owner"),
            Signal("4 branches retried after a collateral red", "a flake goes to its owner", "ops, the test's owner"),
            Signal("3 batches in error", "restart through the tool; the cause ledgered with a remedy in the tool", "ops"),
            Signal("oldest ready wait 90.0 minutes (prev 61.0)", "look for a stuck batch; else capacity", "ops"),
            Signal("1.2 minutes of disk waits at the gate", "the gate's disk: its target, its headroom", "ops"),
            Signal("unread: queue: offline", "the report is partial: the machine's ssh and fab install", "ops"),
            Signal("unread: heavy: offline", "the report is partial: the machine's ssh and fab install", "ops"),
        ])

    def test_landing_report_signals_for_quiet_or_steady_days(self):
        self.assertEqual(landing.signals({}, {}, []), [])
        self.assertEqual(landing.signals({key: None for key, _ in landing.FIGURES}, {}, []), [])
        for oldest, before in ((60.0, 0), (90.0, 90.0), (90.0, 100.0)):
            with self.subTest(oldest=oldest, before=before):
                self.assertEqual(landing.signals({"oldest_wait": oldest}, {"oldest_wait": before}, []), [])
        self.assertEqual(landing.signals({"oldest_wait": 61.0}, {"oldest_wait": None}, []),
                         [Signal("oldest ready wait 61.0 minutes (prev 0)",
                                 "look for a stuck batch; else capacity", "ops")])

    def test_landing_report_render_sections_tables_and_error_first_line(self):
        sources, hosts = metric_sources()
        sources.unread = ["queue: unavailable"]
        sources.log.append(ready("00:40", "long-tip", "0123456789abcdef"))
        sources.queue.extend([
            rejected("00:07", "d", "d1", "clippy"), rejected("00:08", "e", "e1", "clippy"),
            batch("00:11", [], "error", error="first line\r\nsecond line"),
            batch("00:12", [], "error", error="x" * 121 + "\nhidden"),
            batch("01:00", [], "error", error="outside-window"),
        ])
        result = landing.render(sources, hosts, WINDOW)
        self.assertEqual([line for line in result.splitlines() if line.startswith("#")], [
            "# Landing report, 2026-10-29", "## Figures", "## Signals", "## Red classes",
            "## Steps", "## Waiting", "## Bisections", "## Errors",
        ])
        self.assertIn(f"{START} to {END}; each figure beside the previous window's.", result)
        self.assertIn("| batches | 5 (prev 0) |", result)
        self.assertIn("| branches rejected | 4 (prev 3) |", result)
        self.assertIn("unread: queue: unavailable", result)
        self.assertIn("| clippy | 2 |\n| build | 1 |\n| merge | 1 |", result)
        self.assertIn("| build | 3 | 2 | 0 | 54.0 | 60.0 | 60.0 |", result)
        self.assertIn(f"| long-tip | 0123456789ab | {ts('00:40')} | 20.0 |", result)
        self.assertIn(f"| {ts('00:01')} | 2 | 2 | 2.0 |", result)
        self.assertIn(f"| {ts('00:11')} | first line |", result)
        self.assertIn(f"| {ts('00:12')} | {'x' * 120} |", result)
        for absent in ("second line", "hidden", "outside-window", "x" * 121, "0123456789abcdef"):
            self.assertNotIn(absent, result)
        self.assertNotIn("\n\n\n", result)
        for section in ("Figures", "Signals", "Red classes", "Steps", "Waiting", "Bisections", "Errors"):
            self.assertIn(f"\n\n## {section}\n", result)
        self.assertTrue(result.endswith("\n"))
        self.assertFalse(result.endswith("\n\n"))

    def test_landing_report_render_empty_sections(self):
        result = landing.render(Sources([], [], {}), {}, WINDOW)
        self.assertIn("## Signals\n- none\n\n", result)
        self.assertIn("## Errors\n| Start | Error |\n| --- | --- |\n", result)
