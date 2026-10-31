import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fab import code_report as code
from fab import atomic, hosts, report
from fab.heavy import EX_TEMPFAIL
from fab.plan import Part, Plan, Task
from fab.sh import Result
from fab.tests.support import FakeRunner, tmp_home


def ts(clock, day="2026-10-29"):
    return f"{day}T{clock}:00.000Z"


def event(clock, ev, task="demo/a", *, day="2026-10-29", **fields):
    return {"ts": ts(clock, day), "ev": ev,
            **({"task": task} if task is not None else {}), **fields}


def landed(clock, task="demo/a"):
    return event(clock, "branch.landed", task, tip="tip", main="main")


def fixture():
    parts = {name: Part(name, name.title(), "feature", (), "docs/design/fab.md, 10")
             for name in ("core", "ui", "empty")}
    plan = Plan("demo", "agents", (), 1.0, 2.0, parts, ())
    tasks = {f"demo/{name}": Task(f"demo/{name}", part, "feature", "agents", needs,
                                (), "high", 25, "", f"tasks/{name}.md")
             for name, part, needs in (("a", "core", ()), ("b", "core", ("demo/a",)),
                                       ("c", "ui", ()))}
    machines = hosts.parse('''
[one]
ssh = "one@fake"
roles = ["builder"]
places = 4
[two]
ssh = "two@fake"
roles = ["builder", "dispatcher"]
places = 3
[gate]
ssh = "gate@fake"
roles = ["gate"]
places = 99
''')
    return plan, tasks, machines


def metric_log():
    records = [
        event("00:00", "run.started", run="a-1", kind="implement"),
        event("00:10", "run.ended", run="a-1", outcome="failed", minutes=10, report="a.md"),
        event("00:20", "question.asked", "demo/b", text="Earlier question"),
        event("00:30", "run.started", run="a-2", kind="repair"),
        event("01:00", "run.ended", run="a-2", outcome="question", minutes=30),
        event("01:00", "question.asked", text="Choose"),
        event("01:05", "question.asked", text="Choose again"),
        event("01:10", "question.answered", "demo/b"),
        event("01:15", "question.answered"),
        event("01:20", "run.started", run="a-3", kind="repair"),
        event("01:30", "run.ended", run="a-3", outcome="infra", minutes=10),
        event("01:40", "run.started", run="a-4", kind="repair"),
        event("02:00", "run.ended", run="a-4", outcome="done", minutes=20),
        event("02:05", "branch.ready", tip="tip"),
        event("02:10", "branch.rejected", step="test"),
        landed("02:20"),
        event("02:25", "run.started", "demo/b", run="b-1", kind="implement"),
        event("02:45", "run.ended", "demo/b", run="b-1", outcome="failed", minutes=20,
              report="b.md"),
        event("02:50", "question.asked", "demo/b", text="Still waiting"),
        event("03:00", "run.started", "demo/c", run="c-1", kind="implement"),
        event("04:00", "question.answered", "demo/b"),
        event("04:00", "branch.ready", "demo/c", tip="late"),
        event("01:10", "call.ended", None, subject="demo", minutes=2, tokens="10/3/4"),
        event("01:20", "call.ended", None, subject="demo/core", minutes=3, tokens="5/7/9"),
        event("01:30", "call.ended", None, subject="demo/ui", minutes=4, tokens="bad"),
        event("01:40", "call.ended", None, subject="demo/missing", minutes=100, tokens="90/90/90"),
        event("01:40", "call.ended", None, subject="elsewhere", minutes=100, tokens="90/90/90"),
        event("04:00", "call.ended", None, subject="demo", minutes=100, tokens="90/90/90"),
        event("01:20", "run.started", "demo-other/a", run="other", kind="implement"),
        event("01:30", "run.ended", "demo-other/a", run="other", outcome="infra", minutes=100),
        event("01:25", "question.asked", "demo-other/a", text="Other draft"),
    ]
    return sorted(records, key=lambda record: record["ts"])


class CodeReportTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(tmp_home())
        self.plan, self.tasks, self.hosts = fixture()

    def test_code_spans_pair_first_later_end_in_log_order(self):
        records = [
            event("00:00", "run.ended", run="a-1", outcome="infra"),
            event("00:01", "run.started", run="a-1", kind="implement"),
            event("00:02", "run.started", "other/a", run="other", kind="implement"),
            event("00:03", "run.started", "demo/b", run="b-1", kind="repair"),
            event("00:04", "run.ended", run="a-1", outcome="done"),
            event("00:05", "run.ended", run="a-1", outcome="failed"),
            event("00:06", "run.started", run="a-2", kind="review"),
            event("00:07", "run.ended", run="a-2", outcome="question"),
        ]
        self.assertEqual(code.spans("demo", records), [
            code.Span("a-1", "demo/a", "implement", ts("00:01"), ts("00:04"), "done"),
            code.Span("b-1", "demo/b", "repair", ts("00:03"), None, None),
            code.Span("a-2", "demo/a", "review", ts("00:06"), ts("00:07"), "question"),
        ])
        self.assertEqual(code.spans("missing", records), [])

    def test_code_peak_overlap_boundaries_and_inflight(self):
        def span(start, end):
            return code.Span("run", "demo/a", "implement", ts(start), ts(end) if end else None, None)

        runs = [span("00:00", "01:00"), span("00:30", "02:00"), span("01:00", "01:30"),
                span("01:30", None), span("03:00", "04:00"), span("01:15", "01:15")]
        self.assertEqual(code.peak(runs, ts("01:00"), ts("02:00")), 2)
        self.assertEqual(code.peak(runs[:1] + runs[2:3], ts("00:00"), ts("02:00")), 1)
        self.assertEqual(code.peak(runs, ts("02:00"), ts("03:00")), 1)
        self.assertEqual(code.peak(runs[:1] + runs[4:5], ts("01:00"), ts("03:00")), 0)
        self.assertEqual(code.peak(runs, ts("01:00"), ts("01:00")), 0)
        self.assertEqual(code.peak([], ts("01:00"), ts("02:00")), 0)

    def test_code_hourly_three_hours_last_cut(self):
        records = [event("00:00", "run.started", run="a", kind="implement"),
                   event("01:00", "run.ended", run="a", outcome="done"),
                   event("01:00", "run.started", "demo/b", run="b", kind="repair"),
                   event("01:20", "branch.ready", tip="tip"), landed("02:15"),
                   landed("02:30", "demo/b"), event("02:10", "branch.ready", "other/a")]
        self.assertEqual(code.hourly("demo", records, report.Window(ts("00:00"), ts("02:30"))), [
            code.Hour(ts("00:00"), 1, 1, 0, 0), code.Hour(ts("01:00"), 1, 1, 1, 0),
            code.Hour(ts("02:00"), 1, 0, 0, 1),
        ])

    def test_code_hourly_empty_and_midnight(self):
        end = ts("00:00", "2026-10-30")
        self.assertEqual(code.hourly("demo", [], report.Window(ts("23:00"), end)),
                         [code.Hour(ts("23:00"), 0, 0, 0, 0)])
        self.assertEqual(code.hourly("demo", [], report.Window(end, end)), [])

    def test_code_gaps_long_short_open_and_causes(self):
        records = [event("23:50", "question.asked", text="A?", day="2026-10-28"),
                   event("23:51", "question.asked", "demo/b", text="B?", day="2026-10-28"),
                   event("00:20", "run.started", run="a", kind="implement"),
                   event("00:35", "run.ended", run="a", outcome="done"),
                   event("00:39", "run.started", run="a2", kind="repair"),
                   event("01:00", "run.ended", run="a2", outcome="done")]
        self.assertEqual(code.gaps(self.plan, self.tasks, records,
                                   report.Window(ts("00:00"), ts("01:15"))), [
            code.Gap(ts("00:00"), 20.0, "parked 2, runnable 1"),
            code.Gap(ts("01:00"), 15.0, "parked 1, runnable 1, running 1"),
        ])

    def test_code_gaps_merge_overlaps_and_touching_runs(self):
        records = [event("00:00", "run.started", run="a", kind="implement"),
                   event("00:10", "run.started", "demo/b", run="b", kind="implement"),
                   event("00:20", "run.ended", run="a", outcome="done"),
                   event("00:30", "run.ended", "demo/b", run="b", outcome="done"),
                   event("00:30", "run.started", run="a2", kind="review")]
        self.assertEqual(code.gaps(self.plan, self.tasks, records,
                                   report.Window(ts("00:05"), ts("01:00"))), [])

    def test_code_gaps_zero_duration_run_does_not_split_idle(self):
        records = [event("00:20", "run.started", run="a", kind="implement"),
                   event("00:20", "run.ended", run="a", outcome="done")]
        self.assertEqual(code.gaps(self.plan, self.tasks, records,
                                   report.Window(ts("00:00"), ts("01:00"))),
                         [code.Gap(ts("00:00"), 60.0, "runnable 2, waiting 1")])

    def test_code_gaps_none_when_all_landed_or_no_tasks(self):
        records = [landed("00:00", task) for task in self.tasks]
        window = report.Window(ts("00:01"), ts("01:00"))
        self.assertEqual(code.gaps(self.plan, self.tasks, records, window), [])
        self.assertEqual(code.gaps(self.plan, {}, [], window), [])

    def test_code_stops_all_kinds_open_closed_and_ranked(self):
        records = [
            event("00:10", "question.asked", text="x" * 90 + "\nignored"),
            event("00:20", "question.asked", "demo/b", text="Open question"),
            event("00:30", "run.ended", run="a", outcome="failed", report="a.md"),
            event("00:40", "question.answered"),
            event("00:40", "run.ended", "demo/c", run="c", outcome="failed", report="c.md"),
            event("00:45", "run.ended", "demo/d", run="d", outcome="infra", minutes=12.125),
            event("00:50", "run.started", run="a2", kind="repair"),
            event("00:55", "branch.rejected", step="test"),
            event("01:00", "branch.rejected", "demo/c", step="merge"),
            landed("01:10"),
            event("01:15", "question.asked", "other/a", text="Ignored"),
            event("02:00", "question.answered", "demo/b"),
            landed("02:00", "demo/c"),
            event("02:01", "run.started", "demo/c", run="c2", kind="repair"),
        ]
        self.assertEqual(code.stops("demo", records, report.Window(ts("00:00"), ts("02:00"))), [
            code.Stop("question", "demo/b", ts("00:20"), 100.0, True, "Open question"),
            code.Stop("failed", "demo/c", ts("00:40"), 80.0, True, "c.md"),
            code.Stop("rejected", "demo/c", ts("01:00"), 60.0, True, "merge"),
            code.Stop("question", "demo/a", ts("00:10"), 30.0, False, "x" * 80),
            code.Stop("failed", "demo/a", ts("00:30"), 20.0, False, "a.md"),
            code.Stop("rejected", "demo/a", ts("00:55"), 15.0, False, "test"),
            code.Stop("infra", "demo/d", ts("00:45"), 12.125, False, "d"),
        ])

    def test_code_stops_top_limit_ties_and_window_start(self):
        records = [event(f"00:{minute:02}", "run.ended", run=f"a-{minute}", outcome="infra",
                         minutes=5) for minute in range(code.TOP_STOPS + 2)]
        records.reverse()
        result = code.stops("demo", records, report.Window(ts("00:00"), ts("01:00")))
        self.assertEqual(len(result), code.TOP_STOPS)
        self.assertEqual([stop.start for stop in result],
                         [ts(f"00:{minute:02}") for minute in range(code.TOP_STOPS)])
        self.assertEqual(code.stops("demo", records, report.Window(ts("01:00"), ts("02:00"))), [])

    def test_code_figures_every_key_and_its_value(self):
        heavy = {
            "one": [event("01:00", "heavy", None, lane_wait=30, disk_wait=60, code=EX_TEMPFAIL),
                    event("04:00", "heavy", None, lane_wait=999, disk_wait=999, code=EX_TEMPFAIL)],
            "two": [event("02:00", "heavy", None, lane_wait=90, disk_wait=120, code=0)],
            "gate": [event("02:00", "heavy", None, lane_wait=999, disk_wait=999, code=EX_TEMPFAIL)],
        }
        result = code.figures(self.plan, self.tasks, metric_log(), heavy, self.hosts,
                              report.Window(ts("01:00"), ts("04:00")))
        expected = {
            "runs": 4, "done": 1, "question": 1, "infra": 1, "failed": 1,
            "ready": 1, "landed": 1, "rejected": 1, "peak": 1, "places": 7,
            "codex_minutes": 80.0, "runs_per_task": 4.0, "minutes_per_task": 70.0,
            "questions": 3, "question_rate": 0.75, "answer_median": 10.0,
            "answer_max": 50.0, "open": 1, "idle_minutes": 70.0, "infra_minutes": 10.0,
            "calls": 4, "call_minutes": 109.0, "input_tokens": 205, "output_tokens": 103,
            "codex_input_tokens": 0, "codex_output_tokens": 0,
            "claude_weight": 630 / 1_000_000, "codex_weight": 0.0, "weight_ratio": None,
            "peak_context": None, "over_target": 0,
            "lane_wait": 2.0, "disk_wait": 3.0, "disk_refused": 1,
        }
        self.assertEqual(set(result), {key for key, label in code.FIGURES})
        self.assertEqual(result, expected)
        for key, value in expected.items():
            with self.subTest(key=key):
                self.assertIs(type(result[key]), type(value))

    def test_code_figures_empty_denominators(self):
        result = code.figures(self.plan, {}, [], {}, self.hosts,
                              report.Window(ts("00:00"), ts("01:00")))
        for key in ("runs_per_task", "minutes_per_task", "question_rate", "answer_median", "answer_max"):
            self.assertIsNone(result[key])
        self.assertEqual(result["idle_minutes"], 0.0)
        self.assertEqual(result["open"], 0)
        self.assertEqual(result["peak"], 0)
        self.assertIs(type(result["codex_minutes"]), float)
        self.assertIs(type(result["call_minutes"]), float)

    def test_code_figures_landed_tasks_are_distinct_and_minutes_unrounded(self):
        records = [event("00:01", "run.started", run="a", kind="implement"),
                   event("00:02", "run.ended", run="a", outcome="done", minutes=1.2345),
                   landed("00:03"), landed("00:04"),
                   event("00:05", "question.answered", "demo/b")]
        result = code.figures(self.plan, self.tasks, records, {}, self.hosts,
                              report.Window(ts("00:00"), ts("01:00")))
        self.assertEqual(result["landed"], 2)
        self.assertEqual(result["runs_per_task"], 1.0)
        self.assertEqual(result["minutes_per_task"], 1.2345)
        self.assertEqual(result["codex_minutes"], 1.2345)
        self.assertIsNone(result["answer_max"])

    def test_code_figures_malformed_tokens_contribute_zero(self):
        for tokens in (None, 42, "1/2", "1/2/3/4", "1/oops/3", ""):
            with self.subTest(tokens=tokens):
                records = [event("00:01", "call.ended", None, subject="demo", minutes=1.2345, tokens=tokens)]
                result = code.figures(self.plan, {}, records, {}, {},
                                      report.Window(ts("00:00"), ts("01:00")))
                self.assertEqual(result["input_tokens"], 0)
                self.assertEqual(result["output_tokens"], 0)
                self.assertEqual(result["call_minutes"], 1.2345)

    def test_code_parts_plan_order_whole_log_landing_and_rounding(self):
        records = metric_log()
        records.append(event("03:15", "run.ended", "demo/c", run="c-1", outcome="done", minutes=1.2345))
        records.append(landed("05:00", "demo/c"))
        records.sort(key=lambda record: record["ts"])
        self.assertEqual(code.parts(self.plan, self.tasks, records,
                                    report.Window(ts("01:00"), ts("04:00"))),
                         [("core", 2, 1, 3, 80.0, 3), ("ui", 1, 1, 1, 1.2, 0)])

    def test_code_signals_order_text_action_and_owner(self):
        result = code.signals({"idle_minutes": 12.25, "rejected": 3, "infra": 2, "disk_refused": 1},
                              {"rejected": 1}, ["heavy one: offline", "queue gate: offline"])
        self.assertEqual(result, [
            report.Signal("12.2 minutes in idle gaps",
                          "its cause: a missing pre-approved list, a parked task, no free place",
                          "the dispatcher's keeper"),
            report.Signal("rejections rising: 3 (prev 1)",
                          "readers' tests before ready; the precheck; the task's scope",
                          "the skeleton author; ops"),
            report.Signal("2 runs ended Infra, 1 builds refused for disk",
                          "capacity: bounded slots, more or bigger builders", "ops"),
            report.Signal("unread: heavy one: offline",
                          "the report is partial: the machine's ssh and fab install", "ops"),
            report.Signal("unread: queue gate: offline",
                          "the report is partial: the machine's ssh and fab install", "ops"),
        ])

    def test_code_signals_quiet_day_none_and_non_rising(self):
        self.assertEqual(code.signals({}, {}, []), [])
        self.assertEqual(code.signals({"idle_minutes": None, "rejected": 2, "infra": None,
                                       "disk_refused": None}, {"rejected": 2}, []), [])
        self.assertEqual(code.signals({"rejected": 1}, {"rejected": 2}, []), [])
        self.assertEqual(len(code.signals({"disk_refused": 1}, {}, [])), 1)
        self.assertEqual(len(code.signals({"rejected": 1}, {"rejected": None}, [])), 1)

    def test_code_render_sections_previous_values_and_first_landing(self):
        sources = report.Sources(metric_log(), [], {}, ["heavy one: offline"])
        rendered = code.render(self.plan, self.tasks, sources, self.hosts,
                               report.Window(ts("01:00"), ts("04:00")))
        self.assertTrue(rendered.startswith("# Code report: demo, 2026-10-29\n"))
        self.assertIn(f"{ts('01:00')} to {ts('04:00')}; each figure beside the previous window's.", rendered)
        self.assertIn(f"First run {ts('00:00')}; first landing {ts('02:20')}, 140.0 minutes later.", rendered)
        self.assertEqual([line for line in rendered.splitlines() if line.startswith("## ")], [
            "## Figures", "## Signals", "## Hours", "## Idle gaps", "## Stops, longest first",
            "## Parts", "## Calls", "## Rejections by step",
        ])
        self.assertIn("| Codex runs started | 4 (prev 2) |", rendered)
        self.assertIn("| 01:00 | 1 | 2 | 0 | 0 |", rendered)
        self.assertIn("| core | 2 | 1 | 3 | 80.0 | 3 |", rendered)
        self.assertIn("| test | 1 |", rendered)
        self.assertIn("unread: heavy one: offline", rendered)
        self.assertTrue(rendered.endswith("\n"))
        self.assertNotIn("\n\n\n", rendered)

    def test_code_render_measured_calls_and_historical_gaps(self):
        records = [event("00:01", "call.started", None, subject="demo/core/decision", call="root"),
                   event("00:02", "run.ended", "root", run="review-1", outcome="done", tokens="1000000/0/0"),
                   event("00:03", "call.ended", None, call="root", role="decision",
                         subject="demo/core/decision", minutes=1.25, turns=2, peak=600001,
                         tokens="1000000/0/0", cache_write=800000),
                   event("00:04", "call.ended", None, call="old", role="answer", subject="demo")]
        window = report.Window(ts("00:00"), ts("01:00"))
        result = code.figures(self.plan, self.tasks, records, {}, self.hosts, window)
        self.assertEqual((result["claude_weight"], result["codex_weight"], result["weight_ratio"]),
                         (2.0, 1.0, 2.0))
        rendered = code.render(self.plan, self.tasks, report.Sources(records, [], {}), self.hosts, window)
        self.assertIn("| Call | Role | Subject | Minutes | Turns | Peak context | Weight (M) | Over target |", rendered)
        self.assertIn("| root | decision | demo/core/decision | 1.2 | 2 | 600001 | 2.0 | yes |", rendered)
        self.assertIn("| old | answer | demo | 0.0 | - | - | - | - |", rendered)

    def test_code_render_hand_totals_and_both_weight_ratios(self):
        home = Path.home()
        atomic.write(home / "fab/hand-sessions", "session demo\n")
        transcript = home / ".claude/projects/project/session.jsonl"
        atomic.write(transcript, '\n'.join([
            '{"type":"assistant","requestId":"one","message":{"usage":{"input_tokens":1000000,"cache_creation_input_tokens":800000}}}',
            '{"type":"assistant","requestId":"one","message":{"usage":{"input_tokens":1000000,"cache_creation_input_tokens":800000}}}',
            '{"type":"assistant","requestId":"two","message":{"usage":{"input_tokens":1000000}}}']))
        atomic.write(transcript.parent / "session/subagents/agent.jsonl",
                     '{"type":"assistant","requestId":"three","message":{"usage":{"input_tokens":1000000}}}\n')
        records = [event("00:01", "call.ended", None, subject="demo", tokens="2000000/0/0"),
                   event("00:02", "run.ended", run="run", tokens="1000000/0/0")]
        window = report.Window(ts("00:00"), ts("01:00"))
        rendered = code.render(self.plan, {}, report.Sources(records, [], {}), {}, window)
        self.assertIn("| Hand input tokens | 3800000 |", rendered)
        self.assertIn("| Hand output tokens | 0 |", rendered)
        self.assertIn("| Hand weight, millions | 4.0 |", rendered)
        self.assertIn("| Claude to Codex weight, without Hand | 2.0 (prev -) |", rendered)
        self.assertIn("| Claude to Codex weight, with Hand | 6.0 |", rendered)
        self.assertIn("Hand figures cover the listed sessions in full.", rendered)
        rendered = code.render(self.plan, {}, report.Sources([], [], {}), {}, window)
        self.assertIn("| Claude to Codex weight, with Hand | - |", rendered)

    def test_code_render_hand_missing_manifest_has_no_line_and_unread_is_a_note(self):
        window = report.Window(ts("00:00"), ts("01:00"))
        sources = report.Sources([], [], {})
        self.assertNotIn("Hand", code.render(self.plan, {}, sources, {}, window))
        atomic.write(Path.home() / "fab/hand-sessions", "missing demo\n")
        rendered = code.render(self.plan, {}, sources, {}, window)
        self.assertIn("unread: hand session missing", rendered)
        self.assertIn("| Hand weight, millions | 0.0 |", rendered)
        self.assertEqual(sources.unread, [])

    def test_code_render_empty_and_no_landing(self):
        window = report.Window(ts("00:00"), ts("01:00"))
        sources = report.Sources([], [], {})
        rendered = code.render(self.plan, {}, sources, {}, window)
        self.assertIn("No run yet.", rendered)
        self.assertIn("## Signals\n- none", rendered)
        self.assertIn("| minutes to answer, median | - (prev -) |", rendered)
        sources.log = [event("00:01", "run.started", run="a", kind="implement")]
        self.assertIn(f"First run {ts('00:01')}; No landing yet.",
                      code.render(self.plan, self.tasks, sources, self.hosts, window))

    def test_code_render_rejections_ranked_by_count_then_step(self):
        records = [event(f"00:{minute:02}", "branch.rejected", step=step)
                   for minute, step in enumerate(("z", "b", "a", "z"))]
        rendered = code.render(self.plan, self.tasks, report.Sources(records, [], {}), self.hosts,
                               report.Window(ts("00:00"), ts("01:00")))
        self.assertTrue(rendered.endswith("| z | 2 |\n| a | 1 |\n| b | 1 |\n"))


class PartMeasuresTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.plan, self.tasks, self.hosts = fixture()
        self.repo = self.home / "checkout"
        self.tasks = {name: replace(task, path=str(self.repo / "docs/plan/demo" / task.path),
                                   files=("fab/core*.py", "fab/tests/test_core.py", "docs/core.md"))
                      for name, task in self.tasks.items()}
        self.records = [
            event("00:00", "call.started", None, call="root", role="skeleton", subject="demo/core",
                  branch="calls/root"),
            event("00:01", "call.ended", None, call="root", role="skeleton", subject="demo/core",
                  tokens="1000000/0/0", cache_write=800000),
            event("00:02", "run.started", "root", run="review-1", kind="review", base="base", tip="first"),
            event("00:03", "run.ended", "root", run="review-1", outcome="done", tokens="1000000/0/0"),
            event("00:04", "call.started", None, call="amend", role="amend", amends="root"),
            event("00:05", "call.ended", None, call="amend", tokens="1000000/0/0"),
            event("00:06", "run.started", "root", run="review-2", kind="review", base="base", tip="amended"),
            event("00:07", "run.ended", "root", run="review-2", outcome="done", tokens="1000000/0/0"),
            event("00:08", "run.started", run="implement", kind="implement"),
            event("00:09", "run.ended", run="implement", outcome="done", tokens="2000000/0/0"),
            event("00:10", "run.started", run="repair", kind="repair"),
            event("00:11", "run.ended", run="repair", outcome="done", tokens="1000000/0/0"),
            event("00:12", "run.started", "demo/b", run="rebase", kind="rebase"),
            event("00:13", "run.ended", "demo/b", run="rebase", outcome="done", tokens="2000000/0/0"),
            landed("00:14"),
            event("00:15", "branch.landed", "demo/b", tip="last", main="final-main"),
        ]
        self.sh = FakeRunner().on(["git", "hash-object"], Result(0, "empty-tree\n"))
        self.sh.on(["git", "diff", "--numstat", "-z", "--no-renames", "base", "amended"],
                   Result(0, "30\t5\tfab/core.py\0"
                          "900\t0\tfab/tests/test_core.py\0"
                          "800\t0\tdocs/core.md\0-\t-\tfab/image.bin\0"))
        self.sh.on(["git", "diff", "--numstat", "-z", "--no-renames", "empty-tree", "final-main"],
                   Result(0, "70\t0\tfab/core.py\0"
                          "30\t0\tfab/core_extra.py\0"
                          "1000\t0\tfab/tests/test_core.py\0"))

    def test_part_measures_finished_weights_share_and_per_line(self):
        numstat = code._part_numstat(self.plan, self.tasks, self.records, sh=self.sh)
        self.assertEqual(numstat, {"core": (30, 100)})
        self.assertEqual(code.part_rows(self.plan, self.tasks, self.records, numstat),
                         [("core", 5.0, 5.0, 1.0, 0.3, 30000.0, 70000.0)])
        paths = [":(glob)docs/core.md", ":(glob)fab/core*.py", ":(glob)fab/tests/test_core.py"]
        self.assertEqual(self.sh.argvs(), [
            ["git", "diff", "--numstat", "-z", "--no-renames", "base", "amended", "--", *paths],
            ["git", "hash-object", "-t", "tree", "--stdin"],
            ["git", "diff", "--numstat", "-z", "--no-renames", "empty-tree", "final-main", "--", *paths],
        ])
        self.assertTrue(all(call.cwd == str(self.repo) for call in self.sh.calls))
        self.assertEqual(self.sh.calls[1].input, "")

    def test_part_measures_unfinished_and_empty_parts_are_not_measured(self):
        unfinished = self.records[:-1]
        self.assertEqual(code.part_rows(self.plan, self.tasks, unfinished, {"core": (30, 100)}), [])
        self.assertEqual(code._part_numstat(self.plan, self.tasks, unfinished, sh=self.sh), {})
        self.assertEqual(self.sh.calls, [])

    def test_part_measures_count_only_part_design_and_task_run_kinds(self):
        unrelated = [
            event("00:16", "call.ended", None, role=role, subject=subject, tokens="9000000/0/0")
            for role, subject in (("skeleton", "demo/core2"), ("answer", "demo/core"),
                                  ("review", "demo/review"), ("skeleton", "other/core"))]
        for kind in ("foreman", "tests", "accept", "review"):
            unrelated += [event("00:16", "run.started", "demo/c", run=kind, kind=kind),
                          event("00:17", "run.ended", "demo/c", run=kind, outcome="done", tokens="9000000/0/0")]
        # A part's test run is also excluded, even when its task belongs to the finished part.
        unrelated += [event("00:16", "run.started", run="tests-core", kind="tests"),
                      event("00:17", "run.ended", run="tests-core", outcome="done", tokens="9000000/0/0"),
                      landed("00:18")]
        self.assertEqual(code.part_rows(self.plan, self.tasks, self.records + unrelated, {"core": (30, 100)}),
                         [("core", 5.0, 5.0, 1.0, 0.3, 30000.0, 70000.0)])

    def test_part_measures_missing_history_and_zero_denominators(self):
        records = [landed("00:01"), landed("00:02", "demo/b")]
        for counts, share in (((None, None), None), ((0, 0), None), ((0, 100), 0.0)):
            with self.subTest(counts=counts):
                row = code.part_rows(self.plan, self.tasks, records, {"core": counts})[0]
                self.assertEqual(row[:4], ("core", 0.0, 0.0, None))
                self.assertEqual(row[4], share)
                self.assertEqual(row[5:], (0.0, 0.0) if counts[1] else (None, None))
        row = code.part_rows(self.plan, self.tasks, self.records, {})[0]
        self.assertEqual(row[4:], (None, None, None))
        self.assertEqual(row[1:4], (5.0, 5.0, 1.0))

    def test_part_measures_numstat_failures_binary_and_malformed_records(self):
        for output, expected in (("", 0), ("-\t-\tfab/blob\0", 0),
                                 ("10\t0\tfab/a\tb.py\0", 10),
                                 ("4\t2\tfab/core.py\0torn", None),
                                 ("bad\t0\tfab/core.py\0", None),
                                 ("-2\t0\tfab/core.py\0", None)):
            with self.subTest(output=output):
                self.assertEqual(code._production_lines(output), expected)
        failed = FakeRunner().on(["git", "diff"], Result(1, err="missing revision"))
        failed.on(["git", "hash-object"], Result(0, "empty-tree\n"))
        self.assertEqual(code._part_numstat(self.plan, self.tasks, self.records, sh=failed),
                         {"core": (None, None)})

    def test_part_measures_render_finished_unfinished_and_share_signal(self):
        window = report.Window(ts("00:00"), ts("01:00"))
        with patch.object(code, "_part_numstat", return_value={"core": (30, 100)}):
            rendered = code.render(self.plan, self.tasks, report.Sources(self.records, [], {}),
                                   self.hosts, window)
        self.assertIn("| core | 2 | 2 | 3 | 0.0 | 0 | finished | 5.0 | 5.0 | 1.0 | 30.0% | 30000.0 | 70000.0 |", rendered)
        self.assertIn("| ui | 1 | 0 | 0 | 0.0 | 0 | unfinished | - | - | - | - | - | - |", rendered)
        self.assertIn("| empty | 0 | 0 | 0 | 0.0 | 0 | unfinished | - | - | - | - | - | - |", rendered)
        self.assertIn("core skeleton share 30.0%, above 25%", rendered)
        self.assertIn("target 10-20%", rendered)

    def test_part_measures_share_signal_strictly_above_threshold(self):
        for added, signal in ((10, False), (20, False), (25, False), (26, True)):
            with self.subTest(added=added):
                rows = code.part_rows(self.plan, self.tasks, self.records, {"core": (added, 100)})
                self.assertEqual(bool(code._part_signals(rows)), signal)
        self.assertEqual(code._part_signals(code.part_rows(self.plan, self.tasks, self.records, {})), [])

    def test_part_measures_plan_order_and_missing_skeleton(self):
        records = [*self.records, landed("00:16", "demo/c")]
        self.assertEqual([row[0] for row in code.part_rows(self.plan, self.tasks, records, {})],
                         ["core", "ui"])
        self.assertEqual(code.part_rows(self.plan, self.tasks, records, {"ui": (None, 100)})[1],
                         ("ui", 0.0, 0.0, None, None, 0.0, 0.0))

    def test_part_measures_skeleton_landing_fallback_and_no_files(self):
        records = [event("00:00", "call.started", None, call="root", role="contract",
                         subject="demo/core", branch="calls/root"),
                   event("00:01", "branch.landed", "calls/root", branch="calls/root", tip="skeleton", main="skeleton"),
                   *self.records[-2:]]
        sh = FakeRunner().on(["git", "hash-object"], Result(0, "empty-tree\n"))
        sh.on(["git", "diff"], Result(0, "12\t0\tfab/core.py\0"))
        self.assertEqual(code._part_numstat(self.plan, self.tasks, records, sh=sh), {"core": (12, 12)})
        self.assertEqual(sh.argvs()[0][5:7], ["skeleton^", "skeleton"])
        no_files = {name: replace(task, files=()) for name, task in self.tasks.items()}
        self.assertEqual(code._part_numstat(self.plan, no_files, records, sh=FakeRunner()), {})

    def test_part_measures_review_ending_without_start_is_attributed_to_root(self):
        records = [record for record in self.records
                   if not (record["ev"] == "run.started" and record["task"] == "root")]
        self.assertEqual(code.part_rows(self.plan, self.tasks, records, {"core": (30, 100)}),
                         [("core", 5.0, 5.0, 1.0, 0.3, 30000.0, 70000.0)])

    def test_part_measures_missing_branch_never_uses_a_task_as_skeleton(self):
        records = [event("00:00", "call.started", None, call="root", role="skeleton", subject="demo/core"),
                   *self.records[-2:]]
        self.assertEqual(code._part_numstat(self.plan, self.tasks, records, sh=self.sh),
                         {"core": (None, 100)})
        self.assertEqual(len(self.sh.calls), 2)
