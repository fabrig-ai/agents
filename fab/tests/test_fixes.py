"""Finding foremen and repairs, over records and fake commands (fab-qa.md, 2)."""

import shlex
import unittest
from dataclasses import FrozenInstanceError, replace
from unittest.mock import patch

from fab import atomic, findings, fixes, foreman, log
from fab.hosts import Host
from fab.plan import load_plan
from fab.sh import Result
from fab.tests.ladder_plans import write_ladder
from fab.tests.qa_records import (STAMP, finding_merged, finding_raised, finding_triaged,
                                  rung_passed, walk_ended)
from fab.tests.support import FakeRunner, run_ended, run_started, tmp_home

TASK = "ladder/finding-1"
FOREMAN_TASK = TASK + "/foreman"
RUN = FOREMAN_TASK + "-1"
HOST = Host("builder", "worker@builder.invalid", ("builder",), places=0)
SECTION = "## Repair (2026-11-01, finding 1, foreman " + RUN + ")\n\nrepair the cause\nwhere\n"


def records(*, merged=False):
    """An ended walk routed to the path, optionally with a second sighting."""
    events = [finding_raised("finding-1", "walk-1", "b0", title="Lost review",
                             area="jig tasks", reproduction="Ask for a review",
                             expected="Review completes", seen="Review disappears"),
              walk_ended("walk-1", "fail", ("finding-1",)),
              finding_triaged("finding-1", "path", owner="jig", reason="Blocks the ladder")]
    if merged:
        events += [finding_raised("finding-2", "walk-2", "b1", reproduction="Ask again from box two"),
                   walk_ended("walk-2", "fail", ("finding-2",)),
                   finding_merged("finding-2", "finding-1")]
    return events


def foreman_events(outcome="done"):
    """The routed finding's first foreman start and optional completion."""
    events = [run_started(FOREMAN_TASK, kind=foreman.KIND, finding="finding-1", tip="main-tip", ts=STAMP)]
    if outcome is not None:
        events += [run_ended(FOREMAN_TASK, outcome=outcome, report="/collected/report.md", ts=STAMP)]
    return events


def settlement(verdict="fix", **fields):
    """A settlement with the shared finding record fields."""
    return log.record(fixes.SETTLED, ts=STAMP, **(dict(finding="finding-1", run=RUN, verdict=verdict,
                      reason="repair the cause", section=SECTION if verdict == "fix" else "") | fields))


class FixesForemenTest(unittest.TestCase):
    def test_first_foreman_and_first_end_win_in_log_order(self):
        start, end = foreman_events()
        inflight = fixes.foremen([start])["finding-1"]
        self.assertEqual((inflight.finding, inflight.run, inflight.tip, inflight.outcome, inflight.report),
                         ("finding-1", RUN, "main-tip", "", ""))
        with self.assertRaises(FrozenInstanceError):
            inflight.tip = "other"
        events = [end, start, start | {"run": "second"}, end,
                  end | {"outcome": "failed", "report": "other"}]
        self.assertEqual(fixes.foremen(events)["finding-1"],
                         fixes.Foreman("finding-1", RUN, "main-tip", "done", "/collected/report.md"))

    def test_other_tasks_kinds_and_malformed_starts_do_not_count(self):
        start = foreman_events(None)[0]
        changes = [{"task": "ladder/other/foreman"}, {"kind": "implement"}, {"finding": ""},
                   {"finding": []}, {"run": None}, {"tip": None}, {"task": "/finding-1/foreman"}]
        for fields in changes:
            with self.subTest(fields=fields):
                self.assertEqual(fixes.foremen([start | fields]), {})
        self.assertEqual(fixes.foremen([foreman_events()[1]]), {})


class FixesBriefTest(unittest.TestCase):
    def test_sections_name_every_fact_and_keep_report_whole(self):
        with tmp_home() as home:
            plan_path = write_ladder(home / "plan")
            plan = load_plan(plan_path / "plan.toml")
            found = findings.findings(records(merged=True))
            report = "Transcript with a model turn.\n\nLast line.\n\n"
            text = fixes.brief(found["finding-1"], plan, run_id=RUN, report="/output/report.md",
                               tip="main-tip", briefs=("docs/plan/ladder/briefs/kit.md",),
                               merged=[found["finding-2"]], walk_report=report, role="ROLE\n")
            headings = ["ROLE", "# The finding", "# The record", "# The walk's report"]
            self.assertEqual([text.index(h) for h in headings], sorted(text.index(h) for h in headings))
            for fact in (RUN, "finding-1", "b0", "chatgpt-forgejo", "walk-1", "commit", "jig tasks",
                         "jig", "Blocks the ladder", "docs/plan/ladder/briefs/kit.md", "/output/report.md",
                         "Your checkout is fabrig at main-tip, read-only.", "Lost review",
                         "Ask for a review", "Review completes", "Review disappears", "finding-2",
                         "walk-2", "Ask again from box two"):
                self.assertIn(fact, text)
            self.assertTrue(text.endswith(report))

    def test_start_launches_one_readonly_foreman_at_tip_with_merged_evidence(self):
        def respond(call):
            argv = shlex.split(shlex.split(call.argv[-1])[2])
            return Result(0, "codex-finding /state/run\n") if argv[:3] == ["fab", "codex", "start"] else Result(0)

        with tmp_home() as home:
            directory = write_ladder(home / "docs/plan/ladder")
            plan = load_plan(directory / "plan.toml")
            events = records(merged=True)
            finding = findings.findings(events)["finding-1"]
            atomic.write(log.home() / "walks/walk-1/report.md", "Whole transcript\n")
            fake, path = FakeRunner().on(["ssh"], respond), home / "events"
            self.assertEqual(fixes.start(finding, plan, directory, HOST, "main-tip", events,
                                         sh=fake, log_path=path), RUN)
            started, = log.read(path)
            self.assertEqual({key: started[key] for key in ("task", "run", "kind", "finding", "tip", "base")},
                             dict(task=FOREMAN_TASK, run=RUN, kind="foreman", finding="finding-1",
                                  tip="main-tip", base="main-tip"))
            commands = [shlex.split(shlex.split(call.argv[-1])[2]) for call in fake.calls]
            detached, = [argv for argv in commands if "--detach" in argv]
            self.assertEqual(detached[-1], "main-tip")
            self.assertIn("/repos/fabrig", " ".join(detached))
            launcher, = [argv for argv in commands if argv[:3] == ["fab", "codex", "start"]]
            self.assertIn("--read-only", launcher)
            self.assertEqual(launcher[launcher.index("--effort") + 1], foreman.EFFORT)
            text = (log.home() / "runs" / RUN / "brief.md").read_text()
            for fact in ("Whole transcript", "Ask again from box two", str(directory / "briefs/kit.md"),
                         str(directory / "briefs/b0.md"), fixes.ROLE.read_text().rstrip(), launcher[-1]):
                self.assertIn(fact, text)
            self.assertEqual(log.read(), [])

    def test_walk_report_missing_or_overlong_is_marked_at_byte_cap(self):
        for content, marker in ((None, "walk report unreadable:"),
                                ("x" * fixes.WALK_REPORT_BYTES, None),
                                ("x" * (fixes.WALK_REPORT_BYTES - 1) + "éTAIL", "truncated")):
            with self.subTest(marker=marker), tmp_home() as home:
                directory = write_ladder(home / "plan")
                plan = load_plan(directory / "plan.toml")
                if content is not None:
                    atomic.write(log.home() / "walks/walk-1/report.md", content)
                finding = findings.findings(records())["finding-1"]
                fake = FakeRunner().on(["ssh"], Result(0, "codex-finding /state/run\n"))
                fixes.start(finding, plan, directory, HOST, "main-tip", records(), sh=fake)
                text = (log.home() / "runs" / RUN / "brief.md").read_text()
                if marker:
                    self.assertIn(marker, text)
                else:
                    self.assertTrue(text.endswith(content))
                    self.assertNotIn("truncated", text)
                self.assertNotIn("TAIL", text)


class FixesSettleTest(unittest.TestCase):
    def test_settle_records_verdict_section_and_folded_state(self):
        cases = [("Done: fix: repair the cause\nwhere\n", "fix", "repairing", SECTION),
                 ("Done: retry: backend outage\nevidence", "left", "left", ""),
                 ("Failed: cannot decide", "none", "repairing", "")]
        for report, verdict, state, section in cases:
            with self.subTest(verdict=verdict), tmp_home() as home:
                events = records() + foreman_events()
                finding = findings.findings(events)["finding-1"]
                foreman_run = fixes.foremen(events)[finding.id]
                with patch.object(log, "now", return_value=STAMP) as now:
                    record = fixes.settle(finding, foreman_run, report, log_path=home / "events")
                self.assertEqual((record["ev"], record["finding"], record["run"], record["verdict"],
                                  record["section"]), (fixes.SETTLED, finding.id, RUN, verdict, section))
                self.assertEqual(record["reason"], {"fix": "repair the cause", "left": "backend outage",
                                                   "none": "no verdict: Failed: cannot decide"}[verdict])
                self.assertEqual(log.read(home / "events"), [record])
                self.assertEqual(findings.findings(events + [record])[finding.id].state, state)
                now.assert_called_once_with()
                self.assertEqual(log.read(), [])


class FixesTasksTest(unittest.TestCase):
    def setUp(self):
        self.home_context = tmp_home()
        self.home = self.home_context.__enter__()
        self.addCleanup(self.home_context.__exit__, None, None, None)
        self.plan = load_plan(write_ladder(self.home / "plan") / "plan.toml")

    def test_fix_none_and_all_nondone_fallbacks_create_specless_tasks(self):
        cases = [records() + foreman_events() + [settlement(verdict)] for verdict in ("fix", "none")]
        cases += [records() + foreman_events(outcome) for outcome in ("failed", "infra", "question", "lost")]
        for events in cases:
            with self.subTest(last=events[-1]):
                task, = fixes.tasks(self.plan, events).values()
                self.assertEqual((task.id, task.kind, task.part, task.repo, task.files, task.path,
                                  task.needs, task.effort, task.minutes),
                                 (TASK, "finding", "qa", "fabrig", ("**",), "", (), "high", 20))

    def test_no_task_before_settlement_left_or_for_another_draft(self):
        cases = [[], records(), records() + foreman_events(None), records() + foreman_events(),
                 records() + foreman_events() + [settlement("left")]]
        for events in cases:
            self.assertEqual(fixes.tasks(self.plan, events), {})
        self.assertEqual(fixes.tasks(replace(self.plan, draft="other"),
                                     records() + foreman_events() + [settlement()]), {})

    def test_body_keeps_triage_reason_merges_sections_answers_and_acceptance(self):
        events = records(merged=True) + foreman_events() + [settlement(),
                  log.record("refusal.settled", task=TASK, verdict="fix", section="## Refusal\n\nAdjust it\n"),
                  log.record("question.answered", task=TASK, answer="Use the fake model"),
                  log.record("question.answered", task=TASK, answer="Keep the story")]
        task = fixes.tasks(self.plan, events)[TASK]
        for fragment in ("# Repair a QA finding (finding-1)", "b0", "chatgpt-forgejo", "walk-1",
                         "commit", "edition", "jig tasks", "jig", "Blocks the ladder", "## The finding",
                         "Lost review", "Ask for a review", "Review completes", "Review disappears",
                         "walk-2", "Ask again from box two", SECTION, "## Refusal", "Adjust it",
                         "## Answers", "- Use the fake model", "- Keep the story", "## Acceptance",
                         "lowest world", "red on main", "green after", "why it is the lowest",
                         "docs/design/", "status file", "temper/docs/help/", "help tests",
                         "precheck --onto origin/main"):
            self.assertIn(fragment, task.body)
        self.assertLess(task.body.index(SECTION), task.body.index("## Refusal"))
        self.assertLess(task.body.index("Use the fake model"), task.body.index("Keep the story"))

    def test_late_merge_updates_one_existing_repair_and_preserves_raise_order(self):
        events = records() + foreman_events() + [settlement()]
        self.assertEqual(list(fixes.tasks(self.plan, events)), [TASK])
        events += records(merged=True)[3:]
        self.assertEqual(list(fixes.tasks(self.plan, events)), [TASK])
        self.assertIn("Ask again from box two", fixes.tasks(self.plan, events)[TASK].body)
        events += [finding_raised("finding-3", "walk-3", "b0"),
                   walk_ended("walk-3", "fail", ("finding-3",)),
                   finding_triaged("finding-3", "path"),
                   run_started("ladder/finding-3/foreman", kind="foreman", finding="finding-3", tip="tip", ts=STAMP),
                   run_ended("ladder/finding-3/foreman", outcome="infra", ts=STAMP)]
        self.assertEqual(list(fixes.tasks(self.plan, events)), [TASK, "ladder/finding-3"])

    def test_repair_survives_landing_pass_and_recurrence(self):
        events = records() + foreman_events() + [settlement()]
        landed = log.record("branch.landed", task=TASK, branch=TASK, tip="repair", main="landed", into="main")
        stages = [[landed], [rung_passed("b0")],
                  [finding_raised("finding-3", "walk-3", "b0", again="finding-1"),
                   walk_ended("walk-3", "fail", ("finding-3",))]]
        for stage, state in zip(stages, ("landed", "fixed", "unfixed")):
            events += stage
            self.assertEqual(findings.findings(events)["finding-1"].state, state)
            self.assertEqual(list(fixes.tasks(self.plan, events)), [TASK])

    def test_first_settlement_wins_and_wrong_run_or_early_settlement_is_ignored(self):
        start, end = foreman_events()
        events = records() + [end, settlement(), start, settlement(), end, settlement(run="other")]
        self.assertEqual(fixes.tasks(self.plan, events), {})
        self.assertEqual(fixes.tasks(self.plan, events + [settlement("left"), settlement()]), {})
        self.assertEqual(fixes.tasks(self.plan, events + [settlement(), settlement("left")])[TASK].body.count(SECTION), 1)

    def test_later_foreman_cannot_replace_fallback_or_create_a_second_repair(self):
        events = records() + foreman_events("infra")
        events += [run_started(FOREMAN_TASK, n=2, kind="foreman", finding="finding-1", tip="later", ts=STAMP),
                   run_ended(FOREMAN_TASK, n=2, ts=STAMP), settlement(run=FOREMAN_TASK + "-2")]
        self.assertEqual(list(fixes.tasks(self.plan, events)), [TASK])
        self.assertNotIn(SECTION, fixes.tasks(self.plan, events)[TASK].body)
