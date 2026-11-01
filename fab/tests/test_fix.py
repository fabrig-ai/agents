"""Shared Fix-mode contracts, with temporary homes and fake commands."""

import shlex
import unittest
from unittest.mock import Mock, patch

from fab import fix, foreman, log
from fab.hosts import Host
from fab.sh import Result
from fab.tests.support import FakeRunner, run_ended, run_started, tmp_home

HOST = Host("builder", "worker@builder.invalid", ("builder",))


class FixParseTest(unittest.TestCase):
    def test_fix_uses_first_nonblank_line_and_right_strips_following_lines(self):
        self.assertEqual(fix.parse("\n \n Done : fix : repair the test  \n  cause  \n\n"),
                         ("fix", "repair the test", ["  cause", ""], []))

    def test_retry_returns_left_without_fix_lines_or_skips(self):
        skip = Mock(return_value=True)
        self.assertEqual(fix.parse("Done: retry: expired login\nOwner: demo/a\nevidence", skip=skip),
                         ("left", "expired login", [], []))
        skip.assert_not_called()

    def test_malformed_first_line_does_not_search_for_a_later_verdict(self):
        for head in ("Failed: cannot say", "Done: fix:", "Done: retry: ", "Question: what?",
                     "Done: accept: yes", "x" * 200):
            with self.subTest(head=head):
                self.assertEqual(fix.parse(head + "\nDone: fix: later"),
                                 ("none", "no verdict: " + head.strip()[:120], [], []))

    def test_blank_report_has_an_empty_no_verdict_reason(self):
        for report in ("", "\n \t\n"):
            with self.subTest(report=report):
                self.assertEqual(fix.parse(report), ("none", "no verdict: ", [], []))

    def test_skip_removes_only_the_immediate_line_and_returns_it_verbatim(self):
        skip = Mock(side_effect=lambda line: line.strip().startswith("Owner:"))
        self.assertEqual(fix.parse("Done: fix: repair\n Owner: demo/a  \nOwner: demo/b\ncause", skip=skip),
                         ("fix", "repair", ["Owner: demo/b", "cause"], [" Owner: demo/a  "]))
        skip.assert_called_once_with(" Owner: demo/a  ")

    def test_skip_does_not_search_past_a_blank_or_nonmatching_line(self):
        for line in ("", "cause"):
            with self.subTest(line=line):
                skip = Mock(return_value=False)
                self.assertEqual(fix.parse(f"Done: fix: repair\n{line}\nOwner: demo/a", skip=skip),
                                 ("fix", "repair", [line, "Owner: demo/a"], []))
                skip.assert_called_once_with(line)

    def test_no_following_line_does_not_call_skip(self):
        skip = Mock(return_value=True)
        self.assertEqual(fix.parse("Done: fix: repair", skip=skip), ("fix", "repair", [], []))
        skip.assert_not_called()

    def test_line_limit_is_applied_after_skip(self):
        lines = [f"line {number}  " for number in range(fix.SECTION_LINES + 5)]
        for prefix in ("", "Owner: demo/a\n"):
            with self.subTest(prefix=prefix):
                verdict, reason, kept, skipped = fix.parse(
                    "Done: fix: repair\n" + prefix + "\n".join(lines),
                    skip=lambda line: line.startswith("Owner:"))
                self.assertEqual((verdict, reason), ("fix", "repair"))
                self.assertEqual(kept, [line.rstrip() for line in lines[:fix.SECTION_LINES]])
                self.assertEqual(skipped, ["Owner: demo/a"] if prefix else [])


class FixSectionTest(unittest.TestCase):
    def test_section_drops_trailing_blanks_and_keeps_inner_blanks(self):
        lines = ["where", "", "  change", "", "  "]
        self.assertEqual(fix.section("## Repair", "repair the test", lines),
                         "## Repair\n\nrepair the test\nwhere\n\n  change\n")
        self.assertEqual(lines, ["where", "", "  change", "", "  "])

    def test_section_without_lines_keeps_reason_and_final_newline(self):
        self.assertEqual(fix.section("## Repair", "repair the test", []),
                         "## Repair\n\nrepair the test\n")


class FixSettleTest(unittest.TestCase):
    def test_settle_stamps_timestamp_and_day_with_one_clock_read(self):
        stamp = "2026-11-02T00:00:00.000Z"
        fields = Mock(side_effect=lambda day: dict(finding="finding-1", run="foreman-1",
                                                   verdict="fix", reason="repair", section=day))
        with tmp_home() as home, patch.object(log, "now", return_value=stamp) as now:
            path = home / "events"
            record = fix.settle("finding.settled", fields, log_path=path)
            self.assertEqual(record, dict(ev="finding.settled", ts=stamp, finding="finding-1",
                                          run="foreman-1", verdict="fix", reason="repair",
                                          section="2026-11-02"))
            self.assertEqual(log.read(path), [record])
            self.assertEqual(log.read(), [])
            fields.assert_called_once_with("2026-11-02")
            now.assert_called_once_with()

    def test_settle_defaults_to_the_temporary_homes_log(self):
        with tmp_home():
            record = fix.settle("red.settled", lambda day: dict(red="red-1", verdict="none"))
            self.assertEqual(log.read(), [record])


class FixTaskTest(unittest.TestCase):
    def test_answers_keep_each_tasks_log_order_and_ignore_empty_answers(self):
        events = [dict(ev="question.answered", task="demo/red-1", answer="first", ts="later"),
                  dict(ev="question.answered", task="demo/finding-2", answer="other"),
                  dict(ev="question.answered", task="demo/red-1", answer="second", ts="earlier"),
                  dict(ev="question.answered", task="demo/red-1", answer=""),
                  dict(ev="question.answered", task="demo/red-1"),
                  dict(ev="question.answered", answer="missing task"),
                  dict(ev="note", task="demo/red-1", answer="foreign")]
        self.assertEqual(fix.answers(events), {"demo/red-1": ["first", "second"],
                                              "demo/finding-2": ["other"]})
        self.assertEqual(fix.answers([]), {})

    def test_sections_keep_each_tasks_log_order_and_ignore_nonfix_settlements(self):
        events = [dict(ev="refusal.settled", task="demo/red-1", verdict="fix", section="first", ts="later"),
                  dict(ev="refusal.settled", task="demo/finding-2", verdict="fix", section="other"),
                  dict(ev="refusal.settled", task="demo/red-1", verdict="fix", section="second", ts="earlier"),
                  dict(ev="refusal.settled", task="demo/red-1", verdict="fix", section=""),
                  dict(ev="refusal.settled", task="demo/red-1", verdict="fix"),
                  dict(ev="red.settled", task="demo/red-1", verdict="fix", section="foreign")]
        events += [dict(ev="refusal.settled", task="demo/red-1", verdict=verdict, section="ignored")
                   for verdict in ("left", "retry", "none", "")]
        self.assertEqual(fix.sections(events), {"demo/red-1": ["first", "second"],
                                               "demo/finding-2": ["other"]})
        self.assertEqual(fix.sections([]), {})

    def test_task_fields_and_answers_for_both_fix_kinds(self):
        self.assertEqual(fix.FIX_KINDS, ("red", "finding"))
        self.assertEqual((fix.RUNS, fix.SECTION_LINES), (2, 30))
        for kind, part in (("red", "after-landing"), ("finding", "qa")):
            with self.subTest(kind=kind):
                task = fix.task(f"demo/{kind}-1", kind, part, "body\n", ["first", "second"])
                self.assertEqual((task.id, task.kind, task.part, task.repo, task.needs, task.files,
                                  task.effort, task.minutes, task.path, task.consolidation),
                                 (f"demo/{kind}-1", kind, part, "fabrig", (), ("**",), "high", 20, "", False))
                self.assertEqual(task.body, "body\n\n## Answers\n\n- first\n- second\n")

    def test_task_without_answers_keeps_the_body_unchanged(self):
        self.assertEqual(fix.task("demo/red-1", "red", "after-landing", "body", []).body, "body")


class FixLaunchTest(unittest.TestCase):
    def test_report_path_uses_the_builders_home_and_nested_run_id(self):
        self.assertEqual(fix.report_path(HOST, "demo/finding-1/foreman-2"),
                         "/home/worker/src/fabrig/fab/runs/demo/finding-1/foreman-2/report.md")

    def test_launch_numbers_foreman_runs_and_passes_caller_fields(self):
        def answer(call):
            command = shlex.split(shlex.split(call.argv[-1])[2])
            return Result(0, "codex-fix /state/fix\n") if command[:3] == ["fab", "codex", "start"] else Result(0)

        for kind, previous in (("red", False), ("finding", True)):
            with self.subTest(kind=kind), tmp_home() as home:
                task_id = f"demo/{kind}-1"
                events = [run_started(task_id), run_ended(foreman.task_field(task_id)),
                          run_started("other/task/foreman")]
                if previous:
                    events += [run_started(foreman.task_field(task_id), kind=foreman.KIND)]
                run_id = f"{task_id}/foreman-{2 if previous else 1}"
                report = f"/home/worker/src/fabrig/fab/runs/{run_id}/report.md"
                brief = Mock(side_effect=lambda number, path: f"Run: {number}\nReport: {path}\n")
                fake, path = FakeRunner().on(["ssh"], answer), home / "events"
                actual = fix.launch(task_id, HOST, "main-tip", brief, events, sh=fake,
                                    log_path=path, **{kind: f"{kind}-1", "cause": "confirmed"})
                self.assertEqual(actual, run_id)
                brief.assert_called_once_with(run_id, report)
                started, = log.read(path)
                self.assertEqual({key: started[key] for key in
                                  ("run", "task", "kind", "branch", "base", "tip", kind, "cause")},
                                 dict(run=run_id, task=foreman.task_field(task_id), kind=foreman.KIND,
                                      branch=task_id, base="main-tip", tip="main-tip",
                                      **{kind: f"{kind}-1", "cause": "confirmed"}))
                commands = [shlex.split(shlex.split(call.argv[-1])[2]) for call in fake.calls]
                detached = next(command for command in commands if "--detach" in command)
                self.assertEqual(detached[-2:], [f"/home/worker/src/fabrig/fab/wt/{run_id}", "main-tip"])
                launcher = next(command for command in commands if command[:3] == ["fab", "codex", "start"])
                self.assertIn("--read-only", launcher)
                self.assertEqual(launcher[launcher.index("--effort") + 1], foreman.EFFORT)
                self.assertEqual(launcher[-1], report)
                self.assertEqual((log.home() / "runs" / run_id / "brief.md").read_text(),
                                 f"Run: {run_id}\nReport: {report}\n")
                self.assertEqual(log.read(), [])
