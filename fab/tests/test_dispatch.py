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
from unittest.mock import patch

from fab import cli, dispatch, log, plan, state
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


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    sibling = path.with_name(path.name + ".tmp")
    sibling.write_text(text)
    sibling.replace(path)


class DecideTest(unittest.TestCase):
    def setUp(self):
        self.plan = make_plan(part("core"))
        self.hosts = {"builder": Host("builder", "fake@builder", ("builder",), places=2)}

    def decide(self, tasks, events=(), hosts=None, spec=None):
        return dispatch.decide(spec or self.plan, {t.id: t for t in tasks}, list(events),
                               self.hosts if hosts is None else hosts)

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

    def test_four_steps_order_and_last_run_branch(self):
        tasks = [task("a"), task("b"), task("c"), task("d", repo="fabrig"), task("e")]
        events = [started("a"), started("b"), ended("b", outcome="infra"),
                  started("b", 2, branch="draft/b-r1"), ended("b", 2),
                  started("d"), ended("d"), started("c"), ended("c"),
                  event("branch.rejected", "c", step="merge")]
        actions = self.decide(tasks, events, spec=make_plan(part("core"), part("next"), low=2))
        self.assertEqual([a.kind for a in actions], ["collect", "land", "ready", "start", "design"])
        self.assertEqual(actions[0].run, "draft/a-1")
        self.assertEqual(actions[1].branch, "draft/b-r1")
        self.assertEqual(actions[2].branch, "draft/d")
        self.assertEqual((actions[3].task, actions[3].run_kind), ("draft/c", "rebase"))
        self.assertEqual(actions[4].detail, "next")

    def test_rejected_before_runnable_and_task_order_within_each(self):
        tasks = [task(name) for name in ("a", "b", "c", "d")]
        events = [event("branch.rejected", name, step="test") for name in ("d", "b")]
        actions = self.decide(tasks, events)
        self.assertEqual([a.task for a in actions], ["draft/b", "draft/d"])
        self.assertEqual([a.run_kind for a in actions], ["repair", "repair"])

    def test_builder_most_free_first_recomputed_and_ties_by_name(self):
        hosts = {"z": Host("z", "fake@z", ("builder",), places=3),
                 "a": Host("a", "fake@a", ("builder",), places=1)}
        actions = self.decide([task(str(i)) for i in range(6)], hosts=hosts)
        self.assertEqual([a.host for a in actions], ["z", "z", "a", "z"])

    def test_other_plans_occupy_places_and_collect_in_log_order(self):
        events = [started("other"), started("foreign")]
        actions = self.decide([task("a")], events)
        self.assertEqual([a.kind for a in actions], ["collect", "collect"])
        self.assertEqual([a.task for a in actions], ["draft/other", "draft/foreign"])
        self.assertEqual(self.decide([task("a")], hosts={}), [])

    def test_rejections_use_last_step(self):
        for step, expected in (("merge", "rebase"), ("rebase", "rebase"),
                               ("test", "repair"), ("push", "repair"), ("paths", "repair")):
            with self.subTest(step=step):
                events = [event("branch.rejected", step="rebase"),
                          event("branch.rejected", step=step)]
                self.assertEqual(self.decide([task("a")], events)[0].run_kind, expected)

    def test_infra_repairs_and_new_tasks_implement(self):
        events = [started(), ended(outcome="infra")]
        actions = self.decide([task("a"), task("b")], events)
        self.assertEqual([(a.task, a.run_kind) for a in actions],
                         [("draft/a", "repair"), ("draft/b", "implement")])

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


class TickTest(unittest.TestCase):
    def setUp(self):
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
        return dispatch.tick(self.directory, sh=self.fake, hosts=self.hosts, **kwargs)

    def queue(self, records):
        self.fake.on(ssh("fake@gate", ["fab", "queue", "log"])[:-1],
                     Result(0, "\n".join(json.dumps(r) for r in records)))

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
        self.tick()
        self.assertEqual(log.read(), first)
        commands = [shlex.split(c.argv[-1].removeprefix("bash -lc "))[0]
                    for c in self.fake.calls if c.argv[0] == "ssh"]
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
                         [f"{a.kind} {a.task or '-'} {a.detail}" for a in actions])
        # Ready and parked tasks are not handed off or parked twice.
        self.tick()
        self.assertEqual(len([e for e in log.read() if e["ev"] == "branch.ready"]), 1)
        self.assertEqual(len([e for e in log.read() if e["ev"] == "question.asked"]), 1)

    def test_design_only_prints(self):
        write(self.directory / "plan.toml", (self.directory / "plan.toml").read_text() +
              '\n[[part]]\nid="next"\ntitle="Next"\nmode="feature"\nneeds=[]\ndesign="next.md"\n')
        # Extend the slice to include the new part.
        path = self.directory / "plan.toml"
        write(path, path.read_text().replace('parts = ["core"]', 'parts = ["core", "next"]'))
        self.append(event("question.asked", text="Which?"))
        actions = self.tick()
        self.assertEqual(actions, [Action("design", detail="next")])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.out.getvalue(), "design - next\n")
        self.assertEqual(len(log.read()), 1)

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
                         ["land draft/a failed: offline retry later", "land draft/b draft/b"])

    def test_land_output_is_captured_to_keep_one_line_per_action(self):
        self.append(started(), ended())

        def landing(argv):
            print("draft/a: landed: Landed; branch deleted")
            return 0

        self.land.side_effect = landing
        self.tick()
        self.assertEqual(self.out.getvalue(), "land draft/a draft/a\n")

    def test_failed_land_output_is_printed_and_noted_on_one_line(self):
        self.append(started(), ended())

        def landing(argv):
            print("draft/a: rebase: conflict\nfile.py")
            return 1

        self.land.side_effect = landing
        self.tick()
        self.assertEqual(self.out.getvalue(), "land draft/a failed: draft/a: rebase: conflict file.py\n")
        self.assertEqual(log.read()[-1]["text"], self.out.getvalue().strip())

    def test_run_failures_do_not_stop_following_actions(self):
        self.add_task("b")
        self.add_task("c")
        self.append(started())
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
        self.assertEqual(len(self.fake.calls), 2)

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
            self.assertEqual(dispatch.tick(self.directory, sh=self.fake, hosts={}), [])
        self.assertEqual(len(self.fake.calls), 1)

    def test_explicit_log_path_used_for_import_run_calls_and_park(self):
        path = self.home / "custom.jsonl"
        self.add_task("b")
        self.append(started(), path=path)
        self.queue([dict(ev="rejected", ts="001", branch="draft/b", tip="b", step="test", log="red")])
        self.tick(log_path=path)
        self.assertEqual([c[0] for c in self.calls], ["collect", "start"])
        self.assertEqual(self.calls[0][-1]["log_path"], path)
        self.assertEqual(self.calls[1][-1]["log_path"], path)
        self.assertEqual(self.calls[1][-1]["events"][-1]["ev"], "branch.rejected")
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
             patch("fab.dispatch.run", side_effect=AssertionError("command ran")):
            self.assertEqual(dispatch.main([str(self.directory), "--dry-run"]), 0)
        self.assertEqual(self.out.getvalue(), "land draft/a draft/a\n")
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
