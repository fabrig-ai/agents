"""The dispatcher's decisions and shell, isolated from machine state (docs/design/fab.md, 8)."""

import fcntl
import io
import json
import shlex
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fab import call_review, channel, cli, designer, dispatch, drafts, flow, foreman, gates, log, plan, repairs, run as runs, state
from fab.dispatch import Action, MAX_RUNS
from fab.hosts import Host
from fab.sh import Result, ssh
from fab.tests.test_repairs import (TASK as REPAIR_TASK, foreman_run, rejected, report,
                                    settled, task_run)
from fab.tests.support import (FakeRunner, call_ended, call_started, run_ended, run_started,
                               tmp_home, units, write_plan)


def task(name, *, part="core", repo="agents", needs=()):
    return plan.Task(f"draft/{name}", part, "feature", repo, needs, (), "high", 25, "", "task.md")


def part(name, needs=()):
    return plan.Part(name, name, "feature", needs, "design.md")


def make_plan(*parts, low=1):
    return plan.Plan("draft", "agents", (), low, 2, {p.id: p for p in parts}, ())


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
        hosts = {"builder": replace(self.hosts["builder"], places=10)}
        tasks = {t.id: t for t in (task("a"), task("b"), task("c"))}
        actions = dispatch.decide(self.plan, tasks, [], hosts)
        self.assertEqual(actions[0], Action("flow", task="draft", detail="target 2, 0 in flight"))
        self.assertEqual([a.task for a in actions[1:]], ["draft/a", "draft/b"])
        events = [event("branch.rejected", "c", step="test")]
        actions = dispatch.decide(self.plan, tasks, events, hosts)
        self.assertEqual(actions[0], Action("flow", task="draft", detail="target 1, 0 in flight"))
        self.assertEqual([(a.task, a.run_kind) for a in actions[1:]], [("draft/c", "repair")])

    def test_decide_collects_only_owned_runs_including_call_reviews(self):
        events = [run_started("other/task"), call_started("own", "answer", "draft"),
                  run_started("own", kind="review"), run_started("draft/a/foreman", kind="foreman"),
                  call_started("foreign", "review", "other/review"), run_started("foreign", kind="review")]
        actions = self.decide([], events)
        self.assertEqual([a.run for a in actions if a.kind == "collect"], ["own-1", "draft/a/foreman-1"])

    def test_only_drafts_runs_count_toward_target_including_unspecified_tasks(self):
        hosts = {"builder": replace(self.hosts["builder"], places=10)}
        tasks = {t.id: t for t in (task("a"), task("b"), task("c"))}
        foreign = [dict(started("foreign"), task="other/foreign"),
                   dict(started("outside"), task="drafted/outside")]
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
        events = growth() + [event("branch.rejected", name, step="test") for name in ("d", "b")]
        actions = self.decide(tasks, events)
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
                               ("gate:files", "repair"), ("gate:parse", "repair")):
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

    def test_design_buffer_uses_starting_flow_target_regardless_of_places(self):
        for places in (0, 1, 2, 20):
            for low in (0.5, 1, 1.5):
                for count in range(4):
                    with self.subTest(places=places, low=low, count=count):
                        hosts = {"builder": replace(self.hosts["builder"], places=places)}
                        spec = make_plan(part("core"), part("next"), low=low)
                        tasks = [task(str(n)) for n in range(count)]
                        actions = self.decide(tasks, hosts=hosts, spec=spec)
                        expected = ([Action("design", detail="next" if count else "core, next")]
                                    if count < 2 * low else [])
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
        answered = asked + [dict(ev=channel.ANSWERED, subject="draft/core", by="user", answer="see fab.md 12")]
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
                    "hold": [Action("hold", task="draft/core", run="root", detail="refused after its amendment")],
                }.get(status, [])
                self.assertEqual(self.actions(history, ["core", "next"]),
                                 [*step, Action("call", task="next", run_kind="skeleton")])

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


class TickTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(dispatch, "blocking", return_value=False))
        self.home = self.enterContext(tmp_home())
        self.directory = self.home / "plan"
        write(self.directory / "plan.toml", '''draft = "draft"
repo = "agents"
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
        self.assertEqual(actions[0], Action("flow", task="draft", detail="target 2, 0 in flight"))
        self.assertEqual(self.out.getvalue().splitlines()[0], "flow draft target 2, 0 in flight")
        self.assertEqual(self.fake.argvs().count(probe), 1)
        self.assertEqual([e["ev"] for e in log.read()], ["run.started"])
        self.start.assert_called_once()

    def test_tick_writes_page_after_actions_using_explicit_log_and_registered_plans(self):
        path = self.home / "custom/log.jsonl"
        self.append(dict(ev="call.ended", call="cut", subject="draft/cut", outcome="question"), path=path)
        write(log.home() / "calls/cut/report.md", "Question: Buy a host?\n")
        registered = self.home / "other"
        write(registered / "plan.toml", '''draft = "other"
repo = "agents"
part = []
[[question]]
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
        self.assertEqual([(e["ev"], e["task"]) for e in first],
                         [("branch.landed", "draft/a"), ("branch.rejected", "draft/b"),
                          ("branch.landed", "draft/c")])
        self.assertTrue(all(e["queue_ts"] == "002" for e in first))
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
                          f"page - {log.home() / channel.PAGE}"])
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
        return branch

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
                          "fab", "call", "skeleton", "next", "--plan", str(self.directory)])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.out.getvalue(), "flow draft target 2, 0 in flight\ndesign - next\ncall next \n"
                         + f"page - {log.home() / channel.PAGE}\n")
        self.assertEqual(len(log.read()), 1)

    def test_contract_unit_passes_the_part_and_plan(self):
        """The tick launches a contract with its part in the subject-named unit."""
        (self.directory / "tasks/a.md").unlink()
        path = self.directory / "plan.toml"
        write(path, path.read_text().replace('mode = "feature"', 'mode = "feature"\ncontract = true'))
        self.assertEqual(self.tick(), [Action("design", detail="core"),
                                      Action("call", task="core", run_kind="contract")])
        self.assertEqual(self.fake.argvs()[-1],
                         ["systemd-run", "--user", "--collect", "--unit", drafts.unit("contract", "draft/core"),
                          "fab", "call", "contract", "core", "--plan", str(self.directory)])
        self.assertEqual(self.calls, [])

    def test_retire_unit_takes_no_part_and_uses_subject(self):
        """Retirement follows completion and has no subject argument in the call argv."""
        self.append(event("branch.landed", tip="tip", main="main"),
                    dict(ev="call.started", call="old", role="retire", subject="draft/retire"),
                    dict(ev="call.ended", call="old", outcome="failed"))
        self.assertEqual(self.tick(), [Action("call", task="draft/retire", run_kind="retire")])
        self.assertEqual(self.fake.argvs()[-1],
                         ["systemd-run", "--user", "--collect", "--unit", drafts.unit("retire", "draft/retire"),
                          "fab", "call", "retire", "--plan", str(self.directory)])
        self.assertEqual(self.calls, [])

    def test_uncut_plan_moves_its_cut_chain_after_fetch_with_no_tasks(self):
        """A logged cut substitutes an empty plan, imports the queue and reviews its branch."""
        (self.directory / "plan.toml").unlink()
        path = self.home / "cut.jsonl"
        self.append(*chain_history("review", role="cut", subject="plan/cut"), path=path)
        self.fake = FakeRunner().on(["git", "rev-parse", "--show-toplevel"],
                                    Result(0, "/checkout\n"))
        self.fake.on(["git", "remote", "get-url", "origin"], Result(0, runs.REMOTES["agents"] + "\n"))
        with patch.object(call_review, "start", return_value="root-1") as start:
            actions = self.tick(log_path=path)
        self.assertEqual(actions, [Action("vet", task="root", run="root", run_kind="cut",
                                          branch="calls/root")])
        self.assertEqual(start.call_args.args[1:3], ("agents", Path("/checkout")))
        self.assertEqual(start.call_args.kwargs, dict(sh=self.fake, log_path=path))
        self.assertEqual(self.fake.argvs()[:3], [["git", "rev-parse", "--show-toplevel"],
                                               ["git", "fetch", "origin"],
                                               ["git", "remote", "get-url", "origin"]])
        self.assertEqual(self.fake.calls[2].cwd, "/checkout")
        self.assertIn(ssh("fake@gate", ["fab", "queue", "log", "--since", ""]), self.fake.argvs())
        self.assertEqual(len(self.fake.calls), 5)
        self.assertEqual(self.calls, [])

    def test_uncut_directory_need_not_exist_for_tick_or_dry_run(self):
        """Both tick modes locate git from an existing ancestor of an unwritten plan."""
        directory = self.home / "checkout/docs/plan/new"
        self.append(dict(ev="call.started", call="cut", role="cut", subject="new/cut"))
        fake = FakeRunner().on(["git", "rev-parse", "--show-toplevel"], Result(0, "/checkout\n"))
        fake.on(["git", "remote", "get-url", "origin"], Result(0, runs.REMOTES["agents"]))
        self.assertEqual(dispatch.tick(directory, sh=fake, hosts={}),
                         [Action("flow", task="new", detail="target 2, 0 in flight")])
        with patch.object(dispatch, "run", fake), patch("fab.hosts.load", return_value={}):
            self.assertEqual(dispatch.main([str(directory), "--dry-run"]), 0)
        lookups = [call for call in fake.calls if call.argv == ["git", "rev-parse", "--show-toplevel"]]
        self.assertEqual([call.cwd for call in lookups], [str(self.home)] * 2)
        self.assertEqual([call.cwd for call in fake.calls if call.argv ==
                          ["git", "remote", "get-url", "origin"]], ["/checkout"] * 2)
        self.assertFalse(directory.exists())

    def test_missing_plan_without_its_cut_call_fails_before_import(self):
        """A different draft or role does not authorize ticking a missing plan file."""
        (self.directory / "plan.toml").unlink()
        self.append(dict(ev="call.started", call="other", role="cut", subject="other/cut"),
                    dict(ev="call.started", call="wrong", role="skeleton", subject="plan/cut"))
        actions = self.tick()
        self.assertEqual([action.kind for action in actions], ["load"])
        self.assertIn(str(self.directory), actions[0].detail)
        self.assertEqual(self.fake.argvs(), [["git", "rev-parse", "--show-toplevel"]])
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

    def test_retired_plan_prints_and_skips_import_measurement_and_actions(self):
        """After fetch, retirement exits before loading hosts or doing any plan work."""
        write(log.home() / channel.PAGE, "keep page\n")
        path = self.directory / "plan.toml"
        write(path, 'retired = true\n' + path.read_text())
        self.append(started(), *chain_history("review"))
        self.fake = FakeRunner().on(["git", "rev-parse", "--show-toplevel"], Result(0, "/checkout\n"))
        with patch("fab.hosts.load", side_effect=AssertionError("hosts loaded")), \
             patch.object(dispatch, "_import_queue", side_effect=AssertionError("queue imported")), \
             patch.object(flow, "measure", side_effect=AssertionError("builder measured")), \
             patch.object(dispatch, "decide", side_effect=AssertionError("actions decided")):
            self.assertEqual(dispatch.tick(self.directory, sh=self.fake), [])
        self.assertEqual(self.out.getvalue(), "retired draft\n")
        self.assertEqual((log.home() / channel.PAGE).read_text(), "keep page\n")
        self.assertEqual(self.fake.argvs(), [["git", "rev-parse", "--show-toplevel"],
                                           ["git", "fetch", "origin"]])
        self.assertEqual(self.calls, [])

    def completed_call(self, role="answer", identifier="answer-1", path=None):
        self.append(dict(ev="call.started", call=identifier, role=role, subject="draft",
                         branch=f"calls/{identifier}"),
                    dict(ev="call.ended", call=identifier, role=role, outcome="done"), path=path)
        return log.home() / "calls" / identifier / "report.md"

    def approve(self, root="answer-1", number=1, path=None):
        self.append(dict(ev="run.started", run=f"{root}-{number}", task=root, kind="review", host="builder"),
                    dict(ev="run.ended", run=f"{root}-{number}", outcome="done"), path=path)

    def test_answer_unit_uses_draft_and_no_part_argument(self):
        self.completed_call("answer", "old")
        self.append(dict(ev="call.finished", call="old", outcome="done"))
        self.completed_call("skeleton", "s1")
        self.append(dict(ev="call.finished", call="s1", outcome="done"))
        self.append(event("question.asked", ts="2000-01-01T00:00:00Z", text="Which?"))
        self.assertEqual(self.tick(), [Action("call", task="draft", run_kind="answer")])
        self.assertEqual(self.fake.argvs()[-1],
                         ["systemd-run", "--user", "--collect", "--unit", drafts.unit("answer", "draft"),
                          "fab", "call", "answer", "--plan", str(self.directory)])
        self.assertEqual(len([e for e in log.read() if e["ev"] == "call.started"]), 2)

    def test_call_decisions_see_questions_written_by_collect(self):
        self.append(started())
        self.collect.side_effect = lambda *a, **kw: self.append(
            event("question.asked", ts="2000-01-01T00:00:00Z", text="Which?"))
        actions = self.tick()
        self.assertEqual([a.kind for a in actions], ["collect", "call"])
        self.assertEqual(self.fake.argvs()[-1][-5:],
                         ["fab", "call", "answer", "--plan", str(self.directory)])

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
                                               sh=self.fake, log_path=path)
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
                                       run_id="draft/a/foreman-1", day="2026-10-31", sh=self.fake)
        self.land.assert_called_once_with([branch])
        answered = log.read(path)[-1]
        self.assertEqual(answered, dict(ts="2026-10-31T23:59:00.000Z", ev="question.answered",
                                        task="draft/a", by="draft/a/foreman-1", run="draft/a-1",
                                        answer="Use option A"))
        self.assertEqual([action.kind for action in self.tick(log_path=path)], ["start"])
        self.start.assert_called_once()
        self.assertEqual(log.read(), [])

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
        self.assertEqual(self.fake.argvs()[-1][-5:], ["fab", "call", "answer", "--plan", str(self.directory)])

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

    def test_hold_logs_last_refusal_once_and_answer_reopens_chain(self):
        path = self.home / "custom.jsonl"
        self.append(event("question.asked", text="Which?"), *chain_history("hold"), path=path)
        actions = self.tick(log_path=path)
        self.assertEqual(actions, [Action("hold", task="draft/core", run="root",
                                          detail="refused after its amendment")])
        self.assertEqual({key: value for key, value in log.read(path)[-1].items() if key != "ts"},
                         dict(ev="call.parked", call="root", subject="draft/core",
                              reason="refused after its amendment", report="last-refusal.md"))
        page = (log.home() / channel.PAGE).read_text()
        self.assertIn("### draft/core, parked", page)
        self.assertIn("refused after its amendment", page)
        self.assertEqual(self.tick(log_path=path), [])
        self.assertEqual(sum(entry["ev"] == "call.parked" for entry in log.read(path)), 1)
        self.append(dict(ev=channel.ANSWERED, subject="draft/core"), path=path)
        with patch.object(call_review, "start") as vet:
            self.assertEqual(self.tick(log_path=path)[0].kind, "vet")
        vet.assert_called_once()
        self.assertEqual(log.read(), [])

    def test_hold_without_refusal_report_uses_empty_path(self):
        self.append(event("question.asked", text="Which?"), *chain_history("review"))
        for number in range(call_review.INFRA_LIMIT):
            self.append(dict(ev="run.started", run=f"root-{number}", task="root", kind="review", host="builder"),
                        dict(ev="run.ended", run=f"root-{number}", outcome="infra"))
        self.tick()
        self.assertEqual((log.read()[-1]["ev"], log.read()[-1]["report"]), ("call.parked", ""))
        self.assertEqual(self.tick(), [])

    def test_amend_unit_passes_root_and_uses_root_key(self):
        self.append(event("question.asked", text="Which?"), *chain_history("amend"),
                    dict(ev="call.started", call="old-amend", role="amend", amends="other"),
                    dict(ev="call.ended", call="old-amend", outcome="failed"))
        self.assertEqual(self.tick(), [Action("call", task="root", run_kind="amend")])
        self.assertEqual(self.fake.argvs()[-1],
                         ["systemd-run", "--user", "--collect", "--unit", drafts.unit("amend", "root"),
                          "fab", "call", "amend", "root", "--plan", str(self.directory)])
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

    def test_finish_lands_then_parses_answered_line_and_logs_once(self):
        self.add_task("b")
        self.append(event("question.asked", text="Which?"), event("question.asked", "b", text="Why?"))
        report = self.completed_call()
        self.approve()
        write(report, "Done: answered\nOther: draft/ignored\nAnswered: draft/a  draft/b draft/a\nDetails.\n")

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
                         ["flow draft target 2, 0 in flight", "finish answer-1 ",
                          f"page - {log.home() / channel.PAGE}", "flow draft target 2, 0 in flight",
                          f"page - {log.home() / channel.PAGE}"])

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
        self.screen.return_value = [gates.Finding("files", "outside"),
                                    gates.Finding("files", "also outside"),
                                    gates.Finding("docs", "no docstring")]
        self.tick()
        self.land.assert_not_called()
        self.assertEqual(self.out.getvalue(), "flow draft target 2, 0 in flight\nland draft/a rejected gate:files,docs\n"
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

    def test_other_repository_ready_is_not_screened(self):
        self.add_task("a", repo="fabrig")
        self.append(started(), ended())
        self.fake.on(["git", "rev-parse", "--verify"], Result(0, "tip\n"))
        self.tick()
        self.screen.assert_not_called()
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
                             [Action("flow", task="draft", detail="target 2, 0 in flight")])
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
        self.assertEqual(examine.call_args.kwargs, dict(sh=self.fake, log_path=path))
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
        tick.assert_called_once_with(self.directory)

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
        self.queue_records = [dict(ev="landed", branch=f"{draft}/a", ts=stamp, tip=draft, main="main")
                              for draft, stamp in (("one", "020"), ("two", "010"))]
        first = self.tick(one, two)
        self.assertEqual(first[0].kind, "load")
        self.assertEqual([(e["task"], e["queue_ts"]) for e in log.read()], [("one/a", "020")])
        self.plan_dir("two", tasks=("a",))
        self.tick(one, two)
        self.tick(one, two)
        self.assertEqual([(e["task"], e["queue_ts"]) for e in log.read()],
                         [("one/a", "020"), ("two/a", "010")])
        self.assertEqual(self.queries(), [ssh("fake@gate", ["fab", "queue", "log", "--since", stamp])
                                          for stamp in ("", "", "010")])

    def test_newly_listed_plan_reads_older_queue_records(self):
        one = self.plan_dir("one", tasks=("a",))
        two = self.plan_dir("two", tasks=("a",))
        designer.enlist(one)
        self.queue_records = [dict(ev="landed", branch=f"{draft}/a", ts=stamp, tip=draft, main="main")
                              for draft, stamp in (("one", "020"), ("two", "010"))]
        self.tick()
        designer.enlist(two)
        self.tick()
        self.assertEqual(self.queries(), [ssh("fake@gate", ["fab", "queue", "log", "--since", ""])] * 2)
        self.assertEqual([e["task"] for e in log.read()], ["one/a", "two/a"])

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
        with patch.object(dispatch, "tick", side_effect=lambda *paths: real_tick(
                *paths, sh=self.fake, hosts=self.hosts)):
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

    def test_retired_among_plans_is_skipped(self):
        one, two = self.plan_dir("one"), self.plan_dir("two")
        path = one / "plan.toml"
        write(path, "retired = true\n" + path.read_text())
        actions = self.tick(one, two)
        self.assertEqual([a.task for a in actions if a.kind == "flow"], ["two"])
        self.assertEqual(self.out.getvalue().splitlines()[0], "retired one")
        self.assertEqual(units(self.fake), [drafts.unit("skeleton", "two/core")])

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

    def test_main_two_directories_and_no_plans(self):
        one, two = self.plan_dir("one"), self.plan_dir("two")
        with patch.object(dispatch, "tick", return_value=[]) as tick:
            self.assertEqual(dispatch.main([str(one), str(two)]), 0)
        tick.assert_called_once_with(one, two)
        self.assertEqual(self.tick(), [])
        self.assertEqual(self.out.getvalue(), "plans - none\n")
        self.assertEqual(self.fake.calls, [])
        self.assertFalse(log.home().exists())

    def test_dry_run_continues_after_failed_load_and_returns_one(self):
        one, two = self.plan_dir("one"), self.plan_dir("two", tasks=("a",))
        write(one / "plan.toml", "invalid [")
        with patch.object(dispatch, "run", side_effect=AssertionError("command ran")), \
             patch("fab.hosts.load", return_value=self.hosts):
            self.assertEqual(dispatch.main([str(one), str(two), "--dry-run"]), 1)
        lines = self.out.getvalue().splitlines()
        self.assertTrue(lines[0].startswith(f"load {one} failed: "))
        self.assertEqual(lines[1:], ["flow two target 2, 0 in flight", "start two/a implement builder"])
        self.assertFalse(log.home().exists())
        self.starts.assert_not_called()

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
                         ["flow one target 2, 0 in flight", "start one/a implement builder",
                          "flow two target 2, 0 in flight", "start two/a implement builder"])
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
                    self.append(rejected("03", step="gate:files", findings="outside files"))
                    return [gates.Finding("files", "outside files")]

                self.screen.side_effect = refuse
                self.examine.reset_mock()
                actions = self.tick(hosts=hosts)
                self.assertEqual([action.kind for action in actions], ["land", "examine", "collect", "collect"])
                args = self.examine.call_args.args
                self.assertEqual((args[0].step, args[0].findings, args[2]),
                                 ("gate:files", "outside files", hosts[expected]))
                self.assertEqual(args[3][-1]["ev"], "branch.rejected")
                self.assertEqual(self.examine.call_args.kwargs, dict(sh=self.fake, log_path=self.path))
                self.assertIn(f"examine draft/task gate:files {expected}\n", self.out.getvalue())
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
                                            run_id=refusal.foreman, sh=self.fake)
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
