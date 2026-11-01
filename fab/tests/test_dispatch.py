"""The dispatcher's decisions and shell, isolated from machine state (docs/design/fab.md, 4)."""

import fcntl
import io
import json
import os
import shlex
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fab import atomic, call_review, calls, channel, cli, designer, dispatch, drafts, findings, fix, fixes, flow, foreman, gates, integration, log, overlaps, plan, repairs, run as runs, rust_gates, state, tier_reds, triage, wake, walks
from fab.dispatch import Action, MAX_RUNS
from fab.hosts import Host
from fab.sh import Failed, Result, run, ssh
from fab.tests import qa_records as qa, wakes
from fab.tests.buffer_order import ids, sliced, spec, specs
from fab.tests.ladder_plans import write_ladder
from fab.tests.test_repairs import (TASK as REPAIR_TASK, foreman_run, rejected, report,
                                    settled, task_run)
from fab.tests.support import (GIT_ENV, FakeRunner, call_ended, call_started, git, git_pair,
                               run_ended, run_started,
                               tmp_home, units, write_plan)


def task(name, *, part="core", repo="agents", needs=()):
    return plan.Task(f"draft/{name}", part, "feature", repo, needs, (), "high", 25, "", "task.md")


def part(name, needs=()):
    return plan.Part(name, name, "feature", needs, "design.md")


def make_plan(*parts, low=1):
    return plan.Plan("draft", "agents", (), low, 2, {p.id: p for p in parts}, (),
                     landing="queue", reviews=True, direct=False)


def event(ev, name="a", **fields):
    """Build a task event, giving questions the asking run required by their contract."""
    if ev == "question.asked":
        fields.setdefault("run", f"draft/{name}-1")
    return {"ev": ev, "task": f"draft/{name}", **fields}


def started(name="a", n=1, *, host="builder", branch=None):
    return event("run.started", name, run=f"draft/{name}-{n}", host=host,
                 branch=branch or f"draft/{name}")


def ended(name="a", n=1, outcome="done"):
    return event("run.ended", name, run=f"draft/{name}-{n}", outcome=outcome, report="report.md")


def growth():
    """Two clean landings with full windows earn a target of four from START."""
    return [started("seed-a"), started("seed-b"), ended("seed-a"),
            event("branch.landed", "seed-a"), started("seed-c"), started("seed-d"),
            ended("seed-b"), event("branch.landed", "seed-b"), ended("seed-c"), ended("seed-d")]


FAB = str(Path(dispatch.__file__).resolve().parent.parent / "bin/fab")


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    sibling = path.with_name(path.name + ".tmp")
    sibling.write_text(text)
    sibling.replace(path)


def chain_history(status, *, role="skeleton", root="root", subject="draft/core"):
    events = [dict(ev="call.started", call=root, role=role, subject=subject,
                   branch=f"calls/{root}", ts="2026-10-30T00:00:00.000Z"),
              dict(ev="call.ended", call=root, outcome="done")]
    if status == "review":
        return events
    events.append(dict(ev="run.started", run=f"{root}-1", task=root, kind="review", host="builder"))
    if status == "reviewing":
        return events
    events.append(dict(ev="run.ended", run=f"{root}-1", outcome="done" if status in
                       ("approved", "finished") else "failed", report="first-refusal.md"))
    if status in ("approved", "amend"):
        return events
    if status == "finished":
        return events + [dict(ev="call.finished", call=root, outcome="done")]
    events.append(dict(ev="call.started", call=f"{root}-amend", role="amend", amends=root,
                       subject=subject, branch=f"calls/{root}"))
    if status == "amending":
        return events
    events.extend([dict(ev="call.ended", call=f"{root}-amend", outcome="done"),
                   dict(ev="run.started", run=f"{root}-2", task=root, kind="review", host="builder"),
                   dict(ev="run.ended", run=f"{root}-2", outcome="failed", report="last-refusal.md")])
    if status == "parked":
        events.append(dict(ev="call.parked", call=root, subject=subject))
    return events


def question_history(name="a", status="foreman", *, since="2026-10-30T12:29:00.000Z"):
    """Build a question's real event history in one of the foreman's four states or parked."""
    asked = event("question.asked", name, run=f"draft/{name}-1", text=f"Choose for {name}?",
                  ts="2026-10-30T09:00:00.000Z")
    if status == "parked":
        return [dict(asked, ts=since)]
    history = [dict(started(name), kind="implement", ts="2026-10-30T08:00:00.000Z"),
               dict(ended(name, outcome="question"), ts="2026-10-30T09:00:00.000Z"), asked]
    if status == "foreman":
        return history
    run_id = f"draft/{name}/foreman-1"
    history.append(dict(ev="run.started", task=f"draft/{name}/foreman", run=run_id,
                        kind="foreman", asked=asked["run"], host="builder",
                        ts="2026-10-30T10:00:00.000Z"))
    if status != "deciding":
        history.append(dict(ev="run.ended", task=f"draft/{name}/foreman", run=run_id,
                            outcome="done" if status == "settled" else "failed",
                            report=f"collected/{run_id}/report.md", ts=since))
    return history


def refusal_history(name="task", status="foreman", *, step="test", verdict="fix", section=""):
    """Build a refusal history from repairs' vocabulary, renaming its task for this plan."""
    history = [dict(task_run("01"), host="builder"),
               dict(ev="run.ended", ts="02", task=REPAIR_TASK.id, run=REPAIR_TASK.id + "-1",
                    outcome="done", report="task-report.md"), rejected("03", step=step)]
    if status != "foreman":
        history.extend(foreman_run("04", outcome=None if status == "deciding" else
                                   "infra" if status == "fallback" else "done", ended="05"))
        history[3]["host"] = "builder"
    if status == "settled":
        history.append(settled("06", verdict, section=section))
    return [{key: value.replace(REPAIR_TASK.id, f"draft/{name}") if isinstance(value, str)
             else value for key, value in entry.items()} for entry in history]


class RepairActionsTest(unittest.TestCase):
    def test_states_order_plan_filter_and_purity(self):
        tasks = {f"draft/{name}": task(name) for name in ("a", "b", "c", "d", "e")}
        events = [*refusal_history("b", "decided"), *refusal_history("d", "deciding"),
                  *refusal_history("a"), *refusal_history("c", "settled"),
                  *refusal_history("e", "fallback"),
                  *(dict(entry, task=entry["task"].replace("draft/", "other/"))
                    for entry in refusal_history("outside"))]
        before = deepcopy((tasks, events))
        expected = [Action("remedy", task="draft/b", run="draft/b/foreman-1",
                           detail="draft/b/foreman-1"),
                    Action("examine", task="draft/a", branch="draft/a", detail="test draft/a")]
        self.assertEqual(dispatch.repair_actions(tasks, events), expected)
        self.assertEqual(dispatch.repair_actions(tasks, events), expected)
        self.assertEqual((tasks, events), before)
        self.assertEqual(dispatch.repair_actions({}, events), [])


class RefusalDecideTest(unittest.TestCase):
    def setUp(self):
        self.plan = make_plan(part("core"))
        self.task = task("task")
        self.hosts = {"builder": Host("builder", "fake@builder", ("builder",), places=10)}

    def actions(self, events, *, hosts=None):
        return dispatch.decide(self.plan, {self.task.id: self.task}, events,
                               self.hosts if hosts is None else hosts)

    def test_waiting_refusals_neither_start_nor_park_even_at_run_limit(self):
        for status in ("foreman", "deciding", "decided"):
            for count in (1, MAX_RUNS):
                for hosts in (self.hosts, {}):
                    with self.subTest(status=status, count=count, hosts=hosts):
                        events = [entry for n in range(2, count + 1) for entry in
                                  (dict(task_run("00", n=n), host="builder"),
                                   dict(ev="run.ended", run=f"{self.task.id}-{n}", outcome="done"))]
                        events += refusal_history(status=status)
                        self.assertFalse(any(action.kind in ("start", "park")
                                             for action in self.actions(events, hosts=hosts)))

    def test_settled_fix_none_and_fallback_start_with_their_context(self):
        section = "## Repair\n\nKeep  spaces.\n"
        for status, verdict in (("settled", "fix"), ("settled", "none"), ("fallback", "")):
            for step in ("test", *repairs.REBASE_STEPS):
                with self.subTest(status=status, verdict=verdict, step=step):
                    events = refusal_history(status=status, verdict=verdict, section=section, step=step)
                    before = deepcopy(events)
                    action, = [action for action in self.actions(events) if action.kind == "start"]
                    rejection = next(entry for entry in events if entry["ev"] == "branch.rejected")
                    expected = {**rejection, "section": section} if verdict == "fix" else rejection
                    self.assertEqual(action.rejection, expected)
                    self.assertEqual(action.run_kind, "rebase" if step in repairs.REBASE_STEPS else "repair")
                    self.assertEqual(events, before)

    def test_retry_lands_or_readies_the_same_branch_without_a_run(self):
        events = refusal_history(status="settled", verdict="retry")
        for repo, kind in (("agents", "land"), ("fabrig", "ready")):
            with self.subTest(repo=repo):
                self.task = replace(self.task, repo=repo)
                self.assertEqual(self.actions(events)[1:],
                                 [Action(kind, task=self.task.id, branch=self.task.id, detail=self.task.id)])


class ForemanActionsTest(unittest.TestCase):
    def test_states_question_order_plan_filter_and_purity(self):
        tasks = {f"draft/{name}": task(name) for name in ("a", "b", "c", "d", "e")}
        events = [*question_history("b", "settled"), *question_history("d", "deciding"),
                  *question_history("a"), *question_history("c", "queued"),
                  *question_history("e", "parked"),
                  *(dict(entry, task="other/task") for entry in question_history("outside"))]
        before = deepcopy((tasks, events))
        expected = [Action("settle", task="draft/b", run="draft/b/foreman-1",
                           detail="draft/b/foreman-1"),
                    Action("foreman", task="draft/a", run="draft/a-1", detail="draft/a-1")]
        self.assertEqual(dispatch.foreman_actions(tasks, events), expected)
        self.assertEqual(dispatch.foreman_actions(tasks, events), expected)
        self.assertEqual((tasks, events), before)
        self.assertEqual(dispatch.foreman_actions({}, events), [])


class BufferDecideTest(unittest.TestCase):
    def setUp(self):
        self.hosts = {"builder": Host("builder", "fake@builder", ("builder",), places=1)}

    def test_consolidation_starts_before_rejected_task(self):
        the_plan = sliced(["early"], ["late"])
        tasks = specs(spec("fix", "early"), spec("merge", "late", consolidation=True))
        actions = dispatch.decide(the_plan, tasks, [event("branch.rejected", "fix", step="test")],
                                  self.hosts)
        self.assertEqual([action.task for action in actions if action.kind == "start"], ids("merge"))

    def test_refused_slice_two_task_starts_before_runnable_slice_one(self):
        the_plan = sliced(["early"], ["late"])
        tasks = specs(spec("early", "early"), spec("fix", "late"))
        actions = dispatch.decide(the_plan, tasks, [event("branch.rejected", "fix", step="merge")],
                                  self.hosts)
        self.assertEqual([(action.task, action.run_kind) for action in actions if action.kind == "start"],
                         [("draft/fix", "rebase")])

    def test_infra_rerun_keeps_its_slice_place(self):
        the_plan = sliced(["early"], ["late"])
        tasks = specs(spec("late", "late"), spec("early", "early"))
        for name, expected_kind in (("late", "implement"), ("early", "repair")):
            with self.subTest(infra=name):
                events = [started(name), ended(name, outcome="infra")]
                actions = dispatch.decide(the_plan, tasks, events, self.hosts)
                start, = [action for action in actions if action.kind == "start"]
                self.assertEqual((start.task, start.run_kind, start.rejection),
                                 ("draft/early", expected_kind, None))

    def test_contract_task_starts_before_slice_one_task(self):
        the_plan = sliced(["early"], ["wire"], contracts=["wire"])
        tasks = specs(spec("early", "early"), spec("wire", "wire"))
        actions = dispatch.decide(the_plan, tasks, [], self.hosts)
        self.assertEqual([action.task for action in actions if action.kind == "start"], ids("wire"))

    def test_refused_runnable_and_rejected_tasks_keep_spec_order(self):
        the_plan = sliced(["core"])
        tasks = specs(spec("earlier", "core"), spec("later", "core"))
        rejection = event("branch.rejected", "earlier", step="merge")
        events = [started("earlier"), ended("earlier"), rejection,
                  event("question.asked", "earlier", text="Proceed?"),
                  event("question.answered", "earlier", answer="yes"),
                  event("branch.rejected", "later", step="test")]
        views = state.fold(tasks, events)
        self.assertEqual(views["draft/earlier"].status, "runnable")
        self.assertEqual(views["draft/later"].status, "rejected")
        actions = dispatch.decide(the_plan, tasks, events, self.hosts)
        start, = [action for action in actions if action.kind == "start"]
        self.assertEqual((start.task, start.run_kind, start.rejection),
                         ("draft/earlier", "rebase", rejection))

    def test_run_limit_parks_even_after_the_order_fills_the_place(self):
        the_plan = sliced(["early"], ["late"])
        tasks = specs(spec("exhausted", "late"), spec("merge", "early", consolidation=True))
        events = [entry for n in range(1, MAX_RUNS + 1)
                  for entry in (started("exhausted", n), ended("exhausted", n, outcome="infra"))]
        actions = dispatch.decide(the_plan, tasks, events, self.hosts)
        self.assertEqual([(action.kind, action.task) for action in actions[1:]],
                         [("start", "draft/merge"), ("park", "draft/exhausted")])


class DecideTest(unittest.TestCase):
    def setUp(self):
        self.plan = make_plan(part("core"))
        self.hosts = {"builder": Host("builder", "fake@builder", ("builder",), places=2)}

    def decide(self, tasks, events=(), hosts=None, spec=None):
        """Return work actions; the flow diagnostic is checked directly in its own test."""
        return dispatch.decide(spec or self.plan, {t.id: t for t in tasks}, list(events),
                               self.hosts if hosts is None else hosts)[1:]

    def test_in_flight_matches_run_not_task_and_keeps_log_order(self):
        events = [started(n=1), started("b"), ended(n=1), started(n=2),
                  event("note", run="draft/b-1"), ended("unknown")]
        self.assertEqual(dispatch.in_flight(iter(events)), [events[1], events[3]])
        self.assertEqual(dispatch.in_flight([]), [])

    def test_places_counts_all_flight_and_clamps_only_builders(self):
        hosts = {**self.hosts, "full": Host("full", "fake@full", ("builder",), places=1),
                 "gate": Host("gate", "fake@gate", ("gate",), places=9)}
        flight = [started("other"), started(host="full"), started("b", host="full"),
                  started(host="unknown")]
        self.assertEqual(dispatch.places(hosts, iter(flight)), {"builder": 1, "full": 0})
        self.assertEqual(dispatch.places({}, flight), {})

    def test_places_full_calm_builder_gets_one_until_slots_full(self):
        host = Host("builder", "fake@builder", ("builder",), places=1, slots=2)
        hosts = {"builder": host}
        flight = [started()]
        self.assertEqual(dispatch.places(hosts, flight, {"builder": True}), {"builder": 1})
        self.assertEqual(dispatch.places(hosts, flight, {"builder": False}), {"builder": 0})
        self.assertEqual(dispatch.places(hosts, flight, {}), {"builder": 0})
        self.assertEqual(dispatch.places(hosts, flight), {"builder": 0})
        self.assertEqual(dispatch.places(hosts, flight + [started("b")], {"builder": True}),
                         {"builder": 0})
        hosts["builder"] = replace(host, slots=0)
        self.assertEqual(dispatch.places(hosts, flight * 3, {"builder": True}), {"builder": 1})
        self.assertEqual(dispatch.places(hosts, [], {"builder": True}), {"builder": 1})

    def test_flow_is_first_and_target_caps_starts_with_rejections_first(self):
        hosts = {"builder": replace(self.hosts["builder"], places=4),
                 "second": Host("second", "fake@second", ("builder",), places=4),
                 "gate": Host("gate", "fake@gate", ("gate",), places=9)}
        tasks = {t.id: t for t in (task(name) for name in "abcdefghi")}
        actions = dispatch.decide(self.plan, tasks, [], hosts)
        self.assertEqual(actions[0], Action("flow", task="draft", detail="target 8, 0 in flight"))
        self.assertEqual([a.task for a in actions[1:]], [f"draft/{name}" for name in "abcdefgh"])
        events = [event("branch.rejected", "c", step="test")]
        actions = dispatch.decide(self.plan, tasks, events, hosts)
        self.assertEqual(actions[0], Action("flow", task="draft", detail="target 4, 0 in flight"))
        self.assertEqual([(a.task, a.run_kind) for a in actions[1:]],
                         [("draft/c", "repair"), ("draft/a", "implement"),
                          ("draft/b", "implement"), ("draft/d", "implement")])

    def test_decide_collects_only_owned_runs_including_call_reviews(self):
        events = [run_started("other/task"), call_started("own", "answer", "draft"),
                  run_started("own", kind="review"), run_started("draft/a/foreman", kind="foreman"),
                  call_started("foreign", "review", "other/review"), run_started("foreign", kind="review")]
        actions = self.decide([], events)
        self.assertEqual([a.run for a in actions if a.kind == "collect"], ["own-1", "draft/a/foreman-1"])

    def test_only_drafts_runs_count_toward_target_including_unspecified_tasks(self):
        hosts = {"builder": replace(self.hosts["builder"], places=2)}
        tasks = {t.id: t for t in (task("a"), task("b"), task("c"))}
        foreign = [dict(started("foreign", host="foreign"), task="other/foreign"),
                   dict(started("outside", host="foreign"), task="drafted/outside")]
        events = foreign + [started("not-in-specs")]
        actions = dispatch.decide(self.plan, tasks, events, hosts)
        self.assertEqual(actions[0], Action("flow", task="draft", detail="target 2, 1 in flight"))
        self.assertEqual([a.task for a in actions if a.kind == "start"], ["draft/a"])
        actions = dispatch.decide(self.plan, tasks, foreign, hosts)
        self.assertEqual(actions[0], Action("flow", task="draft", detail="target 2, 0 in flight"))
        self.assertEqual([a.task for a in actions if a.kind == "start"], ["draft/a", "draft/b"])

    def test_calm_extra_place_used_once_per_decide_and_inputs_unchanged(self):
        hosts = {"builder": replace(self.hosts["builder"], places=1, slots=4)}
        tasks = {t.id: t for t in (task("a"), task("b"), task("c"))}
        events = [dict(started("foreign"), task="other/foreign")]
        calm = {"builder": True}
        before = deepcopy((hosts, tasks, events, calm))
        actions = dispatch.decide(self.plan, tasks, events, hosts, calm)
        self.assertEqual([a.task for a in actions if a.kind == "start"], ["draft/a"])
        self.assertEqual(dispatch.decide(self.plan, tasks, events, hosts, calm), actions)
        self.assertEqual((hosts, tasks, events, calm), before)

    def test_parks_do_not_use_target_and_still_happen_when_target_full(self):
        events = [e for n in range(1, MAX_RUNS + 1) for e in (started(n=n), ended(n=n))]
        events.append(event("branch.rejected", step="test"))
        actions = self.decide([task("a"), task("b"), task("c")], events)
        self.assertEqual([a.kind for a in actions], ["park", "start"])
        actions = self.decide([task("a"), task("b")], events + [started("c")])
        self.assertEqual([a.kind for a in actions], ["collect", "park"])

    def test_four_steps_order_and_last_run_branch(self):
        tasks = [task("a"), task("b"), task("c"), task("d", repo="fabrig"), task("e")]
        events = [started("a"), started("b"), ended("b", outcome="infra"),
                  started("b", 2, branch="draft/b-r1"), ended("b", 2),
                  started("d"), ended("d"), started("c"), ended("c"),
                  event("branch.rejected", "c", step="merge")]
        actions = self.decide(tasks, growth() + events, spec=make_plan(part("core"), part("next"), low=2))
        self.assertEqual([a.kind for a in actions], ["collect", "land", "ready", "start", "design"])
        self.assertEqual(actions[0].run, "draft/a-1")
        self.assertEqual(actions[1].branch, "draft/b-r1")
        self.assertEqual(actions[2].branch, "draft/d")
        self.assertEqual((actions[3].task, actions[3].run_kind), ("draft/c", "rebase"))
        self.assertEqual(actions[4].detail, "next")

    def test_rejected_before_runnable_and_task_order_within_each(self):
        tasks = [task(name) for name in ("a", "b", "c", "d")]
        hosts = {"builder": replace(self.hosts["builder"], places=8)}
        events = [event("branch.rejected", name, step="test") for name in ("d", "b")]
        actions = self.decide(tasks, events, hosts=hosts)
        self.assertEqual([a.task for a in actions], ["draft/b", "draft/d"])
        self.assertEqual([a.run_kind for a in actions], ["repair", "repair"])

    def test_builder_most_free_first_recomputed_and_ties_by_name(self):
        hosts = {"z": Host("z", "fake@z", ("builder",), places=3),
                 "a": Host("a", "fake@a", ("builder",), places=1)}
        actions = self.decide([task(str(i)) for i in range(6)], growth(), hosts=hosts)
        self.assertEqual([a.host for a in actions], ["z", "z", "a", "z"])

    def test_other_plans_occupy_places_and_collect_in_log_order(self):
        events = [started("other"), started("foreign")]
        actions = self.decide([task("a")], events)
        self.assertEqual([a.kind for a in actions], ["collect", "collect"])
        self.assertEqual([a.task for a in actions], ["draft/other", "draft/foreign"])
        self.assertEqual(self.decide([task("a")], hosts={}), [])

    def test_rejections_use_last_step(self):
        for step, expected in (("merge", "rebase"), ("rebase", "rebase"),
                               ("test", "repair"), ("push", "repair"), ("paths", "repair"),
                               ("gate:names", "repair"), ("gate:parse", "repair")):
            with self.subTest(step=step):
                events = [event("branch.rejected", step="rebase"),
                          event("branch.rejected", step=step)]
                action = self.decide([task("a")], events)[0]
                self.assertEqual(action.run_kind, expected)
                self.assertEqual(action.rejection, events[-1])

    def test_infra_repairs_and_new_tasks_implement(self):
        events = growth() + [started(), ended(outcome="infra")]
        actions = self.decide([task("a"), task("b")], events)
        self.assertEqual([(a.task, a.run_kind) for a in actions],
                         [("draft/a", "repair"), ("draft/b", "implement")])
        self.assertTrue(all(action.rejection is None for action in actions))

    def test_waiting_running_parked_ready_landed_do_not_start(self):
        tasks = [task("a", needs=("draft/b",)), task("b"), task("c"), task("d"), task("e")]
        events = [started("b"), event("question.asked", "c", text="Which?"),
                  event("branch.ready", "d", tip="tip"),
                  event("branch.landed", "e", tip="tip", main="main")]
        self.assertEqual([a.kind for a in self.decide(tasks, events)], ["collect"])

    def test_park_at_limit_without_using_or_requiring_a_place(self):
        for count in (MAX_RUNS, MAX_RUNS + 1):
            with self.subTest(count=count):
                events = [e for n in range(1, count + 1)
                          for e in (started(n=n), ended(n=n, outcome="infra"))]
                events.append(event("branch.rejected", step="merge"))
                parked = self.decide([task("a")], events, hosts={})
                self.assertEqual([(a.kind, a.run) for a in parked], [("park", f"draft/a-{count}")])
                self.assertIn(str(MAX_RUNS), parked[0].detail)
                actions = self.decide([task("a"), task("b")], events)
                self.assertEqual([a.kind for a in actions], ["park", "start"])
                events.append(ended(n=count))
                self.assertEqual(self.decide([task("a")], events)[0].kind, "land")

    def test_an_answered_park_grants_fresh_runs(self):
        events = [e for n in range(1, MAX_RUNS + 1) for e in (started(n=n), ended(n=n, outcome="question"))]
        events += [event("question.asked", run=f"draft/a-{MAX_RUNS}", text="limit", park=True),
                   event("question.answered")]
        self.assertEqual([a.kind for a in self.decide([task("a")], events)], ["start"])
        # An answer to an ordinary question leaves the count alone.
        plain = [*events[:-2], event("question.asked", run=f"draft/a-{MAX_RUNS}", text="Which?"),
                 event("question.answered")]
        self.assertEqual([a.kind for a in self.decide([task("a")], plain)], ["park"])
        # Fresh runs count again from the answer.
        more = [e for n in range(MAX_RUNS + 1, 2 * MAX_RUNS + 1)
                for e in (started(n=n), ended(n=n, outcome="question"))]
        self.assertEqual([a.kind for a in self.decide([task("a")], events + more + [event("question.answered")])],
                         ["park"])

    def test_one_below_run_limit_can_repair(self):
        events = [e for n in range(1, MAX_RUNS)
                  for e in (started(n=n), ended(n=n, outcome="infra"))]
        self.assertEqual(self.decide([task("a")], events)[0].kind, "start")

    def test_design_only_unspecced_parts_with_all_needs_designed_in_plan_order(self):
        spec = make_plan(part("core"), part("z", ("core",)), part("a"),
                         part("blocked", ("other",)), part("other"),
                         part("empty_need", ("a",)), part("two", ("core", "other")))
        tasks = [task("x"), task("y"), task("w", part="other")]
        events = [event("branch.landed", "x", tip="tip", main="main"),
                  event("branch.landed", "y", tip="tip", main="main"),
                  event("question.asked", "w", text="Which?")]
        self.assertEqual(self.decide(tasks, events, spec=spec),
                         [Action("design", detail="z, a, blocked, two")])
        events.pop(1)
        actions = self.decide(tasks, events, spec=spec)
        self.assertEqual(actions[-1], Action("design", detail="z, a, blocked, two"))

    def test_open_plan_questions_hold_only_named_parts_until_answered(self):
        """Open questions exclude their named parts while other eligible work proceeds."""
        question = plan.Question("budget", "Which budget?", ("core", "held"))
        spec = replace(make_plan(part("core"), part("held"), part("free"),
                                 part("reader", ("core",))), questions=(question,))
        self.assertEqual(self.decide([], spec=spec), [Action("design", detail="free")])
        answered = replace(spec, questions=(replace(question, answer="Use the smaller budget"),))
        self.assertEqual(self.decide([], spec=answered), [Action("design", detail="core, held, free")])
        still_open = replace(answered, questions=(*answered.questions, question))
        self.assertEqual(self.decide([], spec=still_open), [Action("design", detail="free")])

    def test_a_done_part_is_never_designed_and_counts_as_landed_for_its_readers(self):
        spec = make_plan(plan.Part("built", "built", "feature", (), "design.md", done=True),
                         part("reader", ("built",)))
        self.assertEqual(self.decide([], spec=spec), [Action("design", detail="reader")])

    def test_contract_reader_is_eligible_before_any_contract_task_lands(self):
        spec = make_plan(replace(part("core"), contract=True), part("reader", ("core",)))
        tasks = [task("a"), task("b", needs=("draft/a",))]
        actions = self.decide(tasks, spec=spec)
        self.assertEqual(actions[-1], Action("design", detail="reader"))
        self.assertEqual([a.task for a in actions if a.kind == "start"], ["draft/a"])
        self.assertEqual(self.decide([], spec=spec), [Action("design", detail="core")])

    def test_needs_landed_and_probe_readers_wait_for_every_task_to_land(self):
        for dependency, reader in (
            (part("core"), replace(part("reader", ("core",)), needs_landed=("core",))),
            (replace(part("core"), mode="probe"), part("reader", ("core",))),
        ):
            with self.subTest(dependency=dependency, reader=reader):
                spec = make_plan(dependency, reader, low=2)
                tasks = [task("a"), task("b")]
                events = [event("branch.landed", "a", tip="tip", main="main")]
                for history in ([], events):
                    self.assertNotIn("design", [a.kind for a in self.decide(tasks, history, spec=spec)])
                events.append(event("branch.landed", "b", tip="tip", main="main"))
                self.assertEqual(self.decide(tasks, events, spec=spec),
                                 [Action("design", detail="reader")])
                spec.parts["core"] = replace(dependency, done=True)
                self.assertEqual(self.decide([], spec=spec), [Action("design", detail="reader")])

    def test_design_buffer_uses_starting_flow_target_from_places(self):
        for places in (0, 1, 2, 20):
            for low in (0.5, 1, 1.5):
                for count in range(4):
                    with self.subTest(places=places, low=low, count=count):
                        hosts = {"builder": replace(self.hosts["builder"], places=places)}
                        spec = make_plan(part("core"), part("next"), low=low)
                        tasks = [task(str(n)) for n in range(count)]
                        actions = self.decide(tasks, hosts=hosts, spec=spec)
                        expected = ([Action("design", detail="next" if count else "core, next")]
                                    if count < max(1, places) * low else [])
                        self.assertEqual([a for a in actions if a.kind == "design"], expected)
        spec = make_plan(part("core"))
        self.assertEqual(self.decide([], hosts={}, spec=spec), [Action("design", detail="core")])
        self.assertEqual(self.decide([], spec=replace(spec, low=0)), [])

    def test_design_buffer_follows_grown_and_reduced_targets_and_counts_rejections(self):
        spec = make_plan(part("core"), part("next"))
        tasks = [task("a"), task("b")]
        self.assertNotIn("design", [a.kind for a in self.decide(tasks, spec=spec)])
        self.assertEqual(self.decide(tasks, growth(), spec=spec)[-1], Action("design", detail="next"))
        events = [event("branch.rejected", "b", step="test")]
        self.assertNotIn("design", [a.kind for a in self.decide(tasks, events, spec=spec)])
        events.append(started("a"))
        self.assertNotIn("design", [a.kind for a in self.decide(tasks, events, spec=spec)])
        events.append(started("b"))
        self.assertEqual(self.decide(tasks, events, spec=spec)[-1], Action("design", detail="next"))
        infra = [started("a"), ended("a", outcome="infra")]
        self.assertNotIn("design", [a.kind for a in self.decide([task("a")], infra, spec=spec)])

    def test_decide_is_repeatable_and_does_not_mutate_inputs(self):
        tasks = {t.id: t for t in (task("a"), task("b"))}
        events = [started(), ended(outcome="infra")]
        before = deepcopy((self.plan, tasks, events, self.hosts))
        first = dispatch.decide(self.plan, tasks, events, self.hosts)
        self.assertEqual(first, dispatch.decide(self.plan, tasks, events, self.hosts))
        self.assertEqual((self.plan, tasks, events, self.hosts), before)


class CallActionsTest(unittest.TestCase):
    def test_reply_calls_and_issue_subjects_reserve_no_work_or_limits(self):
        with tmp_home():
            plan = make_plan(part("core"))
            now = "2026-11-01T00:00:00.000Z"
            expected = dispatch.call_actions(plan, {}, [], ["core"], now)
            for role, subject in (("reply", "issues/1"), ("reply", "draft/core"),
                                  ("skeleton", "issues/1")):
                for outcome in (None, "done", "question", "failed"):
                    with self.subTest(role=role, subject=subject, outcome=outcome):
                        events = [call_started("conversation", role, subject)]
                        if outcome:
                            events.append(call_ended("conversation", outcome, role=role, subject=subject))
                        self.assertEqual(dispatch.call_actions(plan, {}, events, ["core"], now), expected)
                        actions = dispatch.decide(plan, {}, events, {})
                        self.assertFalse(any(action.kind in ("collect", "vet", "finish", "hold")
                                             for action in actions))

    def setUp(self):
        self.enterContext(tmp_home())
        # These tests are about batching; blocking() has its own tests below.
        self.enterContext(patch.object(dispatch, "blocking", return_value=False))
        self.plan = make_plan(part("core"), part("next"))
        self.tasks = {t.id: t for t in (task(str(n)) for n in range(dispatch.ANSWER_AT))}
        self.now = "2026-10-30T12:30:00.000Z"

    def actions(self, events=(), design=()):
        return dispatch.call_actions(self.plan, self.tasks, list(events), list(design), self.now)

    def question(self, name="0", ts="2026-10-30T12:29:00.000Z"):
        return event("question.asked", name, ts=ts, text="Which type?")

    def call(self, role="answer", identifier="a"):
        return dict(ev="call.started", call=identifier, role=role, subject="draft",
                    branch=f"calls/{identifier}")

    def test_answer_count_threshold_and_plan_questions_only(self):
        questions = [self.question(str(n)) for n in range(dispatch.ANSWER_AT)]
        expected = [Action("call", task="draft", run_kind="answer")]
        self.assertEqual(self.actions(questions[:-1]), [])
        self.assertEqual(self.actions(questions), expected)
        self.assertEqual(self.actions(questions + [self.question("0")]), expected)
        self.assertEqual(self.actions(questions[:-1] + [self.question("other")]), [])
        questions.append(event("question.answered", "0"))
        self.assertEqual(self.actions(questions), [])

    def test_integration_answers_one_queued_question_at_once(self):
        self.plan = replace(self.plan, landing="integration")
        self.assertEqual(self.actions([self.question()]), [Action("call", task="draft", run_kind="answer")])
        self.assertEqual(self.actions([self.question(), self.call()]), [])

    def test_integration_answers_its_only_stop_question_at_once(self):
        self.plan = replace(self.plan, landing="integration")
        self.tasks = {"draft/a": task("a")}
        events = [dict(ev="plan.stopped", task="draft/integration", why="red"),
                  self.question("integration", ts=self.now)]
        events[-1]["park"] = True
        self.assertEqual(self.actions(events), [Action("call", task="draft", run_kind="answer")])
        self.assertEqual(self.actions([*events, self.call()]), [])

    def test_answer_age_threshold_uses_oldest_timestamp(self):
        for ts, expected in (("2026-10-30T12:00:00.001Z", False),
                             ("2026-10-30T12:00:00.000Z", True),
                             ("2026-10-30T11:59:59.999Z", True)):
            with self.subTest(ts=ts):
                actions = self.actions([self.question(), self.question("1", ts)])
                self.assertEqual(actions, [Action("call", task="draft", run_kind="answer")]
                                 if expected else [])
        self.assertEqual(self.actions(), [])

    def test_only_queued_questions_count_toward_answer_threshold(self):
        self.tasks.update({f"draft/{name}": task(name) for name in ("pending", "deciding", "settled")})
        events = [entry for name in ("pending", "deciding", "settled")
                  for entry in question_history(name, "foreman" if name == "pending" else name)]
        events.extend(entry for n in range(dispatch.ANSWER_AT - 1)
                      for entry in question_history(str(n), "parked"))
        self.assertEqual(self.actions(events), [])
        events.extend(question_history(str(dispatch.ANSWER_AT - 1), "parked"))
        self.assertEqual(self.actions(events), [Action("call", task="draft", run_kind="answer")])

    def test_queued_age_begins_at_foreman_end_and_park_age_at_question(self):
        for since, due in (("2026-10-30T12:00:00.001Z", False),
                           ("2026-10-30T12:00:00.000Z", True)):
            for status in ("queued", "parked"):
                with self.subTest(since=since, status=status):
                    self.assertEqual(self.actions(question_history("0", status, since=since)),
                                     [Action("call", task="draft", run_kind="answer")] if due else [])

    def test_a_part_with_a_successful_skeleton_call_is_not_designed_again(self):
        done = [dict(self.call("skeleton", "s1"), subject="draft/core"),
                dict(ev="call.ended", call="s1", role="skeleton", outcome="done")]
        skeleton = [a for a in self.actions(done, ["core", "next"]) if a.kind == "call"]
        self.assertEqual(skeleton, [Action("call", task="next", run_kind="skeleton")])
        failed = [done[0], dict(done[1], outcome="failed")]
        self.assertEqual(self.actions(failed, ["core"]), [Action("call", task="core", run_kind="skeleton")])

    def test_a_call_that_asked_parks_its_part_until_answered(self):
        asked = [dict(self.call("skeleton", "s1"), subject="draft/core"),
                 dict(ev="call.ended", call="s1", role="skeleton", subject="draft/core",
                      ts=self.now, outcome="question")]
        self.assertEqual(self.actions(asked, ["core", "next"]),
                         [Action("call", task="next", run_kind="skeleton")])
        answered = asked + [dict(ev=channel.ANSWERED, subject="draft/core", by="user", answer="see fab-gates.md, 2")]
        self.assertEqual(self.actions(answered, ["core", "next"]),
                         [Action("call", task="core", run_kind="skeleton"),
                          Action("call", task="next", run_kind="skeleton")])

    def test_task_answer_does_not_unpark_a_part_with_the_same_name(self):
        events = [dict(self.call("skeleton", "s1"), subject="draft/core"),
                  dict(ev="call.ended", call="s1", subject="draft/core", ts=self.now, outcome="question"),
                  event("question.answered", "core", subject="draft/core", answer="Task only")]
        self.assertEqual(self.actions(events, ["core", "next"]),
                         [Action("call", task="next", run_kind="skeleton")])

    def test_later_done_call_closes_subject_question(self):
        events = [dict(ev="call.ended", call="first", subject="draft/core", ts=self.now, outcome="question"),
                  dict(ev="call.ended", call="later", subject="draft/core", ts=self.now, outcome="done")]
        self.assertEqual(dispatch._parked_subjects(events), set())
        self.assertEqual(self.actions(events, ["core"]), [Action("call", task="core", run_kind="skeleton")])

    def test_answer_question_parks_draft_until_subject_answer_or_later_done_call(self):
        questions = [self.question(str(n)) for n in range(dispatch.ANSWER_AT + 1)]
        asked = [self.call("answer", "a1"), dict(ev="call.ended", call="a1", subject="draft",
                                               ts=self.now, outcome="question"), *questions]
        answer = Action("call", task="draft", run_kind="answer")
        self.assertEqual(self.actions(asked), [])
        self.assertEqual(self.actions(asked + [dict(ev="question.answered", task="draft", subject="draft")]), [])
        self.assertEqual(self.actions(asked + [dict(ev=channel.ANSWERED, subject="other")]), [])
        self.assertEqual(self.actions(asked + [dict(ev=channel.ANSWERED, subject="draft")]), [answer])
        done = [self.call("answer", "a2"), dict(ev="call.ended", call="a2", subject="draft",
                                              ts=self.now, outcome="done"),
                dict(ev="call.finished", call="a2", outcome="done")]
        self.assertEqual(self.actions(asked + done), [answer])

    def test_design_parts_share_target_and_answer_reserves_only_its_role(self):
        questions = [self.question(ts="2026-10-30T12:00:00.000Z")]
        answer = Action("call", task="draft", run_kind="answer")
        skeleton = Action("call", task="core", run_kind="skeleton")
        next_call = Action("call", task="next", run_kind="skeleton")
        self.assertEqual(self.actions(questions, ["core", "next"]), [answer, skeleton, next_call])
        self.assertEqual(self.actions(questions + [self.call()], ["core", "next"]), [skeleton, next_call])
        busy = dict(self.call("skeleton", "s"), subject="draft/core")
        self.assertEqual(self.actions(questions + [busy], ["core", "next"]), [answer, next_call])
        self.assertEqual(self.actions(questions + [self.call(), busy], ["core", "next"]), [next_call])

    def test_contract_and_skeleton_share_limit_in_design_order(self):
        """Both roles use the same target, starting fresh parts in plan order."""
        self.plan = make_plan(replace(part("core"), contract=True), part("next"),
                              replace(part("contract-two"), contract=True), part("last"))
        contract = Action("call", task="core", run_kind="contract")
        skeleton = Action("call", task="next", run_kind="skeleton")
        self.assertEqual(self.actions(design=["core"]), [contract])
        design = ["core", "next", "contract-two", "last"]
        self.assertEqual(self.actions(design=design), [contract, skeleton])
        busy = dict(self.call("contract", "c"), subject="draft/other")
        self.assertEqual(self.actions([busy], design), [contract])
        busy_skeleton = dict(self.call("skeleton"), subject="draft/next")
        self.assertEqual(self.actions([busy_skeleton], design), [contract])
        self.assertEqual(self.actions([busy, busy_skeleton], design), [])

    def test_completed_and_question_contracts_reserve_their_part(self):
        """Done contracts stay designed and question outcomes park until an answer."""
        self.plan = make_plan(replace(part("core"), contract=True), part("next"))
        start = dict(self.call("contract", "c"), subject="draft/core")
        for outcome in ("done", "question", "failed"):
            with self.subTest(outcome=outcome):
                history = [start, dict(ev="call.ended", call="c", subject="draft/core", ts=self.now, outcome=outcome)]
                calls = [a for a in self.actions(history, ["core"]) if a.kind == "call"]
                expected = [Action("call", task="core", run_kind="contract")]
                self.assertEqual(calls, expected if outcome == "failed" else [])
                if outcome == "question":
                    history.append(dict(ev=channel.ANSWERED, subject="draft/core"))
                    self.assertEqual(self.actions(history, ["core"]), expected)

    def test_retire_starts_only_when_every_part_is_done(self):
        """Retirement follows the last task landing and respects plan-marked done."""
        self.tasks = {"draft/a": task("a"), "draft/b": task("b", part="next")}
        landed = [event("branch.landed", name, tip="tip", main="main", ts=self.now)
                  for name in ("a", "b")]
        self.assertEqual(self.actions(landed[:1]), [])
        retire = Action("call", task="draft/retire", run_kind="retire")
        self.assertEqual(self.actions(landed), [retire])
        self.plan = replace(self.plan, parts={key: replace(value, done=True)
                                             for key, value in self.plan.parts.items()})
        self.assertEqual(self.actions(), [retire])

    def test_retire_waits_for_flight_parking_open_chains_and_completed_calls(self):
        """Retirement starts once with the usual role and subject guards."""
        self.plan = make_plan(replace(part("core"), done=True))
        retire = Action("call", task="draft/retire", run_kind="retire")
        start = dict(self.call("retire", "r"), subject="draft/retire")
        self.assertEqual(self.actions([start]), [])
        question = [start, dict(ev="call.ended", call="r", subject="draft/retire", ts=self.now, outcome="question")]
        self.assertEqual(self.actions(question), [])
        self.assertEqual(self.actions(question + [dict(ev=channel.ANSWERED, subject="draft/retire")]), [retire])
        done = [start, dict(ev="call.ended", call="r", outcome="done"),
                dict(ev="call.finished", call="r", outcome="done")]
        self.assertEqual(self.actions(done), [])
        for status in call_review.STATES:
            with self.subTest(status=status):
                history = chain_history(status, subject="draft/retire")
                calls = [action for action in self.actions(history) if action.run_kind == "retire"]
                self.assertEqual(calls, [retire] if status == "finished" else [])

    def test_retire_follows_structure_review(self):
        """A due structure review precedes retirement in the same tick."""
        self.plan = make_plan(replace(part("core"), done=True))
        self.assertEqual(self.actions(self.landings(dispatch.REVIEW_AT)),
                         [Action("call", task="draft/review", run_kind="review"),
                          Action("call", task="draft/retire", run_kind="retire")])

    def test_another_drafts_chains_take_no_steps(self):
        """The draft prefix selects chains without matching a longer draft name."""
        for status in call_review.STATES:
            for subject in ("other", "other/core", "draft-other/core"):
                with self.subTest(status=status, subject=subject):
                    self.assertEqual(self.actions(chain_history(status, subject=subject)), [])
        history = chain_history("review", subject="draft")
        self.assertEqual([action.kind for action in self.actions(history)], ["vet"])

    def test_ended_releases_role_and_only_done_needs_review(self):
        for outcome in ("done", "failed", "question", "infra"):
            with self.subTest(outcome=outcome):
                events = [self.call("skeleton"), dict(ev="call.ended", call="a", outcome=outcome)]
                vet = Action("vet", task="a", run="a", run_kind="skeleton", branch="calls/a")
                skeleton = Action("call", task="next", run_kind="skeleton")
                self.assertEqual(self.actions(events, ["next"]),
                                 [vet, skeleton] if outcome == "done" else [skeleton])
                events.append(dict(ev="call.finished", call="a", outcome="failed"))
                self.assertEqual(self.actions(events, ["next"]), [skeleton])

    def test_chain_order_uses_done_endings_and_later_finished_record(self):
        events = [self.call("skeleton", "s"), self.call(),
                  dict(ev="call.finished", call="a", outcome="done"),
                  dict(ev="call.ended", call="a", outcome="done"),
                  dict(ev="call.ended", call="s", outcome="done")]
        self.assertEqual(self.actions(events),
                         [Action("vet", task="a", run="a", run_kind="answer", branch="calls/a"),
                          Action("vet", task="s", run="s", run_kind="skeleton", branch="calls/s")])
        events.append(dict(ev="call.finished", call="a", outcome="done"))
        self.assertEqual([a.run for a in self.actions(events)], ["s"])

    def test_each_chain_state_and_steps_before_new_calls(self):
        for status in call_review.STATES:
            with self.subTest(status=status):
                history = chain_history(status)
                latest = "root-amend" if status in ("hold", "parked") else "root"
                step = {
                    "review": [Action("vet", task="root", run=latest, run_kind="skeleton", branch="calls/root")],
                    "approved": [Action("finish", task="root", run=latest, run_kind="skeleton", branch="calls/root")],
                    "amend": [Action("call", task="root", run_kind="amend")],
                    "hold": [Action("call", task="root", run_kind="settle")],
                }.get(status, [])
                self.assertEqual(self.actions(history, ["core", "next"]),
                                 [*step, Action("call", task="next", run_kind="skeleton")])

    def test_settle_shares_only_its_plans_answer_limit(self):
        held = chain_history("hold", root="one") + chain_history("hold", root="two", subject="draft/other")
        self.assertEqual(self.actions(held), [Action("call", task="one", run_kind="settle")])
        for role, subject in (("settle", "draft/core/settle"), ("answer", "draft")):
            with self.subTest(role=role):
                history = held + [call_started("running", role, subject)]
                self.assertEqual(self.actions(history, ["next"]), [Action("call", task="next", run_kind="skeleton")])
        foreign = [call_started("foreign", "settle", "other/core/settle")]
        self.assertEqual(self.actions(held + foreign), [Action("call", task="one", run_kind="settle")])
        question = self.question(ts="2000-01-01T00:00:00.000Z")
        self.assertEqual(self.actions(held + [question]), [Action("call", task="one", run_kind="settle")])
        history = [call_started("running", "settle", "draft/core/settle"), question]
        self.assertEqual(self.actions(history), [])
        self.assertEqual(self.actions(foreign + [question]), [Action("call", task="draft", run_kind="answer")])

    def test_no_third_settle_after_two_recorded_attempts(self):
        history = chain_history("hold")
        for number in (1, 2):
            history += [dict(ev="call.started", call=f"settle-{number}", role="settle", settles="root"),
                        dict(ev="call.ended", call=f"settle-{number}", outcome="done"),
                        dict(ev="chain.settled", call="root", subject="draft/core", settle=f"settle-{number}",
                             verdict="amend" if number == 1 else "land", text="Guidance.")]
        history.append(dict(ev="branch.rejected", branch="calls/root", step="test", tip="third"))
        # After the amend reset, one ordinary amendment precedes this hold.
        history += [dict(ev="call.started", call="amend-2", role="amend", amends="root"),
                    dict(ev="call.ended", call="amend-2", outcome="failed")]
        self.assertEqual(self.actions(history), [Action("hold", task="draft/core", run="root", detail="settle failed")])

    def test_amend_call_in_flight_reserves_role_across_chains(self):
        history = chain_history("amending", root="one") + chain_history("amend", root="two")
        self.assertEqual(self.actions(history), [])
        history = chain_history("amend", root="one") + chain_history("amend", root="two")
        self.assertEqual(self.actions(history), [Action("call", task="one", run_kind="amend")])

    def test_open_answer_chain_blocks_until_finished(self):
        for status in call_review.STATES:
            with self.subTest(status=status):
                history = chain_history(status, role="answer", subject="draft")
                actions = self.actions(history + [self.question(ts="2026-10-30T12:00:00.000Z")])
                starts = [action for action in actions if action.kind == "call" and action.run_kind == "answer"]
                self.assertEqual(starts, [Action("call", task="draft", run_kind="answer")]
                                 if status == "finished" else [])

    def test_open_review_chain_blocks_until_finished(self):
        for status in call_review.STATES:
            with self.subTest(status=status):
                history = chain_history(status, role="review", subject="draft/review")
                actions = self.actions(history + self.landings(dispatch.REVIEW_AT))
                starts = [action for action in actions if action.kind == "call" and action.run_kind == "review"]
                self.assertEqual(starts, [Action("call", task="draft/review", run_kind="review")]
                                 if status == "finished" else [])

    def landings(self, count, ts="2026-10-30T12:29:00.000Z"):
        """Build complete landings for both review counting and retirement folding."""
        tasks = [task(str(n)) for n in range(count)]
        self.tasks.update((item.id, item) for item in tasks)
        return [dict(ev="branch.landed", task=item.id, ts=ts, tip="tip", main="main") for item in tasks]

    def test_review_count_threshold_and_plan_landings_only(self):
        landed = self.landings(dispatch.REVIEW_AT)
        expected = [Action("call", task="draft/review", run_kind="review")]
        self.assertEqual(self.actions(landed[:-1]), [])
        self.assertEqual(self.actions(landed), expected)
        foreign = dict(landed[-1], task="other/task")
        self.assertEqual(self.actions(landed[:-1] + [foreign]), [])

    def test_review_age_threshold_since_first_landing_with_no_review(self):
        threshold = datetime.fromisoformat(self.now) - timedelta(minutes=dispatch.REVIEW_AFTER)
        for delta, due in ((1, False), (0, True), (-1, True)):
            with self.subTest(delta=delta):
                ts = (threshold + timedelta(milliseconds=delta)).isoformat()
                landed = self.landings(1, ts)
                expected = [Action("call", task="draft/review", run_kind="review")] if due else []
                self.assertEqual(self.actions(landed), expected)
        self.assertEqual(self.actions(), [])

    def test_review_count_resets_at_latest_start_including_failed_review(self):
        old = self.landings(dispatch.REVIEW_AT, "2026-10-29T00:00:00.000Z")
        for outcome in ("done", "failed"):
            with self.subTest(outcome=outcome):
                review = dict(self.call("review", "r1"), ts="2026-10-30T12:00:00.000Z",
                              subject="draft/review")
                history = old + [review,
                                 dict(ev="call.ended", call="r1", outcome=outcome, ts="2026-10-30T12:15:00.000Z"),
                                 dict(ev="call.finished", call="r1", outcome=outcome)]
                recent = self.landings(dispatch.REVIEW_AT)
                self.assertEqual(self.actions(history + recent[:-1]), [])
                self.assertEqual(self.actions(history + recent),
                                 [Action("call", task="draft/review", run_kind="review")])

    def test_review_age_uses_start_instead_of_end_and_requires_a_landing(self):
        threshold = datetime.fromisoformat(self.now) - timedelta(minutes=dispatch.REVIEW_AFTER)
        for outcome in ("done", "failed"):
            with self.subTest(outcome=outcome):
                review = dict(self.call("review", "r1"), ts=threshold.isoformat(), subject="draft/review")
                ended = [dict(ev="call.ended", call="r1", outcome=outcome, ts=self.now),
                         dict(ev="call.finished", call="r1", outcome=outcome)]
                history = [review, *self.landings(1), *ended]
                self.assertEqual(self.actions(history),
                                 [Action("call", task="draft/review", run_kind="review")])
                self.assertEqual(self.actions([review, *ended]), [])
                later_start = dict(review, ts=(threshold + timedelta(milliseconds=1)).isoformat())
                self.assertEqual(self.actions([later_start, *history[1:]]), [])

    def test_review_in_flight_blocks_review_and_other_roles_do_not(self):
        review = dict(self.call("review"), ts="2026-10-29T00:00:00.000Z", subject="draft/review")
        landed = self.landings(dispatch.REVIEW_AT)
        self.assertEqual(self.actions([review, *landed]), [])
        self.assertEqual(self.actions([self.call("skeleton"), *landed]),
                         [Action("call", task="draft/review", run_kind="review")])

    def test_brief_park_blocks_only_its_subject_until_answer_or_start(self):
        park = dict(ev="call.parked", subject="draft/core", role="skeleton", call="",
                    reason="brief failed: oversized", report="", ts=self.now)
        expected = [Action("call", task="core", run_kind="skeleton")]
        self.assertEqual(self.actions([], ["core"]), expected)
        self.assertEqual(self.actions([park], ["core"]), [])
        for subject in ("other/core", "draft/next"):
            self.assertEqual(self.actions([dict(park, subject=subject)], ["core"]), expected)
        self.assertEqual(dispatch._parked_subjects([dict(park, call="chain")]), set())
        answered = dict(ev=channel.ANSWERED, subject="draft/core")
        self.assertEqual(self.actions([park, answered], ["core"]), expected)
        started = call_started("retry", "skeleton", "draft/core", ts=self.now)
        self.assertEqual(dispatch._parked_subjects([park, started]), set())
        ended = call_ended("retry", "failed", subject="draft/core", role="skeleton")
        self.assertEqual(self.actions([park, started, ended], ["core"]), expected)

    def test_call_argv_ends_in_tick_for_each_role(self):
        directory = log.home().parent / "plan"
        for role in calls.ROLES:
            sh = FakeRunner()
            with self.subTest(role=role):
                dispatch._call(Action("call", task="core", run_kind=role), directory, "draft", sh=sh)
                argv, = sh.argvs()
                self.assertEqual(argv[-3:], ["--plan", str(directory.resolve()), "--tick"])

    def test_review_question_parks_subject_until_matching_answer(self):
        asked = [dict(self.call("review", "r1"), ts="2026-10-30T12:00:00.000Z", subject="draft/review"),
                 dict(ev="call.ended", call="r1", role="review", subject="draft/review",
                      ts=self.now, outcome="question"),
                 *self.landings(dispatch.REVIEW_AT)]
        self.assertEqual(self.actions(asked), [])
        self.assertEqual(self.actions(asked + [event("question.answered", "core")]), [])
        self.assertEqual(self.actions(asked + [dict(ev=channel.ANSWERED, subject="draft/review")]),
                         [Action("call", task="draft/review", run_kind="review")])

    def test_review_start_follows_answer_and_skeleton(self):
        history = [self.question(ts="2026-10-30T12:00:00.000Z"), *self.landings(dispatch.REVIEW_AT)]
        self.assertEqual(self.actions(history, ["core"]),
                         [Action("call", task="draft", run_kind="answer"),
                          Action("call", task="core", run_kind="skeleton"),
                          Action("call", task="draft/review", run_kind="review")])

    def test_answer_blocking_receives_the_plan_draft(self):
        self.actions([self.question()])
        self.assertEqual(dispatch.blocking.call_args.kwargs["draft"], "draft")

    def test_other_draft_review_does_not_reset_threshold(self):
        landed = self.landings(dispatch.REVIEW_AT, "2026-10-30T12:00:00.000Z")
        other = [call_started("other", "review", "other/review", ts=self.now),
                 call_ended("other", outcome="failed", ts=self.now)]
        self.assertEqual(self.actions(landed + other),
                         [Action("call", task="draft/review", run_kind="review")])

    def test_other_drafts_chains_and_amend_calls_do_not_reserve_roles(self):
        for role, subject in (("answer", "other"), ("review", "other/review")):
            for status in call_review.STATES:
                with self.subTest(role=role, status=status):
                    history = chain_history(status, role=role, subject=subject)
                    actions = self.actions(history + [self.question(ts="2000-01-01T00:00:00.000Z")]
                                           + self.landings(dispatch.REVIEW_AT))
                    self.assertEqual([a.run_kind for a in actions], ["answer", "review"])
        history = chain_history("amend") + [call_started("foreign-amend", "amend", "other/core")]
        self.assertEqual(self.actions(history), [Action("call", task="root", run_kind="amend")])

    def test_pure_repeatable_and_inputs_unchanged(self):
        events = [self.call(), self.question()]
        design = ["core", "next"]
        before = deepcopy((self.plan, self.tasks, events, design))
        with patch("fab.log.read", side_effect=AssertionError("read log")), \
             patch("fab.log.home", side_effect=AssertionError("read home")):
            first = self.actions(events, design)
            self.assertEqual(self.actions(events, design), first)
        self.assertEqual((self.plan, self.tasks, events, design), before)


class LadderTickTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.directory = write_ladder(self.home / "plan")
        self.plan = plan.load_plan(self.directory / "plan.toml")
        self.editions = {rung.id: walks.edition([
            (path, (self.directory / path).read_text()) for path in rung.brief])
            for rung in self.plan.rungs.values()}
        self.fake = FakeRunner().on(["git", "rev-parse", "--show-toplevel"],
                                    Result(0, str(self.home)))
        self.backlog = triage.backlog_text(self.plan, [])
        self.fake.on(["git", "ls-tree"], lambda call: Result(
            0, self.plan.ladder.backlog if self.backlog is not None else ""))
        self.fake.on(["git", "show"], self.read_origin)
        self.fake.on(["git", "worktree", "add"], self.add_worktree)
        self.fake.on(["git", "rev-parse", "--verify"], Result(0, "backlog-tip\n"))
        self.now = self.enterContext(patch.object(log, "now", return_value=qa.STAMP))
        self.out = io.StringIO()
        self.enterContext(redirect_stdout(self.out))

    def append(self, *events):
        for entry in events:
            fields = dict(entry)
            log.append(fields.pop("ev"), **fields)

    def add_walk(self, number=1, *, verdict="fail", identifiers=("finding-1",),
                 draft="ladder", edition=None):
        walk = f"walk-{number}"
        fields = dict(draft=draft, backend="claude-forgejo",
                      edition=self.editions["b0"] if edition is None else edition)
        self.append(qa.walk_started(walk, "b0", **fields))
        for index, identifier in enumerate(identifiers, 1):
            self.append(qa.finding_raised(identifier, walk, "b0", index=index, **fields))
        self.append(qa.walk_ended(walk, verdict, identifiers))

    def end_triage(self, report, *, call="triage-1", draft="ladder", outcome="done"):
        fields = dict(call=call, role="triage", subject=triage.subject(draft))
        self.append(log.record("call.started", **fields),
                    log.record("call.ended", outcome=outcome, **fields))
        if report is not None:
            atomic.write(log.home() / "calls" / call / "report.md", report)

    def read_origin(self, call):
        path = call.argv[-1].split(":", 1)[1]
        if path == self.plan.ladder.backlog:
            return Result(0, self.backlog) if self.backlog is not None else Result(1)
        return Result(0, (self.home / path).read_text())

    def add_worktree(self, call):
        path = Path(call.argv[-2]) / self.plan.ladder.backlog
        path.unlink(missing_ok=True)
        if self.backlog is not None:
            atomic.write(path, self.backlog)
        return Result(0)

    def tick(self, **kwargs):
        return dispatch.tick(self.directory, sh=self.fake, hosts=kwargs.pop("hosts", {}), **kwargs)

    def finding_hosts(self, *, places=2):
        self.finding_reports, self.finding_queue, self.finding_tiers = {}, [], []
        self.fake.on(["git", "rev-parse", "origin/main"], Result(0, "main-tip\n"))
        self.fake.rules.insert(0, (["git", "rev-parse", "--verify"], Result(0, "a" * 40 + "\n")))
        package = Path(runs.__file__).resolve().parent.parent
        self.fake.on(["git", "-C", str(package), "rev-parse", "HEAD"], Result(0, "a" * 40 + "\n"))
        self.fake.on(["ssh"], self.finding_remote)
        self.enterContext(patch.object(rust_gates, "screen", return_value=[]))
        return {"builder": Host("builder", "fake@builder", ("builder",), places=places),
                "gate": Host("gate", "fake@gate", ("gate",))}

    def finding_remote(self, call):
        argv = shlex.split(shlex.split(call.argv[-1])[2])
        if argv[:3] == ["fab", "queue", "log"]:
            return Result(0, "\n".join(json.dumps(record) for record in self.finding_queue))
        if argv[:3] == ["fab", "after-landing", "log"]:
            return Result(0, "\n".join(json.dumps(record) for record in self.finding_tiers))
        if argv[:2] == ["bash", "-c"] and "printf 'running" in argv[2]:
            report = next((text for run_id, text in self.finding_reports.items()
                           if f"/runs/{run_id}/report.md" in argv[2]), None)
            return Result(0, "running\n" if report is None else "ended\n{}\n" + report)
        if argv[:1] == ["git"] and "rev-parse" in argv and "-q" in argv:
            return Result(1)
        if argv == ["fab", "slot", "list"]:
            return Result(0, json.dumps(dict(slot=1, claim=None, idle=0)) + "\n")
        if argv[:3] == ["fab", "slot", "release"]:
            return Result(0, "0\n")
        if argv[:3] == ["fab", "codex", "start"]:
            return Result(0, "codex-finding /state/finding\n")
        if argv[:1] == ["cat"] and "/precheck/" in argv[-1]:
            return Result(1)
        return Result(0)

    def test_finding_tick_actions_are_pure_in_raise_order_and_scoped_to_draft(self):
        self.add_walk(identifiers=("finding-9", "finding-2"))
        self.add_walk(2, identifiers=("finding-3",), draft="other")
        for identifier in ("finding-9", "finding-2", "finding-3"):
            self.append(qa.finding_triaged(identifier, "path"))
        self.append(run_started("ladder/finding-2/foreman", kind="foreman",
                                finding="finding-2", tip="tip"),
                    run_ended("ladder/finding-2/foreman"))
        events = log.read()
        before = deepcopy(events)
        with patch.object(log, "read", side_effect=AssertionError("read log")), \
             patch.object(log, "home", side_effect=AssertionError("read home")):
            actions = dispatch.finding_actions(self.plan, events)
        self.assertEqual(actions, [
            Action("examine-fix", task="ladder/finding-9", detail="finding-9", run_kind="finding"),
            Action("remedy-fix", task="ladder/finding-2", run="ladder/finding-2/foreman-1",
                   detail="finding-2", run_kind="finding")])
        self.assertEqual(events, before)

    def test_finding_tick_fix_is_collected_started_readied_and_landed_for_rerun(self):
        hosts = self.finding_hosts()
        self.add_walk()
        self.end_triage("Done: routed\nfinding-1: path ctl: Repair the story\n")
        actions = self.tick(hosts=hosts)
        self.assertIn(Action("examine-fix", task="ladder/finding-1", detail="finding-1",
                             run_kind="finding"), actions)
        survey, = [entry for entry in log.read() if entry["ev"] == "run.started"]
        self.assertEqual((survey["base"], survey["tip"], survey["host"]),
                         ("main-tip", "main-tip", "builder"))
        brief = (log.home() / "runs" / survey["run"] / "brief.md").read_text()
        self.assertIn("`plan/briefs/b0.md`", brief)
        self.assertFalse(any(a.kind == "examine-fix" for a in self.tick(hosts=hosts)))
        self.finding_reports[survey["run"]] = "Done: fix: Repair the story\nUnit reproduction.\n"
        actions = self.tick(hosts=hosts)
        self.assertTrue(any(a.kind == "remedy-fix" for a in actions))
        settlement, = [entry for entry in log.read() if entry["ev"] == "finding.settled"]
        self.assertEqual((settlement["verdict"], settlement["run"]), ("fix", survey["run"]))
        self.assertIn("Unit reproduction.", settlement["section"])
        self.tick(hosts=hosts)
        repair = [entry for entry in log.read() if entry["ev"] == "run.started"][-1]
        self.assertEqual((repair["task"], repair["base"], repair["kind"], repair["slot"]),
                         ("ladder/finding-1", "origin/main", "implement", 1))
        brief = (log.home() / "runs" / repair["run"] / "brief.md").read_text()
        self.assertIn(settlement["section"].rstrip(), brief)
        self.finding_reports[repair["run"]] = "Done: repaired\n"
        self.tick(hosts=hosts)
        self.assertTrue(any(a.kind == "ready" and a.task == repair["task"]
                            for a in self.tick(hosts=hosts)))
        ready, = [entry for entry in log.read() if entry["ev"] == "branch.ready"
                  and entry.get("task") == repair["task"]]
        self.assertEqual((ready["branch"], ready["tip"]), (repair["task"], "a" * 40))
        self.finding_queue.append(dict(ev="landed", ts="queue-1", branch=ready["branch"],
                                       tip=ready["tip"], main="fixed-main"))
        self.tick(hosts=hosts)
        self.tick(hosts=hosts)
        landed, = [entry for entry in log.read() if entry["ev"] == "branch.landed"]
        self.assertEqual((landed["task"], landed["main"]), (repair["task"], "fixed-main"))
        self.assertEqual(sum(entry["ev"] == "finding.settled" for entry in log.read()), 1)
        rung = findings.rungs(self.plan, log.read(), self.editions, qa.STAMP)[0]
        self.assertEqual((rung.state, rung.due, rung.at), ("due", "rerun", "fixed-main"))

    def test_finding_tick_retry_settles_left_once_and_releases_the_rung(self):
        hosts = self.finding_hosts()
        self.add_walk()
        self.append(qa.finding_triaged("finding-1", "path"))
        self.tick(hosts=hosts)
        self.finding_reports["ladder/finding-1/foreman-1"] = "Done: retry: Backend outage\n"
        self.tick(hosts=hosts)
        self.tick(hosts=hosts)
        settlement, = [entry for entry in log.read() if entry["ev"] == "finding.settled"]
        self.assertEqual((settlement["verdict"], settlement["section"]), ("left", ""))
        self.assertEqual(fixes.tasks(self.plan, log.read()), {})
        self.assertEqual(findings.findings(log.read())["finding-1"].state, "left")
        self.assertEqual(findings.rungs(self.plan, log.read(), self.editions, qa.STAMP)[0].state, "due")
        self.assertFalse(any(entry["kind"] == "implement" for entry in log.read()
                             if entry["ev"] == "run.started"))

    def test_finding_tick_failed_foreman_starts_with_the_finding_alone(self):
        hosts = self.finding_hosts()
        self.add_walk()
        self.append(qa.finding_triaged("finding-1", "path", reason="Blocks the story"))
        self.tick(hosts=hosts)
        self.finding_reports["ladder/finding-1/foreman-1"] = "Failed: Cannot decide\n"
        self.tick(hosts=hosts)
        self.assertTrue(any(a.kind == "start" and a.task == "ladder/finding-1"
                            for a in self.tick(hosts=hosts)))
        brief = (log.home() / "runs/ladder/finding-1-1/brief.md").read_text()
        self.assertIn("Blocks the story", brief)
        self.assertIn("The story stalled", brief)
        self.assertNotIn("## Repair (", brief)
        self.assertFalse(any(entry["ev"] == "finding.settled" for entry in log.read()))

    def test_finding_tick_unreadable_foreman_report_settles_none(self):
        hosts = self.finding_hosts()
        self.add_walk()
        self.append(qa.finding_triaged("finding-1", "path"))
        self.tick(hosts=hosts)
        self.append(run_ended("ladder/finding-1/foreman", report=str(self.home / "missing")))
        self.tick(hosts=hosts)
        settlement, = [entry for entry in log.read() if entry["ev"] == "finding.settled"]
        self.assertEqual((settlement["verdict"], settlement["section"]), ("none", ""))
        self.assertTrue(any(a.kind == "start" and a.task == "ladder/finding-1"
                            for a in self.tick(hosts=hosts)))

    def test_finding_tick_foremen_share_one_tip_even_at_zero_places(self):
        hosts = self.finding_hosts(places=0)
        self.add_walk(identifiers=("finding-9", "finding-2"))
        self.append(qa.finding_triaged("finding-9", "path"), qa.finding_triaged("finding-2", "path"))
        self.tick(hosts=hosts)
        started = [entry for entry in log.read() if entry["ev"] == "run.started"]
        self.assertEqual([(entry["finding"], entry["host"], entry["tip"]) for entry in started],
                         [("finding-9", "builder", "main-tip"), ("finding-2", "builder", "main-tip")])
        self.tick(hosts=hosts)
        tips = [call for call in self.fake.calls if call.argv == ["git", "rev-parse", "origin/main"]]
        self.assertEqual([call.cwd for call in tips], [str(self.home)])
        self.assertEqual(sum(entry["ev"] == "run.started" for entry in log.read()), 2)

    def test_finding_tick_chooses_builder_with_most_free_places(self):
        hosts = self.finding_hosts(places=1)
        hosts["other"] = Host("other", "fake@other", ("builder",), places=3)
        self.add_walk()
        self.append(qa.finding_triaged("finding-1", "path"))
        self.tick(hosts=hosts)
        survey, = [entry for entry in log.read() if entry["ev"] == "run.started"]
        self.assertEqual(survey["host"], "other")

    def test_finding_tick_failed_tip_notes_once_for_all_foremen_and_retries(self):
        hosts = self.finding_hosts()
        self.add_walk(identifiers=("finding-1", "finding-2"))
        self.append(qa.finding_triaged("finding-1", "path"), qa.finding_triaged("finding-2", "path"))
        failure = (["git", "rev-parse", "origin/main"], Result(1, err="main unavailable"))
        self.fake.rules.insert(0, failure)
        self.tick(hosts=hosts)
        notes = [entry for entry in log.read() if entry["ev"] == "note"]
        self.assertEqual(len(notes), 1)
        self.assertIn("main unavailable", notes[0]["text"])
        self.assertFalse(any(entry["ev"] == "run.started" for entry in log.read()))
        self.fake.rules.remove(failure)
        self.tick(hosts=hosts)
        self.assertEqual(sum(entry["ev"] == "run.started" for entry in log.read()), 2)

    def test_finding_tick_red_and_finding_share_examine_and_remedy_rounds(self):
        hosts = self.finding_hosts()
        self.add_walk()
        self.append(qa.finding_triaged("finding-1", "path"),
                    log.record("red.opened", red="red-1", tip="red-tip", keys=["key"],
                               suspects=[], tasks=[], draft="ladder", route="foreman"))
        actions = self.tick(hosts=hosts)
        self.assertEqual([a.run_kind for a in actions if a.kind == "examine-fix"], ["red", "finding"])
        self.finding_reports.update({"ladder/red-1/foreman-1": "Done: fix: Repair the red\n",
                                     "ladder/finding-1/foreman-1": "Done: fix: Repair the finding\n"})
        actions = self.tick(hosts=hosts)
        self.assertEqual([a.run_kind for a in actions if a.kind == "remedy-fix"], ["red", "finding"])
        self.assertEqual([entry["ev"] for entry in log.read()
                          if entry["ev"] in ("red.settled", "finding.settled")],
                         ["red.settled", "finding.settled"])
        self.assertEqual([call.argv for call in self.fake.calls].count(
            ["git", "rev-parse", "origin/main"]), 1)

    def test_finding_tick_landed_repair_is_an_after_landing_suspect_with_its_body(self):
        hosts = self.finding_hosts()
        hosts["tiers"] = Host("tiers", "fake@tiers", ("after-landing",))
        self.add_walk()
        self.append(qa.finding_triaged("finding-1", "path"))
        self.tick(hosts=hosts)
        self.finding_reports["ladder/finding-1/foreman-1"] = "Failed: Cannot decide\n"
        self.tick(hosts=hosts)
        self.tick(hosts=hosts)
        self.finding_queue.append(dict(ev="landed", ts="queue-1", branch="ladder/finding-1",
                                       tip="repair-tip", main="fixed-main"))
        self.finding_tiers += [dict(ev="test", state="new", ts="tiers-1", key="new-key", tip="fixed-main",
                                   branches=["ladder/finding-1"]),
                               dict(ev="run", ts="tiers-2", tip="fixed-main", reds=["new-key"],
                                    branches=["ladder/finding-1"])]
        self.tick(hosts=hosts)
        opened, = [entry for entry in log.read() if entry["ev"] == "red.opened"]
        self.assertEqual((opened["draft"], opened["route"], opened["tasks"]),
                         ("ladder", "foreman", ["ladder/finding-1"]))
        brief = (log.home() / "runs/ladder/red-1/foreman-1/brief.md").read_text()
        self.assertIn("# Repair a QA finding (finding-1)", brief)

    def test_brief_park_blocks_triage_until_answer_or_later_start(self):
        self.add_walk()
        park = dict(ev="call.parked", subject="ladder/triage", call="", role="triage",
                    reason="brief failed: oversized", report="", ts="2026-11-01T00:01:00.000Z")
        events = log.read()
        actions = lambda records: dispatch.call_actions(self.plan, {}, records, [], "2026-11-01T01:00:00.000Z")
        self.assertTrue(any(action.run_kind == "triage" for action in actions(events)))
        self.assertFalse(any(action.run_kind == "triage" for action in actions(events + [park])))
        answered = dict(ev=channel.ANSWERED, subject="ladder/triage")
        started = call_started("retry", "triage", "ladder/triage", ts="2026-11-01T00:02:00.000Z")
        ended = call_ended("retry", "failed", role="triage", subject="ladder/triage",
                           ts="2026-11-01T00:03:00.000Z")
        for lifted in ([answered], [started, ended]):
            self.assertTrue(any(action.run_kind == "triage" for action in actions(events + [park, *lifted])))

    def test_failed_walk_starts_one_triage_call_with_subject_unit_and_plan(self):
        self.add_walk()
        actions = self.tick()
        self.assertEqual([action for action in actions if action.kind == "call"],
                         [Action("call", task="ladder/triage", run_kind="triage")])
        self.assertEqual([argv for argv in self.fake.argvs() if argv[0] == "systemd-run"],
                         [["systemd-run", "--user", "--collect", "--unit",
                           drafts.unit("triage", "ladder/triage"),
                           f"--setenv=FAB_HOME={log.home()}",
                           FAB, "call", "triage",
                           "--plan", str(self.directory.resolve()), "--tick"]])

    def test_passing_walk_waits_until_thirty_minutes(self):
        self.add_walk(verdict="pass")
        self.now.return_value = "2026-11-01T00:29:59.000Z"
        self.assertFalse(any(action.kind == "call" for action in self.tick()))
        self.now.return_value = "2026-11-01T00:30:00.000Z"
        self.assertEqual([action.run_kind for action in self.tick() if action.kind == "call"],
                         ["triage"])

    def test_passing_walk_starts_when_four_new_findings_accumulate(self):
        self.add_walk(verdict="pass", identifiers=("finding-1", "finding-2", "finding-3"))
        self.assertFalse(any(action.kind == "call" for action in self.tick()))
        self.add_walk(2, verdict="pass", identifiers=("finding-4",))
        self.assertEqual([action.run_kind for action in self.tick() if action.kind == "call"],
                         ["triage"])

    def test_open_triage_question_blocks_urgent_findings_across_ticks(self):
        self.add_walk()
        self.end_triage("Question: Which path?", outcome="question")
        self.tick()
        self.tick()
        self.assertEqual(units(self.fake), [])

    def test_triage_in_flight_starts_no_second_call(self):
        self.add_walk()
        self.append(log.record("call.started", call="triage-1", role="triage",
                               subject="ladder/triage"))
        self.tick()
        self.tick()
        self.assertEqual(units(self.fake), [])

    def test_other_drafts_findings_do_not_start_triage(self):
        self.add_walk(draft="other")
        self.tick()
        self.assertEqual(units(self.fake), [])

    def test_ended_triage_report_records_each_decision_once_across_ticks(self):
        self.add_walk(identifiers=tuple(f"finding-{n}" for n in range(1, 8)))
        self.end_triage("""Done: 7 decisions
finding-1: path ctl: Repair the story
finding-2: path box: Repair the connection; user: Reinstall the app
finding-3: backlog: Outside the story
finding-4: user: Which account?
finding-5: brief b0: The gate is beatable
finding-6: merge finding-1: Same cause
finding-7: drop: Walk setup
""")
        self.end_triage("Done: 1 decisions\nfinding-3: drop: Other draft\n",
                        call="other-triage", draft="other")
        self.tick()
        first = [entry for entry in log.read() if entry["ev"].startswith("finding.")
                 and entry["ev"] != "finding.raised"]
        self.tick()
        self.assertEqual([entry for entry in log.read() if entry["ev"].startswith("finding.")
                          and entry["ev"] != "finding.raised"], first)
        self.assertEqual([entry.get("decision", "merge") for entry in first],
                         ["path", "path", "backlog", "user", "brief", "merge", "drop"])
        self.assertEqual(first[1]["question"], "Reinstall the app")
        self.assertEqual(first[4]["owner"], "b0")
        self.assertEqual(first[5]["by"], "triage-1")
        self.assertEqual(units(self.fake), [])
        self.assertEqual(self.out.getvalue().count("triage ladder 7 records\n"), 1)

    def test_report_with_no_decisions_records_one_note(self):
        self.add_walk()
        self.end_triage("Done: no valid lines\n")
        self.tick()
        self.tick()
        notes = [entry for entry in log.read() if entry["ev"] == "note"]
        self.assertEqual([entry["text"] for entry in notes], ["triage triage-1: no decisions"])

    def test_missing_report_is_noted_and_retried_when_it_arrives(self):
        self.add_walk()
        self.end_triage(None)
        self.tick()
        notes = [entry for entry in log.read() if entry["ev"] == "note"]
        self.assertEqual(len(notes), 1)
        self.assertIn("triage-1/report.md", notes[0]["text"])
        atomic.write(log.home() / "calls/triage-1/report.md",
                     "Done: 1 decisions\nfinding-1: drop: Walk setup\n")
        self.tick()
        self.assertEqual([entry["decision"] for entry in log.read()
                          if entry["ev"] == "finding.triaged"], ["drop"])

    def test_rerun_records_one_pass_before_decide_and_none_on_next_tick(self):
        self.add_walk(verdict="pass", identifiers=())
        self.add_walk(2, verdict="pass", identifiers=())
        with patch.object(dispatch, "decide", wraps=dispatch.decide) as decide:
            self.tick()
        passed = [entry for entry in log.read() if entry["ev"] == "rung.passed"]
        self.assertEqual(passed, [qa.rung_passed("b0", walk="walk-2", commit="commit",
                                               edition=self.editions["b0"])])
        self.assertIn(passed[0], decide.call_args.args[2])
        self.tick()
        self.assertEqual([entry for entry in log.read() if entry["ev"] == "rung.passed"], passed)
        self.assertEqual(self.out.getvalue().count("passes ladder 1 rungs\n"), 1)

    def test_decisions_then_passes_reach_decide_and_use_one_edition_read(self):
        self.add_walk(verdict="pass")
        self.add_walk(2, verdict="pass", identifiers=())
        self.end_triage("Done: 1 decisions\nfinding-1: backlog: Off path\n")
        with patch.object(walks, "editions", wraps=walks.editions) as editions:
            with patch.object(dispatch, "decide", wraps=dispatch.decide) as decide:
                self.tick()
        editions.assert_called_once_with(self.plan, self.directory, sh=self.fake)
        self.assertEqual([entry["ev"] for entry in decide.call_args.args[2]][-3:],
                         ["finding.triaged", "rung.passed", "branch.ready"])
        self.assertEqual(units(self.fake), [])
        self.assertLess(self.out.getvalue().index("triage ladder"),
                        self.out.getvalue().index("passes ladder"))

    def test_changed_edition_does_not_record_old_rerun(self):
        self.add_walk(verdict="pass", identifiers=(), edition="old-edition")
        self.add_walk(2, verdict="pass", identifiers=(), edition="old-edition")
        self.tick()
        self.assertFalse(any(entry["ev"] == "rung.passed" for entry in log.read()))

    def test_unreadable_edition_logs_one_note_and_keeps_triage_moving(self):
        self.add_walk(verdict="pass", identifiers=tuple(f"finding-{n}" for n in range(1, 5)))
        self.add_walk(2, verdict="pass", identifiers=())
        brief = str((self.directory / "briefs/kit.md").relative_to(self.home))
        self.fake.rules.insert(0, (["git", "show", f"origin/main:{brief}"],
                                  Result(1, err="missing brief")))
        self.tick()
        notes = [entry for entry in log.read() if entry["ev"] == "note"]
        self.assertEqual(len(notes), 1)
        self.assertIn("b0", notes[0]["text"])
        self.assertIn("briefs/kit.md", notes[0]["text"])
        self.assertFalse(any(entry["ev"] == "rung.passed" for entry in log.read()))
        self.assertEqual(units(self.fake), [drafts.unit("triage", "ladder/triage")])
        self.fake.rules.pop(0)
        self.tick()
        self.assertEqual([entry["walk"] for entry in log.read() if entry["ev"] == "rung.passed"],
                         ["walk-2"])

    def test_ladder_records_respect_explicit_log_path(self):
        path = self.home / "custom/log.jsonl"
        self.add_walk(verdict="pass")
        self.add_walk(2, verdict="pass", identifiers=())
        self.end_triage("Done: 1 decisions\nfinding-1: backlog: Off path\n")
        atomic.write(path, log.default_path().read_text())
        log.default_path().unlink()
        self.tick(log_path=path)
        self.tick(log_path=path)
        self.assertEqual(log.read(), [])
        self.assertEqual([entry["ev"] for entry in log.read(path)
                          if entry["ev"] in ("finding.triaged", "rung.passed")],
                         ["finding.triaged", "rung.passed"])


    def ready_backlogs(self, path=None):
        return [entry for entry in log.read(path) if entry["ev"] == "branch.ready"
                and entry["branch"].startswith("ladder/ladder/backlog-")]

    def test_backlog_changed_readies_once_without_receipt_from_main(self):
        self.add_walk()
        self.end_triage("Done: 1 decisions\nfinding-1: backlog: Off path\n")
        self.tick()
        ready, = self.ready_backlogs()
        branch = "ladder/ladder/backlog-1"
        render = triage.backlog_text(self.plan, log.read())
        self.assertEqual(ready, log.record("branch.ready", task=branch, branch=branch,
                                          tip="backlog-tip", render=triage.render_key(render)))
        worktree = log.home() / "backlog/ladder-1"
        self.assertEqual((worktree / self.plan.ladder.backlog).read_text(), render)
        self.assertIn(["git", "show", f"origin/main:{self.plan.ladder.backlog}"],
                      self.fake.argvs())
        self.assertIn(["git", "worktree", "add", "-B", branch, str(worktree), "origin/main"],
                      self.fake.argvs())
        self.assertIn([*dispatch.FAB_GIT, "commit", "-q", "-m",
                       "ladder ladder: the backlog from the log (1 findings)", "--",
                       self.plan.ladder.backlog], self.fake.argvs())
        self.assertIn(["git", "push", "origin", f"backlog-tip:refs/heads/ready/{branch}"],
                      self.fake.argvs())
        self.assertFalse(any("receipt" in argv for argv in self.fake.argvs()))
        self.fake.calls.clear()
        self.tick()
        self.assertEqual(self.ready_backlogs(), [ready])
        self.assertFalse(any(argv[:2] == ["git", "worktree"] for argv in self.fake.argvs()))

    def test_backlog_missing_on_main_is_added_even_without_findings(self):
        self.backlog = None
        self.tick()
        ready, = self.ready_backlogs()
        self.assertEqual(ready["branch"], "ladder/ladder/backlog-1")
        self.assertIn(["git", "add", "--", self.plan.ladder.backlog], self.fake.argvs())
        self.assertEqual((log.home() / "backlog/ladder-1" / self.plan.ladder.backlog).read_text(),
                         triage.backlog_text(self.plan, []))

    def test_backlog_unchanged_on_main_readies_nothing_despite_local_edit(self):
        atomic.write(self.home / self.plan.ladder.backlog, "local edits\n")
        self.tick()
        self.assertEqual(self.ready_backlogs(), [])
        self.assertFalse(any(argv[:2] == ["git", "worktree"] for argv in self.fake.argvs()))

    def test_backlog_queue_landing_advances_cursor_and_next_decision_readies_two(self):
        self.add_walk()
        self.end_triage("Done: 1 decisions\nfinding-1: backlog: Off path\n")
        self.tick()
        branch = self.ready_backlogs()[0]["branch"]
        self.backlog = triage.backlog_text(self.plan, log.read())
        queue = [dict(ev="landed", ts="queue-1", branch=branch, tip="backlog-tip", main="main-tip")]
        self.fake.on(["ssh"], lambda call: Result(0, "\n".join(json.dumps(e) for e in queue)))
        hosts = {"gate": Host("gate", "fake@gate", ("gate",))}
        self.tick(hosts=hosts)
        landed, = [entry for entry in log.read() if entry["ev"] == "branch.landed"]
        self.assertEqual((landed["task"], landed["branch"], landed["queue_ts"], landed["into"]),
                         (branch, branch, "queue-1", ""))
        self.assertFalse(any(entry["ev"].startswith("queue.") for entry in log.read()))
        self.fake.calls.clear()
        self.add_walk(2, identifiers=("finding-2",))
        self.end_triage("Done: 1 decisions\nfinding-2: backlog: Later work\n", call="triage-2")
        self.tick(hosts=hosts)
        self.assertIn(ssh("fake@gate", ["fab", "queue", "log", "--since", "queue-1"]),
                      self.fake.argvs())
        self.assertEqual([entry["branch"] for entry in self.ready_backlogs()],
                         [branch, "ladder/ladder/backlog-2"])
        self.assertEqual(len([entry for entry in log.read() if entry["ev"] == "branch.landed"]), 1)

    def reject_backlog_twice(self):
        self.add_walk()
        self.end_triage("Done: 1 decisions\nfinding-1: backlog: Off path\n")
        queue = []
        self.fake.on(["ssh"], lambda call: Result(
            0, "\n".join(json.dumps(entry) for entry in queue)))
        hosts = {"gate": Host("gate", "fake@gate", ("gate",))}
        self.tick(hosts=hosts)
        for number in (1, 2):
            branch = f"ladder/ladder/backlog-{number}"
            queue.append(dict(ev="rejected", ts=f"queue-{number}", branch=branch,
                              tip="backlog-tip", step="test", log="/gate/log"))
            self.tick(hosts=hosts)
        self.tick(hosts=hosts)
        self.assertEqual(len(self.ready_backlogs()), 2)
        rejections = [entry for entry in log.read() if entry["ev"] == "branch.rejected"]
        self.assertEqual([entry["task"] for entry in rejections],
                         [f"ladder/ladder/backlog-{number}" for number in (1, 2)])
        render = triage.render_key(triage.backlog_text(self.plan, log.read()))
        self.assertEqual(triage.backlog_held(self.plan, log.read(), render), rejections[-1])
        return queue, hosts

    def test_backlog_two_queue_rejections_hold_until_render_changes(self):
        queue, hosts = self.reject_backlog_twice()
        self.add_walk(2, identifiers=("finding-2",))
        self.end_triage("Done: 1 decisions\nfinding-2: backlog: Another\n", call="triage-2")
        self.tick(hosts=hosts)
        self.assertEqual(self.ready_backlogs()[-1]["branch"], "ladder/ladder/backlog-3")
        self.assertEqual(len(self.ready_backlogs()), 3)

    def test_backlog_two_queue_rejections_hold_until_clear(self):
        queue, hosts = self.reject_backlog_twice()
        self.append(log.record("signal.cleared", signal="backlog:ladder", by="user", text="Try again"))
        self.tick(hosts=hosts)
        self.assertEqual(self.ready_backlogs()[-1]["branch"], "ladder/ladder/backlog-3")
        self.assertEqual(len(self.ready_backlogs()), 3)

    def test_backlog_queue_landing_clears_rejection_hold(self):
        queue, hosts = self.reject_backlog_twice()
        self.backlog = triage.backlog_text(self.plan, log.read())
        queue.append(dict(ev="landed", ts="queue-3", branch="ladder/ladder/backlog-2",
                          tip="backlog-tip", main="main-tip"))
        self.tick(hosts=hosts)
        render = triage.render_key(self.backlog)
        self.assertIsNone(triage.backlog_held(self.plan, log.read(), render))
        self.assertEqual(len(self.ready_backlogs()), 2)

    def test_backlog_failed_commit_notes_path_and_retries_later(self):
        self.backlog = None
        failure = (["git", "add"], Result(1, err="cannot stage backlog"))
        self.fake.rules.insert(0, failure)
        self.tick()
        self.assertEqual(self.ready_backlogs(), [])
        notes = [entry for entry in log.read() if entry["ev"] == "note"]
        self.assertEqual(len(notes), 1)
        self.assertIn(self.plan.ladder.backlog, notes[0]["text"])
        self.assertIn("cannot stage backlog", notes[0]["text"])
        self.fake.rules.remove(failure)
        self.tick()
        self.assertEqual(self.ready_backlogs()[0]["branch"], "ladder/ladder/backlog-1")

    def test_backlog_unreadable_main_notes_path_and_keeps_triage_moving(self):
        self.add_walk()
        self.fake.rules.insert(0, (["git", "show", f"origin/main:{self.plan.ladder.backlog}"],
                                  Result(1, err="cannot read backlog")))
        self.tick()
        self.assertEqual(self.ready_backlogs(), [])
        notes = [entry for entry in log.read() if entry["ev"] == "note"]
        self.assertEqual(len(notes), 1)
        self.assertIn(self.plan.ladder.backlog, notes[0]["text"])
        self.assertEqual(units(self.fake), [drafts.unit("triage", "ladder/triage")])

    def test_backlog_forms_of_unloaded_and_unreadied_plans_stay_out_of_queue_records(self):
        branches = ("ladder/other/backlog-1", "ladder/ladder/backlog-1", "ladder/other/manual")
        self.append(log.record("branch.ready", task=branches[0], branch=branches[0], tip="tip"))
        queue = [dict(ev="rejected", ts=str(index), branch=branch, tip="tip", step="test")
                 for index, branch in enumerate(branches)]
        self.fake.on(["ssh"], lambda call: Result(0, "\n".join(json.dumps(e) for e in queue)))
        self.tick(hosts={"gate": Host("gate", "fake@gate", ("gate",))})
        self.assertFalse(any("queue_ts" in entry for entry in log.read()))


class TickTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(dispatch, "blocking", return_value=False))
        self.home = self.enterContext(tmp_home())
        self.directory = self.home / "plan"
        write(self.directory / "plan.toml", '''draft = "draft"
repo = "agents"
landing = "queue"
reviews = true
direct = false
[[part]]
id = "core"
title = "Core"
mode = "feature"
needs = []
design = "design.md"
[[slice]]
id = 1
story = "Tasks run"
parts = ["core"]
walk = false
''')
        self.add_task("a")
        self.hosts = {"builder": Host("builder", "fake@builder", ("builder",), places=2),
                      "gate": Host("gate", "fake@gate", ("gate",))}
        self.fake = FakeRunner().on(["git", "rev-parse", "--show-toplevel"], Result(128))
        self.calls = []
        self.start = self.enterContext(patch("fab.run.start", side_effect=self.record_start))
        self.collect = self.enterContext(patch("fab.run.collect", side_effect=self.record_collect))
        self.land = self.enterContext(patch("fab.land.main", side_effect=self.record_land))
        self.screen = self.enterContext(patch("fab.gates.screen", return_value=[]))
        self.rust_screen = self.enterContext(patch.object(rust_gates, "screen", return_value=[]))
        self.out = io.StringIO()
        self.enterContext(redirect_stdout(self.out))

    def add_task(self, name, repo="agents", needs=()):
        write(self.directory / "tasks" / f"{name}.md",
              f'+++\nid = "{name}"\npart = "core"\nkind = "feature"\nrepo = "{repo}"\n'
              f"needs = {list(needs)!r}\n+++\n")

    def record_start(self, task, host, **kwargs):
        self.calls.append(("start", task.id, host.name, kwargs))
        return task.id + "-1"

    def record_collect(self, run_id, events, hosts, **kwargs):
        self.calls.append(("collect", run_id, events, hosts, kwargs))

    def record_land(self, argv):
        self.calls.append(("land", argv))
        return 0

    def append(self, *events, path=None):
        for entry in events:
            fields = dict(entry)
            ev = fields.pop("ev")
            log.append(ev, path=path, **fields)

    def tick(self, **kwargs):
        """Return work actions, leaving the printed flow diagnostic in captured output."""
        return [action for action in dispatch.tick(
            self.directory, sh=self.fake, hosts=kwargs.pop("hosts", self.hosts), **kwargs)
                if action.kind != "flow"]

    def queue(self, records):
        self.fake.on(ssh("fake@gate", ["fab", "queue", "log"])[:-1],
                     Result(0, "\n".join(json.dumps(r) for r in records)))

    def test_tick_measures_before_deciding_and_prints_flow_without_logging_it(self):
        self.hosts["builder"] = replace(self.hosts["builder"], places=1, slots=2)
        self.append(dict(started("foreign"), task="other/foreign"))
        probe = ssh("fake@builder", flow.PROBE + ["/home/fake/src/fabrig/fab/heavy.jsonl"])
        self.fake.on(probe, Result(0, "0.1 0.2 0.3\n2\n"))
        with patch("fab.dispatch.decide", wraps=dispatch.decide) as decide:
            actions = dispatch.tick(self.directory, sh=self.fake, hosts=self.hosts)
        self.assertEqual(decide.call_args.args[-1], {"builder": True})
        self.assertEqual([a.kind for a in actions], ["flow", "start", "collect"])
        self.assertEqual(actions[0], Action("flow", task="draft", detail="target 1, 0 in flight"))
        self.assertEqual(self.out.getvalue().splitlines()[0], "flow draft target 1, 0 in flight")
        self.assertEqual(self.fake.argvs().count(probe), 1)
        self.assertEqual([e["ev"] for e in log.read()], ["run.started"])
        self.start.assert_called_once()

    def test_tick_writes_page_after_actions_using_explicit_log_and_registered_plans(self):
        path = self.home / "custom/log.jsonl"
        self.append(dict(ev="call.ended", call="cut", subject="draft/cut", outcome="question"), path=path)
        write(log.home() / "calls/cut/report.md", "Question: Buy a host?\n")
        from fab.tests.ladder_plans import write_ladder
        registered = write_ladder(self.home / "other", "other")
        write(registered / "plan.toml", (registered / "plan.toml").read_text() + '''[[question]]
id = "budget"
text = "Choose the budget"
parts = []
''')
        write(log.home() / channel.PLANS, str(registered) + "\n")
        self.assertEqual([action.kind for action in self.tick(log_path=path)], ["start"])
        page = (log.home() / channel.PAGE).read_text()
        self.assertIn("Question: Buy a host?", page)
        self.assertIn("Choose the budget", page)
        self.assertEqual(self.out.getvalue().splitlines()[-1], f"page - {log.home() / channel.PAGE}")
        self.assertEqual(log.read(), [])

    def test_tick_page_failure_prints_one_line_logs_nothing_and_keeps_actions(self):
        for failure in (OSError("disk\nfull"), ValueError("invalid\npage")):
            with self.subTest(failure=failure):
                self.out.seek(0)
                self.out.truncate()
                with patch.object(channel, "write", side_effect=failure):
                    actions = self.tick()
                self.assertEqual([action.kind for action in actions], ["start"])
                self.assertEqual(self.out.getvalue().splitlines()[-1],
                                 "page - failed: " + " ".join(str(failure).splitlines()))
                self.assertEqual(log.read(), [])

    def test_tick_measures_even_with_free_places_and_failed_probe_is_not_calm(self):
        probe = ssh("fake@builder", flow.PROBE + ["/home/fake/src/fabrig/fab/heavy.jsonl"])
        self.fake.on(probe, Result(255, err="offline"))
        with patch("fab.dispatch.decide", wraps=dispatch.decide) as decide:
            self.tick()
        self.assertEqual(decide.call_args.args[-1], {"builder": False})
        self.assertEqual(self.fake.argvs().count(probe), 1)
        self.start.assert_called_once()

    def test_torn_queue_lines_skipped_while_valid_records_are_imported(self):
        prefix = ssh("fake@gate", ["fab", "queue", "log"])[:-1]
        self.fake.on(prefix, Result(0, '{"ev":\n[]\n{"ev":"landed","branch":"draft/a"}\n'
                                   '{"ev":"landed","ts":"001","branch":"draft/a","tip":"a","main":"main"}\n'))
        self.tick()
        self.assertEqual([(e["ev"], e["task"]) for e in log.read()], [("branch.landed", "draft/a")])

    def test_queue_import_skips_torn_and_incomplete_records(self):
        record = dict(ev="landed", ts="001", branch="draft/a", tip="tip", main="main")
        self.fake.on(ssh("fake@gate", ["fab", "queue", "log"])[:-1],
                     Result(0, '\n'.join(('torn {', 'null', '[]', '{"ev":"landed"}',
                                           '{"ev":"landed","branch":3,"ts":"001"}', json.dumps(record)))))
        self.tick()
        self.assertEqual([entry["ev"] for entry in log.read()], ["branch.landed"])
        self.assertEqual(log.read()[0]["tip"], "tip")


    def test_queue_import_continues_after_a_torn_line_between_records(self):
        """Import intact landings once even when finishing the plan starts retirement."""
        self.add_task("b")
        first = dict(ev="landed", ts="001", branch="draft/a", tip="a", main="main")
        second = dict(ev="landed", ts="002", branch="draft/b", tip="b", main="main")
        prefix = ssh("fake@gate", ["fab", "queue", "log"])[:-1]
        self.fake.on(prefix, Result(0, json.dumps(first) + '\n{"ev":\n' + json.dumps(second)))
        self.tick()
        self.assertEqual([(entry["task"], entry["queue_ts"]) for entry in log.read()],
                         [("draft/a", "001"), ("draft/b", "002")])
        self.tick()
        self.assertEqual(len(log.read()), 2)
        queries = [argv for argv in self.fake.argvs() if argv[:len(prefix)] == prefix]
        self.assertEqual(queries[-1], ssh("fake@gate", ["fab", "queue", "log", "--since", "002"]))

    def test_import_queue_records_once_including_shared_timestamps_and_rebases(self):
        self.add_task("b")
        self.add_task("c")
        records = [dict(ev="batch", ts="001", branches=["draft/a"]),
                   dict(ev="landed", ts="002", branch="draft/a", tip="a", main="main"),
                   dict(ev="rejected", ts="002", branch="draft/b-r2", tip="b", step="merge", log="conflict"),
                   dict(ev="landed", ts="003", branch="elsewhere/task", tip="x", main="main"),
                   dict(ev="landed", ts="002", branch="draft/c", tip="c", main="main")]
        self.queue(records + [records[1]])
        with patch.object(repairs, "start") as examine:
            self.tick()
            first = log.read()
            self.tick()
        self.assertEqual(examine.call_count, 2)
        self.assertEqual(examine.call_args.args[0].step, "merge")
        self.assertEqual(examine.call_args.args[0].branch, "draft/b-r2")
        self.assertEqual([(e["ev"], e.get("task"), e["branch"]) for e in first],
                         [("branch.landed", "draft/a", "draft/a"),
                          ("branch.rejected", "draft/b", "draft/b-r2"),
                          ("queue.landed", None, "elsewhere/task"),
                          ("branch.landed", "draft/c", "draft/c")])
        self.assertEqual([e["queue_ts"] for e in first], ["002", "002", "003", "002"])
        self.assertEqual(first[1]["step"], "merge")
        self.assertEqual(first[1]["log"], "conflict")
        self.assertEqual(first[1]["branch"], "draft/b-r2")
        self.start.assert_not_called()
        self.assertEqual(log.read(), first)
        commands = [shlex.split(c.argv[-1].removeprefix("bash -lc "))[0]
                    for c in self.fake.calls if c.argv[0] == "ssh" and c.argv[5] == "fake@gate"]
        self.assertEqual(commands, ["fab queue log --since ''", "fab queue log --since 002"])

    def test_a_failed_queue_import_is_noted_and_the_tick_goes_on(self):
        self.add_task("b")
        self.fake.on(ssh("fake@gate", ["fab", "queue", "log"])[:-1], Result(1, err="no queue here"))
        with redirect_stdout(io.StringIO()):
            self.tick()
        notes = [e["text"] for e in log.read() if e["ev"] == "note"]
        self.assertEqual(notes, ["queue import failed: no queue here"])
        self.assertEqual([call[0] for call in self.calls], ["start", "start"])

    def test_each_action_is_carried_out_in_order_and_printed(self):
        for name, repo in (("b", "agents"), ("c", "fabrig"), ("d", "agents"), ("e", "agents")):
            self.add_task(name, repo)
        self.append(started("a"), started("b"), ended("b"), started("c"), ended("c"))
        self.append(*(e for n in range(1, MAX_RUNS + 1)
                      for e in (started("d", n), ended("d", n, "infra"))))
        self.append(*growth())
        self.fake.on(["git", "rev-parse", "--verify"], Result(0, "tip-c\n"))
        actions = self.tick()
        self.assertEqual([a.kind for a in actions], ["collect", "land", "ready", "park", "start"])
        self.assertEqual([c[0] for c in self.calls], ["collect", "land", "start"])
        self.assertEqual(self.calls[0][1], "draft/a-1")
        self.assertEqual(self.calls[0][3], self.hosts)
        self.assertIs(self.calls[0][4]["sh"], self.fake)
        self.assertEqual(self.calls[1][1], ["draft/b", "--task", "draft/b"])
        self.assertEqual(self.calls[2][:3], ("start", "draft/e", "builder"))
        self.assertEqual(self.calls[2][3]["kind"], "implement")
        ready, park = log.read()[-2:]
        self.assertEqual((ready["ev"], ready["branch"], ready["tip"]),
                         ("branch.ready", "draft/c", "tip-c"))
        self.assertEqual((park["ev"], park["task"], park["text"]),
                         ("question.asked", "draft/d", actions[3].detail))
        push = next(c for c in self.fake.calls if c.argv[:2] == ["git", "push"])
        self.assertEqual(push.argv, ["git", "push", "origin", "tip-c:refs/heads/ready/draft/c"])
        self.assertEqual(push.cwd, str(log.home() / "repos" / "fabrig"))
        self.assertEqual(self.out.getvalue().splitlines(),
                         ["flow draft target 3, 1 in flight",
                          *[f"{a.kind} {a.task or '-'} {a.detail}" for a in actions],
                          f"page - {log.home() / channel.PAGE}", "again - tick 1: question.asked"])
        # Ready and parked tasks are not handed off or parked twice.
        self.tick()
        self.assertEqual(len([e for e in log.read() if e["ev"] == "branch.ready"]), 1)
        self.assertEqual(len([e for e in log.read() if e["ev"] == "question.asked"]), 1)

    def repaired_ready(self, rejected_tip):
        self.add_task("a", repo="fabrig")
        branch = "draft/a-r1"
        self.append(started(branch=branch), ended(),
                    event("branch.rejected", branch=branch, tip="tip", step="default", log="old"),
                    event("branch.rejected", branch=branch, tip=rejected_tip, step="default", log="red"),
                    dict(started(n=2, branch=branch), kind="repair"), ended(n=2))
        self.fake.on(["git", "rev-parse", "--verify"], Result(0, "tip\n"))
        self.fake.on(ssh("fake@builder", ["cat", "/home/fake/src/fabrig/fab/precheck/tip.json"]),
                     Result(1))
        return branch

    def test_ready_delivers_builder_receipt_before_push_after_same_tip_untry(self):
        tip = "a" * 40
        branch = "draft/a-r1"
        path = self.home / "custom/events.jsonl"
        self.add_task("a", repo="fabrig")
        self.append(dict(started(branch=branch), kind="implement"), ended(),
                    event("branch.rejected", branch=branch, tip=tip, step="default", log="red"),
                    dict(started(n=2, branch=branch), kind="repair"), ended(n=2), path=path)
        receipt = json.dumps(dict(tip=tip, main="b" * 40, outcome="green",
                                  selection="full", steps=["default:0:1"])) + "\n"
        self.fake.on(["git", "rev-parse", "--verify"], Result(0, tip + "\n"))
        read = ssh("fake@builder", ["cat", f"/home/fake/src/fabrig/fab/precheck/{tip}.json"])
        self.fake.on(read, Result(0, receipt))
        accept = ssh("fake@gate", ["fab", "queue", "receipt", tip])
        self.fake.on(accept, Result(0))

        self.assertEqual([action.kind for action in self.tick(log_path=path)], ["ready"])
        commands = self.fake.argvs()
        untry = ssh("fake@gate", ["fab", "queue", "untry", branch])
        push = ["git", "push", "origin", f"{tip}:refs/heads/ready/{branch}"]
        self.assertLess(commands.index(untry), commands.index(read))
        self.assertLess(commands.index(read), commands.index(accept))
        self.assertLess(commands.index(accept), commands.index(push))
        self.assertEqual(next(call.input for call in self.fake.calls if call.argv == accept), receipt)
        ready = log.read(path)[-1]
        self.assertEqual((ready["ev"], ready["branch"], ready["tip"]),
                         ("branch.ready", branch, tip))
        self.assertEqual(log.read(), [])

    def test_ready_with_missing_builder_receipt_still_pushes_and_logs_ready(self):
        tip = "a" * 40
        self.add_task("a", repo="fabrig")
        self.append(dict(started(), kind="implement"), ended())
        self.fake.on(["git", "rev-parse", "--verify"], Result(0, tip + "\n"))
        read = ssh("fake@builder", ["cat", f"/home/fake/src/fabrig/fab/precheck/{tip}.json"])
        self.fake.on(read, Result(1, err="no receipt"))

        self.assertEqual([action.kind for action in self.tick()], ["ready"])
        commands = self.fake.argvs()
        push = ["git", "push", "origin", f"{tip}:refs/heads/ready/draft/a"]
        self.assertLess(commands.index(read), commands.index(push))
        self.assertNotIn(ssh("fake@gate", ["fab", "queue", "receipt", tip]), commands)
        ready = log.read()[-1]
        self.assertEqual((ready["ev"], ready["branch"], ready["tip"]),
                         ("branch.ready", "draft/a", tip))
        self.assertFalse(any(entry["ev"] == "note" for entry in log.read()))

    def test_same_tip_ready_untries_on_gate_before_push_and_notes_retry_once(self):
        branch = self.repaired_ready("tip")
        self.tick()
        untry = ssh("fake@gate", ["fab", "queue", "untry", branch])
        commands = self.fake.argvs()
        self.assertIn(untry, commands)
        push = ["git", "push", "origin", f"tip:refs/heads/ready/{branch}"]
        self.assertLess(commands.index(untry), commands.index(push))
        note, ready = log.read()[-2:]
        self.assertEqual((note["ev"], note["text"]),
                         ("note", "retry draft/a: same tip after repair"))
        self.assertEqual((ready["ev"], ready["branch"], ready["tip"]),
                         ("branch.ready", branch, "tip"))
        self.tick()
        self.assertEqual(self.fake.argvs().count(untry), 1)

    def test_new_tip_ready_uses_last_rejection_and_pushes_without_untry(self):
        branch = self.repaired_ready("older-tip")
        self.tick()
        self.assertNotIn(ssh("fake@gate", ["fab", "queue", "untry", branch]), self.fake.argvs())
        self.assertIn(["git", "push", "origin", f"tip:refs/heads/ready/{branch}"], self.fake.argvs())
        self.assertEqual(log.read()[-1]["ev"], "branch.ready")
        self.assertFalse(any(e["ev"] == "note" for e in log.read()))

    def test_failed_untry_prevents_ready_push_and_is_noted(self):
        branch = self.repaired_ready("tip")
        self.fake.on(ssh("fake@gate", ["fab", "queue", "untry", branch]),
                     Result(1, err="gate unavailable"))
        self.tick()
        self.assertFalse(any(argv[:2] == ["git", "push"] for argv in self.fake.argvs()))
        self.assertEqual(log.read()[-1]["ev"], "note")
        self.assertIn("gate unavailable", log.read()[-1]["text"])
        self.assertNotIn("branch.ready", [e["ev"] for e in log.read()])

    def test_design_starts_first_skeleton_in_user_unit(self):
        write(self.directory / "plan.toml", (self.directory / "plan.toml").read_text() +
              '\n[[part]]\nid="next"\ntitle="Next"\nmode="feature"\nneeds=[]\ndesign="next.md"\n')
        # Extend the slice to include the new part.
        path = self.directory / "plan.toml"
        write(path, path.read_text().replace('parts = ["core"]', 'parts = ["core", "next"]'))
        self.append(event("question.asked", text="Which?"))
        actions = self.tick()
        self.assertEqual(actions, [Action("design", detail="next"),
                                   Action("call", task="next", run_kind="skeleton")])
        self.assertEqual(self.fake.argvs()[-1],
                         ["systemd-run", "--user", "--collect", "--unit", drafts.unit("skeleton", "draft/next"),
                          f"--setenv=FAB_HOME={log.home()}",
                          FAB, "call", "skeleton", "next", "--plan", str(self.directory), "--tick"])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.out.getvalue(), "flow draft target 2, 0 in flight\ndesign - next\ncall next \n"
                         + f"page - {log.home() / channel.PAGE}\n")
        self.assertEqual(len(log.read()), 1)

    def test_call_unit_inherits_nondefault_fab_home(self):
        """A replay tick passes its runtime home as one unit environment argument."""
        replay_home = self.home / "replay home"
        with patch.dict(os.environ, {"FAB_HOME": str(replay_home)}):
            self.append(event("question.asked", ts="2000-01-01T00:00:00Z", text="Which?"))
            self.assertEqual(self.tick(), [Action("call", task="draft", run_kind="answer")])
        self.assertEqual(self.fake.argvs()[-1],
                         ["systemd-run", "--user", "--collect", "--unit", drafts.unit("answer", "draft"),
                          f"--setenv=FAB_HOME={replay_home}", FAB, "call", "answer",
                          "--plan", str(self.directory), "--tick"])

    def test_direct_part_without_specs_starts_no_design_call(self):
        path = self.directory / "plan.toml"
        write(path, path.read_text().replace('mode = "feature"', 'mode = "direct"'))
        (self.directory / "tasks/a.md").unlink()
        self.assertEqual(self.tick(), [])
        self.assertEqual(units(self.fake), [])
        self.start.assert_not_called()

    def test_start_passes_the_plans_checkout_root(self):
        self.fake.rules.insert(0, (["git", "rev-parse", "--show-toplevel"], Result(0, str(self.home))))
        self.tick()
        self.assertEqual(self.start.call_args.kwargs["checkout"], self.home)

    def test_contract_unit_passes_the_part_and_plan(self):
        """The tick launches a contract with its part in the subject-named unit."""
        (self.directory / "tasks/a.md").unlink()
        path = self.directory / "plan.toml"
        write(path, path.read_text().replace('mode = "feature"', 'mode = "feature"\ncontract = true'))
        self.assertEqual(self.tick(), [Action("design", detail="core"),
                                      Action("call", task="core", run_kind="contract")])
        self.assertEqual(self.fake.argvs()[-1],
                         ["systemd-run", "--user", "--collect", "--unit", drafts.unit("contract", "draft/core"),
                          f"--setenv=FAB_HOME={log.home()}",
                          FAB, "call", "contract", "core", "--plan", str(self.directory), "--tick"])
        self.assertEqual(self.calls, [])

    def test_retire_unit_takes_no_part_and_uses_subject(self):
        """Retirement follows completion and has no subject argument in the call argv."""
        self.append(event("branch.landed", tip="tip", main="main"),
                    dict(ev="call.started", call="old", role="retire", subject="draft/retire"),
                    dict(ev="call.ended", call="old", outcome="failed"))
        self.assertEqual(self.tick(), [Action("call", task="draft/retire", run_kind="retire")])
        self.assertEqual(self.fake.argvs()[-1],
                         ["systemd-run", "--user", "--collect", "--unit", drafts.unit("retire", "draft/retire"),
                          f"--setenv=FAB_HOME={log.home()}",
                          FAB, "call", "retire", "--plan", str(self.directory), "--tick"])
        self.assertEqual(self.calls, [])

    def test_uncut_plan_moves_its_cut_chain_after_fetch_with_no_tasks(self):
        """A logged cut substitutes an empty plan, imports the queue and reviews its branch."""
        (self.directory / "plan.toml").unlink()
        path = self.home / "cut.jsonl"
        history = chain_history("review", role="cut", subject="plan/cut")
        history[0]["options"] = ['landing="queue"', 'reviews=true', 'direct=false']
        self.append(*history, path=path)
        self.fake = FakeRunner().on(["git", "rev-parse", "--show-toplevel"],
                                    Result(0, "/checkout\n"))
        self.fake.on(["git", "remote", "get-url", "origin"], Result(0, runs.REMOTES["agents"] + "\n"))
        with patch.object(call_review, "start", return_value="root-1") as start:
            actions = self.tick(log_path=path)
        self.assertEqual(actions, [Action("vet", task="root", run="root", run_kind="cut",
                                          branch="calls/root")])
        self.assertEqual(start.call_args.args[1:3], ("agents", Path("/checkout")))
        self.assertEqual(start.call_args.kwargs, dict(sh=self.fake, log_path=path))
        self.assertEqual(self.fake.argvs()[:5], [["git", "rev-parse", "--show-toplevel"],
                                               ["git", "fetch", "origin"],
                                               ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
                                               ["git", "merge", "--ff-only", "@{upstream}"],
                                               ["git", "remote", "get-url", "origin"]])
        self.assertEqual(self.fake.calls[4].cwd, "/checkout")
        self.assertIn(ssh("fake@gate", ["fab", "queue", "log", "--since", ""]), self.fake.argvs())
        self.assertEqual(len(self.fake.calls), 7)
        self.assertEqual(self.calls, [])

    def test_uncut_directory_need_not_exist_for_tick_or_dry_run(self):
        """Both tick modes locate git from an existing ancestor of an unwritten plan."""
        directory = self.home / "checkout/docs/plan/new"
        self.append(dict(ev="call.started", call="cut", role="cut", subject="new/cut",
                         options=['landing="queue"', 'reviews=true', 'direct=false']))
        fake = FakeRunner().on(["git", "rev-parse", "--show-toplevel"], Result(0, "/checkout\n"))
        fake.on(["git", "remote", "get-url", "origin"], Result(0, runs.REMOTES["agents"]))
        self.assertEqual(dispatch.tick(directory, sh=fake, hosts={}),
                         [Action("flow", task="new", detail="target 1, 0 in flight")])
        with patch.object(dispatch, "run", fake), patch("fab.hosts.load", return_value={}):
            self.assertEqual(dispatch.main([str(directory), "--dry-run"]), 0)
        lookups = [call for call in fake.calls if call.argv == ["git", "rev-parse", "--show-toplevel"]]
        self.assertEqual([call.cwd for call in lookups], [str(self.home)] * 2)
        self.assertEqual([call.cwd for call in fake.calls if call.argv ==
                          ["git", "remote", "get-url", "origin"]], ["/checkout"] * 2)
        self.assertFalse(directory.exists())

    def test_missing_plan_without_its_cut_call_still_imports_unowned_branches(self):
        """A different draft or role does not authorize ticking a missing plan file."""
        (self.directory / "plan.toml").unlink()
        self.append(dict(ev="call.started", call="other", role="cut", subject="other/cut"),
                    dict(ev="call.started", call="wrong", role="skeleton", subject="plan/cut"))
        actions = self.tick()
        self.assertEqual([action.kind for action in actions], ["load"])
        self.assertIn(str(self.directory), actions[0].detail)
        self.assertEqual(self.fake.argvs(), [["git", "rev-parse", "--show-toplevel"],
                         ssh("fake@gate", ["fab", "queue", "log", "--since", ""])])
        self.assertEqual(self.calls, [])

    def test_uncut_question_parks_until_answered(self):
        """A cut asking the user stays idle until its subject is answered."""
        (self.directory / "plan.toml").unlink()
        self.fake.on(["git", "remote", "get-url", "origin"], Result(0, runs.REMOTES["agents"]))
        self.append(dict(ev="call.started", call="cut", role="cut", subject="plan/cut"),
                    dict(ev="call.ended", call="cut", subject="plan/cut", outcome="question"))
        self.assertEqual(self.tick(), [])
        self.append(dict(ev=channel.ANSWERED, subject="plan/cut"))
        self.assertEqual(self.tick(), [])
        self.assertFalse(any(argv[0] == "systemd-run" for argv in self.fake.argvs()))
        self.assertEqual(self.calls, [])

    def test_retired_plan_imports_unowned_branches_without_measurement_or_actions(self):
        """Retirement skips the plan's work while queue signals still reach the page."""
        path = self.directory / "plan.toml"
        write(path, 'retired = true\n' + path.read_text())
        self.queue([dict(ev="rejected", ts="001", branch="hand/pushed", tip="tip",
                         step="default", tests=[], log="/queue/red.log")])
        with patch.object(flow, "measure", side_effect=AssertionError("builder measured")), \
             patch.object(dispatch, "decide", side_effect=AssertionError("actions decided")):
            self.assertEqual(self.tick(), [])
        self.assertEqual([record["ev"] for record in log.read()], ["queue.rejected"])
        self.assertIn("### queue:hand/pushed,", (log.home() / channel.PAGE).read_text())
        self.assertIn("retired draft\n", self.out.getvalue())
        self.assertEqual(self.calls, [])

    def completed_call(self, role="answer", identifier="answer-1", path=None):
        self.append(dict(ev="call.started", call=identifier, role=role, subject="draft",
                         branch=f"calls/{identifier}"),
                    dict(ev="call.ended", call=identifier, role=role, outcome="done"), path=path)
        return log.home() / "calls" / identifier / "report.md"

    def approve(self, root="answer-1", number=1, path=None):
        self.append(dict(ev="run.started", run=f"{root}-{number}", task=root, kind="review", host="builder"),
                    dict(ev="run.ended", run=f"{root}-{number}", outcome="done"), path=path)

    def refuse_call(self, argv, *, step="rebase", path=None):
        """Log fab land's refusal of the requested call branch and return its exit code."""
        log.append("branch.rejected", path=path, task=argv[0], branch=argv[0],
                   tip=f"tip-{self.land.call_count}", step=step, log="refusal.log")
        return 1

    def test_answer_unit_uses_draft_and_no_part_argument(self):
        self.completed_call("answer", "old")
        self.append(dict(ev="call.finished", call="old", outcome="done"))
        self.completed_call("skeleton", "s1")
        self.append(dict(ev="call.finished", call="s1", outcome="done"))
        self.append(event("question.asked", ts="2000-01-01T00:00:00Z", text="Which?"))
        self.assertEqual(self.tick(), [Action("call", task="draft", run_kind="answer")])
        self.assertEqual(self.fake.argvs()[-1],
                         ["systemd-run", "--user", "--collect", "--unit", drafts.unit("answer", "draft"),
                          f"--setenv=FAB_HOME={log.home()}",
                          FAB, "call", "answer", "--plan", str(self.directory), "--tick"])
        self.assertEqual(len([e for e in log.read() if e["ev"] == "call.started"]), 2)

    def test_call_decisions_see_questions_written_by_collect(self):
        self.append(started())
        self.collect.side_effect = lambda *a, **kw: self.append(
            event("question.asked", ts="2000-01-01T00:00:00Z", text="Which?"))
        actions = self.tick()
        self.assertEqual([a.kind for a in actions], ["collect", "call"])
        self.assertEqual(self.fake.argvs()[-1][-6:],
                         [FAB, "call", "answer", "--plan", str(self.directory), "--tick"])

    def test_vet_selects_freest_builder_then_name_even_with_no_free_places(self):
        self.append(event("question.asked", text="Which?"))
        self.completed_call("skeleton", "root")
        self.append(dict(ev="run.started", run="busy-1", task="draft/one", host="z"),
                    dict(ev="run.started", run="busy-2", task="draft/two", host="z"))
        for capacity, expected in ((3, "a"), (4, "a"), (5, "z"), (0, "a")):
            with self.subTest(capacity=capacity):
                hosts = {"z": Host("z", "fake@z", ("builder",), places=capacity),
                         "a": Host("a", "fake@a", ("builder",), places=min(2, capacity)),
                         "gate": Host("gate", "fake@gate", ("gate",), places=100)}
                path = log.default_path()
                with patch.object(call_review, "start") as vet:
                    actions = self.tick(hosts=hosts, log_path=path)
                self.assertEqual(actions[-1], Action("vet", task="root", run="root",
                                                     run_kind="skeleton", branch="calls/root"))
                vet.assert_called_once_with(call_review.chains(log.read())["root"], "agents",
                                             self.directory.resolve(), hosts[expected], log.read(),
                                             sh=self.fake, log_path=path)
                self.land.assert_not_called()

    def test_vet_uses_checkout_root_and_current_events_after_collect(self):
        self.append(started())
        self.fake = FakeRunner().on(["git", "rev-parse", "--show-toplevel"], Result(0, "/fake/repo\n"))

        def collect(*args, **kwargs):
            self.append(ended(outcome="question"), event("question.asked", text="Which?"))
            self.completed_call("skeleton", "root")

        self.collect.side_effect = collect
        with patch.object(call_review, "start") as vet:
            actions = self.tick()
        self.assertEqual([action.kind for action in actions], ["collect", "vet"])
        self.assertEqual(str(vet.call_args.args[2]), "/fake/repo")
        self.assertEqual(vet.call_args.args[4], log.read())
        self.land.assert_not_called()

    def test_vet_without_builder_fails_without_landing(self):
        """The shared builder selector refuses a review when no builder exists."""
        self.append(event("question.asked", text="Which?"))
        self.completed_call("skeleton", "root")
        with patch.object(call_review, "start") as vet:
            self.tick(hosts={})
        vet.assert_not_called()
        self.land.assert_not_called()
        self.assertEqual(log.read()[-1]["text"], "vet root failed: no builder configured")
        self.assertNotIn("call.finished", [entry["ev"] for entry in log.read()])

    def test_collect_question_starts_foreman_on_freest_builder_even_at_zero(self):
        for capacity, expected in ((3, "a"), (4, "a"), (5, "z"), (0, "a")):
            with self.subTest(capacity=capacity):
                path = self.home / f"questions-{capacity}.jsonl"
                self.append(dict(started(), kind="implement"),
                            dict(ev="run.started", run="busy-1", task="draft/one", host="z"),
                            dict(ev="run.started", run="busy-2", task="draft/two", host="z"), path=path)
                hosts = {"z": Host("z", "fake@z", ("builder",), places=capacity),
                         "a": Host("a", "fake@a", ("builder",), places=min(2, capacity)),
                         "gate": Host("gate", "fake@gate", ("gate",), places=100)}

                def collect(run_id, *args, **kwargs):
                    if run_id == "draft/a-1":
                        self.append(ended(outcome="question"), event("question.asked", text="Which?"),
                                    path=kwargs["log_path"])

                self.collect.side_effect = collect
                with patch.object(foreman, "start") as start:
                    actions = self.tick(hosts=hosts, log_path=path)
                self.assertEqual([action.kind for action in actions], ["collect"] * 3 + ["foreman"])
                _, tasks = plan.load(self.directory)
                start.assert_called_once_with(foreman.questions(tasks, log.read(path))[0],
                                               tasks["draft/a"], hosts[expected], log.read(path),
                                               sh=self.fake, log_path=path, trunk="main")
                self.assertIn(f"foreman draft/a draft/a-1 {expected}\n", self.out.getvalue())
                self.assertEqual(log.read(), [])

    def settled_question(self, *, path=None):
        """Provide a collected foreman answer and a fake checkout for settlement tests."""
        self.append(*question_history(status="settled"), path=path)
        write(log.home() / "runs/draft/a/foreman-1/report.md", "Done: Use option A\nDetails.\n")
        self.fake = FakeRunner().on(["git", "rev-parse", "--show-toplevel"],
                                    Result(0, str(self.home) + "\n"))

    def test_settle_lands_then_answers_and_next_tick_restarts_task(self):
        path = self.home / "settled.jsonl"
        self.settled_question(path=path)
        _, tasks = plan.load(self.directory)
        question = foreman.questions(tasks, log.read(path))[0]
        branch = "answers/draft/a/foreman-1"

        def land_answer(argv):
            self.assertFalse(any(entry["ev"] == "question.answered" for entry in log.read(path)))
            return self.record_land(argv)

        self.land.side_effect = land_answer
        with patch.object(foreman, "commit", return_value=branch) as commit, \
             patch.object(log, "now", return_value="2026-10-31T23:59:00.000Z"):
            actions = self.tick(log_path=path)
        self.assertEqual(actions, [Action("settle", task="draft/a", run="draft/a/foreman-1",
                                          detail="draft/a/foreman-1")])
        commit.assert_called_once_with(question, tasks["draft/a"], "Use option A\nDetails.", self.home,
                                       run_id="draft/a/foreman-1", day="2026-10-31", sh=self.fake, trunk="main")
        self.land.assert_called_once_with([branch])
        answered = log.read(path)[-1]
        self.assertEqual(answered, dict(ts="2026-10-31T23:59:00.000Z", ev="question.answered",
                                        task="draft/a", by="draft/a/foreman-1", run="draft/a-1",
                                        answer="Use option A"))
        self.assertEqual([action.kind for action in self.tick(log_path=path)], ["start"])
        self.start.assert_called_once()
        self.assertEqual(log.read(), [])

    def test_agents_spec_answers_land_even_when_task_builds_in_fabrig(self):
        self.add_task("a", repo="fabrig")
        self.settled_question()
        with patch.object(foreman, "commit", return_value="answers/foreman"):
            self.tick()
        self.land.assert_called_once_with(["answers/foreman"])
        self.assertEqual(log.read()[-1]["ev"], "question.answered")
        self.assertFalse(any(event["ev"] == "branch.ready" for event in log.read()))

    def test_an_integration_accept_answers_with_accept_only_when_the_branch_is_pushed(self):
        self.settled_question()
        write(log.home() / "runs/draft/a/foreman-1/report.md", "Accept: the lint is temper-fake's\nPushed abc.\n")
        loaded, tasks = plan.load(self.directory)
        events = log.read()
        action = Action("settle", task="draft/a", run="draft/a/foreman-1", detail="draft/a/foreman-1")
        for landing, pushed, accepted in (("integration", "abc\trefs/heads/draft/a\n", True),
                                          ("integration", "", False), ("queue", "abc\trefs/heads/draft/a\n", False)):
            with self.subTest(landing=landing, pushed=bool(pushed)):
                path = self.home / f"settle-{landing}-{bool(pushed)}.jsonl"
                self.append(*events, path=path)
                fake = FakeRunner().on(["git", "rev-parse", "--show-toplevel"], Result(0, str(self.home) + "\n")) \
                    .on(["git", "ls-remote", "origin", "refs/heads/draft/a"], Result(0, pushed))
                with patch.object(foreman, "commit", return_value=None):
                    dispatch._settle(action, tasks, self.directory, plan=replace(loaded, landing=landing),
                                     sh=fake, log_path=path)
                answered = log.read(path)[-1]
                self.assertEqual((answered["ev"], answered["answer"]), ("question.answered", "the lint is temper-fake's"))
                self.assertEqual(answered.get("accept", False), accepted)

    def test_settle_already_recorded_answer_skips_landing(self):
        self.settled_question()
        with patch.object(foreman, "commit", return_value=None) as commit:
            self.assertEqual([action.kind for action in self.tick()], ["settle"])
        commit.assert_called_once()
        self.land.assert_not_called()
        self.assertEqual(log.read()[-1]["ev"], "question.answered")

    def test_settle_refused_landing_retries_without_answering(self):
        self.settled_question()
        attempts = []

        def land_answer(argv):
            attempts.append(argv)
            if len(attempts) == 1:
                print("gate refused\ntry again")
                return 1
            return 0

        self.land.side_effect = land_answer
        with patch.object(foreman, "commit", return_value="answers/foreman") as commit:
            self.assertEqual([action.kind for action in self.tick()], ["settle"])
            self.assertEqual(log.read()[-1]["text"], "settle draft/a failed: gate refused try again")
            self.assertFalse(any(entry["ev"] == "question.answered" for entry in log.read()))
            _, tasks = plan.load(self.directory)
            self.assertEqual(foreman.questions(tasks, log.read())[0].state, "settled")
            self.assertEqual([action.kind for action in self.tick()], ["settle"])
        self.assertEqual(commit.call_count, 2)
        self.assertEqual(attempts, [["answers/foreman"], ["answers/foreman"]])
        self.assertEqual(log.read()[-1]["ev"], "question.answered")

    def test_settle_failure_never_answers_or_lands(self):
        for reason in ("commit", "report", "checkout", "empty root"):
            with self.subTest(reason=reason):
                path = self.home / f"{reason}.jsonl"
                self.settled_question(path=path)
                if reason == "report":
                    write(log.home() / "runs/draft/a/foreman-1/report.md", "Failed: no option\n")
                elif reason in ("checkout", "empty root"):
                    self.fake = FakeRunner().on(["git", "rev-parse"], Result(128 if reason == "checkout" else 0))
                with patch.object(foreman, "commit", side_effect=RuntimeError("cannot commit")) as commit:
                    self.assertEqual([action.kind for action in self.tick(log_path=path)], ["settle"])
                self.assertEqual(commit.call_count, int(reason == "commit"))
                self.assertEqual(log.read(path)[-1]["ev"], "note")
                self.assertFalse(any(entry["ev"] == "question.answered" for entry in log.read(path)))
        self.land.assert_not_called()

    def test_foreman_without_builder_is_noted_without_starting(self):
        self.append(*question_history())
        with patch.object(foreman, "start") as start:
            self.assertEqual([action.kind for action in self.tick(hosts={})], ["foreman"])
        start.assert_not_called()
        self.assertEqual(log.read()[-1]["text"], "foreman draft/a failed: no builder configured")

    def test_collected_infra_foreman_queues_for_answerer_without_retry(self):
        now = "2026-10-31T12:00:00.000Z"
        self.append(*question_history(status="deciding"))
        for name in ("b", "c", "d"):
            self.add_task(name)
            self.append(*question_history(name, "parked", since=now))

        def collect(run_id, *args, **kwargs):
            self.append(dict(ev="run.ended", run=run_id, task="draft/a/foreman", outcome="infra",
                             report="collected/foreman/report.md"))

        self.collect.side_effect = collect
        with patch.object(foreman, "start") as start, patch.object(log, "now", return_value=now):
            self.assertEqual([action.kind for action in self.tick()], ["collect", "call"])
        start.assert_not_called()
        self.assertEqual(self.fake.argvs()[-1][-6:], [FAB, "call", "answer", "--plan", str(self.directory), "--tick"])

    def test_foreman_actions_recompute_questions_before_acting(self):
        for status in ("foreman", "settled"):
            with self.subTest(status=status):
                path = self.home / f"stale-{status}.jsonl"
                self.append(*question_history(status=status), path=path)
                decide_questions = dispatch.foreman_actions

                def answered(tasks, events):
                    actions = decide_questions(tasks, events)
                    self.append(event("question.answered"), path=path)
                    return actions

                with patch.object(dispatch, "foreman_actions", side_effect=answered), \
                     patch.object(foreman, "start") as start, patch.object(foreman, "commit") as commit:
                    self.tick(log_path=path)
                start.assert_not_called()
                commit.assert_not_called()
                self.assertIn(f"no {status} question for draft/a", log.read(path)[-1]["text"])
        self.land.assert_not_called()

    def test_foreman_actions_precede_call_decisions_and_calls_see_settlement(self):
        self.settled_question()
        self.append(*question_history("b"))
        self.add_task("b")
        self.completed_call("skeleton", "root")
        order = []

        def start(*args, **kwargs):
            order.append("foreman")
            self.append(dict(ev="run.started", task="draft/b/foreman", run="draft/b/foreman-1",
                             kind="foreman", asked="draft/b-1", host="builder"))

        def commit(*args, **kwargs):
            order.append("settle")
            return None

        def vet(*args, **kwargs):
            order.append("vet")
            self.assertIn("question.answered", [entry["ev"] for entry in args[4]])
            self.assertIn("draft/b/foreman-1", [entry.get("run") for entry in args[4]])

        with patch.object(foreman, "start", side_effect=start), \
             patch.object(foreman, "commit", side_effect=commit), \
             patch.object(call_review, "start", side_effect=vet), \
             patch.object(dispatch, "call_actions", wraps=dispatch.call_actions) as calls:
            self.assertEqual([action.kind for action in self.tick()], ["settle", "foreman", "vet"])
        self.assertEqual(order, ["settle", "foreman", "vet"])
        self.assertIn("question.answered", [entry["ev"] for entry in calls.call_args.args[2]])
        self.assertIn("draft/b/foreman-1", [entry.get("run") for entry in calls.call_args.args[2]])

    def test_done_calls_of_every_role_wait_for_review(self):
        """Every reviewed role, including the designer's calls, waits for acceptance."""
        self.append(event("question.asked", text="Which?"))
        for role in call_review.REVIEWED:
            self.completed_call(role, role)
        with patch.object(call_review, "start") as vet:
            actions = self.tick()
        self.assertEqual([action.kind for action in actions], ["vet"] * len(call_review.REVIEWED))
        self.assertEqual([action.run_kind for action in actions], list(call_review.REVIEWED))
        self.assertEqual(vet.call_count, len(call_review.REVIEWED))
        self.land.assert_not_called()

    def test_hold_launches_settle_once_and_land_delivers_the_chain(self):
        path = self.home / "custom.jsonl"
        self.append(event("question.asked", text="Which?"), *chain_history("hold"), path=path)
        self.assertEqual(self.tick(log_path=path), [Action("call", task="root", run_kind="settle")])
        self.assertIn(["systemd-run", "--user", "--collect", "--unit", drafts.unit("settle", "root/settle"),
                       f"--setenv=FAB_HOME={log.home()}",
                       FAB, "call", "settle", "root", "--plan", str(self.directory), "--tick"], self.fake.argvs())
        self.append(dict(ev="call.started", call="settle-1", role="settle", subject="draft/core/settle",
                         settles="root"), path=path)
        self.assertEqual(self.tick(log_path=path), [])
        write(log.home() / "calls/settle-1/report.md", "Done: land\n\nGood enough. Scanner refinements are later work.\n")
        self.append(dict(ev="call.ended", call="settle-1", outcome="done"), path=path)
        self.assertEqual(self.tick(log_path=path), [Action("judge-chain", task="root", run="settle-1")])
        self.assertEqual(call_review.chains(log.read(path))["root"].state, "approved")
        self.assertEqual(self.tick(log_path=path), [Action("finish", task="root", run="root-amend",
                                                        run_kind="skeleton", branch="calls/root")])
        self.land.assert_called_once_with(["calls/root"])
        self.assertFalse(any(record["ev"] == "call.parked" for record in log.read(path)))
        self.assertEqual(self.tick(log_path=path), [])
        self.assertEqual(log.read(), [])

    def test_each_hold_reason_starts_one_settle_including_old_parks(self):
        histories = [chain_history("hold"),
                     chain_history("amend") + [dict(ev="call.started", call="amend", role="amend", amends="root"),
                                               dict(ev="call.ended", call="amend", outcome="failed")],
                     chain_history("review") + [entry for number in range(call_review.INFRA_LIMIT)
                         for entry in [dict(ev="run.started", run=f"infra-{number}", task="root", kind="review"),
                                       dict(ev="run.ended", run=f"infra-{number}", outcome="infra")]]]
        for number, history in enumerate(histories):
            for old in (False, True):
                with self.subTest(reason=number, old=old):
                    path = self.home / f"hold-{number}-{old}.jsonl"
                    self.append(event("question.asked", text="Which?"), *history, path=path)
                    if old:
                        reason = call_review.chains(log.read(path))["root"].reason
                        self.append(dict(ev="call.parked", call="root", subject="draft/core", reason=reason), path=path)
                        self.assertEqual(len(channel.asks((), log.read(path))), 1)
                    self.assertEqual(self.tick(log_path=path), [Action("call", task="root", run_kind="settle")])
                    self.append(dict(ev="call.started", call="settle", role="settle", subject="draft/core/settle",
                                     settles="root"), path=path)
                    self.assertEqual(self.tick(log_path=path), [])
                    self.land.assert_not_called()

    def test_settle_user_and_failures_park_once(self):
        cases = [("done", "Done: user\nChoose whether to buy the machine.\n", "user: Choose whether to buy the machine."),
                 ("failed", "Done: land\nLooks good.\n", "settle failed"),
                 ("done", "Done: unknown\nAdvice.\n", "settle failed"),
                 ("done", "Done: land\n", "settle failed"),
                 ("question", "Question: what now?\n", "settle failed"),
                 ("done", "Done: user\nOne reason.\nAnother.\n", "settle failed"),
                 ("done", None, "settle failed")]
        for number, (outcome, text, reason) in enumerate(cases):
            with self.subTest(number=number):
                path = self.home / f"verdict-{number}.jsonl"
                self.append(event("question.asked", text="Which?"), *chain_history("hold"),
                            dict(ev="call.started", call="settle-1", role="settle", subject="draft/core/settle", settles="root"),
                            dict(ev="call.ended", call="settle-1", role="settle", subject="draft/core/settle", outcome=outcome), path=path)
                report_path = log.home() / "calls/settle-1/report.md"
                if text is None:
                    report_path.unlink(missing_ok=True)
                else:
                    write(report_path, text)
                self.assertEqual(self.tick(log_path=path), [Action("judge-chain", task="root", run="settle-1")])
                parked = log.read(path)[-1]
                self.assertEqual((parked["ev"], parked["reason"], parked["report"]),
                                 ("call.parked", reason, str(report_path)))
                self.assertEqual([(ask.kind, ask.subject) for ask in channel.asks((), log.read(path))],
                                 [("parked", "draft/core")])
                self.assertEqual(self.tick(log_path=path), [])
                self.assertEqual(sum(record["ev"] == "chain.settled" for record in log.read(path)),
                                 int(reason.startswith("user: ")))

    def test_settle_amend_resets_then_second_hold_cannot_amend(self):
        self.append(event("question.asked", text="Which?"), *chain_history("hold"),
                    dict(ev="call.started", call="settle-1", role="settle", subject="draft/core/settle", settles="root"),
                    dict(ev="call.ended", call="settle-1", outcome="done"))
        write(log.home() / "calls/settle-1/report.md", "Done: amend\nSupport extern blocks.\n")
        self.tick()
        self.assertEqual(call_review.chains(log.read())["root"].state, "review")
        with patch.object(call_review, "start") as vet:
            self.assertEqual(self.tick()[0].kind, "vet")
        vet.assert_called_once()
        self.append(dict(ev="run.started", run="root-3", task="root", kind="review"),
                    dict(ev="run.ended", run="root-3", outcome="failed"))
        self.assertEqual(self.tick(), [Action("call", task="root", run_kind="amend")])
        self.append(dict(ev="call.started", call="amend-2", role="amend", amends="root"),
                    dict(ev="call.ended", call="amend-2", outcome="failed"))
        self.assertEqual(self.tick(), [Action("call", task="root", run_kind="settle")])
        self.append(dict(ev="call.started", call="settle-2", role="settle", subject="draft/core/settle", settles="root"),
                    dict(ev="call.ended", call="settle-2", outcome="done"))
        write(log.home() / "calls/settle-2/report.md", "Done: amend\nTry again.\n")
        self.tick()
        self.assertEqual(log.read()[-1]["reason"], "settle failed")
        self.assertEqual(self.tick(), [])

    def test_land_hold_settle_verdicts_on_both_attempts(self):
        for attempt in (1, 2):
            for verdict in ("land", "amend", "user"):
                with self.subTest(attempt=attempt, verdict=verdict):
                    path = self.home / f"land-hold-{attempt}-{verdict}.jsonl"
                    self.append(*chain_history("hold"), path=path)
                    if attempt == 2:
                        self.append(call_started("settle-1", "settle", "draft/core/settle", settles="root"),
                                    call_ended("settle-1"),
                                    dict(ev="chain.settled", call="root", subject="draft/core", settle="settle-1",
                                         verdict="amend", text="Resolve the conflicts."),
                                    dict(ev="branch.rejected", task="root", branch="calls/root", tip="reset-tip",
                                         step="rebase", log="first.log"),
                                    call_started("amend-2", "amend", "draft/core", amends="root"),
                                    call_ended("amend-2"), path=path)
                    self.append(dict(ev="branch.rejected", task="root", branch="calls/root", tip="refused-tip",
                                     step="rebase", log="last.log"), path=path)
                    chain = call_review.chains(log.read(path))["root"]
                    self.assertEqual((chain.state, chain.reason), ("hold", call_review.LAND_HOLD))
                    settle = f"settle-{attempt}"
                    self.append(call_started(settle, "settle", "draft/core/settle", settles="root"),
                                call_ended(settle), path=path)
                    write(log.home() / "calls" / settle / "report.md", f"Done: {verdict}\nResolve the conflicts.\n")
                    count = len(log.read(path))
                    action = Action("judge-chain", task="root", run=settle)
                    dispatch._judge_chain(action, log_path=path)
                    gained = log.read(path)[count:]
                    valid = verdict == "user" or (verdict == "amend" and attempt == 1)
                    self.assertEqual([entry["ev"] for entry in gained],
                                     ["chain.settled", "call.parked"] if verdict == "user" else
                                     ["chain.settled"] if valid else ["call.parked"])
                    if valid:
                        self.assertEqual((gained[0]["settle"], gained[0]["verdict"]), (settle, verdict))
                    if verdict == "user" or not valid:
                        self.assertEqual(gained[-1]["reason"],
                                         "user: Resolve the conflicts." if valid else "settle failed")
                    dispatch._judge_chain(action, log_path=path)
                    self.assertEqual(log.read(path)[count:], gained)
        self.assertEqual(log.read(), [])

    def test_amend_unit_passes_root_and_uses_root_key(self):
        self.append(event("question.asked", text="Which?"), *chain_history("amend"),
                    dict(ev="call.started", call="old-amend", role="amend", amends="other"),
                    dict(ev="call.ended", call="old-amend", outcome="failed"))
        self.assertEqual(self.tick(), [Action("call", task="root", run_kind="amend")])
        self.assertIn(["systemd-run", "--user", "--collect", "--unit", drafts.unit("amend", "root"),
                       f"--setenv=FAB_HOME={log.home()}",
                       FAB, "call", "amend", "root", "--plan", str(self.directory), "--tick"], self.fake.argvs())
        self.land.assert_not_called()

    def test_finish_answer_uses_latest_call_line_then_root_fallback(self):
        for text in ("Answered: draft/a draft/a\n", "No answer line\n", None):
            with self.subTest(text=text):
                self.append(event("question.asked", text="Which?"))
                root = "root-" + str(self.land.call_count)
                write(self.completed_call(identifier=root), "Done: answered\nAnswered: draft/a\n")
                self.append(dict(ev="run.started", run=f"{root}-1", task=root, kind="review", host="builder"),
                            dict(ev="run.ended", run=f"{root}-1", outcome="failed"),
                            dict(ev="call.started", call=f"{root}-amend", role="amend", amends=root,
                                 subject="draft", branch=f"calls/{root}"),
                            dict(ev="call.ended", call=f"{root}-amend", outcome="done"))
                # A different root answer proves an amend line takes precedence.
                if text and text.startswith("Answered:"):
                    write(log.home() / "calls" / root / "report.md", "Answered: draft/wrong\n")
                if text is not None:
                    write(log.home() / "calls" / f"{root}-amend" / "report.md", "Done: amended\n" + text)
                self.approve(root, number=2)
                self.assertEqual(self.tick(hosts={}), [Action("finish", task=root, run=f"{root}-amend",
                                                             run_kind="answer", branch=f"calls/{root}")])
                answered = [entry for entry in log.read() if entry["ev"] == "question.answered"
                            and entry["call"] == f"{root}-amend"]
                self.assertEqual([entry["task"] for entry in answered], ["draft/a"])
                self.assertEqual(log.read()[-1]["call"], f"{root}-amend")
                self.land.assert_called_with([f"calls/{root}"])

    def test_finish_answer_logs_the_stop_answer_from_the_report(self):
        path = self.home / "stop-answer.jsonl"
        self.append(dict(ev="plan.stopped", task="draft/integration", why="red"),
                    dict(ev="question.asked", task="draft/integration", park=True, text="Three reds."),
                    call_started("answer-stop", "answer", "draft"), call_ended("answer-stop"), path=path)
        write(log.home() / "calls/answer-stop/report.md",
              "Done: judged\nAnswered: draft/integration\n"
              "Answer draft/integration: Repair the shared fixture first.\n")
        dispatch._finish(Action("finish", task="answer-stop"), log_path=path)
        answered, = [entry for entry in log.read(path) if entry["ev"] == "question.answered"]
        self.assertEqual({key: value for key, value in answered.items() if key != "ts"},
                         dict(ev="question.answered", task="draft/integration", call="answer-stop",
                              answer="Repair the shared fixture first."))
        self.assertEqual(log.read(), [])

    def test_finish_lands_then_parses_answered_line_and_logs_once(self):
        self.add_task("b")
        self.append(event("question.asked", text="Which?"), event("question.asked", "b", text="Why?"))
        report = self.completed_call()
        self.approve()
        write(report, "Done: answered\nOther: draft/ignored\nAnswered: draft/a  b draft/a\nDetails.\n")

        def landing(argv):
            self.assertEqual(argv, ["calls/answer-1"])
            self.assertNotIn("question.answered", [e["ev"] for e in log.read()])
            print("Landed")
            return 0

        self.land.side_effect = landing
        actions = self.tick(hosts={})
        self.assertEqual(actions, [Action("finish", task="answer-1", run="answer-1", run_kind="answer", branch="calls/answer-1")])
        answered = [e for e in log.read() if e["ev"] == "question.answered"]
        self.assertEqual([(e["task"], e["call"]) for e in answered],
                         [("draft/a", "answer-1"), ("draft/b", "answer-1")])
        self.assertEqual({k: v for k, v in log.read()[-1].items() if k != "ts"},
                         dict(ev="call.finished", call="answer-1", role="answer", outcome="done"))
        self.assertEqual(self.tick(hosts={}), [])
        self.land.assert_called_once()
        self.assertEqual(self.out.getvalue().splitlines(),
                         ["flow draft target 1, 0 in flight", "finish answer-1 ",
                          f"page - {log.home() / channel.PAGE}",
                          "again - tick 1: question.answered, call.finished",
                          "wake - tick 1: question.answered, call.finished",
                          "flow draft target 1, 0 in flight", f"page - {log.home() / channel.PAGE}"])

    def test_finish_skeleton_needs_no_report_and_respects_explicit_log(self):
        path = self.home / "custom.jsonl"
        self.completed_call("skeleton", "s1", path=path)
        self.approve("s1", path=path)
        self.tick(hosts={}, log_path=path)
        self.land.assert_called_once_with(["calls/s1"])
        self.assertEqual(log.read(), [])
        self.assertEqual(log.read(path)[-1]["outcome"], "done")
        self.assertEqual(log.read(path)[-1]["ev"], "call.finished")

    def test_failed_finish_is_noted_and_finished_without_answering(self):
        for failure in (1, OSError("offline\nretry later")):
            with self.subTest(failure=failure):
                identifier = f"answer-{self.land.call_count}"
                write(self.completed_call(identifier=identifier), "Done: answered\nAnswered: draft/a\n")
                self.approve(identifier)
                if isinstance(failure, Exception):
                    self.land.side_effect = failure
                else:
                    self.land.side_effect = lambda argv: print("conflict") or 1
                self.tick(hosts={})
                note, finished = log.read()[-2:]
                self.assertEqual(note["ev"], "note")
                self.assertIn(f"finish {identifier} failed:", note["text"])
                self.assertEqual((finished["ev"], finished["call"], finished["role"], finished["outcome"]),
                                 ("call.finished", identifier, "answer", "failed"))
                count = self.land.call_count
                self.tick(hosts={})
                self.assertEqual(self.land.call_count, count)
                self.assertNotIn("question.answered", [e["ev"] for e in log.read()])

    def test_finish_rebase_refusal_amends_then_lands_or_holds(self):
        for refused_again in (False, True):
            with self.subTest(refused_again=refused_again):
                path = self.home / f"rebase-{refused_again}.jsonl"
                write(self.completed_call(identifier="root", path=path), "Done: answered\nAnswered: draft/a\n")
                self.approve("root", path=path)
                self.land.side_effect = lambda argv: self.refuse_call(argv, path=path)
                finish = Action("finish", task="root", run="root", run_kind="answer", branch="calls/root")
                self.assertEqual(self.tick(hosts={}, log_path=path), [finish])
                self.assertFalse(any(entry["ev"] in ("call.finished", "question.answered") for entry in log.read(path)))
                self.assertEqual(self.tick(hosts={}, log_path=path), [Action("call", task="root", run_kind="amend")])
                self.append(call_started("amend-1", "amend", "draft", amends="root", branch="calls/root"),
                            call_ended("amend-1"), path=path)
                self.approve("root", number=2, path=path)
                if not refused_again:
                    self.land.side_effect = self.record_land
                self.assertEqual(self.tick(hosts={}, log_path=path), [replace(finish, run="amend-1")])
                records = log.read(path)
                if refused_again:
                    self.assertFalse(any(entry["ev"] in ("call.finished", "question.answered") for entry in records))
                    chain = call_review.chains(records)["root"]
                    self.assertEqual((chain.state, chain.reason), ("hold", call_review.LAND_HOLD))
                    self.assertEqual(self.tick(hosts={}, log_path=path), [Action("call", task="root", run_kind="settle")])
                else:
                    self.assertEqual((records[-1]["ev"], records[-1]["call"], records[-1]["outcome"]),
                                     ("call.finished", "amend-1", "done"))
                    self.assertEqual((records[-2]["ev"], records[-2]["task"]), ("question.answered", "draft/a"))
                    self.assertEqual(self.tick(hosts={}, log_path=path), [])
        self.assertEqual(log.read(), [])

    def test_finish_land_refusal_steps_and_terminal_exceptions(self):
        cases = [(step, 0, False, None) for step in ("fetch", "paths", "test", "push")]
        cases += [("fetch", 2, False, "failed"), ("fetch", 128, False, None),
                  ("fetch", 1, False, None), ("fetch", 2, True, "done"), ("rebase", 0, True, "done")]
        for number, (step, remote_code, landed, outcome) in enumerate(cases):
            with self.subTest(step=step, remote_code=remote_code, landed=landed):
                path = self.home / f"step-{number}.jsonl"
                root = f"root-{number}"
                branch = f"calls/{root}"
                write(self.completed_call(identifier=root, path=path), "Done: answered\nAnswered: draft/a\n")
                self.approve(root, path=path)
                self.append(dict(ev="call.checked", call=root, tip="checked-tip"), path=path)
                if landed:
                    self.append(dict(ev="branch.landed", task=root, branch=branch, tip="landed-tip"), path=path)
                query = ["git", "ls-remote", "--exit-code", "origin", f"refs/heads/{branch}"]
                self.fake.on(query, Result(remote_code, "tip\t" + branch if remote_code == 0 else ""))
                self.land.side_effect = lambda argv: self.refuse_call(argv, step=step, path=path)
                action = Action("finish", task=root, run=root, run_kind="answer", branch=branch)
                dispatch._take(action, {}, {}, self.directory, plan=make_plan(part("core")),
                               checkout=self.home, sh=self.fake, log_path=path)
                records = log.read(path)
                finished = [entry for entry in records if entry["ev"] == "call.finished"]
                self.assertEqual([entry["outcome"] for entry in finished], [] if outcome is None else [outcome])
                if finished:
                    self.assertEqual((finished[0]["call"], finished[0]["tip"]), (root, "checked-tip"))
                self.assertEqual([entry["task"] for entry in records if entry["ev"] == "question.answered"],
                                 ["draft/a"] if outcome == "done" else [])
                notes = [entry["text"] for entry in records if entry["ev"] == "note"]
                self.assertEqual(notes, [f"finish {root} failed: landing refused"])
                queries = [call for call in self.fake.calls if call.argv == query]
                self.assertEqual([call.cwd for call in queries],
                                 [str(self.home)] if step == "fetch" and not landed else [])
        self.assertEqual(log.read(), [])

    def test_finish_refusal_matches_only_new_unqueued_records_on_its_branch(self):
        for case in ("old", "other", "queue", "mixed"):
            with self.subTest(case=case):
                path = self.home / f"filter-{case}.jsonl"
                self.completed_call(identifier="root", path=path)
                refusal = dict(ev="branch.rejected", task="root", branch="calls/root", tip="tip",
                               step="rebase", log="refusal.log")
                if case == "old":
                    self.append(refusal, path=path)
                queued = dict(refusal, queue_ts="queue-stamp")
                other = dict(refusal, branch="calls/other")
                during = {"old": [], "other": [other], "queue": [queued],
                          "mixed": [refusal, queued, other]}[case]

                def landing(argv):
                    self.append(*during, path=path)
                    return 1

                self.land.side_effect = landing
                dispatch._take(Action("finish", task="root", run="root", run_kind="answer", branch="calls/root"),
                               {}, {}, self.directory, plan=make_plan(part("core")), checkout=self.home,
                               sh=self.fake, log_path=path)
                self.assertEqual([entry["outcome"] for entry in log.read(path) if entry["ev"] == "call.finished"],
                                 [] if case == "mixed" else ["failed"])
        self.assertEqual(log.read(), [])

    def test_failed_call_launch_is_noted_and_other_role_still_starts(self):
        self.append(event("question.asked", ts="2000-01-01T00:00:00Z", text="Which?"))
        self.fake.on(["systemd-run", "--user", "--collect", "--unit", drafts.unit("answer", "draft")],
                     Result(1, err="no unit"))
        design = Action("design", detail="core, next")
        with patch("fab.dispatch.decide", return_value=[design]):
            self.tick()
        self.assertEqual([argv[4] for argv in self.fake.argvs() if argv[0] == "systemd-run"],
                         [drafts.unit("answer", "draft"), drafts.unit("skeleton", "draft/core")])
        self.assertIn("call draft failed:", log.read()[-1]["text"])

    def test_action_failure_logs_note_and_next_action_runs(self):
        self.add_task("b")
        self.append(started(), ended(), started("b"), ended("b"))
        self.land.side_effect = [OSError("offline\nretry later"), 0]
        actions = self.tick()
        self.assertEqual([a.kind for a in actions], ["land", "land"])
        self.assertEqual(self.land.call_count, 2)
        note = log.read()[-1]
        self.assertEqual(note["ev"], "note")
        self.assertEqual(note["text"], "land draft/a failed: offline retry later")
        self.assertEqual(self.out.getvalue().splitlines(),
                         ["flow draft target 2, 0 in flight",
                          "land draft/a failed: offline retry later", "land draft/b draft/b",
                          f"page - {log.home() / channel.PAGE}"])

    def test_gate_findings_reject_without_landing_and_print_unique_gates(self):
        self.append(started(), ended())
        self.screen.return_value = [gates.Finding("names", "banned word"),
                                    gates.Finding("names", "another banned word"),
                                    gates.Finding("docs", "no docstring")]
        self.tick()
        self.land.assert_not_called()
        self.assertEqual(self.out.getvalue(), "flow draft target 2, 0 in flight\nland draft/a rejected gate:names,docs\n"
                         + f"page - {log.home() / channel.PAGE}\n")
        self.assertFalse(any(entry["ev"] == "note" for entry in log.read()))

    def test_clean_screen_precedes_landing_with_current_events_and_runner(self):
        path = self.home / "events.jsonl"
        self.append(started(branch="draft/a-r1"), ended(), path=path)
        history = log.read(path)

        def landing(argv):
            self.screen.assert_called_once_with(
                plan.load_tasks(self.directory / "tasks", "draft", "agents")["draft/a"],
                history, sh=self.fake, log_path=path)
            self.assertEqual(argv, ["draft/a-r1", "--task", "draft/a"])
            return 0

        self.land.side_effect = landing
        self.tick(log_path=path)
        self.land.assert_called_once()
        self.assertEqual(self.out.getvalue(), "flow draft target 2, 0 in flight\nland draft/a draft/a-r1\n"
                         + f"page - {log.home() / channel.PAGE}\n")
        self.assertEqual(log.read(path), history)

    def test_failed_screen_never_lands_and_next_action_runs(self):
        self.add_task("b")
        self.append(started(), ended())
        self.screen.side_effect = RuntimeError("screen unavailable")
        self.tick()
        self.land.assert_not_called()
        self.assertEqual(log.read()[-1]["text"], "land draft/a failed: screen unavailable")
        self.assertIn("land draft/a failed: screen unavailable\n", self.out.getvalue())
        self.start.assert_called_once()

    def test_fabrig_ready_uses_rust_gates(self):
        self.add_task("a", repo="fabrig")
        self.append(started(), ended())
        self.fake.on(["git", "rev-parse", "--verify"], Result(0, "tip\n"))
        self.tick()
        self.screen.assert_not_called()
        self.rust_screen.assert_called_once()
        self.assertEqual(log.read()[-1]["ev"], "branch.ready")

    def test_land_output_is_captured_to_keep_one_line_per_action(self):
        self.append(started(), ended())

        def landing(argv):
            print("draft/a: landed: Landed; branch deleted")
            return 0

        self.land.side_effect = landing
        self.tick()
        self.assertEqual(self.out.getvalue(), "flow draft target 2, 0 in flight\nland draft/a draft/a\n"
                         + f"page - {log.home() / channel.PAGE}\n")

    def test_failed_land_output_is_printed_and_noted_on_one_line(self):
        self.append(started(), ended())

        def landing(argv):
            print("draft/a: rebase: conflict\nfile.py")
            return 1

        self.land.side_effect = landing
        self.tick()
        self.assertEqual(self.out.getvalue(), "flow draft target 2, 0 in flight\nland draft/a failed: draft/a: rebase: conflict file.py\n"
                         + f"page - {log.home() / channel.PAGE}\n")
        self.assertEqual(log.read()[-1]["text"], self.out.getvalue().splitlines()[-2])

    def test_run_failures_do_not_stop_following_actions(self):
        self.add_task("b")
        self.add_task("c")
        self.append(*growth(), started())
        self.collect.side_effect = RuntimeError("lost builder")
        self.start.side_effect = [RuntimeError("cannot start"), "draft/c-1"]
        # Capacity is reserved from the snapshot even when a start fails.
        self.hosts["builder"] = replace(self.hosts["builder"], places=3)
        actions = self.tick()
        self.assertEqual([a.kind for a in actions], ["collect", "start", "start"])
        self.assertEqual((self.collect.call_count, self.start.call_count), (1, 2))
        self.assertEqual([e["text"] for e in log.read() if e["ev"] == "note"],
                         ["collect draft/a failed: lost builder", "start draft/b failed: cannot start"])

    def test_start_sees_events_written_by_preceding_collect(self):
        self.add_task("b")
        self.append(started())

        def collect(*args, **kwargs):
            self.append(ended(outcome="infra"))

        self.collect.side_effect = collect
        actions = self.tick()
        self.assertEqual([a.kind for a in actions], ["collect", "start"])
        self.assertEqual(self.calls[0][-1]["events"][-1]["outcome"], "infra")

    def test_nonzero_land_is_also_a_failure(self):
        self.append(started(), ended())
        self.land.side_effect = None
        self.land.return_value = 1
        self.tick()
        self.assertIn("landing refused", log.read()[-1]["text"])

    def test_failed_ready_push_does_not_log_ready_and_next_start_runs(self):
        self.add_task("b")
        self.add_task("a", repo="fabrig")
        self.append(started(), ended())
        self.fake.on(["git", "rev-parse", "--verify"], Result(0, "tip\n"))
        self.fake.on(["git", "push"], Result(1, err="refused"))
        self.tick()
        self.assertEqual(self.calls[0][0], "start")
        self.assertEqual(log.read()[-1]["ev"], "note")
        self.assertNotIn("branch.ready", [e["ev"] for e in log.read()])

    def test_lock_is_nonblocking_and_is_held_during_actions(self):
        result = []
        errors = []
        attempted = threading.Event()

        def second_tick():
            try:
                with patch.object(channel, "write", side_effect=AssertionError("page written while locked")):
                    result.append(self.tick())
            except Exception as error:
                errors.append(error)
            finally:
                attempted.set()

        def start(*args, **kwargs):
            worker = threading.Thread(target=second_tick, daemon=True)
            worker.start()
            self.assertTrue(attempted.wait(0.2), "second tick waited for the lock")
            worker.join(0.2)
            return "draft/a-1"

        self.start.side_effect = start
        self.tick()
        self.assertEqual((result, errors), ([[]], []))
        self.assertEqual(self.start.call_count, 1)
        self.assertEqual(len(self.fake.calls), 3)

    def test_lock_released_after_input_failure(self):
        write(self.directory / "plan.toml", "invalid")
        self.assertEqual([action.kind for action in self.tick()], ["load"])
        with open(log.home() / "tick.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_fetch_checkout_before_loading_specs_and_skip_non_checkout(self):
        self.tick()
        self.assertNotIn(["git", "fetch", "origin"], self.fake.argvs())
        self.fake = FakeRunner().on(["git", "rev-parse", "--show-toplevel"], Result(0, "/fake/repo\n"))
        self.tick()
        self.assertEqual(self.fake.calls[1].argv, ["git", "fetch", "origin"])
        self.assertEqual(self.fake.calls[1].cwd, "/fake/repo")

    def test_explicit_empty_hosts_does_not_load_config_or_import_queue(self):
        with patch("fab.hosts.load", side_effect=AssertionError("unexpected load")):
            self.assertEqual(dispatch.tick(self.directory, sh=self.fake, hosts={}),
                             [Action("flow", task="draft", detail="target 1, 0 in flight")])
        self.assertEqual(len(self.fake.calls), 1)

    def test_explicit_log_path_used_for_import_run_calls_and_park(self):
        path = self.home / "custom.jsonl"
        self.add_task("b")
        self.append(*growth(), started(), path=path)
        self.queue([dict(ev="rejected", ts="001", branch="draft/b", tip="b", step="test", log="red")])
        with patch.object(repairs, "start") as examine:
            self.tick(log_path=path)
        self.assertEqual([c[0] for c in self.calls], ["collect"])
        self.assertEqual(self.calls[0][-1]["log_path"], path)
        self.assertEqual(examine.call_args.kwargs, dict(sh=self.fake, log_path=path, trunk="main"))
        self.assertEqual(examine.call_args.args[3][-1]["ev"], "branch.rejected")
        self.assertEqual(examine.call_args.args[0].tip, "b")
        self.assertEqual(log.read(), [])
        self.assertEqual(log.read(path)[-1]["queue_ts"], "001")

    def test_default_hosts_loaded(self):
        with patch("fab.hosts.load", return_value=self.hosts) as load:
            dispatch.tick(self.directory, sh=self.fake)
        load.assert_called_once_with()
        self.start.assert_called_once()

    def test_dry_run_prints_decisions_without_commands_locks_or_writes(self):
        self.append(started(), ended())
        before = log.default_path().read_bytes()
        with patch("fab.hosts.load", return_value=self.hosts), \
             patch("fab.dispatch.tick", side_effect=AssertionError("tick called")), \
             patch("fab.dispatch.run", side_effect=AssertionError("command ran")), \
             patch("fab.flow.measure", side_effect=AssertionError("builder measured")):
            self.assertEqual(dispatch.main([str(self.directory), "--dry-run"]), 0)
        self.assertEqual(self.out.getvalue(), "flow draft target 2, 0 in flight\nland draft/a draft/a\n")
        self.assertEqual(log.default_path().read_bytes(), before)
        self.assertFalse((log.home() / "tick.lock").exists())
        self.assertEqual(self.calls, [])

    def test_dry_run_loads_uncut_plan_without_fetch_or_actions(self):
        """Dry-run resolves an uncut repository without fetching, locking or starting reviews."""
        (self.directory / "plan.toml").unlink()
        self.append(*chain_history("review", role="cut", subject="plan/cut"))
        fake = FakeRunner().on(["git", "rev-parse", "--show-toplevel"], Result(0, "/checkout\n"))
        fake.on(["git", "remote", "get-url", "origin"], Result(0, runs.REMOTES["agents"]))
        before = log.read()
        with patch.object(dispatch, "run", fake), patch("fab.hosts.load", return_value=self.hosts), \
             patch.object(flow, "measure", side_effect=AssertionError("builder measured")), \
             patch.object(call_review, "start", side_effect=AssertionError("review started")):
            self.assertEqual(dispatch.main([str(self.directory), "--dry-run"]), 0)
        self.assertEqual(self.out.getvalue(), "flow plan target 2, 0 in flight\n")
        self.assertEqual(fake.argvs(), [["git", "rev-parse", "--show-toplevel"],
                                       ["git", "remote", "get-url", "origin"]])
        self.assertEqual(log.read(), before)
        self.assertFalse((log.home() / "tick.lock").exists())

    def test_dry_run_skips_retired_plan_without_commands_or_hosts(self):
        """A retired dry-run only prints the retirement line."""
        path = self.directory / "plan.toml"
        write(path, 'retired = true\n' + path.read_text())
        with patch.object(dispatch, "run", side_effect=AssertionError("command ran")), \
             patch("fab.hosts.load", side_effect=AssertionError("hosts loaded")), \
             patch.object(dispatch, "decide", side_effect=AssertionError("actions decided")):
            self.assertEqual(dispatch.main([str(self.directory), "--dry-run"]), 0)
        self.assertEqual(self.out.getvalue(), "retired draft\n")
        self.assertFalse(log.home().exists())

    def test_dry_run_missing_plan_without_cut_names_directory(self):
        """A missing plan is still invalid in dry-run without a matching cut start."""
        (self.directory / "plan.toml").unlink()
        err = io.StringIO()
        with redirect_stderr(err), patch.object(dispatch, "run", side_effect=AssertionError("command ran")):
            self.assertEqual(dispatch.main([str(self.directory), "--dry-run"]), 1)
        self.assertIn(str(self.directory), self.out.getvalue())
        self.assertFalse(log.home().exists())

    def test_main_invokes_tick_and_cli_registers_it(self):
        with patch("fab.dispatch.tick") as tick:
            self.assertEqual(cli.main(["tick", str(self.directory)]), 0)
        tick.assert_called_once_with(self.directory, trigger="hand", only=False)

    def test_main_reports_plan_or_shell_errors(self):
        for failure in (plan.PlanError("bad plan"), OSError("offline")):
            with self.subTest(failure=failure), patch("fab.dispatch.tick", side_effect=failure):
                err = io.StringIO()
                with redirect_stderr(err):
                    self.assertEqual(dispatch.main([str(self.directory)]), 1)
                self.assertIn(str(failure), err.getvalue())

    def test_dry_run_refuses_invalid_plans(self):
        self.add_task("a", needs=("missing",))
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(dispatch.main([str(self.directory), "--dry-run"]), 1)
        self.assertIn("unknown task draft/missing", self.out.getvalue())
        self.assertFalse(log.home().exists())
        self.assertEqual(self.calls, [])

    def test_plan_problems_refused_before_queue_or_actions(self):
        self.add_task("a", needs=("missing",))
        actions = self.tick()
        self.assertEqual([action.kind for action in actions], ["load"])
        self.assertIn("unknown task draft/missing", actions[0].detail)
        self.assertEqual(self.calls, [])
        self.assertFalse(log.default_path().exists())


class WakeTickTest(wakes.WakeTestCase):
    def setUp(self):
        super().setUp()
        self.directory = write_plan(self.home / "plan", "draft", tasks=("a",))
        self.fake = FakeRunner().on(["git", "rev-parse", "--show-toplevel"], Result(128))
        self.collect = self.enterContext(patch.object(runs, "collect"))
        self.start = self.enterContext(patch.object(runs, "start", side_effect=self.start_run))
        self.out = io.StringIO()
        self.enterContext(redirect_stdout(self.out))

    def append(self, record):
        log.append(path=self.log_path, **record)

    def start_run(self, task, host, **kwargs):
        self.append(wakes.started(task.id + "-1", host=host.name))
        return task.id + "-1"

    def tick(self, **kwargs):
        return dispatch.tick(self.directory, sh=self.fake, hosts=wakes.HOSTS,
                             log_path=self.log_path, **kwargs)

    def test_want_is_taken_and_printed_before_import(self):
        wake.want("codex 1")
        wake.want("queue landed draft/b")

        def imported(*args, **kwargs):
            self.assertNoWant()
            self.assertEqual(self.out.getvalue(), "wake - codex 1; queue landed draft/b\n")

        with patch.object(dispatch, "_import_queue", side_effect=imported) as imports:
            self.tick(trigger="event")
        imports.assert_called_once()
        self.assertNoWant()
        self.assertEqual(self.notes(), [])

    def test_empty_want_prints_a_dash(self):
        write(self.want, "")
        self.tick()
        self.assertEqual(self.out.getvalue().splitlines()[0], "wake - -")
        self.assertNoWant()

    def test_a_want_during_collect_is_left_for_the_next_round(self):
        wake.want("before")
        self.append(wakes.started("draft/a-1"))
        self.collect.side_effect = lambda *args, **kwargs: wake.want("during")
        self.tick()
        self.assertWanted("during")
        self.assertEqual(self.out.getvalue().splitlines()[0], "wake - before")

    def test_collecting_an_ended_run_wants_again_and_only_backstop_notes_it(self):
        for number, trigger in enumerate(("hand", "backstop"), 1):
            with self.subTest(trigger=trigger):
                run_id = f"draft/a-{number}"
                self.append(wakes.started(run_id))
                self.collect.side_effect = lambda *args, **kwargs: self.append(wakes.ended(run_id))
                self.tick(trigger=trigger)
                self.assertWanted("tick 1: run.ended")
                self.assertEqual(self.notes(), [] if trigger == "hand" else
                                 ["lost event: run.ended draft/a-2"])
                wake.take()
        self.assertIn("again - tick 1: run.ended", self.out.getvalue().splitlines())
        self.assertIn("lost - lost event: run.ended draft/a-2", self.out.getvalue().splitlines())

    def test_backstop_starting_a_run_wants_nothing_and_logs_no_note(self):
        self.tick(trigger="backstop")
        self.start.assert_called_once()
        self.assertNoWant()
        self.assertEqual(self.notes(), [])

    def test_settle_counts_other_writers_records_but_excludes_old_records(self):
        self.append(wakes.ended("other/old-1"))
        with patch.object(channel, "write", side_effect=lambda *args, **kwargs:
                          self.append(wakes.imported("branch.landed", "other/new"))):
            self.tick()
        self.assertWanted("tick 1: branch.landed")

    def test_early_returns_and_errors_still_settle(self):
        for result in ("empty", "failed load", "error"):
            with self.subTest(result=result):
                wake.want("before")
                scenario = (patch.object(dispatch, "_round", side_effect=RuntimeError("round"))
                            if result == "error" else
                            patch.object(channel, "plan_dirs", return_value=(
                                [] if result == "empty" else [self.home / "missing"])))
                with scenario:
                    if result == "error":
                        with self.assertRaisesRegex(RuntimeError, "round"):
                            self.tick(trigger="backstop")
                    else:
                        self.tick(trigger="backstop")
                self.assertNoWant()
        self.assertEqual(self.notes(), ["lost event: wake before"] * 3)

    def test_event_waits_for_lock_while_backstop_leaves_want_untouched(self):
        wake.want("before")
        held, release, attempted, finished = (threading.Event() for _ in range(4))
        errors, actions = [], []
        flock = fcntl.flock

        def hold():
            with open(log.home() / "tick.lock", "a") as lock:
                flock(lock, fcntl.LOCK_EX)
                held.set()
                release.wait(1)

        def locking(lock, operation):
            attempted.set()
            return flock(lock, operation)

        def event_tick():
            try:
                actions.extend(self.tick(trigger="event"))
            except Exception as error:
                errors.append(error)
            finally:
                finished.set()

        holder = threading.Thread(target=hold, daemon=True)
        holder.start()
        worker = threading.Thread(target=event_tick, daemon=True)
        try:
            self.assertTrue(held.wait(0.2))
            self.assertEqual(self.tick(trigger="backstop"), [])
            self.assertWanted("before")
            self.assertEqual(self.fake.calls, [])
            with patch.object(dispatch.fcntl, "flock", side_effect=locking):
                worker.start()
                self.assertTrue(attempted.wait(0.2))
                self.assertFalse(finished.wait(0.02))
                self.assertWanted("before")
                release.set()
                worker.join(0.2)
        finally:
            release.set()
            holder.join(0.2)
            if worker.ident is not None:
                worker.join(0.2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertIn("start", [action.kind for action in actions])
        self.assertNoWant()

    def test_unknown_trigger_raises_before_the_lock_and_takes_nothing(self):
        wake.want("before")
        with patch.object(dispatch.fcntl, "flock", side_effect=AssertionError("locked")):
            with self.assertRaises(ValueError):
                self.tick(trigger="unknown")
        self.assertFalse((log.home() / "tick.lock").exists())
        self.assertWanted("before")
        self.assertEqual(self.fake.calls, [])

    def test_main_passes_backstop_and_dry_run_ignores_trigger_and_want(self):
        with patch.object(dispatch, "tick", return_value=[]) as tick:
            self.assertEqual(dispatch.main([str(self.directory), "--trigger", "backstop"]), 0)
        tick.assert_called_once_with(self.directory, trigger="backstop", only=False)
        wake.want("before")
        with patch.object(dispatch, "run", self.fake), \
                patch.object(dispatch.machines, "load", return_value=wakes.HOSTS), \
                patch.object(wake, "settle", side_effect=AssertionError("settled")):
            self.assertEqual(dispatch.main([str(self.directory), "--dry-run", "--trigger", "event"]), 0)
        self.assertWanted("before")
        self.assertFalse((log.home() / "tick.lock").exists())
        self.assertEqual(self.notes(), [])


class MultiPlanTickTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.checkout = self.home / "checkout"
        self.hosts = {"builder": Host("builder", "fake@builder", ("builder",), places=1, slots=8),
                      "gate": Host("gate", "fake@gate", ("gate",))}
        self.fake = FakeRunner().on(["git", "rev-parse", "--show-toplevel"],
                                    Result(0, str(self.checkout) + "\n"))
        self.queue_records = []
        self.queue_prefix = ssh("fake@gate", ["fab", "queue", "log"])[:-1]
        self.fake.on(self.queue_prefix, self.queue_result)
        self.starts = self.enterContext(patch.object(runs, "start", side_effect=self.start_run))
        self.collects = self.enterContext(patch.object(runs, "collect", return_value=None))
        self.out = io.StringIO()
        self.enterContext(redirect_stdout(self.out))

    def plan_dir(self, draft, **kwargs):
        return write_plan(self.checkout / "docs/plan" / draft, draft, **kwargs)

    def append(self, *events):
        for entry in events:
            fields = dict(entry)
            log.append(fields.pop("ev"), **fields)

    def queue_result(self, call):
        argv = shlex.split(shlex.split(call.argv[-1])[2])
        since = argv[-1]
        records = [record for record in self.queue_records if record["ts"] >= since]
        return Result(0, "\n".join(json.dumps(record) for record in records))

    def start_run(self, task, host, **kwargs):
        record = run_started(task.id, host=host.name, kind=kwargs["kind"], branch=task.id)
        fields = dict(record)
        log.append(fields.pop("ev"), path=kwargs["log_path"], **fields)
        return record["run"]

    def tick(self, *directories):
        return dispatch.tick(*directories, sh=self.fake, hosts=self.hosts)

    def queries(self):
        return [argv for argv in self.fake.argvs() if argv[:len(self.queue_prefix)] == self.queue_prefix]

    def overlap_plans(self):
        directories = [self.plan_dir(draft, tasks=("a",)) for draft in ("one", "two")]
        for directory in directories:
            path = directory / "plan.toml"
            write(path, path.read_text().replace('landing = "queue"', 'landing = "integration"'))
        self.fake.on(["git", "rev-parse", "--verify"],
                     lambda call: Result(0, {"origin/main": "1" * 40,
                                            "origin/one/integration": "a" * 40,
                                            "origin/two/integration": "b" * 40}[call.argv[-1]]))
        self.fake.on(["git", "merge-tree"], lambda call: Result(
            1, "c" * 40 + "\0shared.py\0") if "--name-only" in call.argv else Result(0, "d" * 40))
        return directories

    def test_overlap_probe_once_per_round_after_both_ready_plans_tick(self):
        one, two = self.overlap_plans()
        ticked = []
        tick_loaded = dispatch._tick_loaded

        def tick_plan(plan, *args, **kwargs):
            actions = tick_loaded(plan, *args, **kwargs)
            ticked.append(plan.draft)
            return actions

        probe = overlaps.probe

        def probed(*args, **kwargs):
            self.assertEqual(ticked, ["two", "one"])
            self.assertTrue(args[2])
            return probe(*args, **kwargs)

        with patch.object(dispatch, "_tick_loaded", side_effect=tick_plan), patch.object(
                overlaps, "probe", side_effect=probed) as probes:
            self.tick(two, one)
            probes.assert_called_once()
            ticked.clear()
            self.tick(two, one)
            self.assertEqual(probes.call_count, 2)
        self.assertEqual(len([argv for argv in self.fake.argvs() if argv[:2] == ["git", "merge-tree"]]), 3)
        records = [event for event in log.read() if event["ev"] == "trunks.overlap"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["drafts"], ["one", "two"])
        self.assertIn("overlap one two 1", self.out.getvalue())

    def test_overlap_probe_is_not_called_with_only(self):
        one, two = self.overlap_plans()
        with patch.object(overlaps, "probe", wraps=overlaps.probe) as probe:
            dispatch.tick(one, two, sh=self.fake, hosts=self.hosts, only=True)
            probe.assert_not_called()
        self.assertFalse(any(argv[:2] == ["git", "merge-tree"] for argv in self.fake.argvs()))

    def test_overlap_probe_failed_load_defers_closing_pairs(self):
        one, two = self.overlap_plans()
        self.tick(one, two)
        self.fake.calls.clear()
        actions = self.tick(one, self.home / "missing")
        self.assertTrue(any(action.kind == "load" for action in actions))
        self.assertEqual(len([event for event in log.read() if event["ev"] == "trunks.overlap"]), 1)
        self.assertFalse(any(argv[:2] == ["git", "merge-tree"] for argv in self.fake.argvs()))
        self.tick(one)
        self.assertEqual([event["reason"] for event in log.read() if event["ev"] == "trunks.overlap"],
                         ["probe", "gone"])

    def test_overlap_probe_closes_pairs_when_no_plans_remain(self):
        one, two = self.overlap_plans()
        self.tick(one, two)
        self.tick()
        self.assertEqual([event["reason"] for event in log.read() if event["ev"] == "trunks.overlap"],
                         ["probe", "gone"])

    def test_overlap_probe_checkout_errors_print_and_the_round_refreshes_page(self):
        one, two = self.overlap_plans()
        for error in (OSError("checkout unavailable"), ValueError("checkout unavailable"),
                      Failed(["git", "rev-parse"], Result(128, err="checkout unavailable"))):
            with self.subTest(error=type(error).__name__):
                def revision(call):
                    raise error
                self.fake.rules[-2] = (["git", "rev-parse", "--verify"], revision)
                self.out.truncate(0)
                self.out.seek(0)
                with patch.object(dispatch, "_page") as page:
                    self.tick(one, two)
                    page.assert_called_once()
                self.assertIn("overlap - failed:", self.out.getvalue())
                self.assertIn("checkout unavailable", self.out.getvalue())

    def test_listed_plan_then_given_plan_fetch_and_page_once(self):
        one = self.plan_dir("one", tasks=("a",))
        two = self.plan_dir("two", tasks=("a",))
        designer.enlist(one)
        self.hosts["builder"] = replace(self.hosts["builder"], places=4)
        with patch.object(channel, "write", wraps=channel.write) as page:
            actions = self.tick(two, one)
        self.assertEqual([(a.kind, a.task) for a in actions],
                         [("flow", "one"), ("start", "one/a"), ("flow", "two"), ("start", "two/a")])
        self.assertEqual(self.fake.argvs().count(["git", "fetch", "origin"]), 1)
        self.assertEqual([call.cwd for call in self.fake.calls if call.argv ==
                          ["git", "fetch", "origin"]], [str(self.checkout)])
        self.assertEqual(len(self.queries()), 1)
        page.assert_called_once()

    def fabrig_plan(self, *, draft="draft", tasks=()):
        """A nested fabrig plan and runner that resolves each plan's own checkout."""
        self.fabrig_checkout = log.home() / "repos/fabrig"
        directory = write_plan(self.fabrig_checkout / "skein/docs/plan" / draft,
                               draft, tasks=tasks, repo="fabrig")
        self.fake.rules.insert(0, (["git", "rev-parse", "--show-toplevel"], lambda call: Result(
            0, str(self.fabrig_checkout if Path(call.cwd).is_relative_to(self.fabrig_checkout)
                   else self.checkout) + "\n")))
        self.tip = "first-tip"
        self.fake.on(["git", "rev-parse", "--verify"], lambda call: Result(0, self.tip + "\n"))
        self.lands = self.enterContext(patch.object(dispatch.land, "main", return_value=0))
        return directory

    def test_nested_fabrig_plan_loads_beside_agents_and_fetches_each_checkout_once(self):
        rust = self.fabrig_plan(draft="rust", tasks=("a",))
        agents = self.plan_dir("agents", tasks=("a",))
        self.hosts["builder"] = replace(self.hosts["builder"], places=4)
        designer.enlist(rust)
        designer.enlist(agents)
        self.tick()
        self.assertEqual([call.args[0].repo for call in self.starts.call_args_list], ["fabrig", "agents"])
        self.assertEqual(self.starts.call_args_list[0].args[0].path, str(rust / "tasks/a.md"))
        fetches = [call.cwd for call in self.fake.calls if call.argv == ["git", "fetch", "origin"]]
        self.assertEqual(fetches, [str(self.fabrig_checkout), str(self.checkout)])
        self.assertEqual(len(self.queries()), 1)

    def test_approved_fabrig_skeleton_readies_once_and_finishes_only_on_imported_landing(self):
        rust = self.fabrig_plan()
        self.append(*chain_history("approved"))
        self.tick(rust)
        branch = "calls/root"
        ready = [event for event in log.read() if event["ev"] == "branch.ready"]
        self.assertEqual([(event["task"], event["branch"], event["tip"]) for event in ready],
                         [(branch, branch, self.tip)])
        push = ["git", "push", "origin", f"{self.tip}:refs/heads/ready/{branch}"]
        self.assertEqual(next(call.cwd for call in self.fake.calls if call.argv == push), str(self.fabrig_checkout))
        self.tick(rust)
        self.assertEqual(self.fake.argvs().count(push), 1)
        self.assertFalse(any(event["ev"] == "call.finished" for event in log.read()))
        self.queue_records = [dict(ev="landed", ts="001", branch=branch, tip=self.tip, main="main")]
        self.tick(rust)
        self.tick(rust)
        imported = [event for event in log.read() if "queue_ts" in event]
        self.assertEqual([(event["ev"], event["task"]) for event in imported], [("branch.landed", branch)])
        finished = [event for event in log.read() if event["ev"] == "call.finished"]
        self.assertEqual([(event["call"], event["outcome"]) for event in finished], [("root", "done")])
        self.assertEqual(self.queries()[-1], ssh("fake@gate", ["fab", "queue", "log", "--since", "001"]))
        self.lands.assert_not_called()
        self.assertFalse(any("receipt" in argv[-1] for argv in self.fake.argvs() if argv[0] == "ssh"))

    def test_fabrig_queue_readies_moved_tip_without_later_call_end(self):
        rust = self.fabrig_plan()
        self.append(*chain_history("approved"))
        self.tick(rust)
        self.tip = "moved-tip"
        self.tick(rust)
        self.tick(rust)
        ready = [entry for entry in log.read() if entry["ev"] == "branch.ready"]
        self.assertEqual([entry["tip"] for entry in ready], ["first-tip", "moved-tip"])
        self.assertEqual(self.fake.argvs().count(
            ["git", "push", "origin", "moved-tip:refs/heads/ready/calls/root"]), 1)
        self.lands.assert_not_called()

    def test_fabrig_queue_readies_same_tip_after_later_call_end(self):
        rust = self.fabrig_plan()
        self.append(*chain_history("approved"))
        self.tick(rust)
        self.append(call_ended("root"))
        self.tick(rust)
        self.tick(rust)
        ready = [entry for entry in log.read() if entry["ev"] == "branch.ready"]
        self.assertEqual([entry["tip"] for entry in ready], ["first-tip", "first-tip"])
        self.lands.assert_not_called()

    def test_fabrig_answer_call_keeps_questions_parked_until_landing(self):
        rust = self.fabrig_plan(tasks=("a",))
        self.append(*question_history(status="parked"), *chain_history("approved", role="answer", subject="draft"))
        write(log.home() / "calls/root/report.md", "Done: answered\nAnswered: draft/a draft/a\n")
        self.tick(rust)
        self.tick(rust)
        self.starts.assert_not_called()
        self.assertFalse(any(event["ev"] == "question.answered" for event in log.read()))
        self.queue_records = [dict(ev="landed", ts="001", branch="calls/root", tip=self.tip, main="main")]
        self.tick(rust)
        answered = [event for event in log.read() if event["ev"] == "question.answered"]
        self.assertEqual([(event["task"], event["call"]) for event in answered], [("draft/a", "root")])
        self.tick(rust)
        self.starts.assert_called_once()
        self.assertEqual(len([event for event in log.read() if event["ev"] == "call.finished"]), 1)
        self.lands.assert_not_called()

    def test_fabrig_queue_refusal_amends_once_and_second_refusal_settles(self):
        rust = self.fabrig_plan()
        self.append(*chain_history("approved"))
        self.tick(rust)
        first = dict(ev="rejected", ts="001", branch="calls/root", tip=self.tip,
                     step="cargo", log="/queue/first", findings="compile error")
        self.queue_records = [first]
        actions = self.tick(rust)
        self.assertEqual([action.run_kind for action in actions if action.kind == "call"], ["amend"])
        refusal = next(event for event in log.read() if event["ev"] == "branch.rejected")
        self.assertEqual((refusal["step"], refusal["findings"]), ("cargo", "compile error"))
        self.append(dict(ev="call.started", call="amend", role="amend", amends="root",
                         subject="draft/core", branch="calls/root"))
        self.assertFalse(any(action.kind == "call" for action in self.tick(rust)))
        self.append(dict(ev="call.ended", call="amend", outcome="done"),
                    dict(ev="run.started", run="amend-review", task="root", kind="review", host="builder"),
                    dict(ev="run.ended", run="amend-review", outcome="done"))
        self.tip = "second-tip"
        self.tick(rust)
        self.assertEqual(len([event for event in log.read() if event["ev"] == "branch.ready"]), 2)
        self.queue_records.append(dict(first, ts="002", tip=self.tip, log="/queue/second"))
        self.assertEqual([a.run_kind for a in self.tick(rust) if a.kind == "call"], ["settle"])
        self.append(dict(ev="call.started", call="settle", role="settle", subject="draft/core/settle", settles="root"))
        self.tick(rust)
        self.assertFalse(any(event["ev"] == "call.parked" for event in log.read()))
        self.assertEqual(len(units(self.fake)), 2)
        self.assertFalse(any(event["ev"] == "call.finished" for event in log.read()))
        self.lands.assert_not_called()

    def test_failed_fabrig_ready_push_leaves_approved_chain_retryable(self):
        rust = self.fabrig_plan()
        self.append(*chain_history("approved"))
        push = ["git", "push", "origin", "first-tip:refs/heads/ready/calls/root"]
        attempt = [Result(1, err="push refused"), Result(0)]
        self.fake.on(push, lambda call: attempt.pop(0))
        self.tick(rust)
        self.assertEqual(log.read()[-1]["ev"], "note")
        self.assertEqual(call_review.chains(log.read())["root"].state, "approved")
        self.assertFalse(any(event["ev"] in ("call.finished", "branch.ready") for event in log.read()))
        self.tick(rust)
        self.assertEqual(log.read()[-1]["ev"], "branch.ready")
        self.assertEqual(self.fake.argvs().count(push), 2)
        self.lands.assert_not_called()

    def test_fabrig_foreman_answer_is_committed_once_and_waits_for_landing(self):
        rust = self.fabrig_plan(tasks=("a",))
        self.append(*question_history(status="settled"))
        write(log.home() / "runs/draft/a/foreman-1/report.md", "Done: Use option A\n")
        branch = "answers/draft/a/foreman-1"
        with patch.object(foreman, "commit", return_value=branch) as commit:
            self.tick(rust)
            self.tick(rust)
            commit.assert_called_once()
            self.assertEqual(commit.call_args.args[3], self.fabrig_checkout)
            tasks = plan.load(rust)[1]
            self.assertEqual(foreman.questions(tasks, log.read())[0].state, "settled")
            self.assertEqual(state.fold(tasks, log.read())["draft/a"].status, "parked")
            self.queue_records = [dict(ev="landed", ts="001", branch=branch, tip=self.tip, main="main")]
            self.tick(rust)
            self.tick(rust)
            commit.assert_called_once()
        imported = [event for event in log.read() if "queue_ts" in event]
        self.assertEqual([(event["ev"], event["task"]) for event in imported], [("branch.landed", branch)])
        answered = [event for event in log.read() if event["ev"] == "question.answered"]
        self.assertEqual([(event["task"], event["by"], event["run"]) for event in answered],
                         [("draft/a", "draft/a/foreman-1", "draft/a-1")])
        self.starts.assert_called_once()
        self.assertEqual(len([event for event in log.read() if event["ev"] == "branch.ready"]), 1)
        self.lands.assert_not_called()

    def test_answer_ready_failure_reuses_the_pushed_commit_on_retry(self):
        rust = self.fabrig_plan(tasks=("a",))
        self.append(*question_history(status="settled"))
        write(log.home() / "runs/draft/a/foreman-1/report.md", "Done: Use option A\n")
        worktree = log.home() / "runs/draft/a/foreman-1/wt"
        spec_path = Path("skein/docs/plan/draft/tasks/a.md")
        pushed = []
        self.fake.on(["git", "worktree", "add"], lambda call: (
            write(worktree / spec_path, (rust / "tasks/a.md").read_text()) or Result(0)))
        self.fake.on(["git", "push", "-q", "--force"], lambda call: (
            pushed.append((worktree / spec_path).read_text()) or Result(0)))
        self.fake.on(["git", "show"], lambda call: Result(0, pushed[-1]) if pushed else Result(128))
        attempts = [Result(1, err="push refused"), Result(0)]
        self.fake.on(["git", "push", "origin"], lambda call: attempts.pop(0))
        self.tick(rust)
        self.assertEqual(log.read()[-1]["ev"], "note")
        self.tick(rust)
        self.assertEqual(log.read()[-1]["ev"], "branch.ready")
        self.assertEqual(len(pushed), 1)
        self.assertEqual(len([call for call in self.fake.calls if "commit" in call.argv]), 1)
        self.assertFalse(any(event["ev"] == "question.answered" for event in log.read()))
        self.lands.assert_not_called()

    def test_queue_import_tracks_only_owned_call_and_spec_branches(self):
        rust = self.fabrig_plan(tasks=("a",))
        self.append(*chain_history("approved"), *question_history(status="deciding"))
        branches = ("calls/root", "answers/draft/a/foreman-1", "repairs/draft/a/foreman-1")
        foreign = ("calls/foreign", "answers/other/a/foreman-1", "repairs/other/a/foreman-1")
        self.queue_records = [dict(ev="landed", ts="010", branch=branch, tip="tip", main="main")
                              for branch in (*branches, *foreign)]
        self.tick(rust)
        self.tick(rust)
        imported = [event for event in log.read() if "queue_ts" in event]
        self.assertEqual([event["task"] for event in imported], list(branches))
        self.assertEqual(self.queries()[-1], ssh("fake@gate", ["fab", "queue", "log", "--since", "010"]))

    def test_one_probe_per_builder_for_all_plans(self):
        one, two = self.plan_dir("one"), self.plan_dir("two")
        self.hosts["second"] = Host("second", "fake@second", ("builder",), places=1)
        self.tick(one, two)
        for name in ("builder", "second"):
            probe = ssh(f"fake@{name}", flow.PROBE + ["/home/fake/src/fabrig/fab/heavy.jsonl"])
            self.assertEqual(self.fake.argvs().count(probe), 1)

    def test_places_are_shared_and_later_plan_reads_started_run(self):
        one = self.plan_dir("one", tasks=("a",))
        two = self.plan_dir("two", tasks=("a",))
        actions = self.tick(one, two)
        self.assertEqual([a.task for a in actions if a.kind == "start"], ["one/a"])
        self.assertEqual([a.task for a in actions if a.kind == "collect"], [])
        self.assertEqual([entry["task"] for entry in log.read()], ["one/a"])

    def test_calm_extra_goes_only_to_first_plan(self):
        one = self.plan_dir("one", tasks=("a",))
        two = self.plan_dir("two", tasks=("a",))
        self.append(run_started("other/busy"))
        probe = ssh("fake@builder", flow.PROBE + ["/home/fake/src/fabrig/fab/heavy.jsonl"])
        self.fake.on(probe, Result(0, "0.1 0.2 0.3\n2\n"))
        actions = self.tick(one, two)
        self.assertEqual([a.task for a in actions if a.kind == "start"], ["one/a"])
        self.assertEqual(actions[-1].task, "other/busy")
        self.starts.assert_called_once()

    def test_queue_import_uses_oldest_loaded_draft_cursor(self):
        one = self.plan_dir("one", tasks=("a",))
        two = self.plan_dir("two", tasks=("a",))
        for draft, stamp in (("one", "010"), ("two", "005"), ("other", "999")):
            self.append(dict(ev="branch.landed", task=f"{draft}/a", branch=f"{draft}/a",
                             tip="old", main="main", queue_ts=stamp))
        self.queue_records = [dict(ev="landed", branch=f"{draft}/a", ts=stamp, tip="new", main="main")
                              for draft, stamp in (("one", "011"), ("two", "006"))]
        self.tick(one, two)
        self.assertEqual(self.queries(), [ssh("fake@gate", ["fab", "queue", "log", "--since", "005"])])
        self.assertEqual([(e["task"], e["queue_ts"]) for e in log.read() if e.get("tip") == "new"],
                         [("one/a", "011"), ("two/a", "006")])

    def test_queue_recovers_failed_plan_older_records_once(self):
        one = self.plan_dir("one", tasks=("a",))
        two = self.plan_dir("two", tasks=("a",))
        write(two / "plan.toml", "invalid [")
        self.append(dict(ev="branch.ready", branch="two/a", tip="two"))
        self.queue_records = [dict(ev="landed", branch=f"{draft}/a", ts=stamp, tip=draft, main="main")
                              for draft, stamp in (("one", "020"), ("two", "010"))]
        first = self.tick(one, two)
        self.assertEqual(first[0].kind, "load")
        self.assertEqual([(e["ev"], e.get("task"), e["queue_ts"]) for e in log.read() if "queue_ts" in e],
                         [("branch.landed", "one/a", "020")])
        self.plan_dir("two", tasks=("a",))
        self.tick(one, two)
        self.tick(one, two)
        self.assertEqual([(e["ev"], e.get("task"), e["queue_ts"]) for e in log.read() if "queue_ts" in e],
                         [("branch.landed", "one/a", "020"), ("branch.landed", "two/a", "010")])
        self.assertEqual(self.queries(), [ssh("fake@gate", ["fab", "queue", "log", "--since", stamp])
                                          for stamp in ("", "", "010")])

    def test_newly_listed_plan_reads_older_queue_records(self):
        one = self.plan_dir("one", tasks=("a",))
        two = self.plan_dir("two", tasks=("a",))
        designer.enlist(one)
        self.append(dict(ev="branch.ready", branch="two/a", tip="two"))
        self.queue_records = [dict(ev="landed", branch=f"{draft}/a", ts=stamp, tip=draft, main="main")
                              for draft, stamp in (("one", "020"), ("two", "010"))]
        self.tick()
        designer.enlist(two)
        self.tick()
        self.assertEqual(self.queries(), [ssh("fake@gate", ["fab", "queue", "log", "--since", ""])] * 2)
        self.assertEqual([(e["ev"], e.get("task")) for e in log.read() if "queue_ts" in e],
                         [("branch.landed", "one/a"), ("branch.landed", "two/a")])

    def test_draft_without_queue_records_keeps_empty_cursor(self):
        one, two = self.plan_dir("one", tasks=("a",)), self.plan_dir("two", tasks=("a",))
        self.queue_records = [dict(ev="landed", branch="one/a", ts="020", tip="one", main="main")]
        self.tick(one, two)
        self.tick(one, two)
        self.assertEqual(self.queries(), [ssh("fake@gate", ["fab", "queue", "log", "--since", ""])] * 2)
        self.assertEqual(len([e for e in log.read() if "queue_ts" in e]), 1)

    def test_bad_load_prints_once_logs_nothing_and_main_exits_one_after_other_plan(self):
        one = self.plan_dir("one", tasks=("a",))
        two = self.plan_dir("two", tasks=("a",))
        write(one / "plan.toml", "invalid [")
        real_tick = dispatch.tick
        with patch.object(dispatch, "tick", side_effect=lambda *paths, **kwargs: real_tick(
                *paths, sh=self.fake, hosts=self.hosts, **kwargs)):
            self.assertEqual(dispatch.main([str(one), str(two)]), 1)
        self.assertEqual([e["task"] for e in log.read()], ["two/a"])
        lines = self.out.getvalue().splitlines()
        self.assertTrue(lines[0].startswith(f"load {one} failed: "))
        self.assertEqual(len([line for line in lines if line.startswith("load ")]), 1)
        self.assertTrue(any(line.startswith("flow two ") for line in lines))

    def test_duplicate_draft_is_failed_load_and_first_directory_kept(self):
        one = self.plan_dir("one", tasks=("a",))
        duplicate = write_plan(self.home / "duplicate", "one", tasks=("b",))
        actions = self.tick(one, duplicate)
        self.assertEqual(actions[0], Action("load", task=str(duplicate),
                         detail=f"failed: draft one is already ticked from {one}"))
        self.assertEqual([a.task for a in actions if a.kind == "start"], ["one/a"])
        self.assertFalse(any(e["ev"] == "note" for e in log.read()))

    def test_fetch_failure_defers_red_opening_until_all_owners_load(self):
        one = self.plan_dir("one", tasks=("a",), repo="fabrig")
        two = self.fabrig_plan(draft="two", tasks=("a",))
        self.hosts["tiers"] = Host("tiers", "fake@tiers", ("after-landing",))
        agents = self.plan_dir("agents", tasks=("a",))
        for draft in ("one", "agents"):
            self.append(dict(ev="branch.landed", task=f"{draft}/a", branch=f"{draft}/a",
                             tip="tip", main="main"))
        records = [dict(ev="test", ts="001", state="new", key="key", tip="tip",
                        profile="default", binary="b", test="t", branches=["one/a"]),
                   dict(ev="run", ts="002", tip="tip", reds=["key"], branches=["one/a"])]
        self.fake.on(ssh("fake@tiers", ["fab", "after-landing", "log"])[:-1],
                     Result(0, "\n".join(json.dumps(record) for record in records)))
        self.fake.rules.insert(0, (["git", "fetch", "origin"], lambda call:
            Result(1, err="fetch failed") if call.cwd == str(self.fabrig_checkout) else Result(0)))
        actions = self.tick(one, two, agents)
        self.assertTrue(any(a.kind == "load" and "fetch failed" in a.detail for a in actions))
        self.assertFalse(any(e["ev"] == "red.opened" for e in log.read()))
        verdict, = [e for e in log.read() if e["ev"] == "tiers.run"]
        self.assertEqual(verdict["branches"], ["one/a"])
        self.assertEqual([a.task for a in actions if a.run_kind == "retire"], ["agents/retire"])
        self.assertNotIn(drafts.unit("retire", "one/retire"), units(self.fake))
        self.fake.rules.pop(0)
        actions = self.tick(one, two, agents)
        opened, = [e for e in log.read() if e["ev"] == "red.opened"]
        self.assertEqual((opened["draft"], opened["route"], opened["tasks"]),
                         ("one", "foreman", ["one/a"]))
        self.assertFalse(any(a.run_kind == "retire" and a.task == "one/retire" for a in actions))
        self.assertNotIn(drafts.unit("retire", "one/retire"), units(self.fake))

    def test_fetch_failure_without_after_landing_does_not_hold_retirement(self):
        one = self.plan_dir("one", tasks=("a",), repo="fabrig")
        two = self.fabrig_plan(draft="two", tasks=("a",))
        self.append(dict(ev="branch.landed", task="one/a", branch="one/a", tip="tip", main="main"))
        self.fake.rules.insert(0, (["git", "fetch", "origin"], lambda call:
            Result(1, err="fetch failed") if call.cwd == str(self.fabrig_checkout) else Result(0)))
        actions = self.tick(one, two)
        self.assertTrue(any(a.kind == "load" and "fetch failed" in a.detail for a in actions))
        self.assertEqual([a.task for a in actions if a.run_kind == "retire"], ["one/retire"])
        self.assertIn(drafts.unit("retire", "one/retire"), units(self.fake))

    def test_retired_among_plans_is_skipped(self):
        one, two = self.plan_dir("one"), self.plan_dir("two")
        path = one / "plan.toml"
        write(path, "retired = true\n" + path.read_text())
        actions = self.tick(one, two)
        self.assertEqual([a.task for a in actions if a.kind == "flow"], ["two"])
        self.assertEqual(self.out.getvalue().splitlines()[0], "retired one")
        self.assertEqual(units(self.fake), [drafts.unit("skeleton", "two/core")])

    def retired_fabrig(self, *, landing="queue"):
        directory = self.fabrig_plan(draft="retired", tasks=("a",))
        path = directory / "plan.toml"
        write(path, "retired = true\n" + path.read_text().replace(
            'landing = "queue"', f'landing = "{landing}"'))
        self.append(call_started("retire-last", "retire", "retired/retire"),
                    call_ended("retire-last"),
                    dict(ev="call.checked", call="retire-last", tip="checked-tip", outcome="green"),
                    dict(ev="branch.ready", task="calls/retire-last", branch="calls/retire-last",
                         tip="ready-tip"))
        self.queue_records = [dict(ev="landed", ts="010", branch="calls/retire-last",
                                   tip="ready-tip", main="main")]
        return directory

    def assert_retired_landing(self, *, active, landing="queue"):
        retired = self.retired_fabrig(landing=landing)
        directories = [retired]
        if active:
            directories.append(self.plan_dir("active", tasks=("a",)))
            self.append(dict(ev="branch.landed", task="active/old", branch="active/old",
                             queue_ts="020"))
        else:
            self.enterContext(patch.object(flow, "measure", side_effect=AssertionError("measured")))
        designer.enlist(retired)
        self.append(dict(ev="queue.landed", branch="hand/pushed", queue_ts="999", gate="gate"))
        before = log.read()
        with patch.object(dispatch, "_tick_loaded", wraps=dispatch._tick_loaded) as tick_loaded, \
                patch.object(dispatch, "_merge_branch") as merge, \
                patch.object(overlaps, "probe", wraps=overlaps.probe) as probe:
            first = self.tick(*directories)
            gained = log.read()[len(before):]
            delivery = [entry for entry in gained if entry["ev"] in ("branch.landed", "call.finished")]
            self.assertEqual([entry["ev"] for entry in delivery], ["branch.landed", "call.finished"])
            self.assertEqual((delivery[0]["branch"], delivery[0]["queue_ts"]), ("calls/retire-last", "010"))
            self.assertEqual({key: value for key, value in delivery[1].items() if key != "ts"},
                             dict(ev="call.finished", call="retire-last", role="retire",
                                  outcome="done", tip="checked-tip"))
            count = len(log.read())
            second = self.tick(*directories)
            self.assertFalse(any(entry["ev"] in ("branch.landed", "call.finished")
                                 for entry in log.read()[count:]))
            self.assertEqual([call.args[0].draft for call in tick_loaded.call_args_list],
                             ["active", "active"] if active else [])
            self.assertTrue(all([entry[0].draft for entry in call.args[0]] ==
                                (["active"] if active else []) for call in probe.call_args_list))
            merge.assert_not_called()
        self.assertEqual(self.queries()[0], ssh("fake@gate", ["fab", "queue", "log", "--since", ""]))
        self.assertEqual(self.queries()[1], ssh("fake@gate", ["fab", "queue", "log", "--since", "010"]))
        self.assertFalse(any(action.task.startswith("retired") for action in first + second))
        self.assertFalse(any(entry["ev"] == "call.started" or entry["ev"] == "trunks.overlap"
                             for entry in gained))
        self.assertTrue(all(call.args[0].draft == "active" for call in self.starts.call_args_list))
        self.assertTrue(all(call.args[0].startswith("active/") for call in self.collects.call_args_list))
        self.lands.assert_not_called()
        self.assertEqual(self.out.getvalue().count("retired retired\n"), 2)
        if not active:
            self.assertEqual([entry["ev"] for entry in gained], ["branch.landed", "call.finished"])
            self.assertEqual(first + second, [])

    def test_retired_landing_imports_and_finishes_beside_an_active_plan_once(self):
        self.assert_retired_landing(active=True)

    def test_retired_landing_imports_and_finishes_with_no_loaded_plan_once(self):
        self.assert_retired_landing(active=False)

    def test_retired_landing_imports_and_finishes_an_integration_plan(self):
        self.assert_retired_landing(active=False, landing="integration")

    def test_retired_landing_keeps_an_existing_finish(self):
        directory = self.retired_fabrig()
        self.append(dict(ev="branch.landed", task="calls/retire-last", branch="calls/retire-last",
                         queue_ts="010", tip="ready-tip", main="main"),
                    dict(ev="call.finished", call="retire-last", role="retire", outcome="done",
                         tip="checked-tip"))
        before = log.read()
        self.assertEqual(self.tick(directory), [])
        self.assertEqual(log.read(), before)

    def test_fetch_failure_is_shared_by_checkout_and_other_checkout_still_ticks(self):
        one, two, three = (self.plan_dir(draft, tasks=("a",)) for draft in ("one", "two", "three"))
        self.fake = FakeRunner().on(["git", "rev-parse", "--show-toplevel"], lambda call:
            Result(0, str(self.home / ("good" if call.cwd == str(three) else "bad"))))
        self.fake.on(["git", "fetch", "origin"], lambda call:
                     Result(0) if call.cwd.endswith("good") else Result(1, err="fetch\nfailed"))
        actions = self.tick(one, two, three)
        self.assertEqual([(a.kind, a.task) for a in actions],
                         [("load", str(one)), ("load", str(two)), ("flow", "three"), ("start", "three/a")])
        self.assertEqual(self.fake.argvs().count(["git", "fetch", "origin"]), 2)
        self.assertTrue(all("\n" not in a.detail for a in actions))
        self.assertFalse(any(e["ev"] == "note" for e in log.read()))

    def test_own_task_foreman_and_call_review_collect_before_strays_once(self):
        one, two = self.plan_dir("one", tasks=("a",)), self.plan_dir("two", tasks=("a",))
        self.append(run_started("stray/task"), call_started("root-two", "review", "two/review"),
                    run_started("two/a"), run_started("root-two", kind="review"),
                    call_started("root-one", "answer", "one"), run_started("root-one", kind="review"),
                    run_started("one/a"), run_started("one/a/foreman", kind="foreman"))
        actions = self.tick(one, two)
        self.assertEqual([(a.kind, a.task) for a in actions],
                         [("flow", "one"), ("collect", "root-one"), ("collect", "one/a"),
                          ("collect", "one/a/foreman"), ("flow", "two"), ("collect", "two/a"),
                          ("collect", "root-two"), ("collect", "stray/task")])
        self.assertEqual([call.args[0] for call in self.collects.call_args_list],
                         ["root-one-1", "one/a-1", "one/a/foreman-1", "two/a-1", "root-two-1", "stray/task-1"])
        self.assertTrue(self.out.getvalue().splitlines()[-1].startswith("page - "))

    def test_strays_use_fresh_events_after_plan_actions(self):
        one = self.plan_dir("one", tasks=("a",))
        self.append(run_started("one/a"))
        self.collects.side_effect = lambda run_id, *args, **kwargs: (
            self.append(run_started("new/stray")) if run_id == "one/a-1" else None)
        actions = self.tick(one)
        self.assertEqual([a.task for a in actions if a.kind == "collect"], ["one/a", "new/stray"])

    def test_two_fresh_parts_launch_parallel_subject_units(self):
        directory = self.plan_dir("draft", parts={"first": (), "second": ()})
        actions = self.tick(directory)
        self.assertEqual([(a.task, a.run_kind) for a in actions if a.kind == "call"],
                         [("first", "skeleton"), ("second", "skeleton")])
        self.assertEqual(units(self.fake), ["fab-call-skeleton-draft_first", "fab-call-skeleton-draft_second"])

    def test_three_parts_start_two_then_one_while_one_remains_in_flight(self):
        directory = self.plan_dir("draft", parts={"first": (), "second": (), "third": ()})
        self.tick(directory)
        self.assertEqual(len(units(self.fake)), 2)
        self.append(call_started("first-call", "skeleton", "draft/first"),
                    call_ended("first-call"), dict(ev="call.finished", call="first-call", outcome="done"),
                    call_started("second-call", "skeleton", "draft/second"))
        self.fake.calls.clear()
        actions = self.tick(directory)
        self.assertEqual([(a.task, a.run_kind) for a in actions if a.kind == "call"], [("third", "skeleton")])
        self.assertEqual(units(self.fake), [drafts.unit("skeleton", "draft/third")])

    def test_contract_and_skeleton_share_parallel_limit(self):
        directory = self.plan_dir("draft", parts={"api": (), "first": (), "second": ()}, contracts=("api",))
        self.tick(directory)
        self.assertEqual(units(self.fake), [drafts.unit("contract", "draft/api"),
                                           drafts.unit("skeleton", "draft/first")])
        self.append(call_started("api-call", "contract", "draft/api"),
                    call_started("first-call", "skeleton", "draft/first"))
        self.fake.calls.clear()
        self.tick(directory)
        self.assertEqual(units(self.fake), [])

    def test_other_draft_answer_in_flight_does_not_block_answer(self):
        one = self.plan_dir("one", tasks=("a",))
        two = self.plan_dir("two", tasks=("a",))
        self.append(call_started("answer-one", "answer", "one"),
                    dict(ev="question.asked", task="two/a", run="two/a-1", text="Which?",
                         ts="2000-01-01T00:00:00.000Z"))
        actions = self.tick(one, two)
        self.assertEqual([a.task for a in actions if a.run_kind == "answer"], ["two"])
        self.assertIn(drafts.unit("answer", "two"), units(self.fake))

    def test_only_ticks_the_given_plans_and_writes_no_page(self):
        one, two = self.plan_dir("one"), self.plan_dir("two")
        (log.home() / "plans").parent.mkdir(parents=True, exist_ok=True)
        (log.home() / "plans").write_text(f"{one}\n")
        with patch.object(dispatch, "_load_plans", return_value=([], [])) as load, \
                patch.object(dispatch, "_page") as page:
            dispatch.tick(two, sh=self.fake, hosts=self.hosts, only=True)
        self.assertEqual(load.call_args.args[0], [two.resolve()])
        page.assert_not_called()

    def test_failed_plan_task_rejection_is_known_from_ready(self):
        one = self.plan_dir("one", tasks=("a",))
        two = self.plan_dir("two", tasks=("a",))
        write(two / "plan.toml", "invalid [")
        self.append(dict(ev="branch.ready", task="two/a", branch="two/a", tip="tip"))
        self.queue_records = [dict(ev="rejected", ts="001", branch="two/a", tip="tip",
                                   step="default", log="/queue/red.log")]
        actions = self.tick(one, two)
        self.assertEqual(actions[0].kind, "load")
        self.assertFalse(any("queue_ts" in record for record in log.read()))
        self.assertEqual(channel.signals(log.read()), [])
        self.assertIn("## Open signals\n\n(none)", (log.home() / channel.PAGE).read_text())

    def test_retired_plan_task_rejection_is_known_from_started_branch(self):
        directory = self.plan_dir("draft", tasks=("a",))
        path = directory / "plan.toml"
        write(path, "retired = true\n" + path.read_text())
        self.append(run_started("draft/a", branch="hand/from-fab"), run_ended("draft/a"))
        self.queue_records = [dict(ev="rejected", ts="001", branch="hand/from-fab", tip="tip",
                                   step="default", log="/queue/red.log")]
        self.assertEqual(self.tick(directory), [])
        self.assertFalse(any("queue_ts" in record for record in log.read()))
        self.assertEqual(channel.signals(log.read()), [])
        self.assertIn("## Open signals\n\n(none)", (log.home() / channel.PAGE).read_text())
        self.collects.assert_not_called()

    def test_all_failed_plans_task_rejections_are_known_from_started_tasks(self):
        one, two = self.plan_dir("one", tasks=("a",)), self.plan_dir("two", tasks=("a",))
        for directory in (one, two):
            write(directory / "plan.toml", "invalid [")
        for draft in ("one", "two"):
            record = run_started(f"{draft}/a")
            record.pop("branch", None)
            self.append(record, run_ended(f"{draft}/a"))
        self.queue_records = [dict(ev="rejected", ts="001", branch=f"{draft}/a-r2", tip="tip",
                                   step="default", log="/queue/red.log") for draft in ("one", "two")]
        with patch.object(flow, "measure", side_effect=AssertionError("measured")), \
                patch.object(dispatch, "decide", side_effect=AssertionError("decided")):
            actions = self.tick(one, two)
        self.assertEqual([action.kind for action in actions], ["load", "load"])
        self.assertFalse(any("queue_ts" in record for record in log.read()))
        self.assertEqual(channel.signals(log.read()), [])
        self.assertIn("## Open signals\n\n(none)", (log.home() / channel.PAGE).read_text())
        self.collects.assert_not_called()

    def test_failed_fetch_keeps_log_known_branches_out_of_queue_signals(self):
        directory = self.plan_dir("draft", tasks=("a",))
        self.append(run_started("draft/a"), run_ended("draft/a"))
        self.fake.on(["git", "fetch", "origin"], Result(1, err="fetch failed"))
        self.queue_records = [dict(ev="rejected", ts="001", branch=branch, tip="tip",
                                   step="default", log="/queue/red.log") for branch in (
                                       "draft/a", "draft/a-r2", "calls/foreign", "answers/foreign",
                                       "repairs/foreign", "draft/integration")]
        actions = self.tick(directory)
        self.assertEqual([action.kind for action in actions], ["load"])
        self.assertFalse(any("queue_ts" in record for record in log.read()))
        self.assertEqual(channel.signals(log.read()), [])
        self.assertIn("## Open signals\n\n(none)", (log.home() / channel.PAGE).read_text())
        self.collects.assert_not_called()

    def test_no_plan_cursor_uses_newest_import_of_any_kind_then_plan_recovers(self):
        directory = self.plan_dir("draft", tasks=("a",))
        self.append(dict(ev="branch.landed", task="draft/older", branch="draft/older",
                         tip="old", main="old", queue_ts="010"),
                    dict(ev="queue.collateral", branch="hand/pushed", tip="tip", queue_ts="020"),
                    dict(ev="branch.landed", task="other/a", branch="other/a",
                         tip="other", main="other", queue_ts="025"),
                    dict(ev="branch.ready", task="draft/a", branch="draft/a", tip="tip"))
        self.queue_records = [dict(ev="landed", ts="015", branch="draft/a", tip="tip", main="main"),
                              dict(ev="rejected", ts="030", branch="hand/pushed", tip="new",
                                   step="default", tests=[], log="/queue/red.log")]
        self.assertEqual(self.tick(), [])
        self.assertEqual(self.tick(), [])
        self.tick(directory)
        self.assertEqual(self.queries(), [ssh("fake@gate", ["fab", "queue", "log", "--since", stamp])
                                          for stamp in ("025", "030", "010")])
        imported = [record for record in log.read() if record.get("queue_ts") == "015"]
        self.assertEqual([(record["ev"], record["task"]) for record in imported],
                         [("branch.landed", "draft/a")])
        self.assertEqual(len([record for record in log.read() if record["ev"] == "queue.rejected"]), 1)

    def test_unowned_queue_tests_are_strings_even_with_malformed_tests(self):
        values = (None, "pkg::wrong-shape", [None, 3, {}, "pkg::valid"])
        samples = [(kind, tests) for kind in ("rejected", "collateral") for tests in values]
        self.queue_records = [dict(ev=kind, ts=f"00{number}", branch=f"hand/{number}", tip="tip",
                                   step="default", tests=tests, log="/queue/red.log")
                              for number, (kind, tests) in enumerate(samples, 1)]
        self.assertEqual(self.tick(), [])
        self.assertEqual([record["tests"] for record in log.read()],
                         [[], [], ["pkg::valid"]] * 2)
        self.assertEqual(len(channel.signals(log.read())), 3)
        self.assertNotIn("page - failed:", self.out.getvalue())
        self.assertIn("- Tests: pkg::valid", (log.home() / channel.PAGE).read_text())

    def test_unowned_queue_records_import_once_without_advancing_the_task_cursor(self):
        directory = self.plan_dir("draft", tasks=("a",))
        self.append(dict(ev="branch.landed", task="draft/a", branch="draft/a", tip="a",
                         main="main", queue_ts="001"))
        self.queue_records = [dict(ev="rejected", ts="002", branch="hand/pushed", tip="tip",
                                   step="default", tests=["pkg::test"], log="/queue/red.log"),
                              dict(ev="collateral", ts="003", branch="hand/pushed", tip="new",
                                   step="fuzzy", tests=["pkg::flake"], log="/queue/flake.log"),
                              dict(ev="landed", ts="004", branch="hand/pushed", tip="new", main="merged")]
        self.queue_records.append(self.queue_records[0])
        self.tick(directory)
        first = log.read()
        self.tick(directory)
        imported = [record for record in first if record["ev"].startswith("queue.")]
        self.assertEqual([record["ev"] for record in imported],
                         ["queue.rejected", "queue.collateral", "queue.landed"])
        self.assertEqual([record["queue_ts"] for record in imported], ["002", "003", "004"])
        self.assertEqual(imported[0]["tests"], ["pkg::test"])
        self.assertEqual(imported[1]["tests"], ["pkg::flake"])
        self.assertEqual(imported[2]["main"], "merged")
        self.assertTrue(all("task" not in record for record in imported))
        self.assertEqual([record["gate"] for record in imported], ["gate"] * 3)
        self.assertEqual(log.read(), first)
        self.assertEqual(self.queries(), [ssh("fake@gate", ["fab", "queue", "log", "--since", "001"])] * 2)

    def test_task_rejection_and_fab_branches_never_open_queue_signals(self):
        directory = self.plan_dir("draft", tasks=("a",))
        self.queue_records = [dict(ev="rejected", ts="001", branch=branch, tip="tip",
                                   step="default", log="/queue/red.log") for branch in (
                                       "draft/a-r2", "calls/foreign", "answers/foreign",
                                       "repairs/foreign", "draft/integration", "foreign/integration")]
        self.tick(directory)
        imported = [record for record in log.read() if "queue_ts" in record]
        self.assertEqual([(record["ev"], record["task"]) for record in imported],
                         [("branch.rejected", "draft/a"), ("branch.rejected", "draft/integration")])
        self.assertEqual(channel.signals(log.read()), [])

    def test_unowned_queue_rejection_imports_without_plans_and_old_records_have_no_tests(self):
        self.queue_records = [dict(ev="rejected", ts="001", branch="hand/pushed", tip="tip",
                                   step="default", log="/queue/red.log")]
        self.assertEqual(self.tick(), [])
        self.assertEqual(self.tick(), [])
        self.assertEqual(len(log.read()), 1)
        record = log.read()[0]
        self.assertEqual((record["ev"], record["branch"], record["tests"]),
                         ("queue.rejected", "hand/pushed", []))
        self.assertEqual(self.queries(), [ssh("fake@gate", ["fab", "queue", "log", "--since", stamp])
                                          for stamp in ("", "001")])
        self.assertTrue((log.home() / channel.PAGE).exists())
        self.assertEqual(len(channel.signals(log.read())), 1)
        page = (log.home() / channel.PAGE).read_text()
        for fact in ("### queue:hand/pushed,", "- Tip: `tip`", "- Step: `default`",
                     "- Tests: (see the log)", "- Read: `gate:/queue/red.log`",
                     "- Clear: `fab page clear queue:hand/pushed TEXT`"):
            self.assertIn(fact, page)

    def test_unowned_queue_rejection_page_updates_for_new_tip_and_landing(self):
        first = dict(ev="rejected", ts="001", branch="hand/pushed", tip="first",
                     step="default", tests=["pkg::first"], log="/queue/first.log")
        self.queue_records = [first]
        self.tick()
        page = (log.home() / channel.PAGE).read_text()
        self.assertIn("- Tests: pkg::first", page)
        self.assertIn("- Read: `gate:/queue/first.log`", page)
        self.queue_records.append(dict(first, ts="002", tip="second", tests=["pkg::second"]))
        self.tick()
        page = (log.home() / channel.PAGE).read_text()
        self.assertEqual(page.count("### queue:hand/pushed,"), 1)
        self.assertIn("- Tip: `second`", page)
        self.assertIn("- Tests: pkg::second", page)
        self.assertNotIn("pkg::first", page)
        self.queue_records.append(dict(ev="landed", ts="003", branch="hand/pushed",
                                       tip="second", main="merged"))
        self.tick()
        self.assertIn("## Open signals\n\n(none)", (log.home() / channel.PAGE).read_text())

    def test_main_two_directories_and_no_plans(self):
        one, two = self.plan_dir("one"), self.plan_dir("two")
        with patch.object(dispatch, "tick", return_value=[]) as tick:
            self.assertEqual(dispatch.main([str(one), str(two)]), 0)
        tick.assert_called_once_with(one, two, trigger="hand", only=False)
        with patch.object(dispatch, "tick", return_value=[]) as tick:
            self.assertEqual(dispatch.main(["--only", str(one)]), 0)
        tick.assert_called_once_with(one, trigger="hand", only=True)
        self.assertEqual(self.tick(), [])
        self.assertEqual(self.out.getvalue(), f"plans - none\npage - {log.home() / channel.PAGE}\n")
        self.assertEqual(self.queries(), [ssh("fake@gate", ["fab", "queue", "log", "--since", ""])])
        self.assertEqual(len(self.fake.calls), 1)
        self.assertFalse(wake.want_path().exists())

    def test_dry_run_continues_after_failed_load_and_returns_one(self):
        one, two = self.plan_dir("one"), self.plan_dir("two", tasks=("a",))
        write(one / "plan.toml", "invalid [")
        with patch.object(dispatch, "run", side_effect=AssertionError("command ran")), \
             patch("fab.hosts.load", return_value=self.hosts):
            self.assertEqual(dispatch.main([str(one), str(two), "--dry-run"]), 1)
        lines = self.out.getvalue().splitlines()
        self.assertTrue(lines[0].startswith(f"load {one} failed: "))
        self.assertEqual(lines[1:], ["flow two target 1, 0 in flight", "start two/a implement builder"])
        self.assertFalse(log.home().exists())
        self.starts.assert_not_called()

    def test_dry_run_includes_red_tasks_in_both_landing_modes(self):
        from fab.tests.test_tier_reds import repair_events
        for landing in ("queue", "integration"):
            with self.subTest(landing=landing):
                directory = self.plan_dir("demo", tasks=("a",), repo="fabrig")
                path = directory / "plan.toml"
                write(path, path.read_text().replace('landing = "queue"', f'landing = "{landing}"'))
                events = repair_events()
                with patch.object(dispatch, "run", side_effect=AssertionError("command ran")), \
                     patch.object(log, "read", return_value=events), \
                     patch("fab.hosts.load", return_value=self.hosts), \
                     patch.object(dispatch, "decide", wraps=dispatch.decide) as decide:
                    self.assertEqual(dispatch.main([str(directory), "--dry-run"]), 0)
                self.assertEqual(decide.call_args.args[1]["demo/red-1"].kind, "red")
                self.assertIn("start demo/red-1 implement builder", self.out.getvalue())
                self.out.seek(0)
                self.out.truncate()
                self.assertFalse(log.home().exists())

    def test_dry_run_uses_same_events_for_both_plans_without_fetch_or_writes(self):
        one, two = self.plan_dir("one", tasks=("a",)), self.plan_dir("two", tasks=("a",))
        designer.enlist(one)
        self.append(run_started("old/task"), run_ended("old/task"))
        before = log.read()
        with patch.object(dispatch, "run", side_effect=AssertionError("command ran")), \
             patch.object(flow, "measure", side_effect=AssertionError("measured")), \
             patch("fab.hosts.load", return_value=self.hosts), \
             patch.object(dispatch, "decide", wraps=dispatch.decide) as decide:
            self.assertEqual(dispatch.main([str(one), str(two), "--dry-run"]), 0)
        self.assertEqual(self.out.getvalue().splitlines(),
                         ["flow one target 1, 0 in flight", "start one/a implement builder",
                          "flow two target 1, 0 in flight", "start two/a implement builder"])
        self.assertEqual([call.args[2] for call in decide.call_args_list], [before, before])
        self.assertTrue(all(len(call.args) == 4 for call in decide.call_args_list))
        self.assertEqual(log.read(), before)
        self.assertFalse((log.home() / "tick.lock").exists())
        self.assertFalse((log.home() / channel.PAGE).exists())
        self.starts.assert_not_called()


class BlockingTest(unittest.TestCase):
    def setUp(self):
        self.tasks = {t.id: t for t in (task("a"), task("b", needs=("draft/a",)), task("c"))}
        self.asked = event("question.asked", "a", text="Which?")

    def test_a_question_on_a_task_others_need_blocks_at_once(self):
        busy = started("c")
        self.assertTrue(dispatch.blocking(self.tasks, [busy, self.asked], [self.asked]))

    def test_a_question_nobody_waits_on_does_not_block_while_work_moves(self):
        tasks = {k: v for k, v in self.tasks.items() if k != "draft/b"}
        moving = [started("c"), self.asked]
        self.assertFalse(dispatch.blocking(tasks, moving, [self.asked]))
        self.assertFalse(dispatch.blocking(tasks, [self.asked], [self.asked], design=["next"]))
        self.assertFalse(dispatch.blocking(tasks, [self.asked], [self.asked], calls_in_flight=True))

    def test_nothing_moving_while_work_remains_blocks(self):
        tasks = {"draft/a": self.tasks["draft/a"]}
        self.assertTrue(dispatch.blocking(tasks, [self.asked], [self.asked]))

    def test_draft_counts_only_owned_runs_as_moving(self):
        tasks = {"draft/a": self.tasks["draft/a"]}
        foreign = run_started("other/task")
        events = [foreign, self.asked]
        self.assertFalse(dispatch.blocking(tasks, events, [self.asked]))
        self.assertTrue(dispatch.blocking(tasks, events, [self.asked], draft="draft"))
        own = [call_started("own", "answer", "draft"), run_started("own", kind="review")]
        self.assertFalse(dispatch.blocking(tasks, events + own, [self.asked], draft="draft"))
        other = [call_started("other", "answer", "other"), run_started("other", kind="review")]
        self.assertTrue(dispatch.blocking(tasks, events + other, [self.asked], draft="draft"))



class RebaseRunsTest(unittest.TestCase):
    def test_rebase_runs_do_not_count_toward_max_runs(self):
        spec = make_plan(part("core"))
        hosts = {"builder": Host("builder", "fake@builder", ("builder",), places=2)}
        events = []
        for n in range(1, dispatch.MAX_RUNS + 1):
            kind = "implement" if n == 1 else "rebase"
            events += [dict(started("a", n), kind=kind), ended("a", n)]
        events.append(event("branch.rejected", "a", step="rebase", tip="t", log="conflict"))
        actions = dispatch.decide(spec, {"draft/a": task("a")}, events, hosts)
        self.assertNotIn("park", [action.kind for action in actions])


class AnsweredRefusalTest(unittest.TestCase):
    def test_a_refused_task_answered_after_parking_still_rebases(self):
        spec = make_plan(part("core"))
        hosts = {"builder": Host("builder", "fake@builder", ("builder",), places=2)}
        events = [started("a"), ended("a"),
                  event("branch.rejected", "a", step="rebase", tip="t", log="conflict"),
                  event("question.asked", "a", text="4 runs"), event("question.answered", "a", answer="go")]
        (start,) = [a for a in dispatch.decide(spec, {"draft/a": task("a")}, events, hosts) if a.kind == "start"]
        self.assertEqual(start.run_kind, "rebase")


class RepairTickTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.directory = write_plan(self.home / "plan", "draft", tasks=("task",))
        self.path = self.home / "events.jsonl"
        self.hosts = {"builder": Host("builder", "fake@builder", ("builder",), places=2),
                      "gate": Host("gate", "fake@gate", ("gate",))}
        self.fake = FakeRunner().on(["git", "rev-parse", "--show-toplevel"],
                                    Result(0, str(self.home) + "\n"))
        self.fake.on(["ssh"], self.remote)
        self.land = self.enterContext(patch.object(dispatch.land, "main", return_value=0))
        self.collect = self.enterContext(patch.object(runs, "collect"))
        self.screen = self.enterContext(patch.object(gates, "screen", return_value=[]))
        self.rust_screen = self.enterContext(patch.object(rust_gates, "screen", return_value=[]))
        self.examine = self.enterContext(patch.object(repairs, "start", side_effect=self.start_foreman))
        self.commit = self.enterContext(patch.object(repairs, "commit", return_value="repairs/foreman"))
        self.out = io.StringIO()
        self.enterContext(redirect_stdout(self.out))

    def remote(self, call):
        """Answer launch commands without running a remote service."""
        argv = shlex.split(shlex.split(call.argv[-1])[2])
        return Result(0, "codex-1 /state/codex-1\n") if argv[:3] == ["fab", "codex", "start"] else Result(0)

    def append(self, *events):
        for entry in events:
            log.append(path=self.path, **entry)

    def start_foreman(self, refusal, task, host, events, **kwargs):
        self.append(dict(foreman_run("04")[0], task=task.id + "/foreman",
                         run=task.id + "/foreman-1", host=host.name, step=refusal.step))

    def tick(self, *, hosts=None):
        return [action for action in dispatch.tick(self.directory, sh=self.fake,
                                                   hosts=self.hosts if hosts is None else hosts,
                                                   log_path=self.path) if action.kind != "flow"]

    def decided(self, text=None):
        self.append(*refusal_history(status="decided"))
        if text is not None:
            write(log.home() / "runs/draft/task/foreman-1/report.md", text)
        return repairs.refusals(plan.load(self.directory)[1], log.read(self.path))[0]

    def test_gate_refusal_starts_foreman_in_same_tick_on_freest_builder_even_full(self):
        for capacity, expected in ((3, "a"), (4, "a"), (5, "z"), (0, "a")):
            with self.subTest(capacity=capacity):
                self.path = self.home / f"capacity-{capacity}.jsonl"
                self.append(*refusal_history()[:2],
                            dict(ev="run.started", task="other/a", run="other/a-1", host="z"),
                            dict(ev="run.started", task="other/b", run="other/b-1", host="z"))
                hosts = {"z": Host("z", "fake@z", ("builder",), places=capacity),
                         "a": Host("a", "fake@a", ("builder",), places=min(2, capacity)),
                         "gate": self.hosts["gate"]}

                def refuse(task, events, **kwargs):
                    self.append(rejected("03", step="gate:names", findings="banned word"))
                    return [gates.Finding("names", "banned word")]

                self.screen.side_effect = refuse
                self.examine.reset_mock()
                actions = self.tick(hosts=hosts)
                self.assertEqual([action.kind for action in actions], ["land", "examine", "collect", "collect"])
                args = self.examine.call_args.args
                self.assertEqual((args[0].step, args[0].findings, args[2]),
                                 ("gate:names", "banned word", hosts[expected]))
                self.assertEqual(args[3][-1]["ev"], "branch.rejected")
                self.assertEqual(self.examine.call_args.kwargs, dict(sh=self.fake, log_path=self.path, trunk="main"))
                self.assertIn(f"examine draft/task gate:names {expected}\n", self.out.getvalue())
                self.assertFalse(any(entry.get("kind") == "repair" for entry in log.read(self.path)))
        self.land.assert_not_called()
        self.assertEqual(log.read(), [])

    def test_fix_lands_spec_then_next_tick_starts_with_section_in_brief(self):
        refusal = self.decided(report("fix", "Repair the check.", "Keep  spaces."))
        now = "2026-10-31T23:59:00.000Z"
        text = repairs.section(refusal, day=now[:10], run_id=refusal.foreman,
                               body="Repair the check.\nKeep  spaces.")

        def landing(argv):
            self.assertFalse(any(entry["ev"] == "refusal.settled" for entry in log.read(self.path)))
            return 0

        self.land.side_effect = landing
        with patch.object(log, "now", return_value=now):
            self.assertEqual([action.kind for action in self.tick()], ["remedy"])
        tasks = plan.load(self.directory)[1]
        self.commit.assert_called_once_with(refusal, tasks[REPAIR_TASK.id], text, self.home,
                                            run_id=refusal.foreman, sh=self.fake, trunk="main")
        self.land.assert_called_once_with(["repairs/foreman"])
        self.assertEqual(log.read(self.path)[-1], dict(ts=now, ev="refusal.settled", task=REPAIR_TASK.id,
                                                     run=refusal.foreman, verdict="fix", reason="Repair the check.",
                                                     branch="repairs/foreman", section=text))
        self.assertIn("remedy draft/task fix Repair the check.\n", self.out.getvalue())
        self.assertEqual([action.kind for action in self.tick()], ["start"])
        brief = (log.home() / "runs/draft/task-2/brief.md").read_text()
        self.assertIn(text + "\n## The landing refused this branch", brief)
        self.assertEqual(log.read(self.path)[-1]["kind"], "repair")
        self.assertEqual(log.read(), [])

    def test_already_committed_fix_settles_without_landing(self):
        self.decided(report("fix", "Repair it."))
        self.commit.return_value = None
        self.assertEqual([action.kind for action in self.tick()], ["remedy"])
        self.land.assert_not_called()
        entry = log.read(self.path)[-1]
        self.assertEqual((entry["ev"], entry["verdict"], entry["branch"]), ("refusal.settled", "fix", ""))
        self.assertIn("Repair it.", entry["section"])

    def test_refused_spec_landing_is_noted_and_remedied_again(self):
        self.decided(report("fix", "Repair it."))
        self.land.return_value = 1
        self.assertEqual([action.kind for action in self.tick()], ["remedy"])
        self.assertEqual(log.read(self.path)[-1]["text"], "remedy draft/task failed: landing refused")
        self.assertFalse(any(entry["ev"] == "refusal.settled" for entry in log.read(self.path)))
        self.assertEqual(repairs.refusals(plan.load(self.directory)[1], log.read(self.path))[0].state, "decided")
        self.land.return_value = 0
        self.assertEqual([action.kind for action in self.tick()], ["remedy"])
        self.assertEqual(self.commit.call_count, 2)
        self.assertEqual(self.land.call_count, 2)
        self.assertEqual(log.read(self.path)[-1]["ev"], "refusal.settled")

    def test_fabrig_fix_section_waits_for_queue_landing_without_committing_twice(self):
        write_plan(self.directory, "draft", tasks=("task",), repo="fabrig")
        self.decided(report("fix", "Repair it."))
        branch = "repairs/draft/task/foreman-1"
        self.commit.return_value = branch
        self.fake.rules.insert(0, (["git", "rev-parse", "--verify"], Result(0, "section-tip\n")))
        with patch.object(log, "now", return_value="2026-10-31T23:59:00.000Z"):
            self.tick()
        ready = log.read(self.path)[-1]
        self.assertEqual((ready["ev"], ready["task"], ready["branch"]), ("branch.ready", branch, branch))
        _, tasks = plan.load(self.directory)
        self.assertEqual(repairs.refusals(tasks, log.read(self.path))[0].state, "decided")
        self.assertFalse(any(event["ev"] == "refusal.settled" for event in log.read(self.path)))
        with patch.object(log, "now", return_value="2026-11-01T00:01:00.000Z"):
            self.tick()
            self.commit.assert_called_once()
            record = dict(ev="landed", ts="001", branch=branch, tip="section-tip", main="main")
            prefix = ssh("fake@gate", ["fab", "queue", "log"])[:-1]
            self.fake.rules.insert(0, (prefix, Result(0, json.dumps(record))))
            self.tick()
        self.commit.assert_called_once()
        settlement = log.read(self.path)[-1]
        self.assertEqual((settlement["ev"], settlement["verdict"], settlement["branch"]),
                         ("refusal.settled", "fix", branch))
        self.assertEqual(settlement["section"], ready["section"])
        self.assertIn("2026-10-31", settlement["section"])
        self.assertEqual(repairs.refusals(tasks, log.read(self.path))[0].state, "settled")
        with patch.object(runs, "start") as start:
            self.assertEqual([action.kind for action in self.tick()], ["start"])
        self.assertEqual(start.call_args.args[0].repo, "fabrig")
        self.assertEqual(start.call_args.kwargs["rejection"]["section"], ready["section"])
        self.assertEqual(len([event for event in log.read(self.path) if event["ev"] == "refusal.settled"]), 1)
        self.land.assert_not_called()
        self.assertEqual(log.read(), [])

    def test_fabrig_fix_ready_retry_records_the_section_from_its_pushed_spec(self):
        write_plan(self.directory, "draft", tasks=("task",), repo="fabrig")
        refusal = self.decided(report("fix", "Repair it."))
        branch = "repairs/draft/task/foreman-1"
        self.commit.return_value = branch
        section = repairs.section(refusal, day="2026-10-31", run_id=refusal.foreman, body="Repair it.")
        self.fake.rules.insert(0, (["git", "rev-parse", "--verify"], Result(0, "section-tip\n")))
        self.fake.on(["git", "show"], Result(0, "Spec.\n\n" + section + "\n## Later\nOther work.\n"))
        attempts = [Result(1, err="push refused"), Result(0)]
        self.fake.on(["git", "push", "origin"], lambda call: attempts.pop(0))
        with patch.object(log, "now", return_value="2026-10-31T23:59:00.000Z"):
            self.tick()
        self.assertEqual(log.read(self.path)[-1]["ev"], "note")
        with patch.object(log, "now", return_value="2026-11-01T00:01:00.000Z"):
            self.tick()
        ready = log.read(self.path)[-1]
        self.assertEqual(ready["ev"], "branch.ready")
        self.assertEqual(ready["section"], section)
        self.assertFalse(any(event["ev"] == "refusal.settled" for event in log.read(self.path)))
        self.land.assert_not_called()

    def test_retry_settles_and_next_tick_lands_same_branch(self):
        self.decided(report("retry", "A flake."))
        self.assertEqual([action.kind for action in self.tick()], ["remedy"])
        self.commit.assert_not_called()
        self.land.assert_not_called()
        entry = log.read(self.path)[-1]
        self.assertEqual((entry["verdict"], entry["reason"], entry["branch"], entry["section"]),
                         ("retry", "A flake.", "", ""))
        self.assertEqual([action.kind for action in self.tick()], ["land"])
        self.land.assert_called_once_with([REPAIR_TASK.id, "--task", REPAIR_TASK.id])

    def test_retry_readies_same_fabrig_tip_with_untry_before_push(self):
        write_plan(self.directory, "draft", tasks=("task",), repo="fabrig")
        self.decided(report("retry", "A flake."))
        self.fake.rules.insert(0, (["git", "rev-parse", "--verify"], Result(0, "tip1\n")))
        self.assertEqual([action.kind for action in self.tick()], ["remedy"])
        self.assertEqual([action.kind for action in self.tick()], ["ready"])
        commands = self.fake.argvs()
        untry = ssh("fake@gate", ["fab", "queue", "untry", REPAIR_TASK.id])
        push = ["git", "push", "origin", f"tip1:refs/heads/ready/{REPAIR_TASK.id}"]
        self.assertLess(commands.index(untry), commands.index(push))
        self.assertEqual(log.read(self.path)[-1]["tip"], "tip1")
        self.land.assert_not_called()
        self.commit.assert_not_called()

    def test_none_or_unreadable_report_starts_with_refusal_alone_next_tick(self):
        for form in ("invalid", "missing", "directory", "encoding"):
            with self.subTest(form=form):
                self.path = self.home / f"none-{form}.jsonl"
                self.decided("Done: cannot choose\n" if form == "invalid" else None)
                report_path = log.home() / "runs/draft/task/foreman-1/report.md"
                if report_path.is_dir():
                    report_path.rmdir()
                elif form != "invalid":
                    report_path.unlink(missing_ok=True)
                if form == "directory":
                    report_path.mkdir()
                if form == "encoding":
                    sibling = report_path.with_name("report.md.new")
                    sibling.write_bytes(b"\xff")
                    sibling.replace(report_path)
                self.assertEqual([action.kind for action in self.tick()], ["remedy"])
                entry = log.read(self.path)[-1]
                self.assertEqual((entry["verdict"], entry["branch"], entry["section"]), ("none", "", ""))
                actions = self.tick()
                self.assertEqual([action.kind for action in actions], ["start"])
                rejection = next(entry for entry in log.read(self.path) if entry["ev"] == "branch.rejected")
                self.assertEqual(actions[0].rejection, rejection)
                brief = (log.home() / "runs/draft/task-2/brief.md").read_text()
                self.assertIn("## The landing refused this branch", brief)
                self.assertNotIn("## Repair", brief)
        self.commit.assert_not_called()
        self.land.assert_not_called()

    def test_failed_commit_or_checkout_never_settles(self):
        for failure in ("commit", "checkout", "empty"):
            with self.subTest(failure=failure):
                self.path = self.home / f"failed-{failure}.jsonl"
                self.decided(report("fix", "Repair it."))
                self.commit.reset_mock()
                if failure == "commit":
                    self.commit.side_effect = RuntimeError("cannot commit")
                else:
                    self.fake.rules[0] = (["git", "rev-parse", "--show-toplevel"],
                                          Result(128 if failure == "checkout" else 0))
                self.assertEqual([action.kind for action in self.tick()], ["remedy"])
                self.assertFalse(any(entry["ev"] == "refusal.settled" for entry in log.read(self.path)))
                self.assertEqual(log.read(self.path)[-1]["ev"], "note")
                self.assertEqual(self.commit.call_count, int(failure == "commit"))
        self.land.assert_not_called()

    def test_stale_refusal_or_foreman_is_recomputed_before_acting(self):
        for status in ("foreman", "decided", "other foreman"):
            with self.subTest(status=status):
                self.path = self.home / f"stale-{status}.jsonl"
                self.append(*refusal_history(status="foreman" if status == "foreman" else "decided"))
                decide_repairs = dispatch.repair_actions

                def stale(tasks, events):
                    actions = decide_repairs(tasks, events)
                    if status == "other foreman":
                        self.append(*foreman_run("06", run_id="draft/task/foreman-2", outcome="done", ended="07"))
                    else:
                        self.append(dict(task_run("06", n=2), host="builder"))
                    return actions

                with patch.object(dispatch, "repair_actions", side_effect=stale):
                    self.tick()
                self.assertIn("refusal for draft/task", log.read(self.path)[-1]["text"])
        self.examine.assert_not_called()
        self.commit.assert_not_called()
        self.land.assert_not_called()

    def test_question_then_refusal_actions_share_snapshot_before_fresh_call_decisions(self):
        write_plan(self.directory, "draft", tasks=("task", "a"))
        self.decided(report("fix", "Repair it."))
        self.append(*question_history("a"))
        order = []

        def question(*args, **kwargs):
            order.append("foreman")
            self.append(dict(ev="note", text="foreman started"))

        def commit(*args, **kwargs):
            order.append("remedy")
            return None

        def calls(plan, tasks, events, *args):
            order.append("calls")
            self.assertIn("refusal.settled", [entry["ev"] for entry in events])
            self.assertIn("foreman started", [entry.get("text") for entry in events])
            return []

        with patch.object(foreman, "start", side_effect=question), \
             patch.object(dispatch, "foreman_actions", wraps=dispatch.foreman_actions) as questions, \
             patch.object(dispatch, "repair_actions", wraps=dispatch.repair_actions) as refusals, \
             patch.object(dispatch, "call_actions", side_effect=calls):
            self.commit.side_effect = commit
            self.assertEqual([action.kind for action in self.tick()], ["foreman", "remedy"])
        self.assertEqual(order, ["foreman", "remedy", "calls"])
        self.assertIs(questions.call_args.args[1], refusals.call_args.args[1])
        self.assertNotIn("foreman started", [entry.get("text") for entry in refusals.call_args.args[1]])


class OptimisticStartTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.checkout = self.home / "checkout"
        self.directory = write_plan(self.checkout / "docs/plan/draft", "draft")
        self.path = self.home / "events.jsonl"
        self.hosts = {"builder": Host("builder", "fake@builder", ("builder",), places=4)}
        self.spec = '+++\nid = "a"\npart = "core"\nkind = "feature"\nfiles = ["fab/x.py"]\n+++\nBuild it.\n'
        self.green = True
        self.fake = FakeRunner().on(["git", "rev-parse", "--show-toplevel"], Result(0, str(self.checkout)))
        self.fake.on(["git", "rev-parse", "--verify"], Result(0, "skeleton-tip\n"))
        self.fake.on(["git", "ls-tree"], Result(0, "docs/plan/draft/tasks/a.md\n"))
        self.fake.on(["git", "show"], Result(0, self.spec))
        self.fake.on(["ssh"], self.remote)
        self.fake.on([], lambda call: Result(0 if self.green or not call.argv[0].endswith("/bin/fab") else 1))
        self.screen = self.enterContext(patch.object(gates, "screen", return_value=[]))
        self.rust_screen = self.enterContext(patch.object(rust_gates, "screen", return_value=[]))
        self.land = self.enterContext(patch.object(dispatch.land, "main", return_value=0))
        self.enterContext(patch.object(runs, "collect"))
        self.vet = self.enterContext(patch.object(call_review, "start", side_effect=self.review))
        self.enterContext(redirect_stdout(io.StringIO()))

    def remote(self, call):
        argv = shlex.split(shlex.split(call.argv[-1])[2])
        if argv[3:6] == ["rev-parse", "-q", "--verify"]:
            return Result(1)
        if argv[:3] == ["fab", "slot", "list"]:
            return Result(0, 'torn\n[]\n{"slot": 1, "claim": null, "idle": 0}\n')
        if argv[:3] == ["fab", "codex", "start"]:
            return Result(0, "codex-1 /state/codex-1\n")
        if "diff" in argv:
            return Result(0, "+amended skeleton\n")
        return Result(0)

    def review(self, chain, repo, checkout, host, events, **kwargs):
        log.append("run.started", path=self.path, task=chain.root, run=chain.root + "-1",
                   kind="review", host=host.name, call=chain.latest, tip="skeleton-tip")

    def append(self, *events):
        for entry in events:
            log.append(path=self.path, **entry)

    def tick(self):
        return [action for action in dispatch.tick(self.directory, hosts=self.hosts,
                                                   sh=self.fake, log_path=self.path) if action.kind != "flow"]

    def checked(self, *, repo="agents", role="skeleton"):
        write_plan(self.directory, "draft", repo=repo)
        self.append(*chain_history("review", role=role))
        self.tick()
        return next(event for event in log.read(self.path) if event["ev"] == "call.checked")

    def task_done(self):
        self.tick()
        self.append(ended())

    def test_green_tip_starts_before_review_ends_and_specs_count_for_status_needs_and_buffer(self):
        checked = self.checked()
        self.assertEqual((checked["tip"], checked["outcome"], checked["tasks"]),
                         ("skeleton-tip", "green", ["draft/a"]))
        self.assertFalse((self.directory / "tasks/a.md").exists())
        self.assertEqual(wake.want_path(self.path).read_text(), "call.checked root\n")
        self.assertFalse(wake.want_path().exists())
        self.assertEqual([action.kind for action in self.tick()], ["collect", "start"])
        first = next(event for event in log.read(self.path) if event.get("task") == "draft/a")
        self.assertEqual((first["ev"], first["base"]), ("run.started", "skeleton-tip"))
        launch = [call.argv[-1] for call in self.fake.calls if call.argv[0] == "ssh"]
        self.assertTrue(any("worktree add -B draft/a" in command and command.endswith("skeleton-tip'")
                            for command in launch))
        spec, tasks = dispatch._load_plan(self.directory, log.read(self.path), checkout=self.checkout, sh=self.fake)
        self.assertEqual(state.part_statuses(spec, tasks, {}), {"core": "designed"})
        self.assertEqual(state.fold(tasks, log.read(self.path))["draft/a"].status, "running")
        self.assertFalse(any(event["ev"] == "run.ended" for event in log.read(self.path)))
        self.tick()
        self.assertEqual(sum(event["ev"] == "call.checked" for event in log.read(self.path)), 1)
        self.assertEqual(sum(call.argv[0].endswith("/bin/fab") for call in self.fake.calls), 1)
        commands = self.fake.argvs()
        add = next(command for command in commands if command[:3] == ["git", "worktree", "add"])
        self.assertEqual(add[3], "--detach")
        self.assertIn(["git", "worktree", "remove", "--force", add[4]], commands)
        self.assertEqual(log.read(), [])

    def test_red_tests_or_gates_start_nothing_and_still_review(self):
        for failure in ("tests", "gates"):
            with self.subTest(failure=failure):
                self.path = self.home / (failure + ".jsonl")
                self.green = failure != "tests"
                self.screen.return_value = [gates.Finding("names", "banned")] if failure == "gates" else []
                checked = self.checked()
                self.assertEqual((checked["outcome"], checked["tasks"]), ("red", []))
                self.assertFalse(any(action.kind == "start" for action in self.tick()))
                self.assertEqual(call_review.chains(log.read(self.path))["root"].state, "reviewing")
                self.land.assert_not_called()

    def test_done_task_holds_landing_until_same_tip_skeleton_lands(self):
        self.checked()
        self.task_done()
        self.assertFalse(any(action.kind == "land" for action in self.tick()))
        self.land.assert_not_called()
        self.append(dict(ev="call.finished", call="root", outcome="done", tip="skeleton-tip"))
        self.assertIn("land", [action.kind for action in self.tick()])
        self.land.assert_called_once_with(["draft/a", "--task", "draft/a"])

    def test_integration_task_holds_merge_until_checked_skeleton_finishes(self):
        self.checked()
        self.task_done()
        the_plan, tasks = dispatch._load_plan(self.directory, log.read(self.path))
        the_plan = replace(the_plan, landing="integration")
        actions = dispatch.decide(the_plan, tasks, log.read(self.path), {})
        self.assertFalse(any(action.kind == "merge" for action in actions))
        self.append(dict(ev="call.finished", call="root", outcome="done", tip="skeleton-tip"))
        actions = dispatch.decide(the_plan, tasks, log.read(self.path), {})
        self.assertEqual([action for action in actions if action.kind == "merge"],
                         [Action("merge", task="draft/a", branch="draft/a", detail="draft/a")])

    def test_amended_skeleton_requires_rebase_with_its_diff_then_lands(self):
        self.checked()
        self.task_done()
        self.append(dict(ev="call.started", call="amend", role="amend", amends="root"),
                    dict(ev="call.ended", call="amend", outcome="done"),
                    dict(ev="call.finished", call="amend", outcome="done", tip="amended-tip"))
        actions = self.tick()
        start = next(action for action in actions if action.kind == "start")
        self.assertEqual(start.run_kind, "rebase")
        self.land.assert_not_called()
        entry = log.read(self.path)[-1]
        self.assertEqual((entry["kind"], entry["base"], entry["branch"]),
                         ("rebase", "origin/main", "draft/a-r1"))
        brief = (log.home() / "runs/draft/a-2/brief.md").read_text()
        self.assertIn("+amended skeleton", brief)
        self.assertIn("git reset --hard origin/draft/a", brief)
        self.assertIn("git rebase --onto origin/main skeleton-tip", brief)
        self.append(ended(n=2))
        self.assertIn("land", [action.kind for action in self.tick()])
        self.land.assert_called_once_with(["draft/a-r1", "--task", "draft/a"])

    def test_integration_amendment_rebase_consumed_before_merge(self):
        the_plan = replace(make_plan(part("core")), landing="integration")
        tasks = {"draft/a": task("a")}
        events = [*chain_history("review"),
                  dict(ev="call.checked", call="root", root="root", subject="draft/core",
                       tip="skeleton-tip", outcome="green", tasks=["draft/a"]),
                  dict(started(), kind="implement", base="skeleton-tip"), ended(),
                  dict(ev="call.started", call="amend", role="amend", amends="root"),
                  dict(ev="call.ended", call="amend", outcome="done"),
                  dict(ev="call.finished", call="amend", outcome="done", tip="amended-tip")]
        for base in ("origin/main", f"origin/{the_plan.trunk}"):
            with self.subTest(base=base):
                rebased = [*events, dict(started(n=2, branch="draft/a-r1"), kind="rebase", base=base), ended(n=2)]
                actions = dispatch.decide(the_plan, tasks, rebased, self.hosts)
                merges = [action for action in actions if action.kind == "merge"]
                starts = [action for action in actions if action.kind == "start"]
                if base == f"origin/{the_plan.trunk}":
                    self.assertEqual(merges, [Action("merge", task="draft/a", branch="draft/a-r1",
                                                    detail="draft/a-r1")])
                    self.assertEqual(starts, [])
                else:
                    self.assertEqual(merges, [])
                    self.assertEqual([action.run_kind for action in starts], ["rebase"])

    def test_parked_chain_holds_started_tasks_and_resets_after_answer(self):
        self.checked()
        self.task_done()
        self.append(dict(ev="call.parked", call="root", subject="draft/core"))
        self.assertFalse(any(action.kind in ("start", "land", "ready") for action in self.tick()))
        spec, tasks = dispatch._load_plan(self.directory, log.read(self.path), sh=self.fake)
        self.assertEqual(state.fold(tasks, log.read(self.path))["draft/a"].status, "parked")
        self.append(dict(ev=channel.ANSWERED, subject="draft/core"),
                    dict(ev="call.finished", call="root", outcome="done", tip="skeleton-tip"))
        self.assertIn("land", [action.kind for action in self.tick()])

    def test_fabrig_contract_uses_slot_precheck_holds_ready_then_gates_task(self):
        checked = self.checked(repo="fabrig", role="contract")
        self.assertEqual(checked["outcome"], "green")
        self.task_done()
        self.assertFalse(any(action.kind == "ready" for action in self.tick()))
        commands = [shlex.split(shlex.split(call.argv[-1])[2]) for call in self.fake.calls
                    if call.argv[0] == "ssh"]
        self.assertIn(["fab", "precheck", "/home/fake/src/fabrig/slots/1", "skeleton-tip"], commands)
        self.assertIn(["fab", "slot", "release", "1", "checks/root"], commands)
        self.append(dict(ev="call.finished", call="root", outcome="done", tip="skeleton-tip"))
        self.assertIn("ready", [action.kind for action in self.tick()])
        self.assertEqual(log.read(self.path)[-1]["ev"], "branch.ready")
        self.assertEqual(self.rust_screen.call_args.args[0].id, "draft/a")
        self.land.assert_not_called()

    def test_fabrig_ratchet_refusal_is_logged_and_never_readied(self):
        self.checked(repo="fabrig")
        self.task_done()
        self.append(dict(ev="call.finished", call="root", outcome="done", tip="skeleton-tip"))

        def refuse(task, events, **kwargs):
            log.append("branch.rejected", path=kwargs["log_path"], task=task.id,
                       branch="draft/a", tip="task-tip", step="gate:ratchet", findings="count rose", log="digest")
            return [gates.Finding("ratchet", "count rose")]

        self.rust_screen.side_effect = refuse
        self.tick()
        events = log.read(self.path)
        self.assertTrue(any(event["ev"] == "branch.rejected" and event["step"] == "gate:ratchet" for event in events))
        self.assertFalse(any(event["ev"] == "branch.ready" for event in events))
        self.assertFalse(any("refs/heads/ready/" in arg for call in self.fake.calls for arg in call.argv))
        self.land.assert_not_called()


    def test_checks_pin_the_tip_after_review_starts(self):
        def screen(task, events, **kwargs):
            self.assertEqual(call_review.chains(log.read(self.path))["root"].state, "reviewing")
            kwargs["sh"](["git", "rev-parse", "--verify", "refs/remotes/origin/calls/root^{commit}"],
                         cwd=str(self.checkout), check=True)
            return []

        self.screen.side_effect = screen
        self.checked()
        self.assertIn(["git", "rev-parse", "--verify", "skeleton-tip^{commit}"], self.fake.argvs())

    def test_test_command_failure_frees_worktree_and_retries_without_starting_a_task(self):
        attempts = []

        def test(call):
            if call.argv[0].endswith("/bin/fab"):
                attempts.append(call)
                if len(attempts) == 1:
                    raise OSError("test process unavailable")
            return Result(0)

        self.fake.rules[-1] = ([], test)
        self.append(*chain_history("review"))
        self.tick()
        self.assertFalse(any(event["ev"] == "call.checked" for event in log.read(self.path)))
        self.assertFalse(any(event.get("task") == "draft/a" for event in log.read(self.path)))
        self.tick()
        self.assertEqual(len(attempts), 2)
        self.assertEqual(sum(call.argv[:3] == ["git", "worktree", "remove"] for call in self.fake.calls), 2)
        self.assertEqual(sum(event["ev"] == "call.checked" for event in log.read(self.path)), 1)

    def test_red_precheck_releases_its_slot_and_starts_no_task(self):
        command = ssh("fake@builder", ["fab", "precheck", "/home/fake/src/fabrig/slots/1", "skeleton-tip"])
        self.fake.rules.insert(0, (command, Result(1, "red")))
        self.assertEqual(self.checked(repo="fabrig")["outcome"], "red")
        self.tick()
        self.assertFalse(any(event.get("task") == "draft/a" for event in log.read(self.path)))
        self.assertIn(ssh("fake@builder", ["fab", "slot", "release", "1", "checks/root"]), self.fake.argvs())


    def test_approved_skeleton_finish_records_its_checked_tip_before_task_landing(self):
        self.checked()
        self.task_done()
        self.append(dict(ev="run.ended", run="root-1", outcome="done"))
        actions = self.tick()
        self.assertIn("finish", [action.kind for action in actions])
        self.assertNotIn("land", [action.kind for action in actions])
        self.land.assert_called_once_with(["calls/root"])
        finished = next(event for event in log.read(self.path) if event["ev"] == "call.finished")
        self.assertEqual((finished["call"], finished["outcome"], finished["tip"]),
                         ("root", "done", "skeleton-tip"))
        self.assertIn("land", [action.kind for action in self.tick()])


class IntegrationDecideTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(tmp_home())

    def test_rejection_and_infra_keep_integration_starts_at_builders_places(self):
        the_plan = plan.Plan("draft", "agents", (), 1, 2,
                             {"core": replace(part("core"), mode="direct")}, ())
        tasks = {t.id: t for t in (task(name) for name in "abcdefghi")}
        hosts = {"builder": Host("builder", "fake@builder", ("builder",), places=4),
                 "second": Host("second", "fake@second", ("builder",), places=3),
                 "gate": Host("gate", "fake@gate", ("gate",), places=99)}
        histories = [[], [event("branch.rejected", "c", step="test")],
                     [started("c"), ended("c", outcome="infra")]]
        for events in histories:
            with self.subTest(events=events):
                before = deepcopy((the_plan, tasks, events, hosts))
                actions = dispatch.decide(the_plan, tasks, events, hosts)
                self.assertEqual(actions[0], Action("flow", task="draft", detail="target 7, 0 in flight"))
                starts = [action for action in actions if action.kind == "start"]
                self.assertEqual(len(starts), 7)
                self.assertEqual(sum(action.host == "builder" for action in starts), 4)
                self.assertEqual(sum(action.host == "second" for action in starts), 3)
                if events:
                    repair, = [action for action in starts if action.task == "draft/c"]
                    self.assertEqual(repair.run_kind, "repair")
                self.assertEqual((the_plan, tasks, events, hosts), before)

    def test_stop_keeps_runnable_count_for_design_without_starting_tasks(self):
        the_plan = replace(make_plan(part("core"), part("next"), low=0.5), landing="integration")
        tasks = {"draft/a": task("a")}
        events = [event("branch.landed", into=the_plan.trunk, main="trunk-tip", tip="task-tip")]
        for n in range(1, 4):
            events += [run_started("draft/integration", n, kind="check", base="trunk-tip"),
                       run_ended("draft/integration", n, outcome="failed")]
        hosts = {"builder": Host("builder", "fake@builder", ("builder",), places=2)}
        self.assertEqual(integration.next_step(the_plan, tasks, events).kind, "stop")
        self.assertEqual(dispatch.decide(the_plan, tasks, events, hosts),
                         [Action("flow", task="draft", detail="target 2, 0 in flight")])

    def test_clean_landings_do_not_grow_integration_target(self):
        the_plan = plan.Plan("draft", "agents", (), 1, 2,
                             {"core": replace(part("core"), mode="direct")}, ())
        tasks = {t.id: t for t in (task(name) for name in "abcde")}
        hosts = {"builder": Host("builder", "fake@builder", ("builder",), places=2)}
        actions = dispatch.decide(the_plan, tasks, growth(), hosts)
        self.assertEqual(actions[0], Action("flow", task="draft", detail="target 2, 0 in flight"))
        self.assertEqual([action.task for action in actions if action.kind == "start"],
                         ["draft/a", "draft/b"])

    def test_integration_target_is_zero_without_builder_places(self):
        the_plan = plan.Plan("draft", "agents", (), 1, 2, {}, ())
        hosts = {"gate": Host("gate", "fake@gate", ("gate",), places=99)}
        self.assertEqual(dispatch.decide(the_plan, {}, [], hosts),
                         [Action("flow", task="draft", detail="target 0, 0 in flight")])

    def test_done_tasks_merge_only_for_integration_plans(self):
        for repo in ("agents", "fabrig"):
            for landing in ("queue", "integration"):
                with self.subTest(repo=repo, landing=landing):
                    the_plan = replace(make_plan(part("core")), repo=repo, landing=landing)
                    tasks = {"draft/a": task("a", repo=repo)}
                    events = [started(), ended()]
                    before = deepcopy(events)
                    kind = "merge" if landing == "integration" else "land" if repo == "agents" else "ready"
                    self.assertEqual(dispatch.decide(the_plan, tasks, events, {})[1:],
                                     [Action(kind, task="draft/a", branch="draft/a", detail="draft/a")])
                    self.assertEqual(events, before)

    def test_reviews_off_finishes_unreviewed_chains_and_suppresses_structure_calls(self):
        the_plan = replace(make_plan(part("core")), reviews=False)
        tasks = {"draft/a": task("a")}
        events = [*chain_history("review"),
                  event("branch.landed", tip="tip", main="main", ts="2026-10-30T00:00:00.000Z")]
        now = "2026-10-31T12:00:00.000Z"
        self.assertTrue(dispatch._review_due("draft", tasks, events, now))
        self.assertEqual(dispatch.call_actions(the_plan, tasks, events, [], now),
                         [Action("finish", task="root", run="root", branch="calls/root", run_kind="skeleton"),
                          Action("call", task="draft/retire", run_kind="retire")])
        for status in call_review.STATES:
            if status == "review":
                continue
            with self.subTest(status=status):
                chains = call_review.chains(chain_history(status))
                self.assertEqual(dispatch._chain_actions(chains, False, reviews=False),
                                 dispatch._chain_actions(chains, False))


class CheckoutFollowTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.fake = FakeRunner().on(["git", "rev-parse", "--show-toplevel"], Result(0, str(self.home)))
        self.upstream = ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"]
        self.follow = ["git", "merge", "--ff-only", "@{upstream}"]

    def test_follow_after_fetch_before_loading_and_once_per_checkout(self):
        one = write_plan(self.home / "one", "one")
        two = write_plan(self.home / "two", "two")
        self.fake.on(self.upstream, Result(0, "origin/one/integration\n"))

        def advance(call):
            path = one / "plan.toml"
            write(path, path.read_text().replace('landing = "queue"', 'landing = "integration"'))
            return Result(0)

        self.fake.on(self.follow, advance)
        loaded, failures = dispatch._load_plans([one, two], [], sh=self.fake)
        self.assertEqual(failures, [])
        self.assertEqual(loaded[0][0].trunk, "one/integration")
        self.assertEqual(self.fake.argvs()[:4], [["git", "rev-parse", "--show-toplevel"],
                                               ["git", "fetch", "origin"], self.upstream, self.follow])
        self.assertEqual(self.fake.argvs().count(self.follow), 1)
        self.assertEqual(self.fake.argvs().count(["git", "fetch", "origin"]), 1)
        self.assertTrue(all(call.cwd == str(self.home) for call in self.fake.calls[1:4]))

    def test_landed_trunk_detaches_after_each_fetch_before_loading(self):
        one = write_plan(self.home / "one", "one")
        two = write_plan(self.home / "two", "two")
        detach = ["git", "checkout", "-q", "--detach", "origin/main"]
        events = [dict(ev="branch.landed", task="one/integration", queue_ts="001")]
        path = one / "plan.toml"
        write(path, path.read_text().replace('landing = "queue"', 'landing = "integration"'))

        main_plan = "retired = true\n" + path.read_text()

        def advance(call):
            write(path, main_plan)
            return Result(0)

        self.fake.on(detach, advance)
        with redirect_stdout(io.StringIO()):
            loaded, failures = dispatch._load_plans([one, two], events, sh=self.fake)
        self.assertEqual(failures, [])
        self.assertEqual([entry[0].draft for entry in loaded], ["two"])
        self.assertEqual(self.fake.argvs()[:3], [["git", "rev-parse", "--show-toplevel"],
                                               ["git", "fetch", "origin"], detach])
        self.assertEqual(self.fake.argvs().count(detach), 1)
        self.assertNotIn(self.upstream, self.fake.argvs())
        self.assertNotIn(self.follow, self.fake.argvs())
        self.assertEqual(self.fake.calls[2].cwd, str(self.home))
        dispatch._checkout(one, {}, events, sh=self.fake)
        self.assertEqual(self.fake.argvs().count(detach), 2)
        self.assertEqual(self.fake.argvs().count(["git", "fetch", "origin"]), 2)

    def test_load_plans_returns_retired_plans_only_through_the_optional_list(self):
        retired = write_plan(self.home / "retired", "retired")
        active = write_plan(self.home / "active", "active")
        path = retired / "plan.toml"
        write(path, "retired = true\n" + path.read_text())
        skipped = []
        out = io.StringIO()
        with redirect_stdout(out):
            loaded, failures = dispatch._load_plans([retired, active], [], sh=self.fake, retired=skipped)
        self.assertEqual(failures, [])
        self.assertEqual([entry[0].draft for entry in loaded], ["active"])
        self.assertEqual([(entry.draft, entry.retired) for entry in skipped], [("retired", True)])
        self.assertEqual(out.getvalue(), "retired retired\n")
        self.assertEqual(self.fake.argvs().count(["git", "fetch", "origin"]), 1)

    def test_other_landings_still_follow_upstream(self):
        one = write_plan(self.home / "one", "one")
        self.fake.on(self.upstream, Result(0, "origin/one/integration\n"))
        events = [dict(ev="branch.landed", task="two/integration", queue_ts="001"),
                  dict(ev="branch.landed", task="one/a", queue_ts="002"),
                  dict(ev="branch.landed", task="one/integration", into="one/integration")]
        dispatch._checkout(one, {}, events, sh=self.fake)
        self.assertEqual(self.fake.argvs(), [["git", "rev-parse", "--show-toplevel"],
                                           ["git", "fetch", "origin"], self.upstream, self.follow])

    def test_landed_trunk_fetch_or_detach_failure_is_shared(self):
        one = write_plan(self.home / "one", "one")
        two = write_plan(self.home / "two", "two")
        events = [dict(ev="branch.landed", task="one/integration", queue_ts="001")]
        for command in (["git", "fetch", "origin"], ["git", "checkout", "-q", "--detach", "origin/main"]):
            with self.subTest(command=command):
                fake = FakeRunner().on(["git", "rev-parse", "--show-toplevel"], Result(0, str(self.home)))
                fake.on(command, Result(1, err="cannot advance checkout"))
                with redirect_stdout(io.StringIO()):
                    loaded, failures = dispatch._load_plans([one, two], events, sh=fake)
                self.assertEqual(loaded, [])
                self.assertEqual(len(failures), 2)
                self.assertTrue(all("cannot advance checkout" in failure.detail for failure in failures))
                self.assertEqual(fake.argvs().count(["git", "fetch", "origin"]), 1)
                self.assertEqual(fake.argvs().count(command), 1)

    def test_no_upstream_skips_merge(self):
        self.fake.on(self.upstream, Result(128))
        self.assertEqual(dispatch._checkout(self.home, {}, [], sh=self.fake), self.home)
        self.assertNotIn(self.follow, self.fake.argvs())

    def test_failed_fast_forward_is_shared_as_plan_load_failure(self):
        one = write_plan(self.home / "one", "one")
        two = write_plan(self.home / "two", "two")
        self.fake.on(self.follow, Result(1, err="Not possible to fast-forward"))
        with redirect_stdout(io.StringIO()):
            loaded, failures = dispatch._load_plans([one, two], [], sh=self.fake)
        self.assertEqual(loaded, [])
        self.assertEqual(len(failures), 2)
        self.assertTrue(all("Not possible to fast-forward" in failure.detail for failure in failures))
        self.assertEqual(self.fake.argvs().count(self.follow), 1)

    def test_uncut_uses_newest_own_cut_options_or_defaults(self):
        self.fake.on(["git", "remote", "get-url", "origin"], Result(0, runs.REMOTES["agents"]))
        first = call_started("first", "cut", "draft/cut", options=['landing="integration"', 'reviews=false'])
        latest = call_started("latest", "cut", "draft/cut", options=['ready=false'])
        foreign = call_started("foreign", "cut", "other/cut", options=['reviews=false'])
        for events, landing, reviews, ready in (([first, foreign], "integration", False, True),
                                                ([first, latest, foreign], "integration", False, False),
                                                ([call_started("default", "cut", "draft/cut")], "integration", False, True)):
            with self.subTest(events=events):
                the_plan, tasks = dispatch._load_plan(self.home / "draft", events,
                                                      checkout=self.home, sh=self.fake)
                self.assertEqual((the_plan.landing, the_plan.reviews, the_plan.ready), (landing, reviews, ready))
                self.assertEqual(tasks, {})


class IntegrationMergeTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.origin, self.checkout = git_pair(self.home)
        self.plan = replace(make_plan(part("core")), landing="integration", reviews=False)
        self.path = self.home / "events.jsonl"
        git(self.checkout, "switch", "-q", "-c", self.plan.trunk)
        git(self.checkout, "push", "-q", "-u", "origin", self.plan.trunk)
        self.base = git(self.origin, "rev-parse", self.plan.trunk)
        self.runner = FakeRunner().on(["git", "remote", "get-url", "origin"],
                                      Result(0, runs.REMOTES["agents"]))
        self.runner.on(["git"], lambda call: run(call.argv, cwd=call.cwd, env={**os.environ, **GIT_ENV}))
        self.out = io.StringIO()
        self.enterContext(redirect_stdout(self.out))
        self.land = self.enterContext(patch.object(dispatch.land, "main", side_effect=AssertionError("unexpected land")))
        self.queue = self.enterContext(patch.object(dispatch, "_queue_branch", side_effect=AssertionError("unexpected queue")))

    def branch(self, name, filename="feature.txt", text="feature\n"):
        git(self.checkout, "switch", "-q", "-c", name)
        write(self.checkout / filename, text)
        git(self.checkout, "add", filename)
        git(self.checkout, "commit", "-q", "-m", "Add branch content")
        tip = git(self.checkout, "rev-parse", "HEAD")
        git(self.checkout, "push", "-q", "origin", name)
        git(self.checkout, "switch", "-q", self.plan.trunk)
        return tip

    def test_merge_pushes_trunk_and_dependent_starts_from_it(self):
        tip = self.branch("draft/a")
        tasks = {"draft/a": task("a"), "draft/b": task("b", needs=("draft/a",))}
        for entry in (started(), ended()):
            log.append(path=self.path, **entry)
        action, = dispatch.decide(self.plan, tasks, log.read(self.path), {})[1:]
        self.assertNotIn("feature.txt", tasks["draft/a"].files)
        with patch.object(rust_gates, "screen", side_effect=AssertionError("unexpected gate")) as screen:
            dispatch._take(action, tasks, {}, self.checkout, plan=self.plan, checkout=self.checkout,
                           sh=self.runner, log_path=self.path)
        screen.assert_not_called()
        merged = git(self.origin, "rev-parse", self.plan.trunk)
        self.assertNotEqual(merged, self.base)
        self.assertEqual(git(self.origin, "rev-parse", "main"), self.base)
        self.assertEqual(git(self.origin, "rev-list", "--parents", "-n", "1", merged).split(),
                         [merged, self.base, tip])
        landed = log.read(self.path)[-1]
        self.assertEqual({key: value for key, value in landed.items() if key != "ts"},
                         dict(ev="branch.landed", task="draft/a", branch="draft/a", tip=tip,
                              main=merged, into=self.plan.trunk))
        self.assertEqual(state.fold(tasks, log.read(self.path))["draft/b"].status, "runnable")
        hosts = {"builder": Host("builder", "fake@builder", ("builder",), places=1)}
        start, = [action for action in dispatch.decide(self.plan, tasks, log.read(self.path), hosts)
                  if action.kind == "start"]
        fake = FakeRunner().on(["ssh"], Result(0, "codex-1 /state/codex-1\n"))
        dispatch._take(start, tasks, hosts, self.checkout, plan=self.plan, checkout=self.checkout,
                       sh=fake, log_path=self.path)
        record = log.read(self.path)[-1]
        self.assertEqual((record["ev"], record["task"], record["base"]),
                         ("run.started", "draft/b", "origin/draft/integration"))
        count = len(self.runner.calls)
        self.assertTrue(dispatch._merge_branch("draft/a", self.plan, self.checkout,
                                               sh=self.runner, log_path=self.path))
        self.assertEqual(len(self.runner.calls), count)
        self.assertEqual(log.read(), [])

    def test_running_cut_releases_batches_once_and_finishes_with_its_last_push(self):
        """Real git checks ancestry, repeated pushes and the final merge of one call branch."""
        directory = self.checkout / "docs/plan/draft"
        git(self.checkout, "switch", "-q", "-c", "calls/cut")
        write_plan(directory, "draft", parts={"core": (), "later": ()}, tasks=("a",))
        path = directory / "plan.toml"
        write(path, path.read_text().replace('landing = "queue"', 'landing = "integration"')
              .replace('reviews = true', 'reviews = false').replace('direct = false', 'direct = true')
              .replace('mode = "feature"', 'mode = "direct"'))
        git(self.checkout, "add", "docs")
        git(self.checkout, "commit", "-q", "-m", "Release first specs")
        first = git(self.checkout, "rev-parse", "HEAD")
        git(self.checkout, "push", "-q", "origin", "calls/cut")
        git(self.checkout, "switch", "-q", self.plan.trunk)
        log.append(path=self.path, **call_started("cut", "cut", "draft/cut"))
        hosts = {"builder": Host("builder", "fake@builder", ("builder",), places=2)}
        self.runner.on(["ssh"], Result(0, "codex-1 /state/codex-1\n"))
        with patch.object(call_review, "start", side_effect=AssertionError("unexpected review")):
            actions = dispatch.tick(directory, hosts=hosts, sh=self.runner, log_path=self.path)
            self.assertEqual([action.kind for action in actions], ["merge", "flow", "start"])
            records = log.read(self.path)
            landed, = [entry for entry in records if entry["ev"] == "branch.landed"]
            self.assertEqual((landed["task"], landed["branch"], landed["tip"], landed["into"]),
                             ("calls/cut", "calls/cut", first, self.plan.trunk))
            started_run, = [entry for entry in records if entry["ev"] == "run.started"]
            self.assertEqual((started_run["task"], started_run["base"]),
                             ("draft/a", "origin/draft/integration"))
            self.assertEqual(git(self.origin, "rev-parse", self.plan.trunk), landed["main"])
            brief = (log.home() / "runs/draft/a-1/brief.md").read_text()
            self.assertIn("docs/plan/draft/tasks/a.md", brief)
            self.assertNotIn(str(self.checkout), brief)
            dispatch.tick(directory, hosts=hosts, sh=self.runner, log_path=self.path)
            self.assertEqual([entry for entry in log.read(self.path) if entry["ev"] == "branch.landed"],
                             [landed])
            git(self.checkout, "switch", "-q", "calls/cut")
            write(directory / "tasks/b.md", '+++\nid = "b"\npart = "later"\nkind = "feature"\nneeds = []\n+++\n')
            git(self.checkout, "add", "docs")
            git(self.checkout, "commit", "-q", "-m", "Release remaining specs")
            second = git(self.checkout, "rev-parse", "HEAD")
            git(self.checkout, "push", "-q", "origin", "calls/cut")
            git(self.checkout, "switch", "-q", self.plan.trunk)
            actions = dispatch.tick(directory, hosts=hosts, sh=self.runner, log_path=self.path)
            self.assertEqual([action.task for action in actions if action.kind == "start"], ["draft/b"])
            self.assertFalse(any(entry["ev"] == "call.finished" for entry in log.read(self.path)))
            git(self.checkout, "switch", "-q", "calls/cut")
            write(directory / "notes/done.md", "The cut is complete.\n")
            git(self.checkout, "add", "docs")
            git(self.checkout, "commit", "-q", "-m", "Finish the cut")
            last = git(self.checkout, "rev-parse", "HEAD")
            git(self.checkout, "push", "-q", "origin", "calls/cut")
            git(self.checkout, "switch", "-q", self.plan.trunk)
            log.append(path=self.path, **call_ended("cut"))
            dispatch.tick(directory, hosts=hosts, sh=self.runner, log_path=self.path)
        records = log.read(self.path)
        landings = [entry for entry in records if entry["ev"] == "branch.landed"]
        self.assertEqual([entry["tip"] for entry in landings], [first, second, last])
        self.assertEqual(git(self.origin, "rev-parse", self.plan.trunk), landings[-1]["main"])
        self.assertEqual(git(self.origin, "rev-parse", "main"), self.base)
        self.assertTrue((directory / "tasks/b.md").exists())
        self.assertEqual([(entry["call"], entry["outcome"]) for entry in records
                          if entry["ev"] == "call.finished"], [("cut", "done")])
        dispatch.tick(directory, hosts=hosts, sh=self.runner, log_path=self.path)
        records = log.read(self.path)
        self.assertEqual([entry["task"] for entry in records if entry["ev"] == "run.started"],
                         ["draft/a", "draft/b"])
        self.assertEqual(len([entry for entry in records if entry["ev"] == "branch.landed"]), 3)
        self.assertEqual(units(self.runner), [])

    def test_running_cut_conflict_is_noted_and_resolved_push_retries(self):
        tip = self.branch("calls/cut", "README.md", "cut edits\n")
        write(self.checkout / "README.md", "trunk edits\n")
        git(self.checkout, "commit", "-q", "-a", "-m", "Change trunk")
        git(self.checkout, "push", "-q", "origin", self.plan.trunk)
        before = git(self.origin, "rev-parse", self.plan.trunk)
        log.append(path=self.path, **call_started("cut", "cut", "draft/cut"))
        for _ in range(2):
            dispatch._merge_cut(self.plan, self.checkout, self.checkout, {},
                                sh=self.runner, log_path=self.path)
        records = log.read(self.path)
        self.assertEqual([entry["ev"] for entry in records], ["call.started", "note", "note"])
        self.assertIn("CONFLICT", records[-1]["text"])
        self.assertEqual(records[-1]["tip"], tip)
        self.assertEqual(git(self.origin, "rev-parse", self.plan.trunk), before)
        self.assertEqual(git(self.checkout, "status", "--porcelain"), "")
        git(self.checkout, "switch", "-q", "calls/cut")
        git(self.checkout, "merge", "--no-edit", "-s", "ours", self.plan.trunk)
        git(self.checkout, "push", "-q", "origin", "calls/cut")
        git(self.checkout, "switch", "-q", self.plan.trunk)
        dispatch._merge_cut(self.plan, self.checkout, self.checkout, {},
                            sh=self.runner, log_path=self.path)
        self.assertEqual(log.read(self.path)[-1]["ev"], "branch.landed")

    def test_conflict_aborts_and_logs_findings_without_moving_trunk(self):
        tip = self.branch("draft/a", "README.md", "branch edits\n")
        write(self.checkout / "README.md", "trunk edits\n")
        git(self.checkout, "commit", "-q", "-a", "-m", "Change trunk")
        git(self.checkout, "push", "-q", "origin", self.plan.trunk)
        before = git(self.origin, "rev-parse", self.plan.trunk)
        self.assertFalse(dispatch._merge_branch("draft/a", self.plan, self.checkout, task="draft/a",
                                                sh=self.runner, log_path=self.path))
        rejection, = log.read(self.path)
        self.assertEqual((rejection["ev"], rejection["task"], rejection["branch"], rejection["tip"], rejection["step"]),
                         ("branch.rejected", "draft/a", "draft/a", tip, "merge"))
        self.assertIn("CONFLICT", rejection["findings"])
        self.assertEqual(git(self.origin, "rev-parse", self.plan.trunk), before)
        self.assertEqual(git(self.checkout, "rev-parse", "HEAD"), before)
        self.assertFalse((self.checkout / ".git/MERGE_HEAD").exists())
        self.assertEqual(git(self.checkout, "status", "--porcelain"), "")

    def baselines(self, *, fail=False):
        """Two branches lower different counts on one baseline line; the script is a fake."""
        write(self.checkout / "skein/scripts/old-forms.txt", "a=2 b=2\n")
        write(self.checkout / "skein/a.txt", "2\n")
        write(self.checkout / "skein/b.txt", "2\n")
        write(self.checkout / "skein/scripts/old_forms.py", "# fake old-forms counter\n")
        git(self.checkout, "add", "skein")
        git(self.checkout, "commit", "-q", "-m", "Count old forms")
        git(self.checkout, "push", "-q", "origin", self.plan.trunk)
        base = git(self.checkout, "rev-parse", "HEAD")
        for name, counts, filename in (("a", "a=1 b=2\n", "a.txt"), ("b", "a=2 b=1\n", "b.txt")):
            git(self.checkout, "switch", "-q", "-c", f"draft/{name}", base)
            write(self.checkout / "skein/scripts/old-forms.txt", counts)
            write(self.checkout / "skein" / filename, "1\n")
            git(self.checkout, "commit", "-q", "-a", "-m", f"Lower {name}")
            git(self.checkout, "push", "-q", "origin", f"draft/{name}")
        git(self.checkout, "switch", "-q", self.plan.trunk)
        def count(call):
            tree = Path(call.cwd)
            baseline = tree / "scripts/old-forms.txt"
            counts = f"a={int((tree / 'a.txt').read_text())} b={int((tree / 'b.txt').read_text())}\n"
            if "--write" in call.argv:
                if fail:
                    return Result(1, "count increased\n")
                write(baseline, counts)
            return Result(0 if baseline.read_text() == counts else 1, "count checked\n")
        self.runner.on(["python3"], count)

    def test_baseline_only_conflict_recounts_combined_tree_then_pushes(self):
        self.baselines()
        for name in ("a", "b"):
            self.assertTrue(dispatch._merge_branch(f"draft/{name}", self.plan, self.checkout,
                                                   sh=self.runner, log_path=self.path))
        self.assertEqual((self.checkout / "skein/scripts/old-forms.txt").read_text(), "a=1 b=1\n")
        self.assertEqual([entry["ev"] for entry in log.read(self.path)], ["branch.landed", "branch.landed"])
        recounts = [call for call in self.runner.calls if call.argv[:1] == ["python3"]]
        self.assertEqual([call.argv for call in recounts],
                         [["python3", "-I", "-B", "scripts/old_forms.py", "--write"]])
        self.assertEqual(recounts[0].cwd, str(self.checkout / "skein"))
        self.assertIn(["git", "-c", "user.name=fab", "-c", "user.email=fab@localhost", "commit", "--no-edit"],
                      self.runner.argvs())
        self.assertEqual(git(self.origin, "show", f"{self.plan.trunk}:skein/scripts/old-forms.txt"), "a=1 b=1")

    def test_failed_recount_aborts_without_moving_trunk(self):
        self.baselines(fail=True)
        self.assertTrue(dispatch._merge_branch("draft/a", self.plan, self.checkout,
                                               sh=self.runner, log_path=self.path))
        before = git(self.origin, "rev-parse", self.plan.trunk)
        self.assertFalse(dispatch._merge_branch("draft/b", self.plan, self.checkout,
                                                sh=self.runner, log_path=self.path))
        rejection = log.read(self.path)[-1]
        self.assertEqual(rejection["step"], "merge")
        self.assertIn("Recount failed", rejection["findings"])
        self.assertIn("count increased", rejection["findings"])
        self.assertEqual(git(self.origin, "rev-parse", self.plan.trunk), before)
        self.assertEqual(git(self.checkout, "rev-parse", "HEAD"), before)
        self.assertEqual(git(self.checkout, "status", "--porcelain"), "")

    def test_clean_merge_with_count_increase_pushes_without_checking_ratchet(self):
        write(self.checkout / "skein/scripts/old_forms.py", "# fake old-forms counter\n")
        git(self.checkout, "add", "skein")
        git(self.checkout, "commit", "-q", "-m", "Add ratchet")
        git(self.checkout, "push", "-q", "origin", self.plan.trunk)
        before = git(self.origin, "rev-parse", self.plan.trunk)
        tip = self.branch("draft/a", "skein/src/lib.rs", "more old forms\n")
        self.runner.on(["python3"], Result(1, "old forms raised\n", "baseline exceeded\n"))
        self.assertTrue(dispatch._merge_branch("draft/a", self.plan, self.checkout,
                                               sh=self.runner, log_path=self.path))
        landed, = log.read(self.path)
        self.assertEqual((landed["ev"], landed["tip"]), ("branch.landed", tip))
        self.assertNotEqual(git(self.origin, "rev-parse", self.plan.trunk), before)
        self.assertEqual(git(self.checkout, "rev-parse", "HEAD"), landed["main"])
        self.assertFalse(any(call.argv[0] == "python3" for call in self.runner.calls))
        self.assertIn(["git", "push", "origin", f"HEAD:refs/heads/{self.plan.trunk}"], self.runner.argvs())

    def test_uncut_chain_without_reviews_merges_calls_branch_into_trunk(self):
        cut_plan = write_plan(self.home / "cut-plan", "draft")
        contents = ((cut_plan / "plan.toml").read_text()
                    .replace('landing = "queue"', 'landing = "integration"')
                    .replace('reviews = true', 'reviews = false'))
        tip = self.branch("calls/cut", "docs/plan/draft/plan.toml", contents)
        directory = self.checkout / "docs/plan/draft"
        self.assertFalse((directory / "plan.toml").exists())
        log.append(path=self.path, **call_started("cut", "cut", "draft/cut",
                                                  options=['landing="integration"', 'reviews=false']))
        log.append(path=self.path, **call_ended("cut"))
        with patch.object(call_review, "start", side_effect=AssertionError("unexpected review")):
            actions = dispatch.tick(directory, hosts={}, sh=self.runner, log_path=self.path)
        self.assertEqual([action.kind for action in actions], ["flow", "finish"])
        landed, finished = [entry for entry in log.read(self.path)
                            if entry["ev"] in ("branch.landed", "call.finished")]
        self.assertEqual((landed["task"], landed["branch"], landed["tip"], landed["into"]),
                         ("calls/cut", "calls/cut", tip, self.plan.trunk))
        self.assertEqual((finished["call"], finished["outcome"]), ("cut", "done"))
        self.assertEqual(git(self.origin, "rev-parse", self.plan.trunk), landed["main"])
        self.assertFalse(any(entry["ev"] == "run.started" for entry in log.read(self.path)))
        self.land.assert_not_called()
        self.queue.assert_not_called()


class RetireFinishTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.checkout = self.home / "checkout"
        self.directory = write_plan(self.checkout / "docs/plan/draft", "draft")
        self.plan, self.tasks = plan.load(self.directory)
        self.path = self.home / "events.jsonl"
        self.action = Action("finish", task="root", run="root", run_kind="retire", branch="calls/root")
        self.relative = "docs/plan/draft/plan.toml"
        self.worktree = log.home() / "retire/root"
        self.branch_text = 'draft = "draft"\nretired = false # pending\n[[part]]\nid = "core"\n'
        self.tip = "before-retire"
        self.fake = FakeRunner()
        self.fake.on(["git", "rev-parse", "--verify"], lambda call: Result(0, self.tip))
        self.fake.on(["git", "show"], lambda call: Result(0, self.branch_text))
        self.fake.on(["git", "worktree", "add"], self.populate)
        self.fake.on(["git", "push", "-q", "--force"], self.pushed)
        self.land = self.enterContext(patch.object(dispatch, "_land_branch", side_effect=lambda argv:
                                                  self.fake(["land", *argv], check=True)))
        self.enterContext(redirect_stdout(io.StringIO()))
        self.append(*chain_history("approved", role="retire", subject="draft/retire"))

    def append(self, *events):
        for entry in events:
            log.append(path=self.path, **entry)

    def populate(self, call):
        write(self.worktree / self.relative, self.branch_text)
        return Result(0)

    def pushed(self, call):
        self.branch_text = (self.worktree / self.relative).read_text()
        self.tip = "retired-tip"
        return Result(0)

    def take(self):
        dispatch._take(self.action, self.tasks, {}, self.directory, plan=self.plan,
                       checkout=self.checkout, sh=self.fake, log_path=self.path)

    def test_retire_edit_replaces_or_inserts_top_level_flag(self):
        cases = [
            ('draft = "draft"\nretired = false # pending\n[options]\nretired = false\n',
             'draft = "draft"\nretired = true # pending\n[options]\nretired = false\n'),
            ('draft = "draft"\n  [[part]]\nid = "core"\n',
             'draft = "draft"\nretired = true\n  [[part]]\nid = "core"\n'),
            ('draft = "draft"', 'draft = "draft"\nretired = true\n'),
            ('retired=true # set\n', 'retired=true # set\n'),
            ('[options]\nretired = false\n', 'retired = true\n[options]\nretired = false\n'),
        ]
        for before, after in cases:
            with self.subTest(before=before):
                self.assertEqual(dispatch._retire_plan(before), after)
        with self.assertRaisesRegex(ValueError, "missing plan.toml"):
            dispatch._retire_plan("")
        with self.assertRaises(ValueError):
            dispatch._retire_plan("invalid TOML")

    def test_retire_commits_branch_plan_before_agents_delivery(self):
        write(self.directory / "plan.toml", 'retired = true\n')
        self.take()
        expected = 'draft = "draft"\nretired = true # pending\n[[part]]\nid = "core"\n'
        self.assertEqual(self.branch_text, expected)
        self.assertEqual((self.worktree / self.relative).read_text(), expected)
        self.assertEqual((self.directory / "plan.toml").read_text(), 'retired = true\n')
        commit = [*dispatch.FAB_GIT, "commit", "-q", "-m", "draft: retired", "--", self.relative]
        push = ["git", "push", "-q", "--force", "origin", "HEAD:refs/heads/calls/root"]
        self.assertEqual(self.fake.argvs(), [
            ["git", "fetch", "origin"],
            ["git", "rev-parse", "--verify", "refs/remotes/origin/calls/root^{commit}"],
            ["git", "show", f"origin/calls/root:{self.relative}"],
            ["git", "fetch", "origin"],
            ["git", "worktree", "add", "-B", "calls/root", str(self.worktree), "origin/calls/root"],
            commit, push,
            ["git", "worktree", "remove", "--force", str(self.worktree)],
            ["git", "branch", "-D", "calls/root"],
            ["land", "calls/root"]])
        self.assertEqual([call.cwd for call in self.fake.calls if call.argv in (commit, push)],
                         [str(self.worktree)] * 2)
        finished = log.read(self.path)[-1]
        self.assertEqual((finished["ev"], finished["role"], finished["outcome"]),
                         ("call.finished", "retire", "done"))
        self.assertEqual(log.read(), [])

    def test_retire_guards_skip_commit_and_keep_delivery(self):
        for guard in ("retired", "landed", "gone", "other-role"):
            with self.subTest(guard=guard):
                self.path = self.home / f"{guard}.jsonl"
                self.append(*chain_history("approved", role="retire", subject="draft/retire"))
                if guard == "landed":
                    self.append(dict(ev="branch.landed", branch="calls/root"))
                self.branch_text = "retired=true # already set\n"
                self.action = replace(self.action, run_kind="cut" if guard == "other-role" else "retire")
                self.fake.calls.clear()
                self.fake.rules.insert(0, (["git", "rev-parse", "--verify"],
                                          Result(128 if guard == "gone" else 0, self.tip)))
                self.take()
                self.fake.rules.pop(0)
                self.assertEqual(log.read(self.path)[-1]["outcome"], "done")
                self.assertFalse(any("commit" in argv for argv in self.fake.argvs()))
                self.assertFalse(any("worktree" in argv for argv in self.fake.argvs()))
                self.assertEqual(self.fake.argvs()[-1], ["land", "calls/root"])
                if guard in ("landed", "other-role"):
                    self.assertEqual(self.fake.argvs(), [["land", "calls/root"]])
                if guard == "gone":
                    self.assertFalse(any("show" in argv for argv in self.fake.argvs()))

    def test_retire_commit_or_push_failure_leaves_finish_open_and_retries(self):
        for failing in ([*dispatch.FAB_GIT, "commit"], ["git", "push", "-q", "--force"]):
            with self.subTest(failing=failing):
                self.path = self.home / ("commit.jsonl" if "commit" in failing else "push.jsonl")
                self.append(*chain_history("approved", role="retire", subject="draft/retire"))
                self.branch_text = 'draft = "draft"\nretired = false\n'
                self.fake.calls.clear()
                self.land.reset_mock()
                self.fake.rules.insert(0, (failing, Result(1, err="refused")))
                self.take()
                self.land.assert_not_called()
                records = log.read(self.path)
                self.assertEqual(records[-1]["ev"], "note")
                self.assertIn("finish root failed:", records[-1]["text"])
                self.assertIn("refused", records[-1]["text"])
                self.assertFalse(any(entry["ev"] == "call.finished" for entry in records))
                self.assertEqual(call_review.chains(records)["root"].state, "approved")
                self.assertIn(["git", "worktree", "remove", "--force", str(self.worktree)], self.fake.argvs())
                self.fake.rules.pop(0)
                self.take()
                self.land.assert_called_once_with(["calls/root"])
                self.assertEqual(log.read(self.path)[-1]["outcome"], "done")

    def test_retire_missing_plan_in_worktree_leaves_finish_open(self):
        self.fake.rules.insert(0, (["git", "worktree", "add"], Result(0)))
        self.take()
        self.land.assert_not_called()
        self.assertEqual(log.read(self.path)[-1]["text"], "finish root failed: missing plan.toml")
        self.assertFalse(any(entry["ev"] == "call.finished" for entry in log.read(self.path)))
        self.assertFalse(any("commit" in argv for argv in self.fake.argvs()))

    def test_retire_fabrig_readies_committed_tip_once(self):
        self.plan = replace(self.plan, repo="fabrig")
        self.take()
        self.take()
        ready = [entry for entry in log.read(self.path) if entry["ev"] == "branch.ready"]
        self.assertEqual([entry["tip"] for entry in ready], ["retired-tip"])
        self.assertEqual(self.fake.argvs().count(
            ["git", "push", "origin", "retired-tip:refs/heads/ready/calls/root"]), 1)
        self.assertEqual(sum("commit" in argv for argv in self.fake.argvs()), 1)
        self.assertFalse(any(entry["ev"] == "call.finished" for entry in log.read(self.path)))
        self.land.assert_not_called()

    def test_retire_integration_merges_after_committing(self):
        self.plan = replace(self.plan, landing="integration")
        with patch.object(dispatch, "_merge_branch", side_effect=lambda *args, **kwargs:
                          self.fake(["merge", self.tip], check=True).ok) as merge:
            self.take()
        merge.assert_called_once_with("calls/root", self.plan, self.checkout,
                                      sh=self.fake, log_path=self.path)
        self.assertEqual(self.fake.argvs()[-1], ["merge", "retired-tip"])
        self.assertEqual(log.read(self.path)[-1]["outcome"], "done")
        self.land.assert_not_called()


class RetiredFinishTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.path = self.home / "events.jsonl"
        self.plan = replace(make_plan(part("core")), retired=True)
        self.events = [call_started("retire", "retire", "draft/retire"), call_ended("retire")]
        self.landing = dict(ev="branch.landed", branch="calls/retire", queue_ts="010")

    def test_retired_finish_requires_its_retire_chain_and_a_queue_landing(self):
        histories = {
            "no landing": self.events,
            "local landing": self.events + [dict(ev="branch.landed", branch="calls/retire")],
            "other branch": self.events + [dict(self.landing, branch="calls/other")],
            "other draft": [dict(self.events[0], subject="draft-other/retire"), self.events[1], self.landing],
            "other role": [dict(self.events[0], role="answer"), self.events[1], self.landing],
            "unfinished call": [self.events[0], self.landing],
        }
        for reason, events in histories.items():
            with self.subTest(reason=reason):
                dispatch._finish_retired(self.plan, events, log_path=self.path)
                self.assertEqual(log.read(self.path), [])

    def test_retired_finish_uses_latest_done_amend_and_its_latest_checked_tip(self):
        self.events += [dict(ev="call.checked", call="retire", tip="root-tip"),
                        call_started("amend", "amend", "draft/retire", amends="retire",
                                     branch="calls/retire"), call_ended("amend"),
                        dict(ev="call.checked", call="amend", tip="old-tip"),
                        dict(ev="call.checked", call="amend", tip="latest-tip"), self.landing]
        dispatch._finish_retired(self.plan, self.events, log_path=self.path)
        self.assertEqual([{key: value for key, value in entry.items() if key != "ts"}
                          for entry in log.read(self.path)],
                         [dict(ev="call.finished", call="amend", role="retire", outcome="done",
                               tip="latest-tip")])
        self.assertEqual(log.read(), [])

    def test_retired_finish_omits_tip_when_the_latest_call_has_no_check(self):
        self.events += [dict(ev="call.checked", call="retire", tip="root-tip"),
                        call_started("amend", "amend", "draft/retire", amends="retire",
                                     branch="calls/retire"), call_ended("amend"), self.landing]
        dispatch._finish_retired(self.plan, self.events, log_path=self.path)
        finished = log.read(self.path)
        self.assertEqual(len(finished), 1)
        self.assertEqual(finished[0]["call"], "amend")
        self.assertNotIn("tip", finished[0])

    def test_retired_finish_does_not_reopen_a_chain_finished_by_any_of_its_calls(self):
        self.events += [call_started("amend", "amend", "draft/retire", amends="retire",
                                     branch="calls/retire"), call_ended("amend"), self.landing]
        for call in ("retire", "amend"):
            with self.subTest(call=call):
                events = self.events + [dict(ev="call.finished", call=call, outcome="failed")]
                dispatch._finish_retired(self.plan, events, log_path=self.path)
                self.assertEqual(log.read(self.path), [])


class IntegrationDeliveryTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.plan = replace(make_plan(part("core")), repo="fabrig", landing="integration", reviews=False)
        self.directory = write_plan(self.home / "plan", "draft", tasks=("a",), repo="fabrig")
        self.tasks = plan.load(self.directory)[1]
        self.path = self.home / "events.jsonl"
        self.fake = FakeRunner().on(["git", "rev-parse", "--show-toplevel"], Result(0, str(self.home)))
        self.fake.on(["git", "rev-parse", "--verify"], Result(0, "branch-tip"))
        self.fake.on(["git", "rev-parse", "HEAD"], Result(0, "merged-tip"))
        self.fake.on(["git", "show"], Result(0, "retired = true\n"))
        self.out = io.StringIO()
        self.enterContext(redirect_stdout(self.out))
        self.land = self.enterContext(patch.object(dispatch.land, "main", side_effect=AssertionError("unexpected land")))
        self.queue = self.enterContext(patch.object(dispatch, "_queue_branch", wraps=dispatch._queue_branch))

    def append(self, *events):
        for entry in events:
            log.append(path=self.path, **entry)

    def take(self, action, *, hosts=None):
        dispatch._take(action, self.tasks, hosts or {}, self.directory, plan=self.plan,
                       checkout=self.home, sh=self.fake, log_path=self.path)

    def test_refused_push_leaves_finish_retryable_then_finishes_once(self):
        self.append(*chain_history("review", role="cut", subject="draft/cut"))
        push = ["git", "push", "origin", "HEAD:refs/heads/draft/integration"]
        attempts = [Result(1, err="non-fast-forward"), Result(0)]
        self.fake.on(push, lambda call: attempts.pop(0))
        action = Action("finish", task="root", run="root", run_kind="cut", branch="calls/root")
        self.take(action)
        self.assertEqual(log.read(self.path)[-1]["ev"], "note")
        self.assertEqual(call_review.chains(log.read(self.path))["root"].state, "review")
        self.assertFalse(any(entry["ev"] in ("branch.landed", "call.finished") for entry in log.read(self.path)))
        self.take(action)
        self.assertEqual(log.read(self.path)[-1]["ev"], "call.finished")
        self.assertEqual(log.read(self.path)[-1]["outcome"], "done")
        self.assertEqual(self.fake.argvs().count(push), 2)
        self.assertEqual(log.read(), [])

    def test_landed_trunk_calls_ready_once_and_finish_after_queue_landing(self):
        for role in ("retire", "cut", "review"):
            with self.subTest(role=role):
                self.path = self.home / f"{role}.jsonl"
                self.fake.calls.clear()
                self.append(*chain_history("review", role=role, subject=f"draft/{role}"),
                            dict(ev="branch.landed", task="draft/integration", queue_ts="001"))
                action = Action("finish", task="root", run="root", run_kind=role, branch="calls/root")
                with patch.object(dispatch, "_merge_branch", side_effect=AssertionError("unexpected merge")):
                    self.take(action)
                    self.take(action)
                    ready, = [entry for entry in log.read(self.path) if entry["ev"] == "branch.ready"]
                    self.assertEqual((ready["task"], ready["branch"], ready["tip"]),
                                     ("calls/root", "calls/root", "branch-tip"))
                    push = ["git", "push", "origin", "branch-tip:refs/heads/ready/calls/root"]
                    verify = ["git", "rev-parse", "--verify", "refs/remotes/origin/calls/root^{commit}"]
                    preflight = ([["git", "fetch", "origin"], verify,
                                   ["git", "show", "origin/calls/root:plan/plan.toml"]]
                                 if role == "retire" else [])
                    self.assertEqual(self.fake.argvs(), preflight + [verify, push] + preflight + [verify])
                    self.assertFalse(any(entry["ev"] == "call.finished" for entry in log.read(self.path)))
                    self.append(dict(ev="branch.landed", task="calls/root", branch="calls/root", queue_ts="002"))
                    self.take(action)
                finished = log.read(self.path)[-1]
                self.assertEqual((finished["ev"], finished["role"], finished["outcome"]),
                                 ("call.finished", role, "done"))
        self.land.assert_not_called()
        self.assertEqual(log.read(), [])

    def test_landed_trunk_agents_call_uses_land(self):
        self.plan = replace(self.plan, repo="agents")
        self.append(*chain_history("review", role="retire", subject="draft/retire"),
                    dict(ev="branch.landed", task="draft/integration", queue_ts="001"))
        self.land.side_effect = None
        self.land.return_value = 0
        with patch.object(dispatch, "_merge_branch", side_effect=AssertionError("unexpected merge")):
            self.take(Action("finish", task="root", run="root", run_kind="retire", branch="calls/root"))
        self.land.assert_called_once_with(["calls/root"])
        self.queue.assert_not_called()
        self.assertEqual(log.read(self.path)[-1]["ev"], "call.finished")

    def test_running_cut_merges_only_its_pushed_unmerged_branch(self):
        self.append(call_started("cut", "cut", "draft/cut"))
        for landing, reviews, result in (("queue", False, Result(1)),
                                          ("integration", True, Result(1)),
                                          ("integration", False, Result(0))):
            with self.subTest(landing=landing, reviews=reviews):
                self.fake.calls.clear()
                self.fake.rules.insert(0, (["git", "merge-base"], result))
                actions = dispatch._merge_cut(replace(self.plan, landing=landing, reviews=reviews),
                                              self.directory, self.home, {}, sh=self.fake, log_path=self.path)
                self.assertEqual(actions, [])
                self.assertFalse(any(argv[:2] == ["git", "push"] for argv in self.fake.argvs()))
        for history in ([call_started("foreign", "cut", "other/cut")],
                        [call_started("wrong", "skeleton", "draft/cut")],
                        [call_started("cut", "cut", "draft/cut"), call_ended("cut")]):
            with self.subTest(history=history):
                path = self.home / "filtered.jsonl"
                write(path, "")
                for entry in history:
                    log.append(path=path, **entry)
                self.fake.calls.clear()
                self.assertEqual(dispatch._merge_cut(self.plan, self.directory, self.home, {},
                                                      sh=self.fake, log_path=path), [])
                self.assertEqual(self.fake.calls, [])

    def test_running_cut_without_push_waits_and_failed_push_retries(self):
        self.append(call_started("cut", "cut", "draft/cut"))
        pushed = ["git", "rev-parse", "--verify", "refs/remotes/origin/calls/cut^{commit}"]
        self.fake.rules.insert(0, (pushed, Result(128)))
        self.assertEqual(dispatch._merge_cut(self.plan, self.directory, self.home, {},
                                              sh=self.fake, log_path=self.path), [])
        self.assertEqual([entry["ev"] for entry in log.read(self.path)], ["call.started"])
        self.fake.rules.pop(0)
        self.fake.on(["git", "merge-base"], Result(1))
        attempts = [Result(1, err="push unavailable"), Result(0)]
        push = ["git", "push", "origin", "HEAD:refs/heads/draft/integration"]
        self.fake.on(push, lambda call: attempts.pop(0))
        for _ in range(2):
            dispatch._merge_cut(self.plan, self.directory, self.home, {}, sh=self.fake, log_path=self.path)
        self.assertEqual([entry["ev"] for entry in log.read(self.path)],
                         ["call.started", "note", "branch.landed"])
        self.assertEqual(self.fake.argvs().count(push), 2)
        self.assertFalse(any(entry["ev"] == "call.finished" for entry in log.read(self.path)))

    def test_merge_rejection_keeps_last_forty_output_lines(self):
        self.fake.on(["git", "-c"], Result(1, "".join(f"line {n}\n" for n in range(50)), "stderr\n"))
        self.assertFalse(dispatch._merge_branch("draft/a", self.plan, self.home, task="draft/a",
                                                sh=self.fake, log_path=self.path))
        record, = log.read(self.path)
        self.assertEqual(record["findings"].splitlines(), [f"line {n}" for n in range(11, 50)] + ["stderr"])
        self.assertIn(["git", "merge", "--abort"], self.fake.argvs())
        self.assertFalse(any(argv[:3] == ["git", "push", "origin"] for argv in self.fake.argvs()))

    def test_merge_runs_only_fetch_reset_merge_and_push_without_gates(self):
        self.append(started(), ended())
        with (
            patch.object(rust_gates, "screen", side_effect=AssertionError("unexpected Rust gate")) as rust_screen,
            patch.object(gates, "screen", side_effect=AssertionError("unexpected Python gate")) as screen,
        ):
            self.take(Action("merge", task="draft/a", branch="draft/a"))
        rust_screen.assert_not_called()
        screen.assert_not_called()
        self.assertEqual(self.fake.argvs(), [
            ["git", "fetch", "origin"],
            ["git", "reset", "-q", "--hard", f"origin/{self.plan.trunk}"],
            ["git", "rev-parse", "--verify", "refs/remotes/origin/draft/a^{commit}"],
            ["git", "-c", "user.name=fab", "-c", "user.email=fab@localhost",
             "merge", "--no-ff", "--no-edit", "branch-tip"],
            ["git", "push", "origin", f"HEAD:refs/heads/{self.plan.trunk}"],
            ["git", "rev-parse", "HEAD"]])
        landed = log.read(self.path)[-1]
        self.assertEqual((landed["ev"], landed["tip"], landed["main"], landed["into"]),
                         ("branch.landed", "branch-tip", "merged-tip", self.plan.trunk))

    def test_foremen_start_on_integration_trunk(self):
        hosts = {"builder": Host("builder", "fake@builder", ("builder",), places=1)}
        for history, kind, module in ((question_history(), "foreman", foreman),
                                       (refusal_history("a"), "examine", repairs)):
            with self.subTest(kind=kind):
                self.path = self.home / (kind + ".jsonl")
                self.append(*history)
                action, = (dispatch.foreman_actions if kind == "foreman" else dispatch.repair_actions)(
                    self.tasks, log.read(self.path))
                with patch.object(module, "start") as start:
                    self.take(action, hosts=hosts)
                self.assertEqual(start.call_args.kwargs["trunk"], self.plan.trunk)

    def test_answer_and_repair_specs_use_trunk_and_settle_only_after_merge(self):
        for kind, module, history, text, prefix, settled_ev in (
                ("settle", foreman, question_history(status="settled"), "Done: Choose A\n", "answers", "question.answered"),
                ("remedy", repairs, refusal_history("a", "decided"), report("fix", "Fix the spec."), "repairs", "refusal.settled")):
            for merged in (False, True):
                with self.subTest(kind=kind, merged=merged):
                    self.path = self.home / f"{kind}-{merged}.jsonl"
                    self.append(*history)
                    run_id = "draft/a/foreman-1"
                    branch = f"{prefix}/{run_id}"
                    write(log.home() / "runs" / run_id / "report.md", text)
                    action = Action(kind, task="draft/a", run=run_id)
                    with patch.object(module, "commit", return_value=branch) as commit, \
                         patch.object(dispatch, "_merge_branch", return_value=merged) as merge:
                        self.take(action)
                    self.assertEqual(commit.call_args.kwargs["trunk"], self.plan.trunk)
                    merge.assert_called_once_with(branch, self.plan, self.home, sh=self.fake, log_path=self.path)
                    self.assertEqual(any(entry["ev"] == settled_ev for entry in log.read(self.path)), merged)
        self.land.assert_not_called()
        self.queue.assert_not_called()


class AfterLandingImportTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.path = self.home / "events.jsonl"
        self.hosts = {"b": Host("b", "fake@b", ("builder", "after-landing"))}
        self.lines = [dict(ts="t1", ev="test", state="new", tip="x", profile="qa-jig", test="a"),
                      dict(ts="t1", ev="test", state="new", tip="x", profile="qa-jig", test="b"),
                      dict(ts="t1", ev="test", state="flake", tip="x", profile="qa-jig", test="c"),
                      dict(ts="t2", ev="run", tip="x", verdict="red", new=2)]
        self.fake = FakeRunner().on(["ssh"], lambda call: Result(0, "".join(
            json.dumps(line) + "\n" for line in self.lines)))

    def test_runs_and_new_reds_are_imported_once_from_the_newest(self):
        dispatch._import_after_landing([], self.hosts, sh=self.fake, log_path=self.path)
        dispatch._import_after_landing(log.read(self.path), self.hosts, sh=self.fake, log_path=self.path)
        records = log.read(self.path)
        self.assertEqual([(entry["ev"], entry.get("test")) for entry in records],
                         [("tiers.red", "a"), ("tiers.red", "b"), ("tiers.run", None)])
        self.assertEqual([entry["host"] for entry in records], ["b", "b", "b"])
        self.assertIn("--since t2", self.fake.calls[-1].argv[-1])

    def test_same_test_in_distinct_binaries_is_imported_once_per_binary(self):
        for state, event in (("new", "tiers.red"), ("unattributed", "tiers.red"),
                             ("recovered", "tiers.recovered")):
            with self.subTest(state=state):
                self.path = self.home / f"{state}.jsonl"
                self.lines = [dict(ts="t1", ev="test", state=state, tip="x", profile="p",
                                   binary=binary, test="same") for binary in ("a", "b")]
                dispatch._import_after_landing([], self.hosts, sh=self.fake, log_path=self.path)
                self.assertEqual([(entry["ev"], entry["binary"]) for entry in log.read(self.path)],
                                 [(event, "a"), (event, "b")])
                self.lines.append(dict(self.lines[0], binary="c"))
                for _ in range(2):
                    dispatch._import_after_landing(log.read(self.path), self.hosts,
                                                   sh=self.fake, log_path=self.path)
                self.assertEqual([(entry["ev"], entry["binary"]) for entry in log.read(self.path)],
                                 [(event, "a"), (event, "b"), (event, "c")])
                self.assertTrue(all(entry["host"] == "b" for entry in log.read(self.path)))

    def test_no_machine_with_the_role_reads_nothing_and_a_failed_read_is_a_note(self):
        dispatch._import_after_landing([], {"c": Host("c", "fake@c", ("builder",))}, sh=self.fake,
                                       log_path=self.path)
        self.assertEqual(self.fake.calls, [])
        failing = FakeRunner().on(["ssh"], Result(255, err="no route"))
        dispatch._import_after_landing([], self.hosts, sh=failing, log_path=self.path)
        self.assertEqual(log.read(self.path)[-1]["text"], "after-landing import failed: no route")


class NoPlanRedTickTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        write(log.home() / "plans", "")
        self.hosts = {"builder": Host("builder", "fake@builder", ("builder",)),
                      "gate": Host("gate", "fake@gate", ("gate",)),
                      "tiers": Host("tiers", "fake@tiers", ("after-landing",))}
        self.key = '["default","pkg::bin","case"]'
        self.records = [dict(ev="test", ts="001", state="new", key=self.key, tip="tip",
                             profile="default", binary="pkg::bin", test="case", error="failed",
                             branches=["hand/pushed"], log="/al/test.log", rerun="/al/rerun.log"),
                        dict(ev="run", ts="002", tip="tip", verdict="red", reds=[self.key],
                             branches=["hand/pushed"], faults=["live-temper: exit 4"], log="/al/run.log")]
        self.prefix = ssh("fake@tiers", ["fab", "after-landing", "log"])[:-1]
        self.fake = FakeRunner().on(ssh("fake@tiers", ["tail", "-n", "40", "--", "/al/rerun.log"]),
                                    Result(0, "rerun failed\n"))
        self.fake.on(self.prefix, lambda call: Result(
            0, "\n".join(json.dumps(record) for record in self.records)))
        self.starts = self.enterContext(patch.object(runs, "start"))
        self.collects = self.enterContext(patch.object(runs, "collect"))
        self.enterContext(patch.object(flow, "measure", side_effect=AssertionError("measured")))
        self.enterContext(patch.object(dispatch, "decide", side_effect=AssertionError("decided")))
        self.enterContext(patch.object(drafts, "strays", side_effect=AssertionError("collected strays")))
        self.enterContext(redirect_stdout(io.StringIO()))

    def tick(self):
        actions = dispatch.tick(sh=self.fake, hosts=self.hosts)
        self.starts.assert_not_called()
        self.collects.assert_not_called()
        self.assertEqual(units(self.fake), [])
        self.assertFalse(any(record["ev"] in ("run.started", "call.started") for record in log.read()))
        return actions

    def test_no_plan_red_imports_open_signals_once_and_show_faults_on_page(self):
        self.assertEqual(self.tick(), [])
        first = log.read()
        self.assertEqual([record["ev"] for record in first], ["tiers.red", "tiers.run", "red.opened"])
        opened = first[-1]
        self.assertEqual((opened["route"], opened["draft"], opened["tasks"], opened["suspects"]),
                         ("signal", "", [], ["hand/pushed"]))
        self.assertEqual(opened["reason"], "no fab task among the suspects")
        self.assertIn("rerun failed", tier_reds.evidence_path(opened["red"]).read_text())
        self.assertEqual({signal.id for signal in channel.signals(first)}, {"red-1", "fault:live-temper"})
        page = (log.home() / channel.PAGE).read_text()
        for fact in ("### red-1,", "hand/pushed (hand-pushed)", "default pkg::bin case",
                     "### fault:live-temper,", "live-temper: exit 4", "tiers:/al/run.log"):
            self.assertIn(fact, page)
        self.assertEqual(self.tick(), [])
        self.assertEqual(log.read(), first)
        queries = [argv for argv in self.fake.argvs() if argv[:len(self.prefix)] == self.prefix
                   and "after-landing" in argv[-1]]
        self.assertEqual(queries, [ssh("fake@tiers", ["fab", "after-landing", "log", "--since", stamp])
                                   for stamp in ("", "002")])

    def test_no_plan_red_recovery_closes_and_refreshes_page_without_starting_work(self):
        self.tick()
        self.records += [dict(ev="test", ts="003", state="recovered", key=self.key, tip="green"),
                         dict(ev="run", ts="004", tip="green", reds=[], faults=[])]
        self.assertEqual(self.tick(), [])
        closed, = [record for record in log.read() if record["ev"] == "red.closed"]
        self.assertEqual((closed["red"], closed["reason"], closed["tip"]), ("red-1", "recovered", "green"))
        self.assertIn("## Open signals\n\n(none)", (log.home() / channel.PAGE).read_text())

    def test_no_plan_red_failed_listed_fetch_imports_and_closes_but_defers_opening(self):
        directory = write_plan(self.home / "plan", "draft", tasks=("a",), repo="fabrig")
        write(log.home() / "plans", str(directory) + "\n")
        self.fake.on(["git", "rev-parse", "--show-toplevel"], Result(0, str(self.home) + "\n"))
        self.fake.on(["git", "fetch", "origin"], Result(1, err="fetch failed"))
        log.append("red.opened", red="red-1", tip="old", keys=["old-key"], suspects=[],
                   tasks=[], draft="", route="signal")
        self.records.insert(0, dict(ev="test", ts="000", state="recovered", key="old-key", tip="tip"))
        actions = self.tick()
        self.assertEqual([action.kind for action in actions], ["load"])
        self.assertIn("fetch failed", actions[0].detail)
        events = log.read()
        self.assertEqual([record["ev"] for record in events],
                         ["red.opened", "tiers.recovered", "tiers.red", "tiers.run", "red.closed"])
        self.assertEqual(tier_reds.reds(events)[0].state, "closed")
        self.assertEqual([signal.id for signal in channel.signals(events)], ["fault:live-temper"])
        self.assertFalse(tier_reds.evidence_path("red-2").exists())


class CatchUpTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.origin, self.clone = git_pair(self.home)
        self.plan = plan.Plan("demo", "fabrig", (), 1, 2, {}, (), landing="integration")
        self.path = self.home / "events.jsonl"
        git(self.clone, "switch", "-qc", self.plan.trunk)
        self.tip = self.commit("trunk.txt", "trunk\n")
        git(self.clone, "push", "-q", "origin", f"HEAD:refs/heads/{self.plan.trunk}")
        git(self.clone, "switch", "-q", "main")

    def commit(self, name, text):
        write(self.clone / name, text)
        git(self.clone, "add", name)
        git(self.clone, "commit", "-qm", name)
        return git(self.clone, "rev-parse", "HEAD")

    def sh(self, argv, **kwargs):
        return run(argv, env={**os.environ, **GIT_ENV}, **kwargs)

    def catch_up(self):
        return dispatch._catch_up(self.plan, self.tip, self.clone, sh=self.sh, log_path=self.path)

    def test_a_trunk_that_contains_main_is_checked_as_it_is(self):
        self.assertEqual(self.catch_up(), self.tip)
        self.assertEqual(log.read(self.path), [])

    def test_main_merges_into_the_trunk_and_is_logged_as_a_landing(self):
        main = self.commit("main.txt", "main\n")
        git(self.clone, "push", "-q", "origin", "HEAD:main")
        caught = self.catch_up()
        self.assertEqual(git(self.origin, "rev-parse", self.plan.trunk), caught)
        self.assertEqual(git(self.origin, "rev-parse", f"{caught}^1", f"{caught}^2").split(), [self.tip, main])
        (record,) = log.read(self.path)
        self.assertEqual((record["ev"], record["task"], record["branch"], record["main"], record["into"]),
                         ("branch.landed", "demo/integration", "main", caught, self.plan.trunk))

    def test_a_conflict_with_main_is_aborted_and_rejected(self):
        git(self.clone, "switch", "-q", self.plan.trunk)
        self.tip = self.commit("both.txt", "trunk\n")
        git(self.clone, "push", "-q", "origin", f"HEAD:refs/heads/{self.plan.trunk}")
        git(self.clone, "switch", "-q", "main")
        main = self.commit("both.txt", "main\n")
        git(self.clone, "push", "-q", "origin", "HEAD:main")
        self.assertIsNone(self.catch_up())
        self.assertEqual(git(self.origin, "rev-parse", self.plan.trunk), self.tip)
        (record,) = log.read(self.path)
        self.assertEqual((record["ev"], record["step"], record["tip"], record["main"]),
                         ("branch.rejected", integration.CATCH_UP, self.tip, main))
        self.assertIn("both.txt", record["findings"])
        self.assertEqual(git(self.clone, "status", "--porcelain"), "")


class IntegrationCheckTickTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.directory = write_plan(self.home / "plan", "draft", tasks=("a",), repo="fabrig")
        path = self.directory / "plan.toml"
        write(path, path.read_text().replace('landing = "queue"', 'landing = "integration"')
              .replace('reviews = true', 'reviews = false'))
        self.plan, self.tasks = plan.load(self.directory)
        self.path = self.home / "events.jsonl"
        self.hosts = {name: Host(name, f"fake@{name}", ("builder",), places=places, slots=2)
                      for name, places in (("builder", 2), ("other", 1))}
        self.torn = False
        self.fake = FakeRunner().on(["ssh"], self.remote)
        self.fake.on(["git", "rev-parse", "--verify"], Result(0, "repair-tip"))
        self.fake.on(["git", "rev-parse", "HEAD"], Result(0, "fixed-tip"))
        self.fake.on(["git", "rev-parse", f"origin/{self.plan.trunk}"], Result(0, "fetched-trunk-tip\n"))
        self.enterContext(patch.object(rust_gates, "screen", return_value=[]))
        self.enterContext(patch.object(dispatch, "_check_calls"))
        self.output = io.StringIO()
        self.enterContext(redirect_stdout(self.output))
        self.append(event("branch.landed", into=self.plan.trunk, main="trunk-tip", tip="a-tip"))

    def remote(self, call):
        argv = shlex.split(shlex.split(call.argv[-1])[2])
        if argv == ["fab", "slot", "list"]:
            return Result(0, ('torn\n[]\n' if self.torn else "") + json.dumps(dict(slot=2, claim=None, idle=0)) + '\n')
        if argv[:3] in (["fab", "check", "start"], ["fab", "codex", "start"]):
            return Result(0, "unit-id /state/unit-id\n")
        return Result(0)

    def append(self, *events):
        for entry in events:
            log.append(path=self.path, **entry)

    def tick(self):
        events = log.read(self.path)
        return dispatch._tick_loaded(self.plan, self.tasks, self.directory, self.home, self.hosts, {},
                                     tier_reds.reds(events), self.tasks, sh=self.fake, log_path=self.path)

    def commands(self):
        return [shlex.split(shlex.split(call.argv[-1])[2]) for call in self.fake.calls if call.argv[:1] == ["ssh"]]

    def test_all_merged_starts_one_check_in_claimed_slot_on_freest_builder(self):
        self.torn = True
        self.tick()
        record = log.read(self.path)[-1]
        self.assertEqual((record["ev"], record["kind"], record["task"], record["run"], record["base"], record["slot"], record["host"]),
                         ("run.started", "check", "draft/integration", "draft/integration-1", "trunk-tip", 2, "builder"))
        self.assertEqual(record["branch"], self.plan.trunk)
        commands = self.commands()
        self.assertIn(["fab", "slot", "claim", "2", "draft/integration-1", "draft/integration"], commands)
        self.assertTrue(any(argv[:3] == ["git", "-C", record["dir"]] and argv[-2:] == ["fetch", "origin"] for argv in commands))
        launch = next(argv for argv in commands if argv[:3] == ["fab", "check", "start"])
        self.assertEqual(launch[3:7], ["--tip", "trunk-tip", "--onto", "origin/draft/integration"])
        self.assertIn("integration draft check trunk-tip\n", self.output.getvalue())
        with patch.object(runs, "collect", return_value=None) as collect:
            self.tick()
        collect.assert_called_once()
        self.assertEqual(sum(argv[:3] == ["fab", "check", "start"] for argv in self.commands()), 1)

    def test_failed_check_generates_repair_starts_from_trunk_merges_and_rechecks(self):
        self.tick()
        self.append(run_ended("draft/integration", outcome="failed"))
        write(log.home() / "runs/draft/integration-1/report.md", "Failed: fmt red\nfmt:1:0.1\n/check.log\n")
        loaded, tasks = dispatch._load_plan(self.directory, log.read(self.path))
        self.assertIn("Failed: fmt red", tasks["draft/repair-1"].body)
        actions = self.tick()
        start, = [action for action in actions if action.kind == "start"]
        self.assertEqual((start.task, start.run_kind), ("draft/repair-1", "implement"))
        record = log.read(self.path)[-1]
        self.assertEqual((record["task"], record["base"], record["branch"]),
                         ("draft/repair-1", "origin/draft/integration", "draft/repair-1"))
        self.assertIn("Failed: fmt red", (log.home() / "runs/draft/repair-1-1/brief.md").read_text())
        self.append(run_ended("draft/repair-1"))
        actions = self.tick()
        self.assertTrue(any(action.kind == "merge" and action.task == "draft/repair-1" for action in actions))
        check = log.read(self.path)[-1]
        self.assertEqual((check["kind"], check["run"], check["base"]), ("check", "draft/integration-2", "fixed-tip"))
        self.assertTrue(any(entry["ev"] == "branch.landed" and entry["task"] == "draft/repair-1"
                            and entry["into"] == self.plan.trunk for entry in log.read(self.path)))

    def test_main_moved_passes_sha_and_takes_only_the_catch_up_step(self):
        write(self.path, "")
        self.append(event("branch.landed", into=self.plan.trunk, main="trunk-tip", tip="a-tip",
                          ts="2026-11-01T10:00:00Z"),
                    dict(ev="note", ts="2026-11-01T10:30:00Z"))
        tasks = {**self.tasks, "draft/b": task("b", repo="fabrig")}
        ancestor = ["git", "merge-base", "--is-ancestor", "origin/main", f"origin/{self.plan.trunk}"]
        self.fake.on(ancestor, Result(1)).on(["git", "rev-parse", "origin/main"], Result(0, "main-sha\n"))
        with patch.object(integration, "next_step", wraps=integration.next_step) as next_step, \
                patch.object(dispatch, "_catch_up", return_value="caught") as catch, \
                patch.object(dispatch, "_integration_check") as check:
            dispatch._integration(self.plan, tasks, self.home, self.hosts, sh=self.fake, log_path=self.path)
        self.assertEqual(next_step.call_args.kwargs, {"main": "main-sha", "trunk": "fetched-trunk-tip", "caught": False})
        catch.assert_called_once_with(self.plan, "trunk-tip", self.home, sh=self.fake, log_path=self.path)
        check.assert_not_called()
        self.assertEqual(self.fake.argvs(), [ancestor, ["git", "rev-parse", "origin/main"],
                                            ["git", "rev-parse", f"origin/{self.plan.trunk}"]])
        self.assertTrue(all(call.cwd == str(self.home) for call in self.fake.calls))
        self.assertIn("integration draft catch-up", self.output.getvalue())

    def test_main_contained_still_starts_mid_check_with_default_and_mid_logged(self):
        tasks = {f"draft/t{n}": task(f"t{n}", repo="fabrig") for n in range(11)}
        write(self.path, "")
        self.append(*(event("branch.landed", f"t{n}", into=self.plan.trunk, main=f"tip{n}", tip=f"task{n}",
                            ts=f"2026-11-01T10:{n:02d}:00Z") for n in range(10)))
        dispatch._integration(self.plan, tasks, self.home, self.hosts, sh=self.fake, log_path=self.path)
        check = log.read(self.path)[-1]
        self.assertEqual((check["kind"], check["mid"], check["base"]), ("check", True, "tip9"))
        launch = next(argv for argv in self.commands() if argv[:3] == ["fab", "check", "start"])
        self.assertIn("--default", launch)
        self.assertNotIn(["git", "reset", "-q", "--hard", f"origin/{self.plan.trunk}"], self.fake.argvs())

    def test_main_contained_or_replay_passes_none(self):
        for ready in (True, False):
            with self.subTest(ready=ready):
                self.fake.calls.clear()
                with patch.object(integration, "next_step", return_value=None) as next_step:
                    dispatch._integration(replace(self.plan, ready=ready), self.tasks, self.home, self.hosts,
                                          sh=self.fake, log_path=self.path)
                self.assertEqual(next_step.call_args.kwargs,
                                 {"main": None, "trunk": "fetched-trunk-tip" if ready else None, "caught": False})
                self.assertEqual(self.fake.argvs(), [["git", "merge-base", "--is-ancestor", "origin/main",
                                  f"origin/{self.plan.trunk}"],
                                  ["git", "rev-parse", f"origin/{self.plan.trunk}"]] if ready else [])

    def test_main_ancestry_error_is_not_treated_as_main_moving(self):
        self.fake.on(["git", "merge-base"], Result(128, err="missing trunk"))
        with patch.object(dispatch, "_catch_up") as catch, patch.object(dispatch, "_integration_check") as check:
            dispatch._integration(self.plan, self.tasks, self.home, self.hosts, sh=self.fake, log_path=self.path)
        catch.assert_not_called()
        check.assert_not_called()
        self.assertEqual(log.read(self.path)[-1]["ev"], "note")
        self.assertIn("missing trunk", log.read(self.path)[-1]["text"])
        self.assertIn("integration draft - failed:", self.output.getvalue())

    def test_next_step_error_before_a_step_prints_a_neutral_label(self):
        with patch.object(integration, "next_step", side_effect=ValueError("bad decision")):
            dispatch._integration(self.plan, self.tasks, self.home, self.hosts, sh=self.fake, log_path=self.path)
        self.assertIn("integration draft - failed: bad decision\n", self.output.getvalue())
        self.assertEqual(log.read(self.path)[-1]["text"], "failed: bad decision")

    def test_three_refusals_without_a_clean_catch_up_start_no_third_repair(self):
        self.fake.on(["git", "merge-base"], Result(1))
        self.fake.on(["git", "rev-parse", "origin/main"], Result(0, "main-3\n"))
        for n in range(1, 4):
            self.append(event("branch.rejected", task="draft/integration", branch="main", tip="trunk-tip",
                              step=integration.CATCH_UP, main=f"main-{n}"))
        actions = self.tick()
        self.assertFalse(any(action.kind == "start" for action in actions))
        self.assertFalse(any(entry.get("task") == "draft/catch-up-3" for entry in log.read(self.path)))
        self.assertIn("integration draft stop", self.output.getvalue())

    def test_stopped_catch_up_accepts_its_sha_by_hand_after_main_moves_again(self):
        held = {"sha": False}
        ancestry = ["git", "merge-base", "--is-ancestor", "main-1", f"origin/{self.plan.trunk}"]
        self.fake.on(ancestry, lambda call: Result(0 if held["sha"] else 1))
        self.fake.on(["git", "merge-base", "--is-ancestor", "main-1", "HEAD"], Result(1))
        self.fake.on(["git", "merge-base", "--is-ancestor", "origin/main"], Result(1))
        self.fake.on(["git", "rev-parse", "origin/main"], Result(0, "newer-main-sha\n"))
        self.append(event("branch.rejected", task="draft/integration", branch="main", tip="trunk-tip",
                          step=integration.CATCH_UP, main="main-1", findings="CONFLICT: Cargo.lock"))
        self.tick()
        self.append(run_ended("draft/catch-up-1"))
        self.tick()  # Its merge logs the stopping refusal: it did not contain main-1.
        self.assertIn("integration draft stop", self.output.getvalue())
        held["sha"] = True
        with patch.object(dispatch, "_catch_up") as catch:
            self.tick()
        catch.assert_not_called()
        self.assertIn(ancestry, self.fake.argvs())
        record, answer = log.read(self.path)[-2:]
        self.assertEqual({key: record[key] for key in ("ev", "task", "branch", "tip", "main", "into", "by")},
                         dict(ev="branch.landed", task="draft/integration", branch="main",
                              tip="main-1", main="fetched-trunk-tip", into=self.plan.trunk, by="hand"))
        self.assertEqual({key: value for key, value in answer.items() if key != "ts"},
                         dict(ev="question.answered", task="draft/integration",
                              answer="lifted by a clean catch-up", by="tick"))
        self.assertIn("integration draft caught", self.output.getvalue())
        with patch.object(dispatch, "_catch_up", return_value="newly-caught-tip") as catch:
            self.tick()
        catch.assert_called_once_with(self.plan, "fetched-trunk-tip", self.home, sh=self.fake, log_path=self.path)
        check = log.read(self.path)[-1]
        self.assertEqual((check["ev"], check["kind"], check["base"]), ("run.started", "check", "newly-caught-tip"))
        self.assertEqual(sum(entry.get("by") == "hand" for entry in log.read(self.path)), 1)

    def test_clean_catch_up_answers_only_the_catch_up_stop_once_across_ticks(self):
        for why in ("catch-up", "red", "queue"):
            for by in (None, "repair", "hand"):
                with self.subTest(why=why, by=by):
                    write(self.path, "")
                    self.append(event("branch.landed", into=self.plan.trunk, main="trunk-tip", tip="a-tip"),
                                dict(ev="plan.stopped", task="draft/integration", why=why),
                                dict(ev="question.asked", task="draft/integration", park=True, text="Judge."),
                                dict(ev="branch.landed", task="draft/integration", branch="main",
                                     into=self.plan.trunk, main="caught-tip", tip="main-sha", by=by))
                    with patch.object(dispatch, "_integration_check"), patch.object(dispatch, "_catch_up"):
                        self.tick()
                        self.tick()
                    answers = [{key: value for key, value in entry.items() if key != "ts"}
                               for entry in log.read(self.path) if entry["ev"] == "question.answered"]
                    self.assertEqual(answers, [dict(ev="question.answered", task="draft/integration",
                                     answer="lifted by a clean catch-up", by="tick")] if why == "catch-up" else [])

    def test_clean_catch_up_before_stop_or_before_lift_cannot_answer_a_new_stop(self):
        clean = dict(ev="branch.landed", task="draft/integration", branch="main", into=self.plan.trunk,
                     main="caught-tip", tip="main-sha")
        stop = dict(ev="plan.stopped", task="draft/integration", why="catch-up")
        for history in ([clean, stop], [stop, clean,
                         dict(ev="question.answered", task="draft/integration", answer="Manual lift."), stop]):
            with self.subTest(history=history):
                write(self.path, "")
                self.append(*history)
                dispatch._integration(self.plan, self.tasks, self.home, self.hosts,
                                      sh=self.fake, log_path=self.path)
                self.assertFalse(any(entry.get("by") == "tick" for entry in log.read(self.path)))

    def test_catch_up_refusal_starts_implement_repair_from_trunk_then_merges_and_checks(self):
        self.append(event("branch.rejected", task="draft/integration", branch="main", tip="trunk-tip",
                          step=integration.CATCH_UP, main="main-sha", findings="CONFLICT: skein/src/lib.rs"))
        loaded, tasks = dispatch._load_plan(self.directory, log.read(self.path))
        repair = tasks["draft/catch-up-1"]
        self.assertEqual((repair.kind, repair.path), ("repair", ""))
        self.assertIn("main-sha", repair.body)
        actions = self.tick()
        start, = [action for action in actions if action.kind == "start"]
        self.assertEqual((start.task, start.run_kind), ("draft/catch-up-1", "implement"))
        record = log.read(self.path)[-1]
        self.assertEqual((record["task"], record["base"], record["branch"]),
                         ("draft/catch-up-1", "origin/draft/integration", "draft/catch-up-1"))
        self.assertIn("CONFLICT: skein/src/lib.rs", (log.home() / "runs/draft/catch-up-1-1/brief.md").read_text())
        self.append(run_ended("draft/catch-up-1"))
        actions = self.tick()
        self.assertTrue(any(action.kind == "merge" and action.task == "draft/catch-up-1" for action in actions))
        check = log.read(self.path)[-1]
        self.assertEqual((check["kind"], check["base"]), ("check", "fixed-tip"))
        self.assertTrue(any(entry["ev"] == "branch.landed" and entry["task"] == "draft/catch-up-1"
                            and entry["into"] == self.plan.trunk for entry in log.read(self.path)))

    def test_four_conflicting_main_moves_each_log_a_checked_repair_and_never_stop(self):
        # Drive real catch-up refusals and task merges; only git and builders are faked.
        current = {"sha": "", "caught": True}
        self.fake.on(["git", "rev-parse", "origin/main"], lambda call: Result(0, current["sha"]))
        self.fake.on(["git", "merge-base"],
                     lambda call: Result(0 if call.argv[-2] != "origin/main" or current["caught"] else 1))
        self.fake.on([*dispatch.FAB_GIT, "merge"],
                     lambda call: Result(1, "CONFLICT: Cargo.lock") if call.argv[-1] == current["sha"] else Result(0))
        for n in range(1, 5):
            with self.subTest(move=n), patch.object(dispatch, "_integration_check"):
                current.update(sha=f"main-{n}", caught=False)
                self.assertIsNone(dispatch._catch_up(self.plan, "fixed-tip", self.home,
                                                    sh=self.fake, log_path=self.path))
                actions = self.tick()
                start, = [action for action in actions if action.kind == "start"]
                self.assertEqual((start.task, start.run_kind), (f"draft/catch-up-{n}", "implement"))
                self.append(run_ended(start.task))
                current["caught"] = True
                actions = self.tick()
                self.assertTrue(any(action.kind == "merge" and action.task == start.task for action in actions))
                records = log.read(self.path)
                clean, = [entry for entry in records if entry.get("by") == "repair" and entry["tip"] == current["sha"]]
                self.assertEqual({key: clean[key] for key in ("ev", "task", "branch", "main", "into")},
                                 dict(ev="branch.landed", task="draft/integration", branch="main",
                                      main="fixed-tip", into=self.plan.trunk))
                index = records.index(clean)
                self.assertEqual(records[index - 1]["task"], start.task)
                ancestry = ["git", "merge-base", "--is-ancestor", current["sha"], "HEAD"]
                self.assertIn(ancestry, self.fake.argvs())
                call = next(call for call in self.fake.calls if call.argv == ancestry)
                self.assertEqual(call.cwd, str(self.home))
                self.assertIsNone(integration.catch_up_waiting(self.plan, records))
                tasks = integration.with_repairs(self.plan, self.tasks, records)
                self.assertEqual(integration.next_step(self.plan, tasks, records).kind, "check")
        self.assertEqual(sum(entry.get("by") == "repair" for entry in log.read(self.path)), 4)
        self.assertNotIn("integration draft stop", self.output.getvalue())

    def test_repair_merged_without_its_main_sha_logs_refusal_and_stops_at_once(self):
        ancestry = ["git", "merge-base", "--is-ancestor", "main-sha", "HEAD"]
        self.fake.on(ancestry, Result(1))
        waiting = ["git", "merge-base", "--is-ancestor", "main-sha", f"origin/{self.plan.trunk}"]
        self.fake.on(waiting, Result(1))
        self.append(event("branch.rejected", task="draft/integration", branch="main", tip="trunk-tip",
                          step=integration.CATCH_UP, main="main-sha", findings="CONFLICT: Cargo.lock"))
        self.tick()
        self.append(run_ended("draft/catch-up-1"))
        with patch.object(dispatch, "_catch_up") as catch, patch.object(dispatch, "_integration_check") as check:
            self.tick()
        catch.assert_not_called()
        check.assert_not_called()
        records = log.read(self.path)
        refusal, = [entry for entry in records if entry.get("ev") == "branch.rejected" and entry["tip"] == "fixed-tip"]
        self.assertEqual({key: refusal[key] for key in ("task", "branch", "step", "main")},
                         dict(task="draft/integration", branch="main", step=integration.CATCH_UP, main="main-sha"))
        self.assertIn("draft/catch-up-1 merged without main sha main-sha", refusal["findings"])
        self.assertEqual(records[records.index(refusal) - 1]["task"], "draft/catch-up-1")
        self.assertFalse(any(entry.get("by") == "repair" for entry in records))
        self.assertEqual(list(integration.repair_tasks(self.plan, records, {})), ["draft/catch-up-1"])
        self.assertEqual(integration.catch_up_waiting(self.plan, records), "main-sha")
        self.assertIn("integration draft stop", self.output.getvalue())
        # A later tick still waits for the refused sha, despite containing current main.
        self.tick()
        self.assertFalse(any(entry.get("by") == "hand" for entry in log.read(self.path)))

    def test_catch_up_repair_ancestry_error_leaves_its_merge_retryable(self):
        answer = {"code": 128}
        ancestry = ["git", "merge-base", "--is-ancestor", "main-sha", "HEAD"]
        self.fake.on(ancestry, lambda call: Result(answer["code"], err="ancestry unavailable"))
        self.append(event("branch.rejected", task="draft/integration", branch="main", tip="trunk-tip",
                          step=integration.CATCH_UP, main="main-sha", findings="CONFLICT: Cargo.lock"))
        self.tick()
        self.append(run_ended("draft/catch-up-1"))
        self.tick()
        records = log.read(self.path)
        self.assertFalse(any(entry.get("ev") == "branch.landed" and entry.get("task") == "draft/catch-up-1"
                             for entry in records))
        self.assertEqual(sum(entry["ev"] == "branch.rejected" for entry in records), 1)
        self.assertFalse(any(argv[:2] == ["git", "push"] for argv in self.fake.argvs()))
        self.assertIn("ancestry unavailable", self.output.getvalue())
        answer["code"] = 0
        self.tick()
        self.assertEqual(sum(entry.get("by") == "repair" for entry in log.read(self.path)), 1)
        self.assertEqual(sum(argv[:2] == ["git", "push"] for argv in self.fake.argvs()), 1)

    def test_catch_up_repair_question_skips_foreman_and_report_answer_reaches_next_brief(self):
        self.append(event("branch.rejected", task="draft/integration", branch="main", tip="trunk-tip",
                          step=integration.CATCH_UP, main="main-sha", findings="CONFLICT: skein/src/lib.rs"))
        self.tick()
        self.append(run_ended("draft/catch-up-1", outcome="question"),
                    event("question.asked", task="draft/catch-up-1", run="draft/catch-up-1-1",
                          text="Keep both formats?"))
        with patch.object(foreman, "start", side_effect=AssertionError("unexpected foreman")) as foreman_start:
            actions = self.tick()
        foreman_start.assert_not_called()
        self.assertIn(Action("call", task="draft", run_kind="answer"), actions)
        self.assertFalse(any(action.kind == "foreman" for action in actions))
        self.append(call_started("answer-1", "answer", "draft"), call_ended("answer-1"))
        write(log.home() / "calls/answer-1/report.md",
              "Done: answered\nAnswer draft/catch-up-1: Keep both formats and add a fixture.\n"
              "Answered: draft/catch-up-1\n")
        dispatch._finish(Action("finish", task="answer-1"), log_path=self.path)
        answer = log.read(self.path)[-1]
        self.assertEqual((answer["ev"], answer["task"], answer["answer"]),
                         ("question.answered", "draft/catch-up-1", "Keep both formats and add a fixture."))
        # The answer call is finished before another tick can deliver it.
        self.append(dict(ev="call.finished", call="answer-1", role="answer", outcome="done"))
        self.tick()
        brief = (log.home() / "runs/draft/catch-up-1-2/brief.md").read_text()
        self.assertIn("## Answers\n\n- Keep both formats and add a fixture.", brief)

    def test_collect_failed_check_keeps_report_releases_slot_then_starts_repair(self):
        self.tick()
        report = "Failed: fmt red\nfmt:1:0.1\n/check.log\n"
        current = dict(ended=True, report=report, outcome="failed", tokens=None)
        original = self.fake.rules[0][1]
        def remote(call):
            argv = shlex.split(shlex.split(call.argv[-1])[2])
            if argv[:3] == ["fab", "slot", "release"]:
                return Result(0, "0\n")
            return original(call)
        self.fake.rules[0] = (["ssh"], remote)
        with patch.object(runs, "status", return_value=current):
            self.tick()
        collected = [entry for entry in log.read(self.path) if entry["ev"] == "run.ended"]
        self.assertEqual(len(collected), 1)
        self.assertEqual((collected[0]["task"], collected[0]["outcome"], collected[0]["freed"]),
                         ("draft/integration", "failed", 0))
        self.assertEqual((log.home() / "runs/draft/integration-1/report.md").read_text(), report)
        self.assertIn(["fab", "slot", "release", "2", "draft/integration-1"], self.commands())
        self.tick()
        self.assertEqual(log.read(self.path)[-1]["task"], "draft/repair-1")

    def test_green_without_ready_starts_nothing_more(self):
        self.plan = replace(self.plan, ready=False)
        self.tick()
        self.append(run_ended("draft/integration"))
        before = log.read(self.path)
        self.tick()
        self.tick()
        self.assertEqual(log.read(self.path), before)
        self.assertFalse(any(argv[:3] == ["git", "push", "origin"] for argv in self.fake.argvs()))

    def test_green_readies_trunk_once(self):
        self.tick()
        self.append(run_ended("draft/integration"))
        self.tick()
        self.tick()
        readied = [entry for entry in log.read(self.path) if entry["ev"] == "branch.ready"]
        self.assertEqual(len(readied), 1)
        self.assertEqual((readied[0]["task"], readied[0]["branch"], readied[0]["tip"]),
                         ("draft/integration", self.plan.trunk, "trunk-tip"))
        self.assertEqual(self.fake.argvs().count(["git", "push", "origin", "trunk-tip:refs/heads/ready/draft/integration"]), 1)

    def test_a_queue_rejection_rechecks_then_untries_and_readies_again(self):
        self.hosts["gate"] = Host("gate", "fake@gate", ("gate",))
        self.tick()
        self.append(run_ended("draft/integration"))
        self.tick()
        self.append(event("branch.rejected", task="draft/integration", branch=self.plan.trunk,
                          tip="trunk-tip", step="default", queue_ts="2026-10-31T00:00:00.000Z"))
        self.tick()
        started = [entry for entry in log.read(self.path) if entry["ev"] == "run.started"]
        self.assertEqual([entry["base"] for entry in started], ["trunk-tip", "trunk-tip"])
        self.assertIn(["git", "merge-base", "--is-ancestor", "origin/main", "HEAD"], self.fake.argvs())
        self.append(run_ended("draft/integration", 2))
        self.tick()
        self.assertIn(["fab", "queue", "untry", self.plan.trunk], self.commands())
        readied = [entry["tip"] for entry in log.read(self.path) if entry["ev"] == "branch.ready"]
        self.assertEqual(readied, ["trunk-tip", "trunk-tip"])

    def test_failed_launch_releases_claimed_slot(self):
        with patch.object(runs, "launch", side_effect=ValueError("bad launch")):
            self.tick()
        self.assertIn(["fab", "slot", "release", "2", "draft/integration-1"], self.commands())
        self.assertFalse(any(entry["ev"] == "run.started" for entry in log.read(self.path)))
        self.assertIn("integration draft check failed: bad launch", self.output.getvalue())

    def test_unreadable_report_still_generates_repair(self):
        self.append(run_started("draft/integration", kind="check", base="trunk-tip"),
                    run_ended("draft/integration", outcome="failed"))
        tasks = dispatch._load_plan(self.directory, log.read(self.path))[1]
        self.assertIn("draft/repair-1", tasks)
        self.assertIn("`trunk-tip`", tasks["draft/repair-1"].body)

    def test_third_red_records_stop_then_parked_question_once_across_ticks(self):
        for n in range(1, 4):
            self.append(run_started("draft/integration", n, kind="check", base="trunk-tip"),
                        run_ended("draft/integration", n, "failed"))
        self.tick()
        self.tick()
        records = log.read(self.path)
        stops = [entry for entry in records if entry["ev"] in ("plan.stopped", "question.asked")]
        self.assertEqual([{key: value for key, value in entry.items() if key != "ts"} for entry in stops], [
            dict(ev="plan.stopped", task="draft/integration", tip="trunk-tip", why="red",
                 text="red 3 times; needs judgement",
                 report=str(log.home() / "runs/draft/integration-3/report.md")),
            dict(ev="question.asked", task="draft/integration", run="draft/integration-3",
                 text="red 3 times; needs judgement", park=True)])
        self.assertFalse(any(entry["ev"] == "note" for entry in records))
        self.assertEqual([entry["run"] for entry in records if entry["ev"] == "run.started"],
                         [f"draft/integration-{n}" for n in range(1, 4)])

    def test_tick_starts_answer_call_when_the_stop_is_the_only_question(self):
        for n in range(1, 4):
            self.append(run_started("draft/integration", n, kind="check", base="trunk-tip"),
                        run_ended("draft/integration", n, "failed"))
        self.tick()
        with patch.object(dispatch, "decide", wraps=dispatch.decide) as decide:
            actions = self.tick()
        decide.assert_called_once()
        self.assertEqual([action for action in actions if action.kind == "call"],
                         [Action("call", task="draft", run_kind="answer")])
        self.assertTrue(any(argv[:2] == ["systemd-run", "--user"]
                            and argv[-5:-3] == ["call", "answer"] for argv in self.fake.argvs()))
        self.assertEqual([entry["task"] for entry in log.read(self.path) if entry["ev"] == "question.asked"],
                         ["draft/integration"])

    def test_queue_stop_report_uses_first_gate_by_name_or_empty_without_gates(self):
        for gates_present in (True, False):
            with self.subTest(gates_present=gates_present):
                path = self.home / f"queue-stop-{gates_present}.jsonl"
                for entry in [event("branch.landed", into=self.plan.trunk, main="trunk-tip", tip="a-tip"),
                              run_started("draft/integration", kind="check", base="trunk-tip"),
                              run_ended("draft/integration")]:
                    log.append(path=path, **entry)
                for n in range(3):
                    log.append("branch.rejected", path=path, task="draft/integration", queue_ts=str(n),
                               log=f"/queue/check-{n}.log")
                hosts = {**self.hosts, "z-gate": Host("z-gate", "fake@z", ("gate",)),
                         "a-gate": Host("a-gate", "fake@a", ("gate",))} if gates_present else self.hosts
                dispatch._integration(self.plan, self.tasks, self.home, hosts, sh=self.fake, log_path=path)
                records = log.read(path)
                self.assertEqual(records[-2]["ev"], "plan.stopped")
                self.assertEqual(records[-2]["report"], ("a-gate" if gates_present else "") + ":/queue/check-2.log")
                self.assertEqual((records[-1]["ev"], records[-1]["run"], records[-1]["park"]),
                                 ("question.asked", "", True))

    def test_import_queue_accepts_integration_landing_without_a_spec(self):
        gate = Host("gate", "fake@gate", ("gate",))
        fake = FakeRunner().on(["ssh"], Result(0, json.dumps(dict(ts="now", ev="landed",
                    branch=self.plan.trunk, tip="trunk-tip", main="main-tip")) + "\n"))
        dispatch._import_queue(self.tasks, [], {"gate": gate}, sh=fake, log_path=self.path, plan_drafts=["draft"])
        landed = log.read(self.path)[-1]
        self.assertEqual((landed["ev"], landed["task"], landed["main"]),
                         ("branch.landed", "draft/integration", "main-tip"))
        self.assertNotIn("into", landed)


class ReplayFindingsTest(unittest.TestCase):
    """The playground replay's fixes (11-01): repair answers through answer calls, and starts
    that move on when a builder's slots are all held by other work."""

    def test_answered_reads_the_answer_lines_of_specless_tasks(self):
        with tmp_home():
            write(log.home() / "calls/answer-1/report.md",
                  "Done: 2\n- d/a: B\nAnswer d/repair-2: Add the empty-store fixture.\n"
                  "Answer bad line\nAnswered: d/a d/repair-2\n")
            chain = call_review.Chain("answer-1", "answer", "d", "calls/answer-1", ("answer-1",), "answer-1", (),
                                      "finished")
            names, given = dispatch._answered(chain)
        self.assertEqual(names, ["d/a", "d/repair-2"])
        self.assertEqual(given, {"d/repair-2": "Add the empty-store fixture."})

    def test_a_start_moves_to_the_next_builder_when_slots_are_full(self):
        hosts = {"one": Host("one", "f@one", ("builder",), places=7),
                 "two": Host("two", "f@two", ("builder",), places=7),
                 "none": Host("none", "f@none", ("builder",), places=0)}
        tasks = {"d/a": plan.Task("d/a", "core", "feature", "fabrig", (), (), "high", 20, "", "a.md")}
        loaded = plan.Plan("d", "fabrig", (), 1, 2, {}, (), landing="integration")
        tried = []

        def start(task, host, **kwargs):
            tried.append(host.name)
            if host.name == "one":
                raise ValueError("one: no idle slot")
            return "d/a-1"

        action = Action("start", task="d/a", host="one", run_kind="implement")
        with tmp_home(), patch.object(runs, "start", side_effect=start):
            dispatch._start(action, tasks, hosts, plan=loaded, checkout=Path("."), sh=FakeRunner(),
                            log_path=None)
            self.assertEqual(tried, ["one", "two"])
            tried.clear()
            with patch.object(runs, "start", side_effect=ValueError("one: something else")):
                with self.assertRaises(ValueError):
                    dispatch._start(action, tasks, hosts, plan=loaded, checkout=Path("."),
                                    sh=FakeRunner(), log_path=None)


class EarlyStartTest(unittest.TestCase):
    """Early starts (docs/design/fab-integration.md, 3): a task may start from the pushed work of a need
    that is still running, one level deep, and merges only after its needs have."""

    PLAN = plan.Plan("draft", "fabrig", (), 1, 2, {}, (), landing="integration")
    HOSTS = {"builder": Host("builder", "fake@builder", ("builder",), places=4)}

    def setUp(self):
        self.tasks = {t.id: t for t in (task("a", repo="fabrig"), task("b", repo="fabrig", needs=("draft/a",)),
                                         task("c", repo="fabrig", needs=("draft/b",)))}

    def test_a_task_starts_early_on_a_running_need_that_pushed(self):
        events = [started(branch="draft/a")]
        views = state.fold(self.tasks, events)
        self.assertEqual(dispatch.early_starts(self.PLAN, self.tasks, views, events, frozenset({"draft/a"})),
                         {"draft/b": (("draft/a", "draft/a"),)})
        self.assertEqual(dispatch.early_starts(self.PLAN, self.tasks, views, events, frozenset()), {})
        self.assertEqual(dispatch.early_starts(replace(self.PLAN, early=False), self.tasks, views, events,
                                               frozenset({"draft/a"})), {})
        refused = events + [event("early.refused", "b", needs=["draft/a"])]
        self.assertEqual(dispatch.early_starts(self.PLAN, self.tasks, state.fold(self.tasks, refused), refused,
                                               frozenset({"draft/a"})), {})
        actions = dispatch.decide(self.PLAN, self.tasks, events, self.HOSTS, pushed=frozenset({"draft/a"}))
        start, = [action for action in actions if action.kind == "start"]
        self.assertEqual((start.task, start.early), ("draft/b", (("draft/a", "draft/a"),)))

    def test_one_early_start_per_task_and_an_answer_waits_for_the_need(self):
        events = [started(branch="draft/a"), dict(started("b", branch="draft/b"), early=["draft/a"]),
                  ended("b", outcome="question"), event("question.asked", "b", text="Is a done?"),
                  event("question.answered", "b")]
        views = state.fold(self.tasks, events)
        self.assertEqual(views["draft/b"].status, "waiting")
        self.assertEqual(dispatch.early_starts(self.PLAN, self.tasks, views, events, frozenset({"draft/a"})), {})
        landed = events + [ended("a"), event("branch.landed", "a", tip="t", main="m", into="draft/integration")]
        self.assertEqual(state.fold(self.tasks, landed)["draft/b"].status, "runnable")

    def test_a_failed_early_run_reruns_once_its_needs_merge(self):
        events = [started(branch="draft/a"), dict(started("b", branch="draft/b"), early=["draft/a"]),
                  ended("b", outcome="failed")]
        self.assertEqual(state.fold(self.tasks, events)["draft/b"].status, "waiting")
        landed = events + [ended("a"), event("branch.landed", "a", tip="t", main="m", into="draft/integration")]
        self.assertEqual(state.fold(self.tasks, landed)["draft/b"].status, "runnable")
        # A failed run that did not start early still parks for judgement.
        plain = landed + [started("b", n=2, branch="draft/b"), ended("b", n=2, outcome="failed")]
        self.assertEqual(state.fold(self.tasks, plain)["draft/b"].status, "parked")

    def test_a_failed_run_with_no_question_is_parked_for_the_answerer(self):
        events = [started(branch="draft/a"), ended(outcome="failed")]
        parks = [a for a in dispatch.decide(self.PLAN, self.tasks, events, self.HOSTS) if a.kind == "park"]
        self.assertEqual([(a.task, a.run) for a in parks], [("draft/a", "draft/a-1")])
        self.assertIn("report.md", parks[0].detail)
        asked = events + [event("question.asked", run="draft/a-1", text=parks[0].detail, park=True)]
        self.assertFalse([a for a in dispatch.decide(self.PLAN, self.tasks, asked, self.HOSTS) if a.kind == "park"])
        answered = asked + [event("question.answered")]
        self.assertIn("start", [a.kind for a in dispatch.decide(self.PLAN, self.tasks, answered, self.HOSTS)])

    def test_one_level_only(self):
        # b runs early on a; c may not start on b while b still waits for a.
        events = [started(branch="draft/a"), started("b", branch="draft/b")]
        views = state.fold(self.tasks, events)
        self.assertEqual(dispatch.early_starts(self.PLAN, self.tasks, views, events,
                                               frozenset({"draft/a", "draft/b"})), {})

    def test_an_early_task_merges_only_after_its_needs(self):
        events = [started(branch="draft/a"), started("b", branch="draft/b"), ended("b")]
        kinds = [action.kind for action in dispatch.decide(self.PLAN, self.tasks, events, self.HOSTS)]
        self.assertNotIn("merge", kinds)
        events += [ended("a"), event("branch.landed", "a", tip="t", main="m", into="draft/integration")]
        merges = [action.task for action in dispatch.decide(self.PLAN, self.tasks, events, self.HOSTS)
                  if action.kind == "merge"]
        self.assertEqual(merges, ["draft/b"])

    def test_a_refused_early_start_is_logged_and_waits(self):
        action = Action("start", task="draft/b", host="builder", run_kind="implement",
                        early=(("draft/a", "draft/a"),))
        with tmp_home(), patch.object(runs, "start", side_effect=ValueError("early: draft/a's pushed work conflicts")):
            dispatch._start(action, self.tasks, self.HOSTS, plan=self.PLAN, checkout=Path("."), sh=FakeRunner(),
                            log_path=None)
            refused, = log.read()
        self.assertEqual((refused["ev"], refused["task"], refused["needs"]), ("early.refused", "draft/b", ["draft/a"]))


class RedDispatchTest(unittest.TestCase):
    def test_red_dispatch_fix_failures_are_noted_and_retried(self):
        output = io.StringIO()
        with patch.object(tier_reds, "start", side_effect=ValueError("launch\nfailed")), redirect_stdout(output):
            actions = self.open()
        examine, = [a for a in actions if a.kind == "examine-fix"]
        self.assertEqual(examine.run_kind, "red")
        note = log.read(self.path)[-1]
        self.assertEqual((note["ev"], note["text"]),
                         ("note", "examine-fix draft/red-1 failed: launch failed"))
        self.assertEqual(output.getvalue().splitlines().count(note["text"]), 1)
        self.assertIn(examine, self.tick())
        output = io.StringIO()
        with patch.object(tier_reds, "settle", side_effect=ValueError("settlement\nfailed")), redirect_stdout(output):
            actions = self.finish_foreman()
        remedy, = [a for a in actions if a.kind == "remedy-fix"]
        self.assertEqual(remedy.run_kind, "red")
        note = log.read(self.path)[-1]
        self.assertEqual((note["ev"], note["text"]),
                         ("note", "remedy-fix draft/red-1 failed: settlement failed"))
        self.assertEqual(output.getvalue().splitlines().count(note["text"]), 1)
        self.assertIn(remedy, self.tick())
        self.assertEqual(sum(e["ev"] == "red.settled" for e in log.read(self.path)), 1)

    def test_red_dispatch_unreadable_foreman_report_settles_none(self):
        self.open()
        self.append(dict(ev="run.ended", task="draft/red-1/foreman", run="draft/red-1/foreman-1",
                         outcome="done", report=str(self.home / "missing-report.md")))
        actions = self.tick()
        self.assertTrue(any(a.kind == "remedy-fix" and a.run_kind == "red" for a in actions))
        record, = [e for e in log.read(self.path) if e["ev"] == "red.settled"]
        self.assertEqual((record["verdict"], record["section"]), ("none", ""))
        self.assertTrue(any(a.kind == "start" and a.task == "draft/red-1" for a in self.tick()))

    def test_red_dispatch_foreman_collected_this_round_settles_once(self):
        self.open()
        report_path = log.home() / "runs/draft/red-1/foreman-1/report.md"
        write(report_path, "Done: fix: fix the check\n")
        def collect(run_id, events, hosts, **kwargs):
            self.append(dict(ev="run.ended", task="draft/red-1/foreman", run=run_id,
                             outcome="done", report=str(report_path)))
        with patch.object(runs, "collect", side_effect=collect):
            actions = self.tick()
        self.assertEqual(sum(a.kind == "remedy-fix" for a in actions), 1)
        self.tick()
        self.assertEqual(sum(e["ev"] == "red.settled" for e in log.read(self.path)), 1)

    def test_red_dispatch_queue_rejections_reach_red_tasks_in_both_modes(self):
        for landing in ("queue", "integration"):
            with self.subTest(landing=landing):
                self.plan = replace(self.plan, landing=landing)
                write(self.path, "")
                self.open()
                self.finish_foreman()
                self.tick()
                self.queue_records = [dict(ev="rejected", ts="queue-1", branch="draft/red-1-r2", tip="repair",
                                           step="default", log="/queue.log")]
                self.tick()
                rejected, = [e for e in log.read(self.path) if e["ev"] == "branch.rejected"]
                self.assertEqual((rejected["task"], rejected["branch"]), ("draft/red-1", "draft/red-1-r2"))
                self.queue_records = []

    def test_red_dispatch_answer_report_folds_into_the_next_brief(self):
        self.open()
        self.finish_foreman()
        self.tick()
        self.append(dict(ev="run.ended", task="draft/red-1", run="draft/red-1-1", outcome="question"),
                    dict(ev="question.asked", task="draft/red-1", run="draft/red-1-1", text="Which fix?"),
                    dict(ev="call.started", call="answer-red", role="answer", subject="draft", branch="calls/answer-red"),
                    dict(ev="call.ended", call="answer-red", outcome="done"))
        write(log.home() / "calls/answer-red/report.md",
              "Done: answered\nAnswered: red-1\nAnswer red-1: Reproduce in the unit tier.\n")
        dispatch._finish(Action("finish", task="answer-red"), log_path=self.path)
        answered = log.read(self.path)[-1]
        self.assertEqual((answered["ev"], answered["task"], answered["answer"]),
                         ("question.answered", "draft/red-1", "Reproduce in the unit tier."))
        self.tick()
        self.assertIn("## Answers\n\n- Reproduce in the unit tier.",
                      (log.home() / "runs/draft/red-1-2/brief.md").read_text())

    def test_red_dispatch_decisions_are_pure_and_closed_reds_take_no_action(self):
        from fab.tests.test_tier_reds import opened
        red = tier_reds.reds([opened(draft="draft")])[0]
        decided = replace(red, state="decided", foreman="draft/red-1/foreman-1")
        closed = replace(red, id="red-2", state="closed")
        foreign = replace(red, id="red-3", draft="other")
        folded = [red, decided, closed, foreign]
        before = deepcopy(folded)
        self.assertEqual(dispatch.red_actions(self.plan, folded),
                         [Action("examine-fix", task="draft/red-1", detail="red-1", run_kind="red"),
                          Action("remedy-fix", task="draft/red-1", run="draft/red-1/foreman-1", detail="red-1", run_kind="red")])
        self.assertEqual(folded, before)

    def test_red_dispatch_retire_ignores_unrecognized_branch_names(self):
        for last_branch, checked_branch in (("manual", "unrelated"),
                                            ("manual", "draft/a"), ("draft/a", "manual")):
            with self.subTest(last_branch=last_branch, checked_branch=checked_branch):
                events = [dict(ev="branch.landed", task="draft/a", branch=last_branch),
                          dict(ev="tiers.run", branches=[checked_branch], reds=[])]
                self.assertFalse(dispatch.retire_ready(self.plan, self.tasks, events, [], after_landing=True))

    def test_red_dispatch_retire_uses_main_verdict_even_if_queue_import_lags(self):
        for landing in ("queue", "integration"):
            with self.subTest(landing=landing):
                the_plan = replace(self.plan, landing=landing)
                subject = "draft/integration" if landing == "integration" else "draft/a"
                landed = dict(ev="branch.landed", task=subject, branch=subject + "-r2", main="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
                verdict = dict(ev="tiers.run", branches=[subject + "-r2"], reds=[])
                self.assertFalse(dispatch.retire_ready(the_plan, self.tasks, [landed], [], after_landing=True))
                self.assertTrue(dispatch.retire_ready(the_plan, self.tasks, [verdict, landed], [], after_landing=True))
                self.assertTrue(dispatch.retire_ready(the_plan, self.tasks, [landed], [], after_landing=False))
                from fab.tests.test_tier_reds import opened
                red = tier_reds.reds([opened(draft="draft")])[0]
                for status in ("foreman", "deciding", "decided", "repairing", "landed"):
                    self.assertFalse(dispatch.retire_ready(the_plan, self.tasks, [verdict, landed],
                                                          [replace(red, state=status)], after_landing=True))
                for status in ("signal", "closed"):
                    self.assertTrue(dispatch.retire_ready(the_plan, self.tasks, [verdict, landed],
                                                         [replace(red, state=status)], after_landing=True))

    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.directory = write_plan(self.home / "plan", "draft", tasks=("a",), repo="fabrig")
        self.plan, self.tasks = plan.load(self.directory)
        self.plan = replace(self.plan, direct=True, reviews=False, low=0)
        self.path = self.home / "events.jsonl"
        self.hosts = {"builder": Host("builder", "fake@builder", ("builder",), places=2),
                      "other": Host("other", "fake@other", ("builder",), places=1),
                      "tiers": Host("tiers", "fake@tiers", ("after-landing",)),
                      "gate": Host("gate", "fake@gate", ("gate",))}
        self.queue_records, self.tier_records = [], []
        self.fake = FakeRunner().on(["ssh"], self.remote)
        self.fake.on(["git", "rev-parse", "--verify"], Result(0, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"))
        self.enterContext(patch.object(flow, "measure", return_value={}))
        self.enterContext(patch.object(dispatch, "_check_calls"))
        self.enterContext(patch.object(dispatch, "_integration"))
        self.enterContext(patch.object(dispatch, "_page"))
        self.enterContext(patch.object(runs, "collect", return_value=None))
        self.enterContext(patch.object(rust_gates, "screen", return_value=[]))
        self.enterContext(redirect_stdout(io.StringIO()))
        self.append(dict(ev="branch.landed", task="draft/a", branch="draft/a", tip="a-tip", main="tip"))

    def append(self, *events):
        for record in events:
            log.append(path=self.path, **record)

    def remote(self, call):
        argv = shlex.split(shlex.split(call.argv[-1])[2])
        if argv[:3] == ["fab", "queue", "log"]:
            return Result(0, "\n".join(json.dumps(record) for record in self.queue_records))
        if argv[:3] == ["fab", "after-landing", "log"]:
            return Result(0, "\n".join(json.dumps(record) for record in self.tier_records))
        if argv[:1] == ["git"] and "rev-parse" in argv and "-q" in argv:
            return Result(1)
        if argv[:1] == ["cat"] and argv[-1].endswith("/precheck/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.json"):
            return Result(0, json.dumps(dict(tip="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", main="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", outcome="green",
                                            selection="full", steps=["default:0:1"])) + "\n")
        if argv == ["fab", "slot", "list"]:
            return Result(0, json.dumps(dict(slot=1, claim=None, idle=0)) + "\n")
        if argv[:3] == ["fab", "codex", "start"]:
            return Result(0, "codex-red /state/red\n")
        return Result(0)

    def tick(self, *, only=False):
        loaded = [(self.plan, self.tasks, self.directory, self.home)]
        with patch.object(dispatch, "_load_plans", return_value=(loaded, [])):
            return dispatch._round([self.directory], sh=self.fake, hosts=self.hosts,
                                   log_path=self.path, only=only)

    def red_records(self, count=1, *, tip="tip"):
        records = [dict(ev="tiers.red", key=f"key-{n}", tip=tip, branches=["draft/a"])
                   for n in range(count)]
        return [*records, dict(ev="tiers.run", tip=tip, branches=["draft/a"],
                               reds=[record["key"] for record in records], starved=0, unobserved=0)]

    def open(self, count=1):
        self.append(*self.red_records(count))
        return self.tick()

    def finish_foreman(self, outcome="done", report="Done: fix: fix the red\nwhere to fix\n"):
        run_id = "draft/red-1/foreman-1"
        report_path = log.home() / "runs" / run_id / "report.md"
        write(report_path, report)
        self.append(dict(ev="run.ended", task="draft/red-1/foreman", run=run_id,
                         outcome=outcome, report=str(report_path)))
        return self.tick()

    def commands(self):
        return [shlex.split(shlex.split(call.argv[-1])[2])
                for call in self.fake.calls if call.argv[:1] == ["ssh"]]

    def test_red_dispatch_twelve_reds_start_one_foreman_even_at_zero_places(self):
        self.hosts["builder"] = replace(self.hosts["builder"], places=0)
        self.hosts["other"] = replace(self.hosts["other"], places=0)
        actions = self.open(12)
        self.assertEqual([(a.kind, a.task) for a in actions if a.kind == "examine-fix"],
                         [("examine-fix", "draft/red-1")])
        records = log.read(self.path)
        opened, = [e for e in records if e["ev"] == "red.opened"]
        self.assertEqual(len(opened["keys"]), 12)
        started, = [e for e in records if e["ev"] == "run.started"]
        self.assertEqual((started["kind"], started["host"], started["base"]), ("foreman", "builder", "tip"))
        self.assertIn("Your checkout is fabrig at tip, read-only.",
                      (log.home() / "runs/draft/red-1/foreman-1/brief.md").read_text())
        self.assertFalse(any(a.kind == "examine-fix" for a in self.tick()))

    def test_red_dispatch_fix_runs_from_main_and_readies_in_both_landing_modes(self):
        for landing in ("queue", "integration"):
            with self.subTest(landing=landing):
                self.plan = replace(self.plan, landing=landing)
                write(self.path, "")
                self.append(dict(ev="branch.landed", task="draft/a", branch="draft/a", tip="a-tip", main="tip",
                                 **({"into": self.plan.trunk} if landing == "integration" else {})))
                self.open()
                self.finish_foreman()
                actions = self.tick()
                start, = [a for a in actions if a.kind == "start"]
                self.assertEqual((start.task, start.run_kind), ("draft/red-1", "implement"))
                started = [e for e in log.read(self.path) if e["ev"] == "run.started"][-1]
                self.assertEqual((started["base"], started["branch"], started["slot"]),
                                 ("origin/main", "draft/red-1", 1))
                brief = (log.home() / "runs/draft/red-1-1/brief.md").read_text()
                self.assertIn("fix the red", brief)
                self.assertIn("precheck --onto origin/main", brief)
                self.assertNotIn("- Trunk:", brief)
                self.assertTrue(any(argv[-4:] == ["--discard-changes", "-C", "draft/red-1", "origin/main"]
                                    for argv in self.commands()))
                self.append(dict(ev="run.ended", task=start.task, run=started["run"], outcome="done"))
                actions = self.tick()
                self.assertEqual([(a.kind, a.task) for a in actions if a.kind in ("ready", "merge")],
                                 [("ready", "draft/red-1")])
                ready = [e for e in log.read(self.path) if e["ev"] == "branch.ready"][-1]
                self.assertEqual((ready["task"], ready["branch"], ready["tip"]),
                                 ("draft/red-1", "draft/red-1", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"))
                push = ["git", "push", "origin", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:refs/heads/ready/draft/red-1"]
                accept = ssh("fake@gate", ["fab", "queue", "receipt", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"])
                self.assertIn(push, self.fake.argvs())
                self.assertLess(self.fake.argvs().index(accept), self.fake.argvs().index(push))
                receipt = json.loads(next(call.input for call in self.fake.calls if call.argv == accept))
                self.assertEqual(receipt["main"], "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")

    def test_red_dispatch_left_starts_no_repair_and_failed_foreman_falls_back(self):
        self.open()
        self.finish_foreman(report="Done: retry: environment fault\n")
        self.assertFalse(any(a.kind == "start" for a in self.tick()))
        self.assertEqual(tier_reds.reds(log.read(self.path))[0].state, "signal")
        write(self.path, "")
        self.append(dict(ev="branch.landed", task="draft/a", tip="a", main="tip"))
        self.open()
        actions = self.finish_foreman(outcome="infra")
        self.assertFalse(any(e["ev"] == "red.settled" for e in log.read(self.path)))
        self.assertTrue(any(a.kind == "start" and a.task == "draft/red-1" for a in actions))
        self.assertNotIn("## Repair (", (log.home() / "runs/draft/red-1-1/brief.md").read_text())

    def test_red_dispatch_closed_unstarted_task_drops_and_new_tip_can_open_same_key(self):
        self.open()
        self.finish_foreman()
        self.append(dict(ev="tiers.recovered", key="key-0", tip="green"), *self.red_records(tip="next"))
        actions = self.tick()
        self.assertFalse(any(a.kind == "start" and a.task == "draft/red-1" for a in actions))
        self.assertTrue(any(a.kind == "examine-fix" and a.task == "draft/red-2" for a in actions))
        self.assertEqual([red.state for red in tier_reds.reds(log.read(self.path))], ["closed", "deciding"])

    def test_red_dispatch_no_after_landing_host_opens_nothing(self):
        del self.hosts["tiers"]
        self.open()
        self.assertFalse(any(e["ev"] == "red.opened" for e in log.read(self.path)))

    def test_red_dispatch_import_knows_red_tasks_without_reading_evidence(self):
        self.open()
        self.finish_foreman()
        original_import = dispatch._import_queue

        def checked_import(tasks, *args, **kwargs):
            self.assertIn("draft/red-1", tasks)
            read_evidence.assert_not_called()
            return original_import(tasks, *args, **kwargs)

        with patch.object(tier_reds, "_read_evidence", wraps=tier_reds._read_evidence) as read_evidence, \
             patch.object(dispatch, "_import_queue", side_effect=checked_import):
            self.tick()
        self.assertTrue(read_evidence.called)

    def test_red_dispatch_queue_import_knows_red_tasks_in_both_modes(self):
        for landing in ("queue", "integration"):
            with self.subTest(landing=landing):
                self.plan = replace(self.plan, landing=landing)
                write(self.path, "")
                self.open()
                self.finish_foreman()
                self.tick()
                self.queue_records = [dict(ev="landed", ts="queue-1", branch="draft/red-1-r2", tip="repair", main="fixed")]
                self.tick()
                landed, = [e for e in log.read(self.path) if e["ev"] == "branch.landed"
                           and e.get("task") == "draft/red-1"]
                self.assertEqual((landed["branch"], landed["main"]), ("draft/red-1-r2", "fixed"))
                self.assertFalse(any(e["ev"] == "queue.landed" for e in log.read(self.path)))
                self.queue_records = []

    def test_red_dispatch_two_runs_park_and_queue_while_other_work_moves(self):
        self.open()
        self.finish_foreman()
        self.tick()
        self.append(dict(ev="run.ended", task="draft/red-1", run="draft/red-1-1", outcome="infra"))
        self.tick()
        self.append(dict(ev="run.ended", task="draft/red-1", run="draft/red-1-2", outcome="infra"),
                    dict(ev="run.started", task="draft/other", run="draft/other-1", kind="implement", host="other"))
        actions = self.tick()
        park, = [a for a in actions if a.kind == "park"]
        self.assertEqual((park.task, park.detail), ("draft/red-1", "2 runs without landing; needs judgement"))
        self.assertFalse(any(a.kind == "call" for a in actions))
        self.assertFalse(any(a.kind == "foreman" for a in actions))
        events = log.read(self.path)
        tasks = {**self.tasks, **tier_reds.tasks(self.plan, events)}
        question, = foreman.questions(tasks, events)
        self.assertEqual((question.task, question.state), ("draft/red-1", "queued"))
        due = (datetime.fromisoformat(question.since) + timedelta(minutes=30)).isoformat()
        self.assertEqual([a for a in dispatch.call_actions(self.plan, tasks, events, [], due)
                          if a.run_kind == "answer"],
                         [Action("call", task="draft", run_kind="answer")])
        self.append(dict(ev="run.ended", task="draft/other", run="draft/other-1", outcome="done"),
                    dict(ev="question.answered", task="draft/red-1", answer="Try a unit test."))
        self.assertTrue(any(a.kind == "start" and a.task == "draft/red-1" for a in self.tick()))
        self.assertIn("Try a unit test.", (log.home() / "runs/draft/red-1-3/brief.md").read_text())

    def test_red_dispatch_question_skips_foreman(self):
        self.open()
        self.finish_foreman()
        self.tick()
        self.append(dict(ev="run.ended", task="draft/red-1", run="draft/red-1-1", outcome="question"),
                    dict(ev="question.asked", task="draft/red-1", run="draft/red-1-1", text="Which fix?"))
        tasks = tier_reds.tasks(self.plan, log.read(self.path))
        self.assertEqual([q.state for q in foreman.questions(tasks, log.read(self.path))], ["queued"])
        self.assertFalse(any(a.kind == "foreman" for a in self.tick()))

    def test_red_dispatch_specless_refusal_quotes_body_and_fix_lands_nothing(self):
        self.open()
        self.finish_foreman()
        self.tick()
        self.append(dict(ev="run.ended", task="draft/red-1", run="draft/red-1-1", outcome="done"))
        self.tick()
        self.append(dict(ev="branch.rejected", task="draft/red-1", branch="draft/red-1", tip="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                         step="test", findings="assertion failed"))
        self.tick()
        run_id = "draft/red-1/foreman-2"
        brief = (log.home() / "runs" / run_id / "brief.md").read_text()
        self.assertIn("# The task\n\n# Repair a red after landing", brief)
        self.assertNotIn("# The task spec", brief)
        report_path = log.home() / "runs" / run_id / "report.md"
        write(report_path, "Done: fix: correct the reproduction\nadd a regression test\n")
        self.append(dict(ev="run.ended", task="draft/red-1/foreman", run=run_id, outcome="done", report=str(report_path)))
        self.fake.calls.clear()
        self.tick()
        settled, = [e for e in log.read(self.path) if e["ev"] == "refusal.settled"]
        self.assertEqual((settled["branch"], settled["verdict"]), ("", "fix"))
        self.assertFalse(any(call.argv[:1] == ["git"] for call in self.fake.calls))
        self.tick()
        body = (log.home() / "runs/draft/red-1-2/brief.md").read_text()
        self.assertIn("correct the reproduction", body)
        self.assertIn("add a regression test", body)

    def test_red_dispatch_only_opens_no_reds_and_retires_without_a_verdict(self):
        records = self.red_records()
        for record in records:
            record["branches"] = ["live/a"]
        self.append(*records)
        actions = self.tick(only=True)
        self.assertFalse(any(e["ev"] == "red.opened" for e in log.read(self.path)))
        self.assertFalse(any(a.kind == "examine-fix" for a in actions))
        self.assertTrue(any(a.run_kind == "retire" for a in actions))

    def test_red_dispatch_only_retires_despite_an_open_red(self):
        self.open()
        self.assertFalse(any(a.run_kind == "retire" for a in self.tick()))
        self.assertTrue(any(a.run_kind == "retire" for a in self.tick(only=True)))

    def test_red_dispatch_retire_waits_for_verdict_and_open_reds(self):
        actions = self.tick()
        self.assertFalse(any(a.run_kind == "retire" for a in actions))
        self.append(dict(ev="tiers.run", tip="tip", branches=["draft/a"], reds=[]))
        self.assertTrue(any(a.run_kind == "retire" for a in self.tick()))
        self.open()
        self.assertFalse(any(a.run_kind == "retire" for a in self.tick()))
        self.finish_foreman(report="Done: retry: environment fault\n")
        self.assertTrue(any(a.run_kind == "retire" for a in self.tick()))

    def test_red_dispatch_imported_new_red_and_recovery_note_lost_event(self):
        self.tier_records = [dict(ev="run", ts="1", tip="tip", branches=["draft/a"], reds=["default::b::t"]),
                             dict(ev="test", state="new", key="default::b::t", ts="2", tip="tip", branches=["draft/a"], profile="default",
                                  binary="b", test="t", error="failed", log="/log", rerun="/rerun")]
        self.tick()
        records = log.read(self.path)
        imported = [e for e in records if "al_ts" in e]
        self.assertEqual([e["ev"] for e in imported], ["tiers.run", "tiers.red"])
        wake.settle("backstop", None, imported, log_path=self.path)
        self.assertEqual("lost event: after-landing: 1 records", log.read(self.path)[-1]["text"])


class FindingAnswerDispatchTest(unittest.TestCase):
    def setUp(self):
        from fab.tests.test_fixes import records, foreman_events, settlement
        self.home = self.enterContext(tmp_home())
        self.directory = write_ladder(self.home / "plan")
        path = self.directory / "plan.toml"
        write(path, path.read_text().replace('repo = "agents"', 'repo = "fabrig"'))
        self.plan = plan.load_plan(path)
        for record in records() + foreman_events() + [settlement()]:
            log.append(**record)
        self.fake = FakeRunner().on(["git", "rev-parse", "--show-toplevel"], Result(0, str(self.home)))
        self.fake.on(["git", "ls-tree"], Result(0, self.plan.ladder.backlog))
        self.fake.on(["git", "show"], Result(0, triage.backlog_text(self.plan, log.read())))
        self.enterContext(redirect_stdout(io.StringIO()))

    def ask(self):
        log.append(**run_started("ladder/finding-1"))
        log.append(**run_ended("ladder/finding-1", outcome="question"))
        log.append("question.asked", task="ladder/finding-1", run="ladder/finding-1-1",
                   text="Which finding fix?")

    def test_finding_answer_tick_launches_one_call_whose_brief_has_the_question(self):
        self.ask()
        actions = dispatch.tick(self.directory, sh=self.fake, hosts={}, only=True)
        self.assertEqual([action for action in actions if action.run_kind == "answer"],
                         [Action("call", task="ladder", run_kind="answer")])
        launched = [argv for argv in self.fake.argvs() if argv[:1] == ["systemd-run"] and "answer" in argv]
        self.assertEqual(len(launched), 1)
        self.assertEqual(launched[0][-5:], ["call", "answer", "--plan", str(self.directory.resolve()), "--tick"])
        output = io.StringIO()
        with patch.object(calls, "run", self.fake), redirect_stdout(output):
            self.assertEqual(calls.main(["answer", "--plan", str(self.directory), "--brief-only"]), 0)
        self.assertIn("# Question: ladder/finding-1 (ladder/finding-1-1)", output.getvalue())
        self.assertIn("Which finding fix?", output.getvalue())
        self.assertIn("# Repair a QA finding (finding-1)", output.getvalue())

    def test_finding_answer_tick_starts_no_answer_call_without_a_queued_question(self):
        actions = dispatch.tick(self.directory, sh=self.fake, hosts={}, only=True)
        self.assertFalse(any(action.run_kind == "answer" for action in actions))
        self.assertFalse(any(argv[:1] == ["systemd-run"] and "answer" in argv for argv in self.fake.argvs()))

    def test_finding_answer_dry_run_uses_the_shared_task_set(self):
        self.ask()
        before = log.read()
        output = io.StringIO()
        with patch.object(dispatch, "run", self.fake), patch.object(dispatch.machines, "load", return_value={}), \
             patch.object(calls, "answer_tasks", wraps=calls.answer_tasks) as answer_tasks, redirect_stdout(output):
            self.assertEqual(dispatch.main([str(self.directory), "--dry-run"]), 0)
        answer_tasks.assert_called_once()
        current, tasks, events = answer_tasks.call_args.args
        self.assertEqual(current, self.plan)
        self.assertIn("ladder/finding-1", calls.answer_tasks(current, tasks, events))
        self.assertEqual(log.read(), before)
        self.assertFalse(any(argv[:1] == ["systemd-run"] for argv in self.fake.argvs()))

    def test_finding_answer_report_is_logged_and_folded_into_the_repair_body(self):
        self.ask()
        log.append(**call_started("answer-finding", "answer", "ladder"))
        log.append(**call_ended("answer-finding"))
        write(log.home() / "calls/answer-finding/report.md",
              "Done: answered\nAnswer ladder/finding-1: Reproduce with the fake model.\n"
              "Answered: ladder/finding-1\n")
        dispatch._finish(Action("finish", task="answer-finding"), log_path=None)
        answered = log.read()[-1]
        self.assertEqual({key: answered[key] for key in ("ev", "task", "call", "answer")},
                         dict(ev="question.answered", task="ladder/finding-1", call="answer-finding",
                              answer="Reproduce with the fake model."))
        repair = fixes.tasks(self.plan, log.read())["ladder/finding-1"]
        self.assertIn("## Answers\n\n- Reproduce with the fake model.", repair.body)


class FindingDispatchTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.path = self.home / "events.jsonl"
        self.plan = replace(make_plan(low=0), repo="fabrig", landing="integration")
        self.repair = fix.task("draft/finding-1", "finding", "qa", "Repair the finding.", [])
        self.tasks = {self.repair.id: self.repair}
        self.hosts = {"builder": Host("builder", "fake@builder", ("builder",), places=2)}
        self.fake = FakeRunner().on(["ssh"], self.remote)

    def remote(self, call):
        argv = shlex.split(shlex.split(call.argv[-1])[2])
        if argv[:1] == ["git"] and "rev-parse" in argv and "-q" in argv:
            return Result(1)
        if argv == ["fab", "slot", "list"]:
            return Result(0, json.dumps(dict(slot=1, claim=None, idle=0)) + "\n")
        if argv[:3] == ["fab", "codex", "start"]:
            return Result(0, "codex-finding /state/finding\n")
        return Result(0)

    def test_finding_dispatch_starts_from_main_in_integration_plan(self):
        action, = [a for a in dispatch.decide(self.plan, self.tasks, [], self.hosts) if a.kind == "start"]
        dispatch._start(action, self.tasks, self.hosts, plan=self.plan, checkout=self.home,
                        sh=self.fake, log_path=self.path)
        record, = log.read(self.path)
        self.assertEqual((record["task"], record["base"], record["branch"], record["slot"]),
                         (self.repair.id, "origin/main", self.repair.id, 1))
        brief = (log.home() / "runs/draft/finding-1-1/brief.md").read_text()
        self.assertIn("- Base: `origin/main`", brief)
        self.assertNotIn("- Trunk:", brief)
        commands = [shlex.split(shlex.split(call.argv[-1])[2]) for call in self.fake.calls
                    if call.argv[:1] == ["ssh"]]
        self.assertTrue(any(argv[-4:] == ["--discard-changes", "-C", self.repair.id, "origin/main"]
                            for argv in commands))

    def test_finding_dispatch_readies_instead_of_merging(self):
        events = [run_started(self.repair.id, branch=self.repair.id), run_ended(self.repair.id)]
        actions = dispatch.decide(self.plan, self.tasks, events, self.hosts)
        self.assertEqual([a for a in actions if a.kind != "flow"],
                         [Action("ready", task=self.repair.id, branch=self.repair.id, detail=self.repair.id)])

    def test_finding_dispatch_starts_while_trunk_is_stopped(self):
        tasks = {**self.tasks, "draft/a": task("a"), "draft/b": task("b")}
        events = [event("branch.landed", into=self.plan.trunk, main="trunk-tip", tip="task-tip")]
        for n in range(1, 4):
            events += [run_started("draft/integration", n, kind="check", base="trunk-tip"),
                       run_ended("draft/integration", n, outcome="failed")]
        self.assertEqual(integration.next_step(self.plan, tasks, events).kind, "stop")
        self.assertEqual([a for a in dispatch.decide(self.plan, tasks, events, self.hosts) if a.kind == "start"],
                         [Action("start", task=self.repair.id, host="builder", run_kind="implement",
                                 detail="implement builder")])

    def test_finding_dispatch_parks_fix_kinds_at_shared_run_limit(self):
        for kind in fix.FIX_KINDS:
            repair = replace(self.repair, kind=kind)
            for count in (fix.RUNS - 1, fix.RUNS, fix.RUNS + 1):
                with self.subTest(kind=kind, count=count):
                    events = [record for n in range(1, count + 1)
                              for record in (run_started(repair.id, n, branch=repair.id), run_ended(repair.id, n, "infra"))]
                    actions = dispatch.decide(self.plan, {repair.id: repair}, events, self.hosts)[1:]
                    action, = actions
                    self.assertEqual(action.kind, "start" if count < fix.RUNS else "park")
                    if action.kind == "park":
                        self.assertEqual(action.detail, f"{fix.RUNS} runs without landing; needs judgement")

    def test_finding_dispatch_refusal_foreman_uses_main(self):
        events = [run_started(self.repair.id, branch=self.repair.id), run_ended(self.repair.id),
                  dict(ev="branch.rejected", task=self.repair.id, branch=self.repair.id,
                       tip="repair-tip", step="test", findings="assertion failed")]
        for record in events:
            log.append(path=self.path, **record)
        action, = dispatch.repair_actions(self.tasks, log.read(self.path))
        dispatch._examine(action, self.tasks, self.hosts, plan=self.plan, sh=self.fake, log_path=self.path)
        record = log.read(self.path)[-1]
        self.assertEqual((record["task"], record["base"], record["branch"]),
                         (self.repair.id + "/foreman", "origin/main", self.repair.id))
