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
from unittest.mock import patch

from fab import call_review, cli, dispatch, flow, gates, log, plan, state
from fab.dispatch import Action, MAX_RUNS
from fab.hosts import Host
from fab.sh import Result, ssh
from fab.tests.support import FakeRunner, tmp_home


def task(name, *, part="core", repo="agents", needs=()):
    return plan.Task(f"draft/{name}", part, "feature", repo, needs, (), "high", 25, "", "task.md")


def part(name, needs=()):
    return plan.Part(name, name, "feature", needs, "design.md")


def make_plan(*parts, low=1):
    return plan.Plan("draft", "agents", (), low, 2, {p.id: p for p in parts}, ())


def event(ev, name="a", **fields):
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

    def test_design_only_unspecced_parts_with_all_needs_landed_in_plan_order(self):
        spec = make_plan(part("core"), part("z", ("core",)), part("a"),
                         part("blocked", ("other",)), part("other"),
                         part("empty_need", ("a",)), part("two", ("core", "other")))
        tasks = [task("x"), task("y"), task("w", part="other")]
        events = [event("branch.landed", "x", tip="tip", main="main"),
                  event("branch.landed", "y", tip="tip", main="main"),
                  event("question.asked", "w", text="Which?")]
        self.assertEqual(self.decide(tasks, events, spec=spec), [Action("design", detail="z, a")])
        events.pop(1)
        actions = self.decide(tasks, events, spec=spec)
        self.assertEqual(actions[-1], Action("design", detail="a"))

    def test_a_done_part_is_never_designed_and_counts_as_landed_for_its_readers(self):
        spec = make_plan(plan.Part("built", "built", "feature", (), "design.md", done=True),
                         part("reader", ("built",)))
        self.assertEqual(self.decide([], spec=spec), [Action("design", detail="reader")])

    def test_design_buffer_counts_rejections_and_total_places(self):
        spec = make_plan(part("core"), part("next"))
        tasks = [task("a"), task("b")]
        events = [event("branch.rejected", "b", step="test")]
        self.assertNotIn("design", [a.kind for a in self.decide(tasks, events, spec=spec)])
        events.append(started("a"))
        self.assertEqual(self.decide(tasks, events, spec=spec)[-1].kind, "design")
        self.assertEqual(self.decide([], hosts={}, spec=spec), [])
        self.assertEqual(self.decide([], spec=replace(spec, low=0)), [])

    def test_decide_is_repeatable_and_does_not_mutate_inputs(self):
        tasks = {t.id: t for t in (task("a"), task("b"))}
        events = [started(), ended(outcome="infra")]
        before = deepcopy((self.plan, tasks, events, self.hosts))
        first = dispatch.decide(self.plan, tasks, events, self.hosts)
        self.assertEqual(first, dispatch.decide(self.plan, tasks, events, self.hosts))
        self.assertEqual((self.plan, tasks, events, self.hosts), before)


class CallActionsTest(unittest.TestCase):
    def setUp(self):
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

    def test_a_part_with_a_successful_skeleton_call_is_not_designed_again(self):
        done = [dict(self.call("skeleton", "s1"), subject="draft/core"),
                dict(ev="call.ended", call="s1", role="skeleton", outcome="done")]
        skeleton = [a for a in self.actions(done, ["core", "next"]) if a.kind == "call"]
        self.assertEqual(skeleton, [Action("call", task="next", run_kind="skeleton")])
        failed = [done[0], dict(done[1], outcome="failed")]
        self.assertEqual(self.actions(failed, ["core"]), [Action("call", task="core", run_kind="skeleton")])

    def test_a_call_that_asked_parks_its_part_until_answered(self):
        asked = [dict(self.call("skeleton", "s1"), subject="draft/core"),
                 dict(ev="call.ended", call="s1", role="skeleton", outcome="question")]
        self.assertEqual(self.actions(asked, ["core", "next"]),
                         [Action("call", task="next", run_kind="skeleton")])
        answered = asked + [event("question.answered", "core", by="session", answer="see fab.md 12")]
        self.assertEqual(self.actions(answered, ["core", "next"]),
                         [Action("call", task="core", run_kind="skeleton")])

    def test_only_first_design_part_and_role_exclusion(self):
        questions = [self.question(ts="2026-10-30T12:00:00.000Z")]
        answer = Action("call", task="draft", run_kind="answer")
        skeleton = Action("call", task="core", run_kind="skeleton")
        self.assertEqual(self.actions(questions, ["core", "next"]), [answer, skeleton])
        self.assertEqual(self.actions(questions + [self.call()], ["core", "next"]), [skeleton])
        self.assertEqual(self.actions(questions + [self.call("skeleton")], ["core"]), [answer])
        self.assertEqual(self.actions(questions + [self.call(), self.call("skeleton", "s")], ["core"]), [])

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
                history = chain_history(status, role="answer", subject="other-draft")
                actions = self.actions(history + [self.question(ts="2026-10-30T12:00:00.000Z")])
                starts = [action for action in actions if action.kind == "call" and action.run_kind == "answer"]
                self.assertEqual(starts, [Action("call", task="draft", run_kind="answer")]
                                 if status == "finished" else [])

    def test_open_review_chain_blocks_until_finished(self):
        for status in call_review.STATES:
            with self.subTest(status=status):
                history = chain_history(status, role="review", subject="other/review")
                actions = self.actions(history + self.landings(dispatch.REVIEW_AT))
                starts = [action for action in actions if action.kind == "call" and action.run_kind == "review"]
                self.assertEqual(starts, [Action("call", task="draft/review", run_kind="review")]
                                 if status == "finished" else [])

    def landings(self, count, ts="2026-10-30T12:29:00.000Z"):
        tasks = [task(str(n)) for n in range(count)]
        self.tasks.update((item.id, item) for item in tasks)
        return [dict(ev="branch.landed", task=item.id, ts=ts) for item in tasks]

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
                 dict(ev="call.ended", call="r1", role="review", outcome="question"),
                 *self.landings(dispatch.REVIEW_AT)]
        self.assertEqual(self.actions(asked), [])
        self.assertEqual(self.actions(asked + [event("question.answered", "core")]), [])
        self.assertEqual(self.actions(asked + [event("question.answered", "review")]),
                         [Action("call", task="draft/review", run_kind="review")])

    def test_review_start_follows_answer_and_skeleton(self):
        history = [self.question(ts="2026-10-30T12:00:00.000Z"), *self.landings(dispatch.REVIEW_AT)]
        self.assertEqual(self.actions(history, ["core"]),
                         [Action("call", task="draft", run_kind="answer"),
                          Action("call", task="core", run_kind="skeleton"),
                          Action("call", task="draft/review", run_kind="review")])

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
        self.assertEqual([a.kind for a in actions], ["flow", "collect", "start"])
        self.assertEqual(actions[0], Action("flow", task="draft", detail="target 2, 0 in flight"))
        self.assertEqual(self.out.getvalue().splitlines()[0], "flow draft target 2, 0 in flight")
        self.assertEqual(self.fake.argvs().count(probe), 1)
        self.assertEqual([e["ev"] for e in log.read()], ["run.started"])
        self.start.assert_called_once()

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
        self.assertEqual(self.fake.argvs()[-2],
                         ssh("fake@gate", ["fab", "queue", "log", "--since", "002"]))

    def test_import_queue_records_once_including_shared_timestamps_and_rebases(self):
        self.add_task("b")
        self.add_task("c")
        records = [dict(ev="batch", ts="001", branches=["draft/a"]),
                   dict(ev="landed", ts="002", branch="draft/a", tip="a", main="main"),
                   dict(ev="rejected", ts="002", branch="draft/b-r2", tip="b", step="merge", log="conflict"),
                   dict(ev="landed", ts="003", branch="elsewhere/task", tip="x", main="main"),
                   dict(ev="landed", ts="002", branch="draft/c", tip="c", main="main")]
        self.queue(records + [records[1]])
        self.tick()
        first = log.read()
        self.assertEqual([(e["ev"], e["task"]) for e in first],
                         [("branch.landed", "draft/a"), ("branch.rejected", "draft/b"),
                          ("branch.landed", "draft/c")])
        self.assertTrue(all(e["queue_ts"] == "002" for e in first))
        self.assertEqual(first[1]["step"], "merge")
        self.assertEqual(first[1]["log"], "conflict")
        self.assertEqual(first[1]["branch"], "draft/b-r2")
        self.assertEqual(self.calls[0][:3], ("start", "draft/b", "builder"))
        self.assertEqual(self.calls[0][3]["kind"], "rebase")
        self.assertEqual(self.calls[0][3]["rejection"], first[1])
        self.tick()
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
                          *[f"{a.kind} {a.task or '-'} {a.detail}" for a in actions]])
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
                    started(n=2, branch=branch), ended(n=2))
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
                         ["systemd-run", "--user", "--collect", "--unit", "fab-call-skeleton-1",
                          "fab", "call", "skeleton", "next", "--plan", str(self.directory)])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.out.getvalue(), "flow draft target 2, 0 in flight\ndesign - next\ncall next \n")
        self.assertEqual(len(log.read()), 1)

    def completed_call(self, role="answer", identifier="answer-1", path=None):
        self.append(dict(ev="call.started", call=identifier, role=role, subject="draft",
                         branch=f"calls/{identifier}"),
                    dict(ev="call.ended", call=identifier, role=role, outcome="done"), path=path)
        return log.home() / "calls" / identifier / "report.md"

    def approve(self, root="answer-1", number=1, path=None):
        self.append(dict(ev="run.started", run=f"{root}-{number}", task=root, kind="review", host="builder"),
                    dict(ev="run.ended", run=f"{root}-{number}", outcome="done"), path=path)

    def test_answer_unit_uses_role_start_count_and_no_part_argument(self):
        self.completed_call("answer", "old")
        self.append(dict(ev="call.finished", call="old", outcome="done"))
        self.completed_call("skeleton", "s1")
        self.append(dict(ev="call.finished", call="s1", outcome="done"))
        self.append(event("question.asked", ts="2000-01-01T00:00:00Z", text="Which?"))
        self.assertEqual(self.tick(), [Action("call", task="draft", run_kind="answer")])
        self.assertEqual(self.fake.argvs()[-1],
                         ["systemd-run", "--user", "--collect", "--unit", "fab-call-answer-2",
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
        self.append(dict(ev="run.started", run="busy-1", task="other/one", host="z"),
                    dict(ev="run.started", run="busy-2", task="other/two", host="z"))
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
        self.append(event("question.asked", text="Which?"))
        self.completed_call("skeleton", "root")
        with patch.object(call_review, "start") as vet:
            self.tick(hosts={})
        vet.assert_not_called()
        self.land.assert_not_called()
        self.assertEqual(log.read()[-1]["text"], "vet root failed: no builder configured for call review")
        self.assertNotIn("call.finished", [entry["ev"] for entry in log.read()])

    def test_done_calls_of_every_role_wait_for_review(self):
        self.append(event("question.asked", text="Which?"))
        for role in call_review.REVIEWED:
            self.completed_call(role, role)
        with patch.object(call_review, "start") as vet:
            actions = self.tick()
        self.assertEqual([action.kind for action in actions], ["vet", "vet", "vet"])
        self.assertEqual([action.run_kind for action in actions], list(call_review.REVIEWED))
        self.assertEqual(vet.call_count, 3)
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
        self.assertEqual(self.tick(log_path=path), [])
        self.assertEqual(sum(entry["ev"] == "call.parked" for entry in log.read(path)), 1)
        self.append(event("question.answered", "core"), path=path)
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

    def test_amend_unit_passes_root_and_counts_amend_starts(self):
        self.append(event("question.asked", text="Which?"), *chain_history("amend"),
                    dict(ev="call.started", call="old-amend", role="amend", amends="other"),
                    dict(ev="call.ended", call="old-amend", outcome="failed"))
        self.assertEqual(self.tick(), [Action("call", task="root", run_kind="amend")])
        self.assertEqual(self.fake.argvs()[-1],
                         ["systemd-run", "--user", "--collect", "--unit", "fab-call-amend-2",
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
                          "flow draft target 2, 0 in flight"])

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
        self.fake.on(["systemd-run", "--user", "--collect", "--unit", "fab-call-answer-1"],
                     Result(1, err="no unit"))
        design = Action("design", detail="core, next")
        with patch("fab.dispatch.decide", return_value=[design]):
            self.tick()
        self.assertEqual([argv[4] for argv in self.fake.argvs() if argv[0] == "systemd-run"],
                         ["fab-call-answer-1", "fab-call-skeleton-1"])
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
                          "land draft/a failed: offline retry later", "land draft/b draft/b"])

    def test_gate_findings_reject_without_landing_and_print_unique_gates(self):
        self.append(started(), ended())
        self.screen.return_value = [gates.Finding("files", "outside"),
                                    gates.Finding("files", "also outside"),
                                    gates.Finding("docs", "no docstring")]
        self.tick()
        self.land.assert_not_called()
        self.assertEqual(self.out.getvalue(), "flow draft target 2, 0 in flight\nland draft/a rejected gate:files,docs\n")
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
        self.assertEqual(self.out.getvalue(), "flow draft target 2, 0 in flight\nland draft/a draft/a-r1\n")
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
        self.assertEqual(self.out.getvalue(), "flow draft target 2, 0 in flight\nland draft/a draft/a\n")

    def test_failed_land_output_is_printed_and_noted_on_one_line(self):
        self.append(started(), ended())

        def landing(argv):
            print("draft/a: rebase: conflict\nfile.py")
            return 1

        self.land.side_effect = landing
        self.tick()
        self.assertEqual(self.out.getvalue(), "flow draft target 2, 0 in flight\nland draft/a failed: draft/a: rebase: conflict file.py\n")
        self.assertEqual(log.read()[-1]["text"], self.out.getvalue().splitlines()[-1])

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
        with self.assertRaises(plan.PlanError):
            self.tick()
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
        self.tick(log_path=path)
        self.assertEqual([c[0] for c in self.calls], ["collect", "start"])
        self.assertEqual(self.calls[0][-1]["log_path"], path)
        self.assertEqual(self.calls[1][-1]["log_path"], path)
        self.assertEqual(self.calls[1][-1]["events"][-1]["ev"], "branch.rejected")
        self.assertEqual(self.calls[1][-1]["rejection"], log.read(path)[-1])
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
        self.assertIn("unknown task draft/missing", err.getvalue())
        self.assertFalse(log.home().exists())
        self.assertEqual(self.calls, [])

    def test_plan_problems_refused_before_queue_or_actions(self):
        self.add_task("a", needs=("missing",))
        with self.assertRaisesRegex(plan.PlanError, "unknown task draft/missing"):
            self.tick()
        self.assertEqual(self.calls, [])
        self.assertFalse(log.default_path().exists())


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
