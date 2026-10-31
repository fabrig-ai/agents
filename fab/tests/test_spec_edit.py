import os
import unittest
from dataclasses import replace

from fab import atomic, spec_edit
from fab.plan import Task
from fab.sh import Failed, Result, run as shell
from fab.tests.support import FakeRunner, GIT_ENV, git, git_pair, tmp_home


TASK = Task("draft/task", "part", "feature", "agents", (), ("fab/x.py",), "high", 30,
            "# Task\n", "docs/plan/draft/tasks/task.md")
BRANCH = "edits/spec"
SPEC = "+++\nid = 'task'\n+++\n# Task\n"


def checkout_with_spec(home):
    """A local origin with a task spec on main, isolated from machine git settings."""
    origin, checkout = git_pair(home)
    spec = checkout / TASK.path
    atomic.write(spec, SPEC)
    git(checkout, "add", TASK.path)
    git(checkout, "commit", "-q", "-m", "Add spec")
    git(checkout, "push", "-q", "origin", "main")
    return origin, checkout, replace(TASK, path=str(spec))


def runner(commands, *, fail_push=False):
    """Record fixture commands and optionally refuse the push."""
    def invoke(argv, **keywords):
        commands.append((list(argv), keywords))
        if fail_push and argv[:2] == ["git", "push"]:
            raise Failed(argv, Result(1, err="push refused"))
        return shell(argv, env={**os.environ, **GIT_ENV}, **keywords)
    return invoke


class SpecEditTest(unittest.TestCase):
    def assert_clean(self, checkout, worktree):
        self.assertFalse(worktree.exists())
        self.assertEqual(git(checkout, "branch", "--list", BRANCH), "")
        self.assertEqual(len(git(checkout, "worktree", "list").splitlines()), 1)

    def test_edit_committed_pushed_and_cleaned(self):
        with tmp_home() as home:
            origin, checkout, task = checkout_with_spec(home)
            worktree = home / "fab/runs/edit/wt"
            commands = []
            seen = []
            def edit(spec):
                seen.append(spec)
                return spec + "\nAnswer.\n"
            self.assertEqual(spec_edit.commit(task, checkout, edit, branch=BRANCH,
                             message="Record the answer", worktree=worktree, sh=runner(commands)), BRANCH)
            self.assertEqual(seen, [SPEC])
            self.assertEqual(git(origin, "show", f"{BRANCH}:{TASK.path}") + "\n", SPEC + "\nAnswer.\n")
            self.assertEqual(git(origin, "rev-list", "--count", f"main..{BRANCH}"), "1")
            self.assertEqual(git(origin, "log", "-1", "--format=%s", BRANCH), "Record the answer")
            self.assertTrue(all(keywords["check"] for _, keywords in commands))
            self.assertEqual((checkout / TASK.path).read_text(), SPEC)
            self.assert_clean(checkout, worktree)

    def test_unchanged_spec_pushes_nothing_and_cleans(self):
        with tmp_home() as home:
            origin, checkout, task = checkout_with_spec(home)
            worktree = home / "fab/runs/edit/wt"
            commands = []
            self.assertIsNone(spec_edit.commit(task, checkout, lambda spec: spec, branch=BRANCH,
                              message="Already recorded", worktree=worktree, sh=runner(commands)))
            self.assertFalse(any("commit" in argv or "push" in argv for argv, _ in commands))
            self.assertEqual(git(origin, "branch", "--list", BRANCH), "")
            self.assert_clean(checkout, worktree)

    def test_failing_push_still_cleans(self):
        with tmp_home() as home:
            origin, checkout, task = checkout_with_spec(home)
            worktree = home / "fab/runs/edit/wt"
            with self.assertRaisesRegex(Failed, "push refused"):
                spec_edit.commit(task, checkout, lambda spec: spec + "\nAnswer.\n", branch=BRANCH,
                                 message="Record the answer", worktree=worktree,
                                 sh=runner([], fail_push=True))
            self.assertEqual(git(origin, "branch", "--list", BRANCH), "")
            self.assert_clean(checkout, worktree)

    def test_outside_spec_is_refused_before_commands(self):
        with tmp_home() as home:
            fake = FakeRunner()
            task = replace(TASK, path=str(home / "outside.md"))
            with self.assertRaises(ValueError):
                spec_edit.commit(task, home / "checkout", lambda spec: spec, branch=BRANCH,
                                 message="Edit", worktree=home / "fab/wt", sh=fake)
            self.assertEqual(fake.calls, [])

    def test_edit_failure_still_cleans(self):
        with tmp_home() as home:
            _, checkout, task = checkout_with_spec(home)
            worktree = home / "fab/runs/edit/wt"
            def edit(spec):
                raise ValueError("cannot edit")
            with self.assertRaisesRegex(ValueError, "cannot edit"):
                spec_edit.commit(task, checkout, edit, branch=BRANCH, message="Edit",
                                 worktree=worktree, sh=runner([]))
            self.assert_clean(checkout, worktree)
