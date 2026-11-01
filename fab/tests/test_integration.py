"""Integration decisions over events and the builder command through fakes (fab.md, 4)."""

import io
import json
import unittest
from contextlib import redirect_stdout
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import patch

from fab import atomic, cli, integration, log
from fab.plan import Plan, Task
from fab.sh import Result
from fab.tests.support import FakeRunner, call_ended, call_started, run_ended, run_started, tmp_home


PLAN = Plan("demo", "fabrig", (), 1, 2, {}, (), landing="integration")
TASK = Task("demo/a", "core", "feature", "fabrig", (), (), "high", 20, "", "task.md")


def merged(tip="tip", task="demo/a"):
    return dict(ev="branch.landed", task=task, into=PLAN.trunk, main=tip, tip="branch-tip")


def checked(n=1, outcome="done", tip="tip"):
    return [run_started("demo/integration", n, kind="check", base=tip),
            run_ended("demo/integration", n, outcome)]


class IntegrationTest(unittest.TestCase):
    def test_trunk_landed_requires_its_queue_landing(self):
        with tmp_home():
            self.assertFalse(integration.trunk_landed(PLAN, []))
            ignored = [merged(), merged(task="demo/integration"),
                       dict(ev="branch.landed", task="demo/a", queue_ts="task-landed"),
                       dict(ev="branch.landed", task="other/integration", queue_ts="other-landed"),
                       dict(ev="branch.rejected", task="demo/integration", queue_ts="rejected"),
                       dict(ev="branch.ready", task="demo/integration", queue_ts="ready")]
            for event in ignored:
                with self.subTest(event=event):
                    self.assertFalse(integration.trunk_landed(PLAN, [event]))
            for queue_ts in ("landed", "", None):
                with self.subTest(queue_ts=queue_ts):
                    landed = dict(ev="branch.landed", task="demo/integration", queue_ts=queue_ts)
                    self.assertTrue(integration.trunk_landed(PLAN, [*ignored, landed, *ignored]))
                    self.assertIsNone(integration.queue_step(PLAN, [landed], "tip"))

    def test_red_tasks_do_not_hold_the_end_check_or_appear_as_pending_work(self):
        red = replace(TASK, id="demo/red-1", kind="red", part="after-landing", path="")
        tasks = {TASK.id: TASK, red.id: red}
        self.assertEqual(integration.next_step(PLAN, tasks, [merged()]), integration.Step("check", "tip", "tip"))
        events = [dict(merged(), ts="2026-11-01T00:00:00Z")]
        events += [dict(record, mid=True, ts="2026-11-01T00:01:00Z") for record in checked(outcome="failed")]
        repair, = integration.repair_tasks(PLAN, events, {}, tasks).values()
        self.assertNotIn("demo/red-1", repair.body)
        self.assertNotIn("## Not merged yet", repair.body)

    def test_finding_tasks_do_not_hold_the_end_check(self):
        with tmp_home():
            finding = replace(TASK, id="demo/finding-1", kind="finding", part="qa", path="")
            tasks = {TASK.id: TASK, finding.id: finding}
            self.assertEqual(integration.next_step(PLAN, tasks, [merged()]),
                             integration.Step("check", "tip", "tip"))
            self.assertEqual(integration.next_step(PLAN, tasks, [merged(), *checked()]),
                             integration.Step("ready", "tip", "tip"))

    def test_mid_check_pending_work_excludes_finding_tasks(self):
        with tmp_home():
            finding = replace(TASK, id="demo/finding-1", kind="finding", part="qa", path="")
            pending = replace(TASK, id="demo/b")
            tasks = {TASK.id: TASK, finding.id: finding, pending.id: pending}
            events = [dict(merged(), ts="2026-11-01T00:00:00Z")]
            events += [dict(record, mid=True, ts="2026-11-01T00:01:00Z")
                       for record in checked(outcome="failed")]
            repair, = integration.repair_tasks(PLAN, events, {}, tasks).values()
            self.assertIn("## Not merged yet", repair.body)
            self.assertIn("- demo/b:", repair.body)
            self.assertNotIn(finding.id, repair.body)
            self.assertNotIn("- demo/a:", repair.body)

    def test_refusal_fix_appends_to_a_specless_integrations_repair(self):
        events = [merged(), *checked(outcome="failed"),
                  dict(ev="refusal.settled", task="demo/repair-1", verdict="fix", section="## Repair\n\nFix the test.\n")]
        body = integration.repair_tasks(PLAN, events, {})["demo/repair-1"].body
        self.assertTrue(body.endswith("## Repair\n\nFix the test.\n"))

    def test_trunk_tip_uses_only_last_merge_into_own_trunk(self):
        self.assertIsNone(integration.trunk_tip(PLAN, []))
        events = [merged(), merged("new"), {**merged("foreign"), "into": "other/integration"},
                  {**merged("main"), "into": None}]
        self.assertEqual(integration.trunk_tip(PLAN, events), "new")

    def test_repair_tasks_order_contract_and_report_limit(self):
        events = [merged()] + checked(1, "failed") + checked(2, "done") + checked(3, "failed", "new")
        events += [run_started("foreign/integration", kind="check"), run_ended("foreign/integration", outcome="failed")]
        reports = {"demo/integration-1": "\n".join(f"line {n}" for n in range(130)),
                   "demo/integration-3": "Failed: fmt red\nfmt:1:0.1"}
        tasks = integration.repair_tasks(PLAN, events, reports)
        self.assertEqual(list(tasks), ["demo/repair-1", "demo/repair-2"])
        first, second = tasks.values()
        self.assertEqual((first.part, first.kind, first.repo, first.files, first.effort, first.minutes, first.path),
                         ("integration", "repair", "fabrig", ("**",), "high", 20, ""))
        self.assertIn("`tip`", first.body)
        self.assertIn("`demo/integration-1`", first.body)
        self.assertIn("line 119\n", first.body)
        self.assertNotIn("line 120", first.body)
        for fragment in ("trunk with this change", "narrowest checks first", "failing step itself"):
            self.assertIn(fragment, first.body)
        self.assertIn("`new`", second.body)
        self.assertIn(reports["demo/integration-3"], second.body)
        self.assertEqual(integration.repair_tasks(replace(PLAN, landing="queue"), events, reports), {})
        self.assertEqual(len(integration.repair_tasks(PLAN, events, {})), 2)

    def test_a_repairs_answers_fold_into_its_body(self):
        events = [merged()] + checked(1, "failed")
        events += [dict(ev="question.answered", task="demo/repair-1", answer="Update the journeys."),
                   dict(ev="question.answered", task="demo/repair-1"),
                   dict(ev="question.answered", task="demo/other", answer="Not this one.")]
        body = integration.repair_tasks(PLAN, events, {})["demo/repair-1"].body
        self.assertTrue(body.endswith("## Answers\n\n- Update the journeys.\n"))
        self.assertNotIn("Not this one", body)
        self.assertNotIn("## Answers", integration.repair_tasks(PLAN, events[:-3], {})["demo/repair-1"].body)

    def test_checks_along_the_way(self):
        tasks = {f"demo/t{n}": replace(TASK, id=f"demo/t{n}") for n in range(12)}
        def landed(n, ts):
            return dict(merged(f"tip{n}", task=f"demo/t{n}"), ts=ts)
        ten = [landed(n, f"2026-11-01T10:{n:02d}:00Z") for n in range(10)]
        step = integration.next_step(PLAN, tasks, ten)
        self.assertEqual((step.kind, step.tip), ("mid-check", "tip9"))
        self.assertIsNone(integration.next_step(PLAN, tasks, ten[:3]))
        later = ten[:3] + [dict(ev="note", ts="2026-11-01T10:50:00Z")]
        self.assertEqual(integration.next_step(PLAN, tasks, later).kind, "mid-check")
        # A mid check's reds never stop the plan, and its repair says what is not merged yet.
        reds = list(ten)
        for n in range(1, 4):
            reds += [dict(run_started("demo/integration", n, kind="check", base=f"tip{9}", mid=True,
                                      ts="2026-11-01T10:20:00Z")), run_ended("demo/integration", n, "failed")]
        self.assertIsNone(integration.next_step(PLAN, tasks, reds))  # repairs are open, not a stop
        repair = integration.repair_tasks(PLAN, reds, {}, tasks)["demo/repair-1"]
        self.assertIn("## Not merged yet", repair.body)
        self.assertIn("- demo/t11:", repair.body)
        self.assertNotIn("- demo/t3:", repair.body)

    def test_catch_up_along_the_way_precedes_mid_check(self):
        tasks = {TASK.id: TASK, "demo/b": replace(TASK, id="demo/b")}
        first = dict(merged(), ts="2026-11-01T10:00:00Z")
        def at(minutes):
            return [first, dict(ev="note", ts=f"2026-11-01T10:{minutes:02d}:00Z")]
        self.assertIsNone(integration.next_step(PLAN, tasks, at(29), main="main-sha"))
        step = integration.next_step(PLAN, tasks, at(30), main="main-sha")
        self.assertEqual((step.kind, step.tip), ("catch-up", "tip"))
        self.assertEqual(integration.next_step(PLAN, tasks, at(45), main="main-sha").kind, "catch-up")
        self.assertEqual(integration.next_step(PLAN, tasks, at(45)).kind, "mid-check")
        self.assertIsNone(integration.next_step(replace(PLAN, ready=False), tasks, at(30), main="main-sha"))
        self.assertIsNone(integration.next_step(PLAN, tasks, at(30)))
        self.assertIsNone(integration.next_step(PLAN, tasks,
                           [call_started("cut", "cut", "demo/cut"), *at(45)], main="main-sha"))
        self.assertEqual(integration.next_step(PLAN, {TASK.id: TASK}, at(30), main="main-sha").kind, "check")
        ready = at(30) + checked() + [dict(ev="branch.ready", task="demo/integration", tip="tip")]
        self.assertIsNone(integration.next_step(PLAN, {TASK.id: TASK}, ready, main="main-sha"))
        reds = at(45) + checked(outcome="failed")
        repairs = integration.repair_tasks(PLAN, reds, {})
        self.assertIsNone(integration.next_step(PLAN, {**tasks, **repairs}, reds, main="main-sha"))

    def test_catch_up_clock_uses_last_merge_or_refusal_and_ignores_other_plans(self):
        tasks = {TASK.id: TASK, "demo/b": replace(TASK, id="demo/b")}
        first = dict(merged(), ts="2026-11-01T10:00:00Z")
        for catch in (dict(ev="branch.landed", task="demo/integration", branch="main", into=PLAN.trunk,
                           main="caught", tip="main-sha"),
                      dict(ev="branch.rejected", task="demo/integration", step=integration.CATCH_UP,
                           main="main-sha", tip="tip")):
            with self.subTest(catch=catch):
                events = [first, dict(catch, ts="2026-11-01T10:20:00Z")]
                repairs = integration.repair_tasks(PLAN, events, {})
                if repairs:
                    events += [dict(merged("fixed", "demo/catch-up-1"), ts="2026-11-01T10:21:00Z")]
                events += [dict(ev="note", ts="2026-11-01T10:49:00Z")]
                self.assertNotEqual(getattr(integration.next_step(PLAN, {**tasks, **repairs}, events, main="new"),
                                            "kind", None), "catch-up")
                events += [dict(catch, task="other/integration", ts="2026-11-01T10:50:00Z")]
                self.assertEqual(integration.next_step(PLAN, {**tasks, **repairs}, events, main="new").kind,
                                 "catch-up")

    def test_catch_up_merges_do_not_count_toward_mid_every_or_start_the_clock(self):
        tasks = {f"demo/t{n}": replace(TASK, id=f"demo/t{n}") for n in range(11)}
        catch = dict(ev="branch.landed", task="demo/integration", branch="main", into=PLAN.trunk,
                     main="caught", tip="main-sha", ts="2026-11-01T10:10:00Z")
        self.assertIsNone(integration.next_step(PLAN, tasks, [catch], main="new"))
        events = [dict(merged(f"tip{n}", f"demo/t{n}"), ts=f"2026-11-01T10:{n:02d}:00Z")
                  for n in range(9)]
        self.assertIsNone(integration.next_step(PLAN, tasks, [*events, catch]))
        self.assertEqual(integration.next_step(PLAN, tasks,
                         [*events, catch, dict(merged("tip9", "demo/t9"), ts="2026-11-01T10:11:00Z")]).kind,
                         "mid-check")

    def test_repair_merges_count_toward_mid_every(self):
        tasks = {f"demo/t{n}": replace(TASK, id=f"demo/t{n}") for n in range(11)}
        events = [dict(merged(f"tip{n}", f"demo/t{n}"), ts=f"2026-11-01T10:{n:02d}:00Z")
                  for n in range(integration.MID_EVERY - 1)]
        for name in ("repair-1", "catch-up-1"):
            with self.subTest(repair=name):
                repair = replace(TASK, id=f"demo/{name}", kind="repair", path="")
                pending = {**tasks, repair.id: repair}
                self.assertIsNone(integration.next_step(PLAN, pending, events))
                landed = dict(merged("repaired", repair.id), ts="2026-11-01T10:10:00Z")
                step = integration.next_step(PLAN, pending, [*events, landed])
                self.assertEqual((step.kind, step.tip), ("mid-check", "repaired"))

    def test_three_refusals_without_a_clean_catch_up_stop_without_a_third_repair(self):
        self.assertEqual(integration.CATCH_LIMIT, 3)
        events = [merged()]
        for n in range(1, 3):
            events += [dict(ev="branch.rejected", task="demo/integration", step=integration.CATCH_UP,
                            main=f"main-{n}", tip="tip")]
        clean = dict(ev="branch.landed", task="demo/integration", branch="main", into=PLAN.trunk,
                     tip="main-2", main="tip")
        # Only this plan's main landing into its trunk resets the count.
        for unrelated in (dict(clean, task="other/integration"), dict(clean, into="other/integration"),
                          dict(clean, branch="other")):
            events.append(unrelated)
        events.append(dict(ev="branch.rejected", task="demo/integration", step=integration.CATCH_UP,
                           main="main-3", tip="tip"))
        repairs = integration.repair_tasks(PLAN, events, {})
        self.assertEqual(list(repairs), ["demo/catch-up-1", "demo/catch-up-2"])
        self.assertEqual(integration.next_step(PLAN, repairs, events, main="main-3").kind, "stop")

    def test_both_catch_up_stops_clear_only_after_a_clean_catch_up(self):
        clean = dict(ev="branch.landed", task="demo/integration", branch="main", into=PLAN.trunk,
                     tip="main-0", main="tip")
        for repeated in (True, False):
            with self.subTest(repeated=repeated):
                events = [merged(), clean]
                for n in range(1, 3 if repeated else 4):
                    events.append(dict(ev="branch.rejected", task="demo/integration", step=integration.CATCH_UP,
                                       main="main-1" if repeated else f"main-{n}", tip="tip"))
                    if repeated and n == 1:
                        events.append(merged("tip", f"demo/catch-up-{n}"))
                repairs = integration.repair_tasks(PLAN, events, {})
                self.assertEqual(integration.next_step(PLAN, repairs, events, main="moved", trunk="hand").kind,
                                 "stop")
                self.assertEqual(integration.next_step(PLAN, repairs, events).kind, "stop")
                self.assertEqual(integration.next_step(replace(PLAN, ready=False), repairs, events,
                                                      trunk="hand", caught=True).kind, "stop")
                waiting = "main-1" if repeated else "main-3"
                self.assertEqual(integration.catch_up_waiting(PLAN, events), waiting)
                self.assertEqual(integration.next_step(PLAN, repairs, events, trunk="hand").kind, "stop")
                self.assertEqual(integration.next_step(PLAN, repairs, events, main="moved", trunk="hand", caught=True),
                                 integration.Step("caught", "hand", "main caught up by hand"))
                events.append(dict(clean, tip=waiting, main="hand", by="hand"))
                self.assertIsNone(integration.catch_up_waiting(PLAN, events))
                self.assertEqual(integration.next_step(PLAN, repairs, events),
                                 integration.Step("check", "hand", "hand") if repeated else None)

    def test_any_clean_catch_up_restarts_refusal_count_and_keeps_repair_numbers(self):
        for by in (None, "repair", "hand"):
            with self.subTest(by=by):
                events = [merged()]
                for n in range(1, 3):
                    events.append(dict(ev="branch.rejected", task="demo/integration", step=integration.CATCH_UP,
                                       main=f"main-{n}", tip="tip"))
                clean = dict(ev="branch.landed", task="demo/integration", branch="main", into=PLAN.trunk,
                             tip="main-2", main="caught")
                events.append(clean if by is None else dict(clean, by=by))
                for n in range(3, 6):
                    events.append(dict(ev="branch.rejected", task="demo/integration", step=integration.CATCH_UP,
                                       main=f"main-{n}", tip="caught"))
                    repairs = integration.repair_tasks(PLAN, events, {})
                    self.assertEqual(len(repairs), min(n, 4))
                    step = integration.next_step(PLAN, repairs, events, main=f"main-{n}")
                    if n < 5:
                        self.assertIsNone(step)
                        self.assertIn(f"demo/catch-up-{n}", repairs)
                    else:
                        self.assertEqual(step.kind, "stop")
                        self.assertNotIn("demo/catch-up-5", repairs)

    def test_catch_up_main_uses_the_numbered_refusal_and_ignores_other_events(self):
        refusal = dict(ev="branch.rejected", task="demo/integration", step=integration.CATCH_UP,
                       main="main-1", tip="tip")
        clean = dict(ev="branch.landed", task="demo/integration", branch="main", into=PLAN.trunk,
                     tip="main-1", main="caught", by="repair")
        events = [refusal, merged("caught", "demo/catch-up-1"), clean,
                  dict(refusal, task="other/integration"), dict(refusal, step="default"),
                  dict(refusal, main="main-2")]
        self.assertEqual(integration.catch_up_main(PLAN, events, "demo/catch-up-1"), "main-1")
        self.assertEqual(integration.catch_up_main(PLAN, events, "demo/catch-up-2"), "main-2")
        for identifier in ("demo/catch-up-3", "demo/repair-1", "other/catch-up-1"):
            self.assertIsNone(integration.catch_up_main(PLAN, events, identifier))
        self.assertIsNone(integration.catch_up_waiting(PLAN, events))

    def test_catch_up_repairs_fold_in_log_order_with_separate_numbers_and_answers(self):
        refusal = dict(ev="branch.rejected", task="demo/integration", step=integration.CATCH_UP,
                       main="main-sha", tip="trunk-tip", findings="CONFLICT: crate/src/lib.rs")
        events = [merged(), refusal, *checked(outcome="failed"),
                  dict(refusal, main="newer-sha"),
                  dict(ev="question.answered", task="demo/catch-up-1", answer="Keep both formats."),
                  dict(ev="question.answered", task="demo/catch-up-1", answer="Add a fixture."),
                  dict(ev="question.answered", task="demo/catch-up-1"),
                  dict(refusal, task="other/integration")]
        repairs = integration.repair_tasks(PLAN, events, {})
        self.assertEqual(list(repairs), ["demo/catch-up-1", "demo/repair-1", "demo/catch-up-2"])
        repair = repairs["demo/catch-up-1"]
        self.assertEqual((repair.kind, repair.files, repair.path, repair.needs), ("repair", ("**",), "", ()))
        for fragment in ("`trunk-tip`", "`main-sha`", "CONFLICT: crate/src/lib.rs", "Merge that main sha",
                         "both sides' intent", "other drafts' landed work", "Fix what main's changes break",
                         "push", "contains the main sha", "no conflict markers", "build and pass clippy",
                         "their tests", "next check runs the rest"):
            self.assertIn(fragment, repair.body)
        self.assertTrue(repair.body.endswith("## Answers\n\n- Keep both formats.\n- Add a fixture.\n"))

    def test_catch_up_refusal_waits_for_repair_and_only_repeated_repaired_sha_stops(self):
        tasks = {TASK.id: TASK}
        refusal = dict(ev="branch.rejected", task="demo/integration", step=integration.CATCH_UP,
                       main="main-sha", tip="tip", ts="2026-11-01T10:00:00Z")
        events = [dict(merged(), ts="2026-11-01T09:00:00Z"), refusal,
                  dict(ev="note", ts="2026-11-01T10:30:00Z")]
        def step():
            repairs = integration.repair_tasks(PLAN, events, {})
            return integration.next_step(PLAN, {**tasks, **repairs}, events, main="newer-sha")
        self.assertIsNone(step())
        foreign = events + [dict(merged("foreign", "demo/catch-up-1"), into="other/integration"), refusal]
        self.assertEqual(list(integration.repair_tasks(PLAN, foreign, {})),
                         ["demo/catch-up-1", "demo/catch-up-2"])
        events += [merged("fixed", "demo/catch-up-1")]
        self.assertEqual(step().kind, "check")
        tasks["demo/b"] = replace(TASK, id="demo/b")
        self.assertEqual(step().kind, "catch-up")
        events += [dict(refusal, tip="fixed")]
        self.assertEqual(list(integration.repair_tasks(PLAN, events, {})), ["demo/catch-up-1"])
        self.assertEqual(step(), integration.Step("stop", "fixed",
                         "main catch-up refused repeatedly; needs judgement", why="catch-up"))
        events[-1] = dict(refusal, tip="fixed", main="newer-sha")
        self.assertEqual(list(integration.repair_tasks(PLAN, events, {})),
                         ["demo/catch-up-1", "demo/catch-up-2"])
        self.assertIsNone(step())
        events += [merged("fixed-again", "demo/catch-up-2")]
        del tasks["demo/b"]
        self.assertEqual(step().kind, "check")

    def test_checked_catch_up_repairs_never_count_as_three_reds_and_end_check_ignores_mid(self):
        events = [merged()]
        for n in range(1, 4):
            events += [dict(ev="branch.rejected", task="demo/integration", step=integration.CATCH_UP,
                            main=f"main-{n}", tip=f"tip{n-1}"),
                       merged(f"tip{n}", f"demo/catch-up-{n}"),
                       dict(ev="branch.landed", task="demo/integration", branch="main", into=PLAN.trunk,
                            main=f"tip{n}", tip=f"main-{n}", by="repair")]
        tasks = integration.repair_tasks(PLAN, events, {})
        self.assertEqual(integration.next_step(PLAN, tasks, events), integration.Step("check", "tip3", "tip3"))
        events += [dict(run_started("demo/integration", 1, kind="check", base="tip3"), mid=True),
                   run_ended("demo/integration", 1)]
        self.assertEqual(integration.next_step(PLAN, tasks, events), integration.Step("check", "tip3", "tip3"))
        events += checked(2, tip="tip3")
        self.assertEqual(integration.next_step(PLAN, tasks, events), integration.Step("ready", "tip3", "tip3"))

    def test_a_check_before_any_task_merged_is_ignored(self):
        cut = merged("cut-tip", task="calls/cut-1")
        self.assertIsNone(integration.next_step(PLAN, {}, [cut]))
        early = [cut, *checked(1, "failed", tip="cut-tip")]
        self.assertEqual(integration.repair_tasks(PLAN, early, {}), {})
        events = early + [merged()]
        self.assertEqual(integration.repair_tasks(PLAN, events, {}), {})
        self.assertEqual(integration.next_step(PLAN, {TASK.id: TASK}, events),
                         integration.Step("check", "tip", "tip"))

    def test_next_step_waits_for_merge_and_tasks_and_check(self):
        tasks = {TASK.id: TASK}
        self.assertIsNone(integration.next_step(replace(PLAN, landing="queue"), {}, [merged()]))
        self.assertIsNone(integration.next_step(PLAN, {}, []))
        self.assertIsNone(integration.next_step(PLAN, tasks, [merged(task="demo/other")]))
        events = [merged()]
        step = integration.next_step(PLAN, tasks, events)
        self.assertEqual(step, integration.Step("check", "tip", "tip"))
        with self.assertRaises(FrozenInstanceError):
            step.kind = "ready"
        self.assertIsNone(integration.next_step(PLAN, tasks, events + checked()[:1]))
        self.assertEqual(integration.next_step(PLAN, tasks, events + checked(tip="old")), step)

    def test_next_step_waits_for_own_cut_until_it_ends(self):
        tasks = {TASK.id: TASK}
        events = [merged()]
        cut = call_started("cut", "cut", "demo/cut")
        step = integration.Step("check", "tip", "tip")
        for reviews in (False, True):
            with self.subTest(reviews=reviews):
                the_plan = replace(PLAN, reviews=reviews)
                self.assertIsNone(integration.next_step(the_plan, tasks, [cut, *events]))
                self.assertEqual(integration.next_step(the_plan, tasks,
                                                       [cut, *events, call_ended("cut")]), step)
        for role, subject in (("cut", "other/cut"), ("skeleton", "demo/cut"),
                              ("cut", "demo/cut-more")):
            with self.subTest(role=role, subject=subject):
                self.assertEqual(integration.next_step(PLAN, tasks,
                                                       [call_started("other", role, subject), *events]), step)
        self.assertIsNone(integration.next_step(PLAN, tasks, [cut, *events, *checked()]))
        self.assertIsNone(integration.next_step(PLAN, tasks,
                                               [cut, *events, *checked(1, "failed"),
                                                *checked(2, "failed"), *checked(3, "failed")]))

    def test_next_step_green_readies_once_or_stops_without_ready(self):
        events = [merged()] + checked()
        self.assertEqual(integration.next_step(PLAN, {}, events), integration.Step("ready", "tip", "tip"))
        self.assertIsNone(integration.next_step(replace(PLAN, ready=False), {}, events))
        events.append(dict(ev="branch.ready", task="foreign/integration", tip="tip"))
        self.assertIsNotNone(integration.next_step(PLAN, {}, events))
        events.append(dict(ev="branch.ready", task="demo/integration", tip="tip"))
        self.assertIsNone(integration.next_step(PLAN, {}, events))

    def test_a_queue_rejection_checks_again_then_readies_and_a_landing_ends(self):
        ready = dict(ev="branch.ready", task="demo/integration", tip="tip")
        rejected = dict(ev="branch.rejected", task="demo/integration", tip="tip", step="default",
                        queue_ts="t1")
        events = [merged(), *checked(), ready]
        self.assertIsNone(integration.next_step(PLAN, {}, events))
        events.append(rejected)
        self.assertEqual(integration.next_step(PLAN, {}, events),
                         integration.Step("check", "tip", "queue rejected default: catch up and check again"))
        events += checked(2)
        self.assertEqual(integration.next_step(PLAN, {}, events), integration.Step("ready", "tip", "tip"))
        events.append(ready)
        self.assertIsNone(integration.next_step(PLAN, {}, events))
        landed = dict(ev="branch.landed", task="demo/integration", tip="tip", main="m", queue_ts="t2")
        self.assertIsNone(integration.next_step(PLAN, {}, [*events, rejected, landed]))

    def test_a_trunk_caught_up_with_main_is_readied_at_its_new_tip(self):
        events = [merged(), *checked(), dict(ev="branch.ready", task="demo/integration", tip="tip"),
                  dict(ev="branch.rejected", task="demo/integration", tip="tip", step="merge", queue_ts="t1"),
                  dict(ev="branch.landed", task="demo/integration", branch="main", into=PLAN.trunk,
                       main="caught", tip="main-tip")]
        self.assertEqual(integration.next_step(PLAN, {}, events), integration.Step("check", "caught", "caught"))
        events += checked(2, tip="caught")
        self.assertEqual(integration.next_step(PLAN, {}, events), integration.Step("ready", "caught", "caught"))

    def test_three_queue_rejections_stop(self):
        rejections = [dict(ev="branch.rejected", task="demo/integration", tip="tip", step="default",
                           queue_ts=f"t{n}") for n in range(integration.QUEUE_LIMIT)]
        step = integration.next_step(PLAN, {}, [merged(), *checked(), *rejections])
        self.assertEqual((step.kind, step.why), ("stop", "queue"))

    def test_next_step_red_waits_for_repair_then_checks_new_tip_and_third_red_stops(self):
        events = [merged()] + checked(outcome="failed")
        tasks = integration.repair_tasks(PLAN, events, {})
        self.assertIsNone(integration.next_step(PLAN, {}, events))
        self.assertIsNone(integration.next_step(PLAN, tasks, events))
        events.append(merged("fixed", "demo/repair-1"))
        self.assertEqual(integration.next_step(PLAN, tasks, events), integration.Step("check", "fixed", "fixed"))
        events += checked(2, "failed", "fixed") + checked(3, "failed", "fixed")
        self.assertEqual(integration.next_step(PLAN, integration.repair_tasks(PLAN, events, {}), events),
                         integration.Step("stop", "fixed", "red 3 times; needs judgement", why="red"))

    def test_baselines_accepts_only_known_baseline_paths(self):
        self.assertEqual(integration.baselines(["smith/scripts/old-forms.txt", "skein/scripts/old-forms.txt"]),
                         ["skein", "smith"])
        for paths in ([], ["scripts/old-forms.txt"], ["unknown/scripts/old-forms.txt"],
                      ["skein/scripts/old-forms.txt", "skein/src/lib.rs"]):
            self.assertEqual(integration.baselines(paths), [])

    def test_recount_commands_and_failure(self):
        fake = FakeRunner()
        integration.recount(Path("/checkout"), ["skein"], sh=fake)
        self.assertEqual(fake.argvs(), [["git", "checkout", "--ours", "--", "skein/scripts/old-forms.txt"],
                                      ["python3", "-I", "-B", "scripts/old_forms.py", "--write"],
                                      ["git", "add", "--", "skein/scripts/old-forms.txt"]])
        self.assertEqual([call.cwd for call in fake.calls], ["/checkout", "/checkout/skein", "/checkout"])


class IntegrationStopTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(tmp_home())
        red = [merged()]
        for n in range(1, 4):
            red += checked(n, "failed")
        queue = [merged(), *checked()]
        queue += [dict(ev="branch.rejected", task="demo/integration", tip="tip", queue_ts=f"t{n}",
                       log=f"/queue/check-{n}.log") for n in range(1, 4)]
        catch = [merged()]
        catch += [dict(ev="branch.rejected", task="demo/integration", tip="tip", main=f"main-{n}",
                       step=integration.CATCH_UP, findings=f"conflict {n}") for n in range(1, 4)]
        self.causes = {"red": red, "queue": queue, "catch-up": catch}

    def test_lifted_uses_log_position_and_only_the_integration_answer(self):
        self.assertEqual(integration.lifted(PLAN, []), -1)
        events = [dict(ev="question.answered", task="demo/repair-1"),
                  dict(ev="question.answered", task="other/integration"),
                  dict(ev="question.asked", task="demo/integration")]
        self.assertEqual(integration.lifted(PLAN, events), -1)
        events += [dict(ev="question.answered", task="demo/integration", ts="later"),
                   dict(ev="question.answered", task="demo/integration", ts="earlier"),
                   dict(ev="question.answered", task="demo/repair-2")]
        self.assertEqual(integration.lifted(PLAN, events), 4)

    def test_red_stop_records_last_failed_end_check_report_and_run(self):
        events = self.causes["red"]
        events += [dict(entry, mid=True) for entry in checked(4, "failed")]
        events += checked(5) + [run_started("other/integration", kind="check"),
                                run_ended("other/integration", outcome="failed")]
        step = integration.next_step(PLAN, {}, events)
        self.assertEqual(step.why, "red")
        self.assertEqual(integration.stopped(PLAN, events, step, "gate"), [
            ("plan.stopped", dict(task="demo/integration", tip="tip", why="red", text=step.detail,
                                 report=str(log.home() / "runs/demo/integration-3/report.md"))),
            ("question.asked", dict(task="demo/integration", run="demo/integration-3", text=step.detail, park=True))])

    def test_queue_stop_records_last_imported_rejection_on_the_gate(self):
        events = self.causes["queue"]
        events += [dict(ev="branch.rejected", task="demo/integration", log="/not-imported"),
                   dict(ev="branch.rejected", task="other/integration", queue_ts="foreign", log="/foreign")]
        step = integration.next_step(PLAN, {}, events)
        self.assertEqual(step.why, "queue")
        self.assertEqual(integration.stopped(PLAN, events, step, "gate"), [
            ("plan.stopped", dict(task="demo/integration", tip="tip", why="queue", text=step.detail,
                                 report="gate:/queue/check-3.log")),
            ("question.asked", dict(task="demo/integration", run="", text=step.detail, park=True))])

    def test_catch_up_stop_quotes_twenty_lines_from_the_stopping_refusal(self):
        events = self.causes["catch-up"]
        events += [dict(ev="branch.landed", task="demo/integration", branch="main", into=PLAN.trunk,
                        tip="main-3", main="tip"), *self.causes["catch-up"][1:]]
        events[-1] = dict(events[-1], findings="\n".join(f"conflict line {n}" for n in range(25)))
        events += [dict(events[-1], findings="a later refusal"),
                   dict(events[-1], task="other/integration", findings="foreign refusal")]
        step = integration.next_step(PLAN, {}, events)
        self.assertEqual(step.why, "catch-up")
        text = step.detail + "\n\n" + "\n".join(f"conflict line {n}" for n in range(20))
        self.assertEqual(integration.stopped(PLAN, events, step, "gate"), [
            ("plan.stopped", dict(task="demo/integration", tip="tip", why="catch-up", text=text, report="")),
            ("question.asked", dict(task="demo/integration", run="", text=text, park=True))])

    def test_repaired_main_sha_refused_again_records_that_refusals_findings(self):
        events = self.causes["catch-up"][:2]
        events += [merged("repaired", "demo/catch-up-1"),
                   dict(events[-1], tip="repaired", findings="still conflicts after repair")]
        step = integration.next_step(PLAN, {}, events)
        self.assertEqual(step.why, "catch-up")
        text = step.detail + "\n\nstill conflicts after repair"
        self.assertEqual(integration.stopped(PLAN, events, step, "gate"), [
            ("plan.stopped", dict(task="demo/integration", tip="repaired", why="catch-up", text=text, report="")),
            ("question.asked", dict(task="demo/integration", run="", text=text, park=True))])

    def test_stops_ask_once_across_merges_and_ask_again_after_their_answer(self):
        for why, events in self.causes.items():
            with self.subTest(why=why):
                events += [dict(ev="plan.stopped", task="other/integration")]
                step = integration.next_step(PLAN, {}, events)
                records = integration.stopped(PLAN, events, step, "gate")
                self.assertEqual([ev for ev, fields in records], ["plan.stopped", "question.asked"])
                ev, fields = records[0]
                events += [dict(ev=ev, **fields)]
                self.assertEqual(integration.stopped(PLAN, events, step, "gate"), [])
                events += [merged("new-tip", "demo/repair-1"),
                           dict(ev="question.answered", task="other/integration"),
                           dict(ev="question.answered", task="demo/repair-1")]
                step = replace(step, tip="new-tip")
                self.assertEqual(integration.stopped(PLAN, events, step, "gate"), [])
                events += [dict(ev="question.answered", task="demo/integration")]
                again = integration.stopped(PLAN, events, step, "gate")
                self.assertEqual([ev for ev, fields in again], ["plan.stopped", "question.asked"])
                self.assertEqual(again[0][1]["tip"], "new-tip")
                events += [dict(ev=ev, **fields) for ev, fields in again]
                self.assertEqual(integration.stopped(PLAN, events, step, "gate"), [])

    def test_other_steps_record_no_stop(self):
        step = integration.Step("ready", "tip", "tip")
        self.assertEqual(step.why, "")
        self.assertEqual(integration.stopped(PLAN, [], step, ""), [])


class IntegrationCommandTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.brief, self.report = self.home / "brief.md", self.home / "report.md"
        atomic.write(self.brief, "Check the trunk.\n")
        self.fake = FakeRunner()
        self.enterContext(patch.object(integration, "run", self.fake))
        self.output = io.StringIO()
        self.enterContext(redirect_stdout(self.output))

    def start(self):
        with patch.object(integration.codex, "new_id", return_value="check-id"):
            self.assertEqual(cli.main(["check", "start", "--tip", "tip", "--onto", "origin/demo/integration",
                                       str(self.brief), str(self.home), str(self.report)]), 0)
        return log.home() / "check/check-id"

    def test_start_unit_contract(self):
        directory = self.start()
        self.assertEqual(self.output.getvalue(), f"check-id {directory}\n")
        meta = json.loads((directory / "meta.json").read_text())
        self.assertEqual((meta["tip"], meta["onto"], meta["report"]),
                         ("tip", "origin/demo/integration", str(self.report)))
        argv, = self.fake.argvs()
        self.assertIn("fab-check-check-id", argv)
        self.assertIn("--property=UMask=0077", argv)
        self.assertTrue(any("ExecStopPost=-" in arg and arg.endswith("wake codex check-id") for arg in argv))
        self.assertEqual(argv[-3:], ["check", "_exec", "check-id"])
        self.assertFalse((directory / "ended").exists())

    def test_exec_report_result_ended_order_for_green_red_and_conflict(self):
        for outcome, steps, first in (("green", ["fmt:0:0.1"], "Done: green tip"),
                                      ("red", ["fmt:0:0.1", "gate:ratchet:1:0.2"], "Failed: gate:ratchet red"),
                                      ("conflict", [], "Failed: conflict red")):
            with self.subTest(outcome=outcome):
                directory = log.home() / "check/check-id"
                atomic.write(directory / "meta.json", json.dumps(dict(dir=str(self.home), tip="tip",
                             onto="origin/demo/integration", report=str(self.report))))
                writes = []
                save = atomic.write
                def record(path, text):
                    writes.append(Path(path).name)
                    save(path, text)
                receipt = dict(outcome=outcome, steps=steps, log="/check.log")
                with patch.object(integration.precheck, "precheck", return_value=receipt) as precheck, \
                        patch.object(integration.atomic, "write", side_effect=record):
                    self.assertEqual(cli.main(["check", "_exec", "check-id"]), int(outcome != "green"))
                precheck.assert_called_once_with(self.home, "tip", onto="origin/demo/integration", full=True, without=())
                self.assertEqual(writes, ["report.md", "result.json", "ended"])
                self.assertEqual(self.report.read_text().splitlines(), [first, *steps, "/check.log"])
                result = json.loads((directory / "result.json").read_text())
                self.assertEqual(result["exit"], int(outcome != "green"))
                self.assertIsInstance(result["ended"], str)
                self.assertTrue((directory / "ended").exists())

    def test_exec_exception_still_completes_contract(self):
        directory = self.start()
        with patch.object(integration.precheck, "precheck", side_effect=OSError("no checkout")):
            self.assertEqual(cli.main(["check", "_exec", "check-id"]), 1)
        self.assertIn("no checkout", self.report.read_text())
        self.assertEqual(json.loads((directory / "result.json").read_text())["exit"], 1)
        self.assertTrue((directory / "ended").is_file())
