import os
import shlex
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fab import atomic, foreman, log, repairs, run
from fab.hosts import Host
from fab.plan import Task
from fab.sh import Result, run as shell
from fab.tests.support import FakeRunner, GIT_ENV, git, git_pair, tmp_home

# The vocabulary of fab.repairs' tests: a task, its refusal records and its foreman's, in
# log order. Each builder returns the records the fold reads, nothing more; ts strings
# compare in the order the test writes them.

TASK = Task("draft/task", "part", "feature", "agents", (), ("fab/x.py",), "high", 30,
            "# Task\n", "docs/plan/draft/tasks/task.md")
HOST = Host("builder", "worker@builder.invalid", ("builder",))
SPEC = "+++\nid = 'task'\n+++\n# Task\n\nFill x.\n"
FOREMAN = foreman.task_field(TASK.id)
RUN = FOREMAN + "-1"


def event(ev, ts, **fields):
    """One record with just the fields given."""
    return {"ev": ev, "ts": ts, **fields}


def task_run(ts, n=1, kind="implement", branch=TASK.id):
    """The task's own run n starting at ts."""
    return event("run.started", ts, run=f"{TASK.id}-{n}", task=TASK.id, kind=kind,
                 branch=branch)


def rejected(ts, step="test", tip="tip1", branch=TASK.id, **fields):
    """The landing refusing branch at tip; fields add log or findings."""
    return event("branch.rejected", ts, task=TASK.id, branch=branch, tip=tip, step=step,
                 **fields)


def foreman_run(ts, run_id=RUN, outcome=None, ended=None, tip="tip1"):
    """A refusal's foreman starting at ts and, with outcome, ending at ended."""
    records = [event("run.started", ts, run=run_id, task=FOREMAN, kind=repairs.KIND,
                     branch=TASK.id, refused=tip, step="test")]
    if outcome is not None:
        records.append(event("run.ended", ended or ts, run=run_id, task=FOREMAN,
                             outcome=outcome, report=f"/fab/runs/{run_id}/report.md"))
    return records


def settled(ts, verdict, run_id=RUN, section=""):
    """The tick's record of acting on run_id's verdict."""
    return event(repairs.SETTLED, ts, task=TASK.id, run=run_id, verdict=verdict,
                 reason="why", branch="", section=section)


def report(verdict, line, *body):
    """A foreman's report: `Done: <verdict>: <line>`, then body's lines."""
    return "\n".join([f"Done: {verdict}: {line}", *body]) + "\n"


def refusal(state="foreman", since="02", **fields):
    """The Refusal the fold gives for rejected("02") alone, with fields changed."""
    found = repairs.Refusal(TASK.id, TASK.id, "tip1", "test", "", "", "02", "repair",
                            "foreman", "02")
    return replace(found, state=state, since=since, **fields)


def command(call):
    """Unwrap the recorded ssh command without running it."""
    return shlex.split(shlex.split(call.argv[-1])[2])


def starter():
    """Accept builder commands and answer the launcher."""
    def answer(call):
        if command(call)[:3] == ["fab", "codex", "start"]:
            return Result(0, "codex-1 /state/codex-1\n")
        return Result(0)
    return FakeRunner().on(["ssh"], answer)


def spec_checkout(home):
    """A real origin and checkout with TASK's spec on main."""
    origin, checkout = git_pair(home)
    path = checkout / TASK.path
    atomic.write(path, SPEC)
    git(checkout, "add", TASK.path)
    git(checkout, "commit", "-q", "-m", "Add spec")
    git(checkout, "push", "-q", "origin", "main")
    return origin, checkout, replace(TASK, path=str(path))


def git_runner(commands):
    """Record git commands against only the fixture with an isolated configuration."""
    def invoke(argv, **keywords):
        commands.append(list(argv))
        return shell(argv, env={**os.environ, **GIT_ENV}, **keywords)
    return invoke


class RepairsTestCase(unittest.TestCase):
    def only(self, events):
        """The one open refusal of TASK after events."""
        found = repairs.refusals({TASK.id: TASK}, iter(events))
        self.assertEqual(len(found), 1, found)
        return found[0]

    def assertStands(self, events, state, since, **fields):
        """TASK's open refusal after events is in state since since, with fields."""
        found = self.only(events)
        self.assertEqual((found.state, found.since), (state, since))
        for name, value in fields.items():
            self.assertEqual(getattr(found, name), value, name)


class ExemplarTest(RepairsTestCase):
    def test_a_red_goes_through_its_foreman_into_the_spec(self):
        events = [task_run("01"), rejected("02")]
        self.assertStands(events, "foreman", "02", kind="repair", retried=False)
        events += foreman_run("03")
        self.assertStands(events, "deciding", "03", foreman=RUN)
        events += foreman_run("03", outcome="done", ended="04")[1:]
        decided = self.only(events)
        self.assertEqual(decided, refusal("decided", "04", foreman=RUN,
                                          report=f"/fab/runs/{RUN}/report.md"))
        verdict, reason, body = repairs.remedy(
            decided, report("fix", "make x return 2", "test_x fails: 1 != 2", ""))
        self.assertEqual((verdict, reason), ("fix", "make x return 2"))
        self.assertEqual(body, "make x return 2\ntest_x fails: 1 != 2")
        text = repairs.section(decided, day="2026-10-31", run_id=RUN, body=body)
        self.assertTrue(text.startswith(f"## Repair (2026-10-31, step test, foreman {RUN})\n\n"))
        spec = repairs.with_section(SPEC, text, run_id=RUN)
        self.assertEqual(spec, SPEC + "\n" + text)
        self.assertEqual(repairs.with_section(spec, text, run_id=RUN), spec)
        events.append(settled("05", "fix", section=text))
        self.assertStands(events, "settled", "05", verdict="fix", section=text)
        self.assertEqual(repairs.refusals({TASK.id: TASK}, [*events, task_run("06", n=2)]), [])


class RefusalsTest(RepairsTestCase):
    def test_foreman_since_rejected(self):
        self.assertEqual(self.only([task_run("01"), rejected("02")]), refusal())

    def test_deciding_since_start(self):
        self.assertStands([rejected("02"), *foreman_run("03")], "deciding", "03", foreman=RUN)

    def test_decided_since_end(self):
        self.assertStands([rejected("02"), *foreman_run("03", outcome="done", ended="04")],
                          "decided", "04", report=f"/fab/runs/{RUN}/report.md")

    def test_settled_since_settlement(self):
        self.assertStands([rejected("02"), *foreman_run("03", outcome="done", ended="04"),
                           settled("05", "fix", section="section")],
                          "settled", "05", verdict="fix", section="section")

    def test_failed_falls_back(self):
        self.assertStands([rejected("02"), *foreman_run("03", outcome="failed", ended="04")],
                          "fallback", "04")

    def test_question_falls_back(self):
        self.assertStands([rejected("02"), *foreman_run("03", outcome="question", ended="04")],
                          "fallback", "04")

    def test_infra_falls_back(self):
        self.assertStands([rejected("02"), *foreman_run("03", outcome="infra", ended="04")],
                          "fallback", "04")

    def test_task_run_closes(self):
        self.assertEqual(repairs.refusals({TASK.id: TASK}, [rejected("02"), task_run("03")]), [])

    def test_ready_closes(self):
        self.assertEqual(repairs.refusals({TASK.id: TASK}, [rejected("02"),
                         event("branch.ready", "03", task=TASK.id)]), [])

    def test_landed_closes(self):
        self.assertEqual(repairs.refusals({TASK.id: TASK}, [rejected("02"),
                         event("branch.landed", "03", task=TASK.id)]), [])

    def test_foreman_records_never_close(self):
        events = [rejected("02"), *foreman_run("03"),
                  event("branch.ready", "04", task=FOREMAN),
                  event("branch.landed", "05", task=FOREMAN)]
        self.assertStands(events, "deciding", "03")

    def test_later_rejection_replaces(self):
        events = [rejected("02"), *foreman_run("03", outcome="done"),
                  rejected("04", step="merge", tip="tip2", branch="draft/task-r1")]
        self.assertStands(events, "foreman", "04", tip="tip2", step="merge", kind="rebase",
                          branch="draft/task-r1", foreman=None)

    def test_outside_tasks_left_out(self):
        self.assertEqual(repairs.refusals({}, [rejected("02")]), [])

    def test_question_foreman_does_not_count(self):
        started = foreman_run("03")[0]
        started["asked"] = started.pop("refused")
        self.assertStands([rejected("02"), started], "foreman", "02", foreman=None)

    def test_foreman_before_rejection_does_not_count(self):
        self.assertStands([*foreman_run("01"), rejected("02")], "foreman", "02", foreman=None)

    def test_last_of_two_foremen_counts(self):
        second = RUN.removesuffix("1") + "2"
        self.assertStands([rejected("02"), *foreman_run("03", outcome="done"),
                           *foreman_run("04", run_id=second)], "deciding", "04", foreman=second)

    def test_settlement_for_another_run_does_not_count(self):
        self.assertStands([rejected("02"), *foreman_run("03", outcome="done", ended="04"),
                           settled("05", "fix", run_id="another")], "decided", "04", verdict="")

    def test_settlement_for_another_task_does_not_count(self):
        other = {**settled("05", "fix"), "task": "other/task"}
        self.assertStands([rejected("02"), *foreman_run("03", outcome="done", ended="04"), other],
                          "decided", "04", verdict="")

    def test_settlement_before_end_does_not_count(self):
        self.assertStands([rejected("02"), *foreman_run("03"), settled("04", "fix"),
                           foreman_run("03", outcome="done", ended="05")[1]], "decided", "05")

    def test_first_end_and_settlement_count(self):
        events = [rejected("02"), *foreman_run("03", outcome="done", ended="04"),
                  settled("05", "fix", section="first"), settled("06", "none"),
                  foreman_run("03", outcome="failed", ended="07")[1]]
        self.assertStands(events, "settled", "05", verdict="fix", section="first")

    def test_rebase_step_gives_rebase(self):
        self.assertEqual(self.only([rejected("02", step="rebase")]).kind, "rebase")

    def test_merge_step_gives_rebase(self):
        self.assertEqual(self.only([rejected("02", step="merge")]).kind, "rebase")

    def test_retry_after_last_run_counts(self):
        self.assertStands([task_run("01"), settled("02", "retry"), rejected("03")],
                          "foreman", "03", retried=True)

    def test_retry_before_last_run_does_not_count(self):
        self.assertStands([settled("01", "retry"), task_run("02"), rejected("03")],
                          "foreman", "03", retried=False)

    def test_retry_without_task_run_counts(self):
        self.assertStands([settled("01", "retry"), rejected("02")], "foreman", "02", retried=True)

    def test_retry_after_rejection_does_not_count(self):
        self.assertStands([rejected("02"), settled("03", "retry")], "foreman", "02", retried=False)

    def test_other_verdict_does_not_mark_retried(self):
        self.assertStands([settled("01", "fix"), rejected("02")], "foreman", "02", retried=False)

    def test_findings_and_log_carried(self):
        self.assertStands([rejected("02", log="detail", findings="red")], "foreman", "02",
                          log="detail", findings="red")

    def test_optional_fields_missing_are_empty(self):
        entry = rejected("02")
        entry.pop("tip")
        self.assertStands([entry], "foreman", "02", tip="", log="", findings="")

    def test_two_refusals_keep_log_order(self):
        other = replace(TASK, id="other/task")
        records = [rejected("09"), {**rejected("01"), "task": other.id}]
        self.assertEqual([r.task for r in repairs.refusals({TASK.id: TASK, other.id: other}, records)],
                         [TASK.id, other.id])

    def test_equal_timestamps_keep_log_order_after_replacement(self):
        other = replace(TASK, id="other/task")
        records = [rejected("02"), {**rejected("02"), "task": other.id}, rejected("02", tip="new")]
        found = repairs.refusals({TASK.id: TASK, other.id: other}, records)
        self.assertEqual([(r.task, r.tip) for r in found], [(other.id, "tip1"), (TASK.id, "new")])

    def test_missing_rejection_fields_skipped(self):
        for key in ("task", "branch", "step", "ts"):
            with self.subTest(key=key):
                broken = rejected("02")
                broken.pop(key)
                self.assertEqual(repairs.refusals({TASK.id: TASK}, [broken]), [])

    def test_missing_start_fields_skipped(self):
        for key in ("run", "task", "kind", "ts"):
            with self.subTest(key=key):
                broken = foreman_run("03")[0]
                broken.pop(key)
                self.assertStands([rejected("02"), broken], "foreman", "02")
                broken = task_run("03")
                broken.pop(key)
                self.assertStands([rejected("02"), broken], "foreman", "02")

    def test_missing_end_fields_skipped(self):
        for key in ("run", "outcome", "ts"):
            with self.subTest(key=key):
                broken = foreman_run("03", outcome="done", ended="04")[1]
                broken.pop(key)
                self.assertStands([rejected("02"), *foreman_run("03"), broken], "deciding", "03")

    def test_missing_settlement_fields_skipped(self):
        for key in ("task", "run", "verdict", "ts"):
            with self.subTest(key=key):
                broken = settled("05", "fix")
                broken.pop(key)
                self.assertStands([rejected("02"), *foreman_run("03", outcome="done", ended="04"),
                                   broken], "decided", "04")


class BriefTest(RepairsTestCase):
    def test_every_section_in_order_role_first_spec_verbatim(self):
        role = "# Role\nRead only.\n\n"
        text = repairs.brief(refusal(), TASK, run_id=RUN, report="/report.md", spec=SPEC,
                             text="red\n\n", role=role)
        expected = ("# Role\nRead only.\n\n# The refusal\n\n"
                    f"- Run: {RUN}\n- Task: {TASK.id} (spec `{TASK.path}`)\n"
                    f"- Branch: `{TASK.id}` at `tip1`\n- Step: `test`\n- Next run: repair\n"
                    "- Retried unchanged since its last run: no\n"
                    "- Report: write it to `/report.md`\n"
                    f"Your checkout is the task's repository at origin/{TASK.id}, read-only.\n\n"
                    "# The failing step's log\n\n```text\nred\n```\n\n# The task spec\n\n" + SPEC)
        self.assertEqual(text, expected)

    def test_empty_tip_and_retried_yes(self):
        text = repairs.brief(refusal(tip="", retried=True), TASK, run_id=RUN, report="/r",
                             spec=SPEC, text="", role="role")
        self.assertIn(f"- Branch: `{TASK.id}` at `-`", text)
        self.assertIn("since its last run: yes", text)

    def test_spec_without_newline_gets_one(self):
        text = repairs.brief(refusal(), TASK, run_id=RUN, report="/r", spec="+++\nverbatim  ",
                             text="", role="role")
        self.assertTrue(text.endswith("# The task spec\n\n+++\nverbatim  \n"))


class StartTest(RepairsTestCase):
    def test_detached_branch_launch_and_event_after_question_foreman(self):
        with tmp_home() as home:
            spec = home / "task.md"
            atomic.write(spec, SPEC)
            task = replace(TASK, path=str(spec))
            earlier = foreman_run("01")[0]
            earlier["asked"] = earlier.pop("refused")
            fake = starter()
            run_id = repairs.start(refusal(branch="draft/task-r1"), task, HOST, [earlier], sh=fake)
            self.assertEqual(run_id, FOREMAN + "-2")
            root = Path(run.remote_home(HOST))
            self.assertEqual(command(fake.calls[3]), ["git", "-C", str(root / "repos/agents"),
                             "worktree", "add", "--detach", str(root / "wt" / run_id),
                             "origin/draft/task-r1"])
            self.assertEqual(command(fake.calls[-1]), ["fab", "codex", "start", "--effort", "medium",
                             "--model", run.MODEL, "--read-only", str(root / "runs" / run_id / "brief.md"),
                             str(root / "wt" / run_id), str(root / "runs" / run_id / "report.md")])
            self.assertTrue(all(call.argv[5] == HOST.ssh for call in fake.calls))
            started, = log.read()
            self.assertEqual(started["base"], "origin/main")
            self.assertEqual({key: started[key] for key in ("task", "kind", "branch", "refused", "step")},
                             dict(task=FOREMAN, kind="foreman", branch="draft/task-r1",
                                  refused="tip1", step="test"))
            self.assertIn(SPEC, (home / "fab/runs" / run_id / "brief.md").read_text())

    def test_start_keeps_refused_branch_and_logs_trunk_base(self):
        with tmp_home() as home:
            spec = home / "task.md"
            atomic.write(spec, SPEC)
            fake = starter()
            run_id = repairs.start(refusal(branch="draft/task-r1"), replace(TASK, path=str(spec)),
                                    HOST, [], sh=fake, trunk="component-kit/integration")
            root = Path(run.remote_home(HOST))
            self.assertEqual(command(fake.calls[3]), ["git", "-C", str(root / "repos/agents"),
                             "worktree", "add", "--detach", str(root / "wt" / run_id),
                             "origin/draft/task-r1"])
            self.assertEqual(log.read()[0]["base"], "origin/component-kit/integration")

    def test_unreadable_spec_starts_nothing(self):
        with tmp_home() as home:
            fake = starter()
            with self.assertRaises(OSError):
                repairs.start(refusal(), replace(TASK, path=str(home / "missing")), HOST, [], sh=fake)
            self.assertEqual(fake.calls, [])
            self.assertEqual(log.read(), [])

    def test_unreadable_role_starts_nothing(self):
        with tmp_home() as home, patch.object(repairs, "ROLE", home / "missing"):
            atomic.write(home / "task.md", SPEC)
            fake = starter()
            with self.assertRaises(OSError):
                repairs.start(refusal(), replace(TASK, path=str(home / "task.md")), HOST, [], sh=fake)
            self.assertEqual(fake.calls, [])

    def test_findings_in_brief_without_gate_read(self):
        with tmp_home() as home, patch.object(run.hosts, "load") as load:
            atomic.write(home / "task.md", SPEC)
            fake = starter()
            path = home / "events.jsonl"
            run_id = repairs.start(refusal(step="gate:shape", findings="shape: signature changed"),
                                   replace(TASK, path=str(home / "task.md")), HOST, [], sh=fake,
                                   log_path=path)
            load.assert_not_called()
            self.assertFalse(any(command(call)[0] == "tail" for call in fake.calls))
            text = (home / "fab/runs" / run_id / "brief.md").read_text()
            self.assertIn("```text\nshape: signature changed\n```", text)
            self.assertEqual(log.read(path)[0]["step"], "gate:shape")
            self.assertEqual(log.read(), [])


class RemedyTest(RepairsTestCase):
    def test_fix_cuts_body_and_right_strips(self):
        lines = [f"line {i}  " for i in range(repairs.SECTION_LINES + 2)]
        verdict, reason, body = repairs.remedy(refusal(), report("fix", "make x work", *lines))
        self.assertEqual((verdict, reason), ("fix", "make x work"))
        self.assertEqual(body.splitlines(), ["make x work", *[line.rstrip() for line in lines[:30]]])

    def test_fix_drops_trailing_blank_lines(self):
        self.assertEqual(repairs.remedy(refusal(), report("fix", "fix x", "detail  ", " ", "")),
                         ("fix", "fix x", "fix x\ndetail"))

    def test_retry(self):
        self.assertEqual(repairs.remedy(refusal(), report("retry", "flake", "evidence")),
                         ("retry", "flake", ""))

    def test_spaces_around_colons_and_leading_blanks(self):
        self.assertEqual(repairs.remedy(refusal(), "\n  \n Done : fix : fix x \n detail  \n"),
                         ("fix", "fix x", "fix x\n detail"))

    def test_retry_refused_after_retry(self):
        self.assertEqual(repairs.remedy(refusal(retried=True), report("retry", "flake")),
                         ("none", "retry refused: the branch was retried unchanged once since its last run", ""))

    def test_paths_never_retried(self):
        self.assertEqual(repairs.remedy(refusal(step="paths"), report("retry", "flake")),
                         ("none", "retry refused: step paths is the branch's", ""))

    def test_gate_never_retried(self):
        self.assertEqual(repairs.remedy(refusal(step="gate:shape"), report("retry", "flake")),
                         ("none", "retry refused: step gate:shape is the branch's", ""))

    def test_bad_reports_give_none(self):
        for text in ("Failed: no", "", "\n \n", "Done: fix: ", "Done: retry:",
                     "Done: approve: yes", "Done: Fix: no", "done: fix: no", "Done: fix x",
                     "Question: choose", "Infra: disk", "bad first\nDone: fix: later", "x" * 200):
            with self.subTest(text=text):
                first = next((line.strip() for line in text.splitlines() if line.strip()), "")
                self.assertEqual(repairs.remedy(refusal(), text), ("none", "no verdict: " + first[:120], ""))


class SectionTest(RepairsTestCase):
    def test_repair_section(self):
        self.assertEqual(repairs.section(refusal(), day="2026-10-31", run_id=RUN, body="fix x"),
                         f"## Repair (2026-10-31, step test, foreman {RUN})\n\nfix x\n")

    def test_rebase_section(self):
        self.assertEqual(repairs.section(refusal(kind="rebase", step="merge"), day="today",
                                         run_id=RUN, body="resolve x\n"),
                         f"## Rebase (today, step merge, foreman {RUN})\n\nresolve x\n")

    def test_append_after_one_blank_line(self):
        self.assertEqual(repairs.with_section(SPEC + "\n\n", "section\n", run_id=RUN),
                         SPEC + "\nsection\n")

    def test_existing_run_section_unchanged(self):
        for title in ("Repair", "Rebase"):
            with self.subTest(title=title):
                spec = SPEC + f"\n## {title} (day, step test, foreman {RUN})\n\nexisting\n"
                self.assertEqual(repairs.with_section(spec, "new\n", run_id=RUN), spec)

    def test_other_run_section_does_not_block(self):
        spec = SPEC + "\n## Repair (day, step test, foreman other)\n\nexisting\n"
        self.assertEqual(repairs.with_section(spec, "new\n", run_id=RUN), spec + "\nnew\n")


class CommitTest(RepairsTestCase):
    def test_section_pushed_once_one_commit_above_main(self):
        with tmp_home() as home:
            origin, checkout, task = spec_checkout(home)
            commands = []
            text = repairs.section(refusal(), day="2026-10-31", run_id=RUN, body="fix x")
            branch = repairs.commit(refusal(), task, text, checkout, run_id=RUN, sh=git_runner(commands))
            self.assertEqual(branch, f"repairs/{RUN}")
            self.assertEqual(git(origin, "show", f"{branch}:{TASK.path}") + "\n", SPEC + "\n" + text)
            self.assertEqual(git(origin, "rev-list", "--count", f"main..{branch}"), "1")
            self.assertEqual(git(origin, "log", "-1", "--format=%s", branch),
                             f"Write {TASK.id}'s repair from its refusal at test")
            self.assertFalse((home / "fab/runs" / RUN / "wt").exists())
            self.assertEqual(git(checkout, "branch", "--list", branch), "")
            git(origin, "update-ref", "refs/heads/main", git(origin, "rev-parse", branch))
            commands.clear()
            self.assertIsNone(repairs.commit(refusal(), task, text, checkout, run_id=RUN,
                                              sh=git_runner(commands)))
            self.assertFalse(any("commit" in argv or "push" in argv for argv in commands))
            self.assertFalse((home / "fab/runs" / RUN / "wt").exists())
            self.assertEqual(git(checkout, "branch", "--list", branch), "")

    def test_commit_uses_trunk_for_spec_worktree(self):
        for trunk in ("main", "component-kit/integration"):
            with self.subTest(trunk=trunk), tmp_home() as home:
                checkout = home / "checkout"
                task = replace(TASK, path=str(checkout / TASK.path))
                worktree = log.home() / "runs" / RUN / "wt"
                atomic.write(worktree / TASK.path, SPEC)
                fake = FakeRunner()
                text = repairs.section(refusal(), day="today", run_id=RUN, body="fix x")
                branch = repairs.commit(refusal(), task, text, checkout, run_id=RUN,
                                         sh=fake, trunk=trunk)
                self.assertEqual(branch, f"repairs/{RUN}")
                self.assertEqual(fake.argvs()[1], ["git", "worktree", "add", "-B", branch,
                                                   str(worktree), f"origin/{trunk}"])
                self.assertEqual((worktree / TASK.path).read_text(),
                                 repairs.with_section(SPEC, text, run_id=RUN))

    def test_fabrig_section_reuses_pushed_branch_before_landing(self):
        """Real git verifies the section's pushed commit survives worktree cleanup."""
        with tmp_home() as home:
            origin, checkout, task = spec_checkout(home)
            task = replace(task, repo="fabrig")
            commands = []
            text = repairs.section(refusal(), day="2026-10-31", run_id=RUN, body="fix x")
            branch = repairs.commit(refusal(), task, text, checkout, run_id=RUN, sh=git_runner(commands))
            tip = git(origin, "rev-parse", branch)
            commands.clear()
            self.assertEqual(repairs.commit(refusal(), task, text, checkout, run_id=RUN,
                                             sh=git_runner(commands)), branch)
            self.assertEqual(git(origin, "rev-parse", branch), tip)
            self.assertEqual([argv[1] for argv in commands], ["show"])
            self.assertEqual((checkout / TASK.path).read_text(), SPEC)
            self.assertFalse((home / "fab/runs" / RUN / "wt").exists())


if __name__ == "__main__":
    unittest.main()
