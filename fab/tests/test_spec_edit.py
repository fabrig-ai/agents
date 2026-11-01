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

    def test_commit_reads_spec_from_trunk_worktree(self):
        for trunk in ("main", "component-kit/integration"):
            with self.subTest(trunk=trunk), tmp_home() as home:
                checkout = home / "checkout"
                worktree = home / "fab/runs/edit/wt"
                task = replace(TASK, path=str(checkout / TASK.path))
                atomic.write(checkout / TASK.path, "checkout spec\n")
                source = SPEC + f"\nSpec on {trunk}.\n"

                def add(call):
                    self.assertEqual(call.argv, ["git", "worktree", "add", "-B", BRANCH,
                                                 str(worktree), f"origin/{trunk}"])
                    atomic.write(worktree / TASK.path, source)
                    return Result(0)

                fake = FakeRunner().on(["git", "worktree", "add"], add)
                seen = []

                def edit(spec):
                    seen.append(spec)
                    return spec + "\nAnswer.\n"

                self.assertEqual(spec_edit.commit(task, checkout, edit, branch=BRANCH,
                                 message="Record the answer", worktree=worktree, sh=fake,
                                 trunk=trunk), BRANCH)
                self.assertEqual(seen, [source])
                self.assertEqual((worktree / TASK.path).read_text(), source + "\nAnswer.\n")
                self.assertEqual(fake.argvs()[-3:],
                                 [["git", "push", "-q", "--force", "origin", f"HEAD:refs/heads/{BRANCH}"],
                                  ["git", "worktree", "remove", "--force", str(worktree)],
                                  ["git", "branch", "-D", BRANCH]])
                self.assertEqual((checkout / TASK.path).read_text(), "checkout spec\n")

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

    def test_commit_path_adds_missing_file_and_pushes_it(self):
        with tmp_home() as home:
            origin, checkout = git_pair(home)
            worktree = home / "fab/backlog/draft-1"
            path = "docs/design/debt/backlog.md"
            commands, seen = [], []

            def edit(previous):
                seen.append(previous)
                return "# The backlog\n"

            self.assertEqual(spec_edit.commit_path(path, checkout, edit, branch=BRANCH,
                             message="Record the backlog", worktree=worktree,
                             sh=runner(commands)), BRANCH)
            self.assertEqual(seen, [""])
            self.assertEqual(git(origin, "show", f"{BRANCH}:{path}"), "# The backlog")
            self.assertEqual([argv for argv, keywords in commands], [
                ["git", "fetch", "origin"],
                ["git", "worktree", "add", "-B", BRANCH, str(worktree), "origin/main"],
                ["git", "add", "--", path],
                ["git", "-c", "user.name=fab", "-c", "user.email=fab@localhost", "commit", "-q",
                 "-m", "Record the backlog", "--", path],
                ["git", "push", "-q", "--force", "origin", f"HEAD:refs/heads/{BRANCH}"],
                ["git", "worktree", "remove", "--force", str(worktree)],
                ["git", "branch", "-D", BRANCH]])
            self.assertTrue(all(keywords["check"] for argv, keywords in commands))
            self.assertTrue(all(keywords["cwd"] == str(worktree) for argv, keywords in commands[2:5]))
            self.assertFalse((checkout / path).exists())
            self.assert_clean(checkout, worktree)

    def test_commit_existing_spec_keeps_exact_command_sequence(self):
        with tmp_home() as home:
            checkout, worktree = home / "checkout", home / "fab/wt"
            task = replace(TASK, path=str(checkout / TASK.path))

            def add(call):
                atomic.write(worktree / TASK.path, SPEC)
                return Result(0)

            fake = FakeRunner().on(["git", "worktree", "add"], add)
            spec_edit.commit(task, checkout, lambda spec: spec + "Answer.\n", branch=BRANCH,
                             message="Record the answer", worktree=worktree, sh=fake)
            self.assertEqual(fake.argvs(), [
                ["git", "fetch", "origin"],
                ["git", "worktree", "add", "-B", BRANCH, str(worktree), "origin/main"],
                ["git", "-c", "user.name=fab", "-c", "user.email=fab@localhost", "commit", "-q",
                 "-m", "Record the answer", "--", TASK.path],
                ["git", "push", "-q", "--force", "origin", f"HEAD:refs/heads/{BRANCH}"],
                ["git", "worktree", "remove", "--force", str(worktree)],
                ["git", "branch", "-D", BRANCH]])

    def test_commit_path_unchanged_missing_file_commits_nothing(self):
        with tmp_home() as home:
            fake = FakeRunner()
            seen = []
            def edit(previous):
                seen.append(previous)
                return previous
            self.assertIsNone(spec_edit.commit_path("docs/backlog.md", home / "checkout", edit,
                              branch=BRANCH, message="No change", worktree=home / "fab/wt", sh=fake))
            self.assertEqual(seen, [""])
            self.assertFalse(any("add" in argv and argv[:2] != ["git", "worktree"]
                                 or "commit" in argv or "push" in argv for argv in fake.argvs()))
            self.assertEqual(fake.argvs()[-2:], [
                ["git", "worktree", "remove", "--force", str(home / "fab/wt")],
                ["git", "branch", "-D", BRANCH]])

    def test_commit_path_refuses_absolute_and_escaping_paths_before_commands(self):
        with tmp_home() as home:
            for path in (str(home / "outside.md"), "../outside.md"):
                with self.subTest(path=path):
                    fake = FakeRunner()
                    with self.assertRaises(ValueError):
                        spec_edit.commit_path(path, home / "checkout", lambda spec: spec,
                                              branch=BRANCH, message="Edit",
                                              worktree=home / "fab/wt", sh=fake)
                    self.assertEqual(fake.calls, [])
