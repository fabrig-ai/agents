import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from fab import channel, cli, code_report, landing_report, log, report
from fab.plan import Plan, Question
from fab.tests.support import tmp_home


def ts(minute):
    return f"2026-10-30T12:{minute:02}:00.000Z"


def event(minute, ev, **fields):
    return {"ts": ts(minute), "ev": ev, **fields}


def question(minute, subject="demo/core", call="cut-1"):
    return event(minute, "call.ended", subject=subject, call=call, outcome="question")


def parked(minute, subject="demo/core", call="root-1", **fields):
    return event(minute, "call.parked", subject=subject, call=call,
                 reason="Choose capacity", **fields)


def plan(draft="demo", questions=()):
    return Plan(draft, "agents", (), 1.0, 2.0, {}, (), questions=questions)


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    sibling = path.with_name("." + path.name + ".new")
    sibling.write_text(text, encoding="utf-8")
    sibling.replace(path)
    return path


class ChannelTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.fab_home = log.home()
        self.fab_home.mkdir()

    def test_asks_plans_first_in_given_order_and_whitespace_answer_open(self):
        first = plan(questions=(Question("budget", "How much?", ("core", "ui")),
                                Question("host", "Which host?", (), "hel8"),
                                Question("limit", "Which limit?", (), "   ")))
        second = plan("other", (Question("machine", "Buy one?", ("build",)),))
        first_path, second_path = self.home / "plan.toml", self.home / "other/plan.toml"
        result = channel.asks([(first, first_path), (second, second_path)], [question(1)])
        self.assertEqual(result[:3], [
            channel.Ask("plan", "demo", "budget", "How much?", "",
                        report=str(first_path), parts=("core", "ui")),
            channel.Ask("plan", "demo", "limit", "Which limit?", "", report=str(first_path)),
            channel.Ask("plan", "other", "machine", "Buy one?", "",
                        report=str(second_path), parts=("build",)),
        ])
        self.assertEqual(result[3].kind, "call")

    def test_asks_reopening_moves_key_to_end_and_kinds_coexist(self):
        events = [question(1), question(2, "other", "other-1"),
                  parked(3, report=str(self.fab_home / "runs/review-1/report.md")),
                  question(4, call="cut-2")]
        result = channel.asks((), iter(events))
        self.assertEqual(result, [
            channel.Ask("call", "other", "other", "", ts(2), call="other-1",
                        report=str(self.fab_home / "calls/other-1/report.md")),
            channel.Ask("parked", "demo", "demo/core", "Choose capacity", ts(3),
                        call="root-1", report=str(self.fab_home / "runs/review-1/report.md")),
            channel.Ask("call", "demo", "demo/core", "", ts(4), call="cut-2",
                        report=str(self.fab_home / "calls/cut-2/report.md")),
        ])

    def test_asks_parked_reopening_moves_to_end_and_report_defaults_empty(self):
        result = channel.asks((), [parked(1), question(2, "other"), parked(3, call="root-2")])
        self.assertEqual([(ask.kind, ask.subject, ask.since) for ask in result],
                         [("call", "other", ts(2)), ("parked", "demo/core", ts(3))])
        self.assertEqual(result[-1].call, "root-2")
        self.assertEqual(result[-1].report, "")

    def test_asks_answer_closes_both_kinds_only_for_its_subject(self):
        events = [question(1), parked(2), question(3, "other"),
                  event(4, channel.ANSWERED, subject="demo/core")]
        self.assertEqual([ask.subject for ask in channel.asks((), events)], ["other"])
        self.assertEqual([ask.subject for ask in channel.asks((), events + [question(5)])],
                         ["other", "demo/core"])

    def test_asks_done_closes_call_only_and_task_answer_closes_nothing(self):
        events = [question(1), parked(2),
                  event(3, "question.answered", task="demo/core", subject="demo/core")]
        self.assertEqual([ask.kind for ask in channel.asks((), events)], ["call", "parked"])
        events += [event(4, "call.ended", subject="other", outcome="done"),
                   event(5, "call.ended", subject="demo/core", call="later", outcome="done")]
        self.assertEqual([ask.kind for ask in channel.asks((), events)], ["parked"])

    def test_asks_finished_closes_matching_parked_chain_only(self):
        events = [question(1, call="root-1"), parked(2), parked(3, "other", "other-1"),
                  event(4, "call.finished", call="unrelated"),
                  event(5, "call.finished", call="root-1")]
        self.assertEqual([(ask.kind, ask.subject) for ask in channel.asks((), events)],
                         [("call", "demo/core"), ("parked", "other")])

    def test_asks_missing_fields_are_skipped_without_replacing_open_asks(self):
        events = [question(1), parked(2)]
        malformed = [{}, {"ev": channel.ANSWERED}, {"ev": "call.finished"},
                     event(3, "call.ended", subject="demo/core"),
                     event(3, "call.ended", outcome="done"),
                     event(3, "call.parked", reason="missing subject")]
        for opening, required in ((question(3), ("subject", "call", "ts", "outcome")),
                                  (parked(3), ("subject", "call", "ts", "reason"))):
            malformed.extend({key: value for key, value in opening.items() if key != field}
                             for field in required)
        self.assertEqual(channel.asks((), iter(events + malformed)), channel.asks((), events))
        self.assertEqual(channel.asks((), [event(1, "call.ended", subject="demo", outcome="failed")]), [])

    def test_plan_dirs_missing_file_and_uncreated_given_directory(self):
        given = self.home / "not-cut-yet"
        self.assertEqual(channel.plan_dirs(), [])
        self.assertEqual(channel.plan_dirs([given]), [given.resolve()])

    def test_plan_dirs_lines_resolve_and_keep_first_occurrence(self):
        first, second, third = (self.home / name for name in ("first", "second", "third"))
        _write(self.fab_home / channel.PLANS, f"  {first}  \n\n{second}\n{first}/../first\n")
        self.assertEqual(channel.plan_dirs([second, third, first]), [first, second, third])

    def test_plan_dirs_relative_paths_resolve_against_working_directory(self):
        _write(self.fab_home / channel.PLANS, "plans/../draft\n\n")
        with patch("os.getcwd", return_value=str(self.home)):
            self.assertEqual(channel.plan_dirs([Path("draft"), Path("next")]),
                             [self.home / "draft", self.home / "next"])

    def test_signal_section_matches_both_standing_reports(self):
        sources = report.Sources([], [], {})
        window = report.Window(ts(0), ts(30))
        texts = [code_report.render(plan(), {}, sources, {}, window),
                 landing_report.render(sources, {}, window)]
        for text in texts:
            with self.subTest(heading=text.splitlines()[0]):
                self.assertEqual(channel.signal_section(text), ("- none",))

    def test_signal_section_exact_heading_stops_at_next_section_and_drops_blanks(self):
        self.assertEqual(channel.signal_section("# Report\n## Other\nnone\n"), ())
        self.assertEqual(channel.signal_section("## Signals extra\n- ignored\n"), ())
        self.assertEqual(channel.signal_section(
            "## Signals\n\n- first  \n   \n### Detail\n second\t\n## Next\n- ignored"),
            ("- first", "### Detail", " second"))
        self.assertEqual(channel.signal_section("## Signals\n- last  \n\n"), ("- last",))

    def test_latest_reports_greatest_valid_day_hidden_siblings_and_landing_last(self):
        directory = self.fab_home / "reports"
        _write(directory / "demo/2026-10-29.md", "## Signals\n- old\n")
        latest = _write(directory / "demo/2026-10-30.md", "## Signals\n- latest  \n")
        for name in ("notes.md", "2026-02-30.md", "20261031.md", "2026-W44-6.md",
                     "2026-1-31.md", "2026-12-01.txt", ".2026-12-01.md.new"):
            _write(directory / "demo" / name, "## Signals\n- stray\n")
        (directory / "demo/2026-12-01.md").mkdir()
        landing = _write(directory / "landing/2026-10-29.md", "No signals")
        zed = _write(directory / "zed/2026-10-30.md", "## Signals\n- zed\n")
        _write(directory / ".demo.new/2026-10-30.md", "hidden")
        _write(directory / ".sibling", "hidden")
        _write(directory / "stray.md", "stray")
        (directory / "empty").mkdir()
        self.assertEqual(channel.latest_reports(directory), [
            channel.Report("demo", "2026-10-30", latest, ("- latest",)),
            channel.Report("zed", "2026-10-30", zed, ("- zed",)),
            channel.Report("landing", "2026-10-29", landing, ()),
        ])

    def test_latest_reports_missing_directory(self):
        self.assertEqual(channel.latest_reports(self.fab_home / "missing"), [])

    @unittest.skipIf(os.geteuid() == 0, "root can read mode 000 files")
    def test_latest_reports_unreadable_day_stays_listed(self):
        directory = self.fab_home / "reports"
        path = _write(directory / "demo/2026-10-30.md", "unreadable")
        path.chmod(0)
        try:
            found = channel.latest_reports(directory)
        finally:
            path.chmod(0o600)
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0].name, found[0].day, found[0].path),
                         ("demo", "2026-10-30", path))
        self.assertTrue(found[0].signals[0].startswith("(unreadable: "))
        self.assertTrue(found[0].signals[0].endswith(")"))

    def test_excerpt_cut_at_question_lines_and_trim_trailing_blanks(self):
        path = _write(self.home / "question.md", "\n".join(f"line {n}  " for n in range(20)))
        self.assertEqual(channel.excerpt(path), "\n".join(f"line {n}" for n in range(channel.QUESTION_LINES)))
        _write(path, "first  \n\n second\t\n  \n\n")
        self.assertEqual(channel.excerpt(path), "first\n\n second")
        self.assertEqual(channel.excerpt(path, 2), "first")

    def test_excerpt_missing_empty_and_blank(self):
        path = self.home / "report.md"
        self.assertEqual(channel.excerpt(path), "(report missing)")
        _write(path, "")
        self.assertEqual(channel.excerpt(path), "(empty report)")
        _write(path, " \n\t\n")
        self.assertEqual(channel.excerpt(path), "(empty report)")

    def test_answers_text_keeps_subject_answers_in_log_order_and_multiline(self):
        events = [event(1, channel.ANSWERED, subject="demo/core", call="cut-1",
                        question="Which host?", by="user", answer="hel8\nthen hel9"),
                  event(2, channel.ANSWERED, subject="other", answer="ignored"),
                  event(3, "question.answered", subject="demo/core", answer="ignored"),
                  event(4, channel.ANSWERED, subject="demo/core", call="cut-2",
                        question="Budget?", by="free", answer="100")]
        self.assertEqual(channel.answers_text("demo/core", iter(events)),
                         f"### {ts(1)}, to cut-1\nQuestion: Which host?\n"
                         f"Answer (user): hel8\nthen hel9\n\n### {ts(4)}, to cut-2\n"
                         "Question: Budget?\nAnswer (free): 100")

    def test_answers_text_missing_fields_and_none(self):
        self.assertEqual(channel.answers_text("demo", [{"ev": channel.ANSWERED, "subject": "demo"}]),
                         "### -, to -\nQuestion: -\nAnswer (-): -")
        self.assertEqual(channel.answers_text("demo", [{"ev": channel.ANSWERED}]), "")
        self.assertEqual(channel.answers_text("demo", []), "")

    def test_render_all_question_kinds_quote_bodies_and_report_user_signals(self):
        entries = [
            (channel.Ask("plan", "demo", "budget", "Budget?", "", report="plan.toml",
                         parts=("core", "ui")), "**Budget?**\nkeep `Markdown`"),
            (channel.Ask("call", "demo", "demo/core", "", ts(1), report="calls/cut/report.md"),
             "Question: choose a host\n\n> quoted"),
            (channel.Ask("parked", "demo", "demo/ui", "refused", ts(2), report="review.md"),
             "refused\n\nFailed: scope"),
            (channel.Ask("parked", "other", "other", "capacity", ts(3)), "capacity"),
        ]
        signals = tuple(report.signal_lines([
            report.Signal("Capacity", "buy a builder", "user"),
            report.Signal("Red tests", "fix them", "ops"),
        ]))
        reports = [channel.Report("demo", "2026-10-30", Path("reports/demo.md"), signals),
                   channel.Report("landing", "2026-10-29", Path("reports/landing.md"), ())]
        rendered = channel.render(entries, reports, ts(4), ["plan: bad TOML", "other: missing field"])
        self.assertEqual(rendered, f"""# The user's page
{ts(4)}. Only what is the user's: budgets, machines, what is hard to reverse.

## Questions

### demo: question budget

**Budget?**
keep `Markdown`

- Waits: core, ui
- Answer: write its `answer` in `plan.toml` and land it with `fab land`

### demo/core, asked {ts(1)}

Question: choose a host

> quoted

- Read: `calls/cut/report.md`
- Answer: `fab page answer demo/core TEXT`

### demo/ui, parked {ts(2)}

refused

Failed: scope

- Read: `review.md`
- Answer: `fab page answer demo/ui TEXT`

### other, parked {ts(3)}

capacity

- Answer: `fab page answer other TEXT`

## Daily reports

### demo, 2026-10-30

`reports/demo.md`

- **Capacity:** buy a builder (user)

### landing, 2026-10-29

`reports/landing.md`

- none

## Unread

- plan: bad TOML
- other: missing field
""")

    def test_render_empty_page_and_no_unread_section(self):
        self.assertEqual(channel.render([], [], ts(0)), f"""# The user's page
{ts(0)}. Only what is the user's: budgets, machines, what is hard to reverse.

## Questions

(none)

## Daily reports

(none)
""")

    def test_render_other_owners_hidden_and_unreadable_report_visible(self):
        signals = tuple(report.signal_lines([
            report.Signal("ops signal", "ask the user", "ops"),
            report.Signal("lookalike", "act", "superuser"),
        ]))
        reports = [channel.Report("demo", "2026-10-30", Path("demo.md"), signals),
                   channel.Report("broken", "2026-10-30", Path("broken.md"),
                                  ("(unreadable: denied)",))]
        rendered = channel.render([], reports, ts(0))
        self.assertIn("`demo.md`\n\n- none", rendered)
        self.assertIn("(unreadable: denied)", rendered)
        self.assertNotIn("ops signal", rendered)
        self.assertNotIn("lookalike", rendered)
        self.assertNotIn("## Unread", rendered)
        self.assertTrue(rendered.endswith("\n"))
        self.assertFalse(rendered.endswith("\n\n"))

    def test_compose_loads_questions_reports_and_unread_plans_in_order(self):
        directory = self.home / "draft"
        plan_path = _write(directory / "plan.toml", '''draft = "demo"
repo = "agents"
part = []
[[question]]
id = "budget"
text = "How much?"
parts = ["core"]
''')
        broken = self.home / "broken"
        _write(broken / "plan.toml", "not TOML")
        missing = self.home / "not-cut"
        call_report = _write(self.fab_home / "calls/cut-1/report.md", "Question: Which host?\nOptions.")
        review_report = _write(self.fab_home / "runs/review-1/report.md", "Failed: capacity\nFindings.")
        daily = _write(self.fab_home / "reports/demo/2026-10-30.md",
                       "## Signals\n- **Capacity:** buy a builder (user)\n- red tests (ops)\n")
        events = [question(1), parked(2, "demo/ui", report=str(review_report)),
                  parked(3, "demo/other")]
        page = channel.compose([directory, missing, broken], events, ts(4))
        sections = ["### demo: question budget", f"### demo/core, asked {ts(1)}",
                    f"### demo/ui, parked {ts(2)}", f"### demo/other, parked {ts(3)}",
                    "## Daily reports", "## Unread"]
        self.assertEqual([page.index(section) for section in sections],
                         sorted(page.index(section) for section in sections))
        for quoted in ("How much?", str(plan_path), "Question: Which host?\nOptions.",
                       str(call_report), "Choose capacity\n\nFailed: capacity\nFindings.",
                       str(review_report), str(daily), "- **Capacity:** buy a builder (user)"):
            self.assertIn(quoted, page)
        self.assertIn(f"- {broken}: ", page)
        self.assertNotIn(str(missing), page)
        self.assertNotIn("red tests", page)
        self.assertIn("Choose capacity\n\n- Answer: `fab page answer demo/other TEXT`", page)

    def test_compose_plan_read_failure_is_one_unread_line(self):
        directory = self.home / "draft"
        _write(directory / "plan.toml", "present")
        with patch("fab.plan.load_plan", side_effect=OSError("first\nsecond")):
            page = channel.compose([directory], [], ts(1))
        self.assertIn(f"## Unread\n\n- {directory}: first second\n", page)

    def test_write_replaces_whole_page_under_fab_home(self):
        path = channel.write("old page\n")
        self.assertEqual(path, self.fab_home / "user.md")
        self.assertEqual(channel.write("new page\n"), path)
        self.assertEqual(path.read_text(), "new page\n")
        self.assertEqual(list(self.fab_home.iterdir()), [path])

    def test_answer_call_logs_first_nonblank_report_line_and_stripped_text(self):
        _write(self.fab_home / "calls/cut-1/report.md", "\n  \nQuestion: Which host?  \nOptions.")
        path = self.home / "custom/log.jsonl"
        with patch("fab.log.now", return_value=ts(2)):
            record = channel.answer("demo/core", "  hel8  ", [question(1)], log_path=path)
        self.assertEqual(record, dict(ts=ts(2), ev="call.answered", subject="demo/core",
                                      call="cut-1", by="user", question="Question: Which host?", answer="hel8"))
        self.assertEqual(log.read(path), [record])
        self.assertEqual((path.parent / "tick.want").read_text(), "answer demo/core\n")
        self.assertFalse((self.fab_home / "tick.want").exists())
        self.assertEqual(log.read(), [])

    def test_answer_uses_last_open_ask_and_parked_reason(self):
        record = channel.answer("demo/core", "Buy it", [question(1), parked(2)], by="free")
        self.assertEqual((record["call"], record["question"], record["by"]),
                         ("root-1", "parked: Choose capacity", "free"))
        self.assertEqual(log.read(), [record])
        self.assertEqual((self.fab_home / "tick.want").read_text(), "answer demo/core\n")
        self.assertEqual(channel.asks((), [question(1), parked(2), record]), [])

    def test_answer_refuses_blank_unknown_and_plan_id_without_logging(self):
        events = [question(1), parked(2), question(3, "other", "other-1")]
        for subject, text in (("demo/core", " \t"), ("missing", "yes"), ("budget", "100")):
            with self.subTest(subject=subject), self.assertRaises(ValueError) as caught:
                channel.answer(subject, text, events)
            self.assertIn(subject, str(caught.exception))
            self.assertIn("open subjects: demo/core, other", str(caught.exception))
            self.assertEqual(log.read(), [])
        with self.assertRaisesRegex(ValueError, "open subjects: none"):
            channel.answer("missing", "yes", [])
        self.assertFalse(log.default_path().exists())
        self.assertFalse((self.fab_home / "tick.want").exists())

    def test_main_show_and_write_through_cli(self):
        directory = self.home / "draft"
        _write(directory / "plan.toml", 'draft = "demo"\nrepo = "agents"\npart = []\n')
        output = io.StringIO()
        with patch("fab.log.now", return_value=ts(0)), redirect_stdout(output):
            self.assertEqual(cli.main(["page", "show", str(directory)]), 0)
        self.assertEqual(output.getvalue(), channel.compose([directory], [], ts(0)))
        self.assertFalse((self.fab_home / channel.PAGE).exists())
        output = io.StringIO()
        with patch("fab.log.now", return_value=ts(0)), redirect_stdout(output):
            self.assertEqual(cli.main(["page", "write", str(directory)]), 0)
        self.assertEqual(output.getvalue(), str(self.fab_home / channel.PAGE) + "\n")
        self.assertEqual((self.fab_home / channel.PAGE).read_text(), channel.compose([directory], [], ts(0)))

    def test_main_answer_logs_and_rewrites_page_without_question(self):
        log.append("call.ended", subject="demo/core", call="cut-1", outcome="question", ts=ts(1))
        _write(self.fab_home / "calls/cut-1/report.md", "Question: Which host?\n")
        channel.write(channel.compose([], log.read(), ts(1)))
        output = io.StringIO()
        with patch("fab.log.now", return_value=ts(2)), redirect_stdout(output):
            self.assertEqual(cli.main(["page", "answer", "demo/core", " Use  ", "\nhel8 "]), 0)
        self.assertEqual(log.read()[-1]["answer"], "Use hel8")
        self.assertEqual(log.read()[-1]["by"], "user")
        self.assertEqual(output.getvalue(), f"answered demo/core\n{self.fab_home / channel.PAGE}\n")
        page = (self.fab_home / channel.PAGE).read_text()
        self.assertNotIn("Which host?", page)
        self.assertIn("## Questions\n\n(none)", page)

    def test_main_errors_exit_one_without_logging(self):
        errors = io.StringIO()
        with redirect_stderr(errors):
            self.assertEqual(cli.main(["page", "answer", "missing", "yes"]), 1)
            with patch.object(channel, "write", side_effect=OSError("disk full")):
                self.assertEqual(cli.main(["page", "write"]), 1)
        self.assertIn("fab page: no open call or parked chain", errors.getvalue())
        self.assertIn("fab page: disk full", errors.getvalue())
        self.assertEqual(log.read(), [])

    def test_main_bad_arguments_exit_two(self):
        for argv in ([], ["unknown"], ["answer"], ["answer", "demo/core"],
                     ["answer", "demo/core", "yes", "--by", "other"]):
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                cli.main(["page", *argv])
            self.assertEqual(caught.exception.code, 2)
