import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import replace

from fab import log, state
from fab.plan import Part, Plan, Task
from fab.tests.support import tmp_home


def task(identifier, needs=()):
    return Task(identifier, "core", "feature", "repo", needs, (), "high", 25, "", "task.md")


def event(kind, identifier="draft/a", **fields):
    return {"ev": kind, "task": identifier, **fields}


class FoldTest(unittest.TestCase):
    def setUp(self):
        self.tasks = {"draft/a": task("draft/a"), "draft/b": task("draft/b", ("draft/a",))}
        self.start = event("run.started", run="draft/a-1", branch="draft/a")

    def test_empty_log_waiting_and_runnable_in_task_order(self):
        tasks = {"draft/b": self.tasks["draft/b"], "draft/a": self.tasks["draft/a"],
                 "draft/c": task("draft/c", ("draft/missing",))}
        views = state.fold(tasks, [])
        self.assertEqual(list(views), list(tasks))
        self.assertEqual([v.status for v in views.values()], ["waiting", "runnable", "waiting"])
        self.assertEqual(views["draft/a"], state.TaskView("draft/a", "runnable"))
        self.assertEqual(state.runnable(views), ["draft/a"])

    def test_started_records_each_run_and_current_branch(self):
        events = [self.start, event("run.ended", outcome="infra"),
                  event("run.started", run="draft/a-2", branch="draft/a-r2")]
        view = state.fold(self.tasks, iter(events))["draft/a"]
        self.assertEqual(view.status, "running")
        self.assertEqual(view.runs, ["draft/a-1", "draft/a-2"])
        self.assertEqual(view.branch, "draft/a-r2")

    def test_each_run_outcome(self):
        for outcome, status, question in (("done", "done", None), ("question", "parked", None),
                                         ("failed", "parked", "Failed: runs/a/report.md"),
                                         ("infra", "runnable", None)):
            with self.subTest(outcome=outcome):
                views = state.fold(self.tasks, [self.start, event("run.ended", outcome=outcome,
                                                                report="runs/a/report.md")])
                self.assertEqual((views["draft/a"].status, views["draft/a"].question), (status, question))
                self.assertEqual(views["draft/b"].status, "waiting")
                self.assertEqual(views["draft/a"].runs, ["draft/a-1"])

    def test_question_asked_and_answered(self):
        events = [self.start, event("run.ended", outcome="question"),
                  event("question.asked", text="Which option?\n A or B")]
        view = state.fold(self.tasks, events)["draft/a"]
        self.assertEqual((view.status, view.question), ("parked", "Which option?\n A or B"))
        events.append(event("question.answered", answer="B"))
        view = state.fold(self.tasks, events)["draft/a"]
        self.assertEqual((view.status, view.question), ("runnable", None))

    def test_ready_landed_and_rejected(self):
        events = [self.start, event("run.ended", outcome="done"), event("branch.ready", tip="tip1")]
        view = state.fold(self.tasks, events)["draft/a"]
        self.assertEqual((view.status, view.tip, view.branch), ("ready", "tip1", "draft/a"))
        self.assertIsNone(view.main)
        rejected = state.fold(self.tasks, events + [event("branch.rejected", step="test")])["draft/a"]
        self.assertEqual((rejected.status, rejected.tip), ("rejected", "tip1"))
        landed = state.fold(self.tasks, events + [event("branch.landed", tip="tip2", main="main2")])
        self.assertEqual((landed["draft/a"].status, landed["draft/a"].tip, landed["draft/a"].main),
                         ("landed", "tip2", "main2"))
        self.assertEqual(landed["draft/b"].status, "runnable")

    def test_retry_settlement_restores_done_and_preserves_branch_and_tip(self):
        events = [self.start, event("run.ended", outcome="done"),
                  event("branch.ready", tip="tip1"), event("branch.rejected", step="test")]
        before = state.fold(self.tasks, events)["draft/a"]
        for verdict, status in (("retry", "done"), ("fix", "rejected"), ("none", "rejected")):
            with self.subTest(verdict=verdict):
                view = state.fold(self.tasks, events + [event("refusal.settled", verdict=verdict,
                                                             branch="repairs/foreman")])["draft/a"]
                self.assertEqual(view.status, status)
                self.assertEqual((view.branch, view.tip, view.runs),
                                 (before.branch, before.tip, before.runs))

    def test_every_need_must_land(self):
        tasks = {**self.tasks, "draft/c": task("draft/c", ("draft/a", "draft/b"))}
        first = [event("branch.landed", tip="a", main="a")]
        self.assertEqual(state.fold(tasks, first)["draft/c"].status, "waiting")
        first.append(event("branch.landed", "draft/b", tip="b", main="b"))
        self.assertEqual(state.fold(tasks, first)["draft/c"].status, "runnable")

    def test_explicit_event_status_takes_precedence_over_needs(self):
        for kind, fields, status in (
            ("run.started", {"run": "b-1", "branch": "b"}, "running"),
            ("run.ended", {"outcome": "infra"}, "runnable"),
            ("run.ended", {"outcome": "done"}, "done"),
            ("question.asked", {"text": "Question"}, "parked"),
            ("question.answered", {}, "waiting"),
            ("branch.ready", {"tip": "b"}, "ready"),
            ("branch.landed", {"tip": "b", "main": "m"}, "landed"),
            ("branch.rejected", {}, "rejected"),
        ):
            with self.subTest(kind=kind, fields=fields):
                views = state.fold(self.tasks, [event(kind, "draft/b", **fields)])
                self.assertEqual(views["draft/b"].status, status)

    def test_events_apply_in_log_order(self):
        events = [event("branch.landed", tip="a", main="a"), self.start]
        views = state.fold(self.tasks, events)
        self.assertEqual(views["draft/a"].status, "running")
        self.assertEqual(views["draft/b"].status, "waiting")

    def test_unknown_tasks_and_event_types_ignored(self):
        events = [event("run.started", "other/task"), event("branch.landed", "other/task"),
                  event("future.type"), event("task.added"), {"ev": "note", "text": "hello"}]
        self.assertEqual(state.fold(self.tasks, events), state.fold(self.tasks, []))
        self.assertEqual(state.fold(self.tasks, [self.start, event("run.ended", outcome="future")])
                         ["draft/a"].status, "running")

    def test_fold_does_not_mutate_inputs_or_share_views(self):
        events = [self.start, event("question.asked", text="why?")]
        before = deepcopy((self.tasks, events))
        first = state.fold(self.tasks, events)
        second = state.fold(self.tasks, events)
        self.assertEqual((self.tasks, events), before)
        first["draft/a"].runs.append("another")
        self.assertEqual(second["draft/a"].runs, ["draft/a-1"])

    def test_runnable_preserves_order_and_empty_mapping(self):
        views = {"c": state.TaskView("c", "runnable"), "b": state.TaskView("b", "waiting"),
                 "a": state.TaskView("a", "runnable")}
        self.assertEqual(state.runnable(views), ["c", "a"])
        self.assertEqual(state.runnable({}), [])
        self.assertEqual(state.fold({}, [self.start]), {})


class PartStatusesTest(unittest.TestCase):
    def setUp(self):
        self.plan = Plan("draft", "repo", (), 1, 2, {
            name: Part(name, name, "feature", (), "design.md")
            for name in ("empty", "core", "built")
        }, (), landing="queue", reviews=True, direct=False)
        self.plan.parts["built"] = replace(self.plan.parts["built"], done=True)
        self.tasks = {"draft/a": task("draft/a"), "draft/b": task("draft/b")}

    def test_empty_parts_and_plan_done_in_plan_order(self):
        self.assertEqual(list(state.part_statuses(self.plan, {}, {}).items()), [
            ("empty", "not designed"), ("core", "not designed"), ("built", "done"),
        ])

    def test_task_specs_design_a_part_but_every_task_must_land_to_finish(self):
        for status in state.STATUSES:
            with self.subTest(status=status):
                statuses = {"draft/a": "landed", "draft/b": status}
                expected = "done" if status == "landed" else "designed"
                self.assertEqual(state.part_statuses(self.plan, self.tasks, statuses)["core"],
                                 expected)
        self.assertEqual(state.part_statuses(self.plan, self.tasks, {})["core"], "designed")
        self.assertEqual(state.part_statuses(self.plan, self.tasks, {"draft/a": "landed"})
                         ["core"], "designed")

    def test_plan_done_overrides_unlanded_tasks(self):
        self.plan.parts["core"] = replace(self.plan.parts["core"], done=True)
        self.assertEqual(state.part_statuses(self.plan, self.tasks, {})["core"], "done")

    def test_each_part_uses_only_its_tasks_and_inputs_stay_unchanged(self):
        self.tasks["draft/c"] = replace(task("draft/c"), part="empty")
        statuses = {"draft/a": "landed", "draft/b": "landed"}
        before = deepcopy((self.plan, self.tasks, statuses))
        self.assertEqual(state.part_statuses(self.plan, self.tasks, statuses), {
            "empty": "designed", "core": "done", "built": "done",
        })
        self.assertEqual((self.plan, self.tasks, statuses), before)


class StatusTest(unittest.TestCase):
    def plan_dir(self, home):
        directory = home / "plan"
        (directory / "tasks").mkdir(parents=True)
        (directory / "plan.toml").write_text('''draft = "draft"
repo = "repo"
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
        for identifier, needs in (("a", []), ("longer", ["a"])):
            (directory / "tasks" / f"{identifier}.md").write_text(
                f'+++\nid = "{identifier}"\npart = "core"\nkind = "feature"\nneeds = {needs!r}\n+++\n')
        return directory

    def run_status(self, directory):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = state.main([str(directory)])
        return code, out.getvalue(), err.getvalue()

    def test_main_empty_log_rows_aligned(self):
        with tmp_home() as home:
            code, out, err = self.run_status(self.plan_dir(home))
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, "draft/a      runnable 0 -\ndraft/longer waiting  0 -\n")

    def test_main_uses_fab_home_log_and_counts_runs(self):
        with tmp_home() as home:
            directory = self.plan_dir(home)
            log.append("run.started", task="draft/a", run="draft/a-1", branch="draft/a")
            log.append("run.ended", task="draft/a", outcome="infra")
            log.append("run.started", task="draft/a", run="draft/a-2", branch="draft/a-r2")
            log.append("branch.landed", task="draft/a", tip="tip", main="main")
            code, out, err = self.run_status(directory)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual([line.split() for line in out.splitlines()],
                         [["draft/a", "landed", "2", "draft/a-r2"],
                          ["draft/longer", "runnable", "0", "-"]])
        self.assertEqual(out.splitlines()[0].index("landed"), out.splitlines()[1].index("runnable"))

    def test_main_plan_problems_exit_one_and_name_the_id(self):
        with tmp_home() as home:
            directory = self.plan_dir(home)
            path = directory / "tasks" / "a.md"
            path.write_text(path.read_text().replace('part = "core"', 'part = "missing"'))
            code, out, err = self.run_status(directory)
        self.assertEqual((code, out), (1, ""))
        self.assertIn("task draft/a names unknown part missing", err)

    def test_main_parse_error_exits_one_and_names_file(self):
        with tmp_home() as home:
            directory = self.plan_dir(home)
            (directory / "tasks" / "a.md").write_text("bad spec")
            code, out, err = self.run_status(directory)
        self.assertEqual((code, out), (1, ""))
        self.assertIn("a.md", err)

    def test_main_empty_plan_prints_nothing(self):
        with tmp_home() as home:
            (home / "tasks").mkdir()
            (home / "plan.toml").write_text('draft = "draft"\nrepo = "repo"\npart = []\n')
            self.assertEqual(self.run_status(home), (0, "", ""))


class AnswerUnparksOnlyTest(unittest.TestCase):
    def test_an_answer_never_reopens_a_landed_task(self):
        tasks = {"d/a": Task("d/a", "p", "feature", "agents", (), (), "high", 25, "", "a.md")}
        events = [{"ev": "run.started", "task": "d/a", "run": "d/a-1", "branch": "d/a"},
                  {"ev": "branch.landed", "task": "d/a", "tip": "t", "main": "t"},
                  {"ev": "question.answered", "task": "d/a", "answer": "x"}]
        self.assertEqual(state.fold(tasks, events)["d/a"].status, "landed")


class CheckedTasksTest(unittest.TestCase):
    def setUp(self):
        self.plan = Plan("draft", "agents", (), 1, 2, {"core": Part("core", "Core", "feature", (), "design.md")}, (),
                         landing="queue", reviews=True, direct=False)
        self.spec = '+++\nid = "a"\npart = "core"\nkind = "feature"\n+++\nBuild it.\n'
        self.checked = dict(ev="call.checked", subject="draft/core", call="root", root="root",
                            outcome="green", tip="tip", tasks=["draft/a"], paths=["tasks/a.md"], specs=[self.spec])

    def test_checked_specs_join_status_needs_and_part_status(self):
        from fab.plan import checked_tasks
        existing = {"draft/b": task("draft/b", needs=("draft/a",))}
        tasks = checked_tasks(self.plan, existing, [self.checked])
        self.assertEqual(set(tasks), {"draft/a", "draft/b"})
        self.assertEqual(set(existing), {"draft/b"})
        views = state.fold(tasks, [])
        self.assertEqual((views["draft/a"].status, views["draft/b"].status), ("runnable", "waiting"))
        self.assertEqual(state.part_statuses(self.plan, tasks, {}), {"core": "designed"})
        self.assertEqual(state.fold(tasks, [dict(ev="branch.landed", task="draft/a", tip="t", main="m")])["draft/b"].status,
                         "runnable")

    def test_red_and_other_drafts_specs_do_not_count(self):
        from fab.plan import checked_tasks
        for changes in ({"outcome": "red"}, {"subject": "another/core"}):
            with self.subTest(changes=changes):
                self.assertEqual(checked_tasks(self.plan, {}, [{**self.checked, **changes}]), {})

    def test_newest_checked_spec_wins_until_main_has_its_spec(self):
        from fab.plan import checked_tasks
        newer = {**self.checked, "specs": [self.spec.replace("Build it.", "Amended.")]}
        tasks = checked_tasks(self.plan, {}, [self.checked, newer])
        self.assertEqual(tasks["draft/a"].body, "Amended.\n")
        main = task("draft/a")
        self.assertEqual(checked_tasks(self.plan, {main.id: main}, [self.checked, newer])[main.id], main)

    def test_status_reads_checked_specs_without_a_task_file(self):
        from fab.tests.support import write_plan
        with tmp_home() as home:
            directory = write_plan(home / "docs/plan/draft", "draft")
            log.append(**self.checked)
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(state.main([str(directory)]), 0)
            self.assertEqual(out.getvalue(), "draft/a runnable 0 -\n")
