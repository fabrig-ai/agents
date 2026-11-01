import os
import unittest
from dataclasses import replace
from pathlib import Path

from fab import atomic, foreman, log, run
from fab.hosts import Host
from fab.plan import Task
from fab.sh import Failed, Result, run as shell, ssh
from fab.tests.support import FakeRunner, GIT_ENV, git, git_pair, tmp_home


TASK = Task("draft/task", "part", "feature", "agents", (), ("src/x.py",), "high", 25,
            "# Task\n", "docs/plan/draft/tasks/task.md")
QUESTION = foreman.Question(TASK.id, TASK.id + "-1", "Question: Which option?\nDetails.",
                            "03", "foreman", "03")
HOST = Host("builder", "worker@builder.invalid", ("builder",))
ROOT = Path("/home/worker/src/fabrig/fab")
RUN = TASK.id + "/foreman-1"
SPEC = "+++\nid = 'task'\n+++\n# Task\n\nChoose the first option.\n"


def _event(ev, **fields):
    """Construct just the fields the question fold reads."""
    return {"ev": ev, "ts": "03", **fields}


def _asking(kind="implement"):
    """A run ending with the question, in log order."""
    return [_event("run.started", run=QUESTION.run, task=TASK.id, kind=kind, ts="01"),
            _event("run.ended", run=QUESTION.run, outcome="question", ts="02"),
            _event("question.asked", task=TASK.id, run=QUESTION.run, text=QUESTION.text)]


def _deciding(outcome=None, run_id=RUN):
    """A foreman start and, when given, its report-bearing ending."""
    events = [_event("run.started", run=run_id, task=foreman.task_field(TASK.id),
                     kind=foreman.KIND, asked=QUESTION.run, ts="04")]
    if outcome is not None:
        events.append(_event("run.ended", run=run_id, outcome=outcome, ts="05",
                             report=f"/reports/{run_id}.md"))
    return events


def _starter():
    """Accept builder preparation and return a well-formed launcher response."""
    launch = ssh(HOST.ssh, ["fab", "codex", "start", "--effort", "medium", "--model", run.MODEL,
                           "--read-only", str(ROOT / "runs" / RUN / "brief.md"),
                           str(ROOT / "wt" / RUN), str(ROOT / "runs" / RUN / "report.md")])
    return FakeRunner().on(launch, Result(0, "codex-1 /state/codex-1\n"))


class QuestionsTest(unittest.TestCase):
    def question(self, events):
        """Fold a single task from a one-shot event iterator."""
        folded = foreman.questions({TASK.id: TASK}, iter(events))
        self.assertEqual(len(folded), 1)
        return folded[0]

    def test_answered_later_is_closed(self):
        events = [*_asking(), _event("question.answered", task=TASK.id)]
        self.assertEqual(foreman.questions({TASK.id: TASK}, events), [])

    def test_task_outside_the_plan_is_left_out(self):
        self.assertEqual(foreman.questions({}, _asking()), [])

    def test_dispatcher_park_queues_since_asked(self):
        question = self.question([_asking()[-1]])
        self.assertEqual(question, replace(QUESTION, state="queued"))

    def test_park_after_a_question_run_queues_since_asked(self):
        # The dispatcher's park names the task's last run, which may have ended with a question.
        events = [*_asking()[:2], _event("question.asked", task=TASK.id, run=QUESTION.run,
                                         text=QUESTION.text, park=True)]
        self.assertEqual(self.question(events), replace(QUESTION, state="queued"))

    def test_a_task_without_a_spec_file_queues(self):
        specless = replace(TASK, path="")
        self.assertEqual(foreman.questions({TASK.id: specless}, _asking())[0].state, "queued")

    def test_stop_question_queues_without_adding_a_task(self):
        tasks = {TASK.id: TASK}
        events = [_event("question.asked", task="draft/integration", run="", text="Third refusal", park=True)]
        self.assertEqual(foreman.questions(tasks, iter(events)),
                         [foreman.Question("draft/integration", "", "Third refusal", "03", "queued", "03")])
        self.assertEqual(tasks, {TASK.id: TASK})

    def test_stop_question_of_another_draft_is_left_out(self):
        events = [_event("question.asked", task="other/integration", run="", text="Stopped", park=True)]
        self.assertEqual(foreman.questions({TASK.id: TASK}, events), [])
        self.assertEqual(foreman.questions({}, events), [])

    def test_stop_answer_closes_only_earlier_questions_in_log_order(self):
        ask = _event("question.asked", task="draft/integration", run="", text="Stopped", park=True)
        events = [ask, _event("question.answered", task="draft/integration")]
        self.assertEqual(foreman.questions({TASK.id: TASK}, events), [])
        later = {**ask, "text": "Stopped again"}
        self.assertEqual(foreman.questions({TASK.id: TASK}, [*events, later]),
                         [foreman.Question("draft/integration", "", "Stopped again", "03", "queued", "03")])

    def test_stop_without_park_is_specless_even_after_a_question_run(self):
        events = [{**event, "task": "draft/integration"} for event in _asking()]
        self.assertEqual(foreman.questions({TASK.id: TASK}, events)[0].state, "queued")

    def test_stop_questions_use_each_tasks_draft(self):
        other = replace(TASK, id="other/task")
        events = [_event("question.asked", task=f"{draft}/integration", run="", text="Stopped", park=True)
                  for draft in ("draft", "other")]
        self.assertEqual([question.task for question in foreman.questions({TASK.id: TASK, other.id: other}, events)],
                         ["draft/integration", "other/integration"])

    def test_review_question_queues_since_asked(self):
        self.assertEqual(self.question(_asking("review")), replace(QUESTION, state="queued"))

    def test_missing_start_queues_since_asked(self):
        self.assertEqual(self.question(_asking()[1:]), replace(QUESTION, state="queued"))

    def test_implement_question_goes_to_foreman(self):
        self.assertEqual(self.question(_asking()), QUESTION)

    def test_repair_question_goes_to_foreman(self):
        self.assertEqual(self.question(_asking("repair")), QUESTION)

    def test_rebase_question_goes_to_foreman(self):
        self.assertEqual(self.question(_asking("rebase")), QUESTION)

    def test_missing_ending_queues(self):
        self.assertEqual(self.question(_asking()[::2]), replace(QUESTION, state="queued"))

    def test_wrong_asking_outcome_queues(self):
        events = _asking()
        events[1]["outcome"] = "done"
        self.assertEqual(self.question(events), replace(QUESTION, state="queued"))

    def test_asking_start_after_question_does_not_count(self):
        events = _asking()
        self.assertEqual(self.question([*events[1:], events[0]]), replace(QUESTION, state="queued"))

    def test_asking_end_after_question_does_not_count(self):
        events = _asking()
        self.assertEqual(self.question([events[0], events[2], events[1]]),
                         replace(QUESTION, state="queued"))

    def test_foreman_in_flight_is_deciding_since_start(self):
        self.assertEqual(self.question([*_asking(), *_deciding()]),
                         replace(QUESTION, state="deciding", since="04", foreman=RUN))

    def ended(self, outcome, state):
        """Check the ending's time and collected report for an outcome."""
        question = self.question([*_asking(), *_deciding(outcome)])
        self.assertEqual(question, replace(QUESTION, state=state, since="05", foreman=RUN,
                                           report=f"/reports/{RUN}.md"))

    def test_done_is_settled_since_ended(self):
        self.ended("done", "settled")

    def test_failed_queues_since_ended(self):
        self.ended("failed", "queued")

    def test_question_queues_since_ended(self):
        self.ended("question", "queued")

    def test_infra_queues_since_ended(self):
        self.ended("infra", "queued")

    def test_foreman_of_another_question_does_not_count(self):
        events = _deciding("done")
        events[0]["asked"] = "another-run"
        self.assertEqual(self.question([*_asking(), *events]), QUESTION)

    def test_foreman_of_another_task_does_not_count(self):
        events = _deciding("done")
        events[0]["task"] = "other/task/foreman"
        self.assertEqual(self.question([*_asking(), *events]), QUESTION)

    def test_foreman_before_question_does_not_count(self):
        self.assertEqual(self.question([*_deciding("done"), *_asking()]), QUESTION)

    def test_last_foreman_counts(self):
        question = self.question([*_asking(), *_deciding("done"), *_deciding(run_id=RUN + "-later")])
        self.assertEqual(question, replace(QUESTION, state="deciding", since="04",
                                           foreman=RUN + "-later"))

    def test_first_foreman_ending_counts(self):
        events = [*_asking(), *_deciding("done"),
                  _event("run.ended", run=RUN, outcome="failed", report="/later", ts="06")]
        self.assertEqual(self.question(events).state, "settled")
        self.assertEqual(self.question(events).since, "05")

    def test_two_questions_keep_log_order(self):
        other = replace(TASK, id="draft/other")
        events = [_event("question.asked", task=other.id, run="other-1", text="First", ts="09"),
                  _asking()[-1]]
        folded = foreman.questions({TASK.id: TASK, other.id: other}, events)
        self.assertEqual([question.task for question in folded], [other.id, TASK.id])

    def test_equal_timestamps_keep_log_order(self):
        events = [_asking()[-1], {**_asking()[-1], "run": "later", "text": "Second"}]
        folded = foreman.questions({TASK.id: TASK}, events)
        self.assertEqual([question.run for question in folded], [QUESTION.run, "later"])

    def test_answer_before_question_does_not_close_it(self):
        self.assertEqual(self.question([_event("question.answered", task=TASK.id), *_asking()]), QUESTION)

    def test_asking_records_missing_required_fields_are_skipped(self):
        for index, record in enumerate(_asking()):
            for key in record:
                with self.subTest(ev=record["ev"], key=key):
                    events = _asking()
                    events[index] = {name: value for name, value in record.items() if name != key}
                    folded = foreman.questions({TASK.id: TASK}, events)
                    self.assertEqual(folded, [] if index == 2 else [replace(QUESTION, state="queued")])
        self.assertEqual(foreman.questions({TASK.id: TASK}, [{}, {"ev": "question.asked"}]), [])

    def test_foreman_records_missing_required_fields_are_skipped(self):
        for index, record in enumerate(_deciding("done")):
            for key in record:
                with self.subTest(ev=record["ev"], key=key):
                    deciding = _deciding("done")
                    deciding[index] = {name: value for name, value in record.items() if name != key}
                    question = self.question([*_asking(), *deciding])
                    expected = QUESTION if index == 0 else replace(
                        QUESTION, state="deciding", since="04", foreman=RUN)
                    self.assertEqual(question, expected)

    def test_malformed_ending_does_not_hide_a_later_complete_ending(self):
        events = [*_asking(), *_deciding(),
                  _event("run.ended", run=RUN, outcome="failed"), *_deciding("done")[1:]]
        self.assertEqual(self.question(events).state, "settled")

    def test_task_field_numbers_foreman_runs_separately(self):
        self.assertEqual(foreman.task_field(TASK.id), TASK.id + "/foreman")
        self.assertEqual(run.next_run(foreman.task_field(TASK.id), _asking()), RUN)
        self.assertEqual(run.next_run(foreman.task_field(TASK.id), [*_asking(), *_deciding()]),
                         TASK.id + "/foreman-2")


class BriefTest(unittest.TestCase):
    def test_sections_fenced_report_and_verbatim_spec(self):
        asking = "Question: Which?\n\nKeep the report.\n\n"
        spec = SPEC + "\n  Preserve spaces.  \n\n"
        text = foreman.brief(QUESTION, TASK, run_id=RUN, report="/remote/report.md", spec=spec,
                             asking=asking)
        facts = (f"# Your question\n\n- Run: {RUN}\n- Task: {TASK.id} (spec `{TASK.path}`)\n"
                 f"- Asked by: {QUESTION.run}\n- Report: write it to `/remote/report.md`\n"
                 "Your checkout is the task's repository at main, read-only.")
        self.assertEqual(text, foreman.ROLE.read_text().rstrip("\n") + "\n\n" + facts
                         + "\n\n# The run's report\n\n```text\n" + asking + "```"
                         + "\n\n# The task spec\n\n" + spec)

    def test_spec_without_newline_gets_one(self):
        text = foreman.brief(QUESTION, TASK, run_id=RUN, report="/report", spec="+++", asking="Why?")
        self.assertTrue(text.endswith("# The task spec\n\n+++\n"))


class StartTest(unittest.TestCase):
    def test_detached_main_medium_read_only_and_started_fields(self):
        with tmp_home() as home:
            spec = home / "spec.md"
            atomic.write(spec, SPEC)
            asking = "Question: Which option?\n\nThe whole asking report.\n"
            atomic.write(log.home() / "runs" / QUESTION.run / "report.md", asking)
            fake = _starter()
            path = home / "custom/events.jsonl"
            run_id = foreman.start(QUESTION, replace(TASK, path=str(spec)), HOST, iter(_asking()),
                                   sh=fake, log_path=path)
            self.assertEqual(run_id, RUN)
            self.assertEqual(fake.calls[3].argv, ssh(HOST.ssh,
                ["git", "-C", str(ROOT / "repos/agents"), "worktree", "add", "--detach",
                 str(ROOT / "wt" / RUN), "origin/main"]))
            self.assertEqual(fake.calls[-1].argv, _starter().rules[0][0])
            text = (log.home() / "runs" / RUN / "brief.md").read_text()
            self.assertIn(asking, text)
            self.assertTrue(text.endswith(SPEC))
            self.assertEqual(fake.calls[-2].input, text)
            record, = log.read(path)
            self.assertEqual({key: value for key, value in record.items() if key != "ts"},
                             {"ev": "run.started", "run": RUN, "task": foreman.task_field(TASK.id),
                              "kind": "foreman", "host": HOST.name, "dir": str(ROOT / "wt" / RUN),
                              "branch": TASK.id, "base": "origin/main", "asked": QUESTION.run,
                              "codex": "codex-1", "state": "/state/codex-1",
                              "report": str(ROOT / "runs" / RUN / "report.md")})
            self.assertEqual(log.read(), [])

    def test_start_detaches_at_trunk_and_names_it_in_base_and_brief(self):
        with tmp_home() as home:
            spec = home / "spec.md"
            atomic.write(spec, SPEC)
            fake = _starter()
            foreman.start(QUESTION, replace(TASK, path=str(spec)), HOST, (), sh=fake,
                          trunk="component-kit/integration")
            self.assertEqual(fake.calls[3].argv, ssh(HOST.ssh,
                ["git", "-C", str(ROOT / "repos/agents"), "worktree", "add", "--detach",
                 str(ROOT / "wt" / RUN), "origin/component-kit/integration"]))
            self.assertEqual(log.read()[0]["base"], "origin/component-kit/integration")
            self.assertIn("repository at component-kit/integration, read-only.", fake.calls[-2].input)

    def test_missing_asking_report_uses_question_text(self):
        with tmp_home() as home:
            spec = home / "spec.md"
            atomic.write(spec, SPEC)
            fake = _starter()
            foreman.start(QUESTION, replace(TASK, path=str(spec)), HOST, (), sh=fake)
            self.assertIn("```text\n" + QUESTION.text + "\n```", fake.calls[-2].input)

    def test_unreadable_spec_never_contacts_builder(self):
        with tmp_home() as home:
            fake = _starter()
            with self.assertRaises(OSError):
                foreman.start(QUESTION, replace(TASK, path=str(home / "missing.md")), HOST, (), sh=fake)
            self.assertEqual(fake.calls, [])
            self.assertEqual(log.read(), [])


class AnswerTest(unittest.TestCase):
    def test_first_nonblank_line_and_following_lines_are_kept(self):
        self.assertEqual(foreman.answer("\n  \n Done: Choose A.  \n\n  Keep indentation.  \n"),
                         "Choose A.\n\n  Keep indentation.")

    def test_trailing_blank_lines_are_dropped(self):
        self.assertEqual(foreman.answer("Done: Choose A.\nEvidence. \n \n\n"), "Choose A.\nEvidence.")

    def test_following_lines_are_cut_at_answer_lines(self):
        lines = [f"line {i}" for i in range(foreman.ANSWER_LINES + 2)]
        self.assertEqual(foreman.answer("Done: A\n" + "\n".join(lines)),
                         "A\n" + "\n".join(lines[:foreman.ANSWER_LINES]))

    def test_failed_and_empty_done_are_refused(self):
        self.assertEqual(foreman.answer("Accept: the lint is theirs\nPushed."), "the lint is theirs\nPushed.")
        self.assertTrue(foreman.accepts("\n Accept: left\n"))
        self.assertFalse(foreman.accepts("Done: Accept: no"))
        for report in ("Failed: undecided", "Done: \nEvidence", "Accept:", "", "\n \n", "Question: Why?"):
            with self.subTest(report=report), self.assertRaises(ValueError):
                foreman.answer(report)


class WithAnswerTest(unittest.TestCase):
    def entry(self, spec):
        """Insert the same stable answer so exact markdown can be checked."""
        return foreman.with_answer(spec, day="2026-10-31", question=QUESTION, answer="Choose A.", run=RUN)

    def heading(self):
        """The answer's unique heading, including both runs."""
        return f"### 2026-10-31: Which option? ({QUESTION.run}, foreman {RUN})"

    def test_new_section_at_end(self):
        self.assertEqual(self.entry(SPEC + "\n"), SPEC.rstrip("\n") + "\n\n## Answers\n\n"
                         + self.heading() + "\n\nChoose A.\n")

    def test_entry_at_end_of_existing_last_section(self):
        spec = SPEC + "\n## Answers\n\n### An earlier answer\n\nEarlier.\n\n"
        self.assertEqual(self.entry(spec), spec.rstrip("\n") + "\n\n" + self.heading()
                         + "\n\nChoose A.\n")

    def test_entry_before_next_second_level_section(self):
        spec = SPEC + "\n## Answers\n\nEarlier.\n\n## Later\n\nKeep this.\n"
        self.assertEqual(self.entry(spec), spec.replace("## Later", self.heading()
                         + "\n\nChoose A.\n\n## Later"))

    def test_same_run_is_unchanged_even_without_trailing_newline(self):
        spec = self.entry(SPEC).rstrip("\n")
        self.assertEqual(self.entry(spec), spec)

    def test_question_prefix_is_removed_from_first_nonblank_line(self):
        question = replace(QUESTION, text="\n  Question:  Use A?  \nMore details.")
        text = foreman.with_answer(SPEC, day="today", question=question, answer="Yes.", run=RUN)
        self.assertIn(f"### today: Use A? ({QUESTION.run}, foreman {RUN})", text)
        self.assertNotIn("More details", text)

    def test_subsection_does_not_end_answers(self):
        spec = "## Answers\n\n### Earlier\n\nAnswer.\n\n## Later\n"
        self.assertLess(self.entry(spec).index(self.heading()), self.entry(spec).index("## Later"))


class CommitTest(unittest.TestCase):
    def prepare(self, home):
        """Put a tracked spec on a temporary origin's main."""
        origin, checkout = git_pair(home)
        spec = checkout / TASK.path
        atomic.write(spec, SPEC)
        git(checkout, "add", TASK.path)
        git(checkout, "commit", "-q", "-m", "Add spec")
        git(checkout, "push", "-q", "origin", "main")
        return origin, checkout, replace(TASK, path=str(spec))

    def runner(self, commands, *, fail_push=False):
        """Record real fixture git commands with isolated git configuration."""
        def invoke(argv, **keywords):
            commands.append((list(argv), keywords))
            if fail_push and argv[:2] == ["git", "push"]:
                raise Failed(argv, Result(1, err="push refused"))
            return shell(argv, env={**os.environ, **GIT_ENV}, **keywords)
        return invoke

    def assert_clean(self, checkout):
        """The transient answer worktree and local branch never survive."""
        self.assertFalse((log.home() / "runs" / RUN / "wt").exists())
        self.assertEqual(git(checkout, "branch", "--list", f"answers/{RUN}"), "")
        self.assertEqual(len(git(checkout, "worktree", "list").splitlines()), 1)

    def test_push_contains_answer_one_commit_above_main_then_retry_pushes_nothing(self):
        with tmp_home() as home:
            origin, checkout, task = self.prepare(home)
            commands = []
            branch = foreman.commit(QUESTION, task, "Choose A.", checkout, run_id=RUN,
                                     day="2026-10-31", sh=self.runner(commands))
            self.assertEqual(branch, f"answers/{RUN}")
            recorded = git(origin, "show", f"{branch}:{TASK.path}")
            self.assertIn(f"foreman {RUN})", recorded)
            self.assertIn("Choose A.", recorded)
            self.assertEqual(git(origin, "rev-list", "--count", f"main..{branch}"), "1")
            self.assertEqual(git(origin, "log", "-1", "--format=%s", branch),
                             f"Answer {TASK.id}'s question from its options")
            self.assertTrue(all(keywords["check"] for _, keywords in commands))
            self.assertEqual((checkout / TASK.path).read_text(), SPEC)
            self.assert_clean(checkout)
            git(origin, "update-ref", "refs/heads/main", git(origin, "rev-parse", branch))
            commands.clear()
            self.assertIsNone(foreman.commit(QUESTION, task, "Choose A.", checkout, run_id=RUN,
                                             day="2026-10-31", sh=self.runner(commands)))
            self.assertFalse(any(argv[1] in ("commit", "push") or "commit" in argv
                                 for argv, _ in commands))
            self.assert_clean(checkout)

    def test_commit_uses_trunk_for_spec_worktree(self):
        for trunk in ("main", "component-kit/integration"):
            with self.subTest(trunk=trunk), tmp_home() as home:
                checkout = home / "checkout"
                task = replace(TASK, path=str(checkout / TASK.path))
                worktree = log.home() / "runs" / RUN / "wt"
                atomic.write(worktree / TASK.path, SPEC)
                fake = FakeRunner()
                branch = foreman.commit(QUESTION, task, "Choose A.", checkout, run_id=RUN,
                                         day="today", sh=fake, trunk=trunk)
                self.assertEqual(branch, f"answers/{RUN}")
                self.assertEqual(fake.argvs()[1], ["git", "worktree", "add", "-B", branch,
                                                   str(worktree), f"origin/{trunk}"])
                self.assertEqual((worktree / TASK.path).read_text(),
                                 foreman.with_answer(SPEC, day="today", question=QUESTION,
                                                     answer="Choose A.", run=RUN))

    def test_fabrig_answer_reuses_pushed_branch_before_landing(self):
        """Real git verifies the push leaves a remote-tracking ref after local cleanup."""
        with tmp_home() as home:
            origin, checkout, task = self.prepare(home)
            task = replace(task, repo="fabrig")
            commands = []
            branch = foreman.commit(QUESTION, task, "Choose A.", checkout, run_id=RUN,
                                     day="2026-10-31", sh=self.runner(commands))
            tip = git(origin, "rev-parse", branch)
            commands.clear()
            self.assertEqual(foreman.commit(QUESTION, task, "Choose A.", checkout, run_id=RUN,
                                             day="2026-11-01", sh=self.runner(commands)), branch)
            self.assertEqual(git(origin, "rev-parse", branch), tip)
            self.assertEqual([argv[1] for argv, _ in commands], ["show"])
            self.assertEqual((checkout / TASK.path).read_text(), SPEC)
            self.assert_clean(checkout)

    def test_failed_push_cleans_worktree_and_branch(self):
        with tmp_home() as home:
            origin, checkout, task = self.prepare(home)
            with self.assertRaisesRegex(Failed, "push refused"):
                foreman.commit(QUESTION, task, "Choose A.", checkout, run_id=RUN,
                               day="today", sh=self.runner([], fail_push=True))
            self.assertEqual(git(origin, "branch", "--list", f"answers/{RUN}"), "")
            self.assert_clean(checkout)

    def test_outside_spec_refused_before_any_command(self):
        with tmp_home() as home:
            fake = FakeRunner()
            task = replace(TASK, path=str(home / "outside.md"))
            with self.assertRaises(ValueError):
                foreman.commit(QUESTION, task, "A", home / "checkout", run_id=RUN, day="today", sh=fake)
            self.assertEqual(fake.calls, [])

    def test_cleanup_failures_do_not_mask_fetch_failure(self):
        with tmp_home() as home:
            fake = FakeRunner().on(["git", "fetch"], Result(1, err="fetch refused"))
            fake.on(["git", "worktree", "remove"], Result(1, err="remove refused"))
            fake.on(["git", "branch"], Result(1, err="branch refused"))
            task = replace(TASK, path=str(home / "checkout/spec.md"))
            with self.assertRaisesRegex(Failed, "fetch refused"):
                foreman.commit(QUESTION, task, "A", home / "checkout", run_id=RUN, day="today", sh=fake)
            self.assertEqual([call.argv[1] for call in fake.calls], ["fetch", "worktree", "branch"])
