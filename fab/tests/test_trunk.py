"""Create trunks against isolated git origins (docs/design/integration.md, 3)."""

import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from fab import atomic, cli, log, trunk
from fab.sh import Failed, Result
from fab.tests.support import FakeRunner, GIT_ENV, git, git_pair, tmp_home


class TrunkGitTest(unittest.TestCase):
    """Check publication, refusal and rollback with git's real refs and worktrees."""

    def setUp(self):
        """Put a disposable clone at the command's FAB_HOME location."""
        self.home = self.enterContext(tmp_home())
        self.enterContext(patch.dict(os.environ, GIT_ENV))
        self.origin, clone = git_pair(self.home)
        self.clone = log.home() / "repos" / "fabrig"
        self.clone.parent.mkdir(parents=True)
        clone.rename(self.clone)
        self.plan_path = "temper/docs/plan/demo"
        self.branch = "demo/integration"
        self.worktree = log.home() / "integration" / "demo"
        self.plan_dir = self.worktree / self.plan_path
        self.log_path = self.home / "events.jsonl"

    def _assert_published(self, base, tip, *, log_path=None):
        """Check the branch, upstream, remote tip and single success record."""
        self.assertTrue(self.worktree.is_dir())
        self.assertEqual(git(self.worktree, "rev-parse", "HEAD"), tip)
        self.assertEqual(git(self.worktree, "branch", "--show-current"), self.branch)
        self.assertEqual(git(self.worktree, "rev-parse", "@{upstream}"), tip)
        self.assertEqual(git(self.worktree, "rev-parse", "--abbrev-ref", "@{upstream}"),
                         f"origin/{self.branch}")
        self.assertEqual(git(self.origin, "rev-parse", f"refs/heads/{self.branch}"), tip)
        entries = log.read(log_path)
        self.assertEqual(len(entries), 1)
        self.assertEqual({key: entries[0][key] for key in ("ev", "draft", "base", "tip")},
                         dict(ev="trunk.made", draft="demo", base=base, tip=tip))

    def _assert_refusal(self, plan_path, message, *, base="origin/main"):
        """Refuse without changing existing branches, worktree listings or the log."""
        heads = git(self.clone, "for-each-ref", "refs/heads/")
        remote = git(self.origin, "for-each-ref", "refs/heads/")
        worktrees = git(self.clone, "worktree", "list", "--porcelain")
        with self.assertRaises(ValueError) as refused:
            trunk.make(plan_path, base=base, log_path=self.log_path)
        self.assertEqual(str(refused.exception), message)
        self.assertEqual(git(self.clone, "for-each-ref", "refs/heads/"), heads)
        self.assertEqual(git(self.origin, "for-each-ref", "refs/heads/"), remote)
        self.assertEqual(git(self.clone, "worktree", "list", "--porcelain"), worktrees)
        self.assertEqual(log.read(self.log_path), [])
        self.assertFalse(self.log_path.exists())

    def test_make_prints_plan_directory_and_publishes_tracking_trunk(self):
        """The public CLI prints the directory that inputs and cut will consume."""
        tip = git(self.clone, "rev-parse", "origin/main")
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli.main(["trunk", "make", self.plan_path]), 0)
        self.assertEqual(output.getvalue(), f"{self.plan_dir}\n")
        self._assert_published("origin/main", tip)
        self.assertFalse((self.plan_dir / "plan.toml").exists())

    def test_base_option_uses_another_commit(self):
        """The requested revision supplies the worktree tip and the logged base."""
        git(self.clone, "commit", "-q", "--allow-empty", "-m", "Another base")
        tip = git(self.clone, "rev-parse", "HEAD")
        self.assertNotEqual(tip, git(self.clone, "rev-parse", "origin/main"))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(trunk.main(["make", self.plan_path, "--base", tip]), 0)
        self._assert_published(tip, tip)

    def test_unprefixed_docs_plan_path_and_explicit_log(self):
        """A prefix before docs is optional and callers may choose their log path."""
        self.plan_path = "docs/plan/demo"
        self.assertEqual(trunk.make(Path(self.plan_path), log_path=self.log_path),
                         self.worktree / self.plan_path)
        self._assert_published("origin/main", git(self.clone, "rev-parse", "origin/main"),
                               log_path=self.log_path)
        self.assertFalse(log.default_path().exists())

    def test_refuses_invalid_and_absolute_plan_paths(self):
        """Reject paths outside the cut's relative docs/plan/draft shape."""
        for plan_path in ("elsewhere/demo", "docs/plan", "docs/plan/demo/child",
                          str(self.home / "docs/plan/demo"), "../docs/plan/demo",
                          "docs/plan/.."):
            with self.subTest(plan_path=plan_path):
                self._assert_refusal(plan_path,
                                     "PLAN_PATH must be a relative <prefix>docs/plan/<draft>: "
                                     + plan_path)
                self.assertFalse(self.worktree.exists())

    def test_refuses_plan_toml_at_requested_revision(self):
        """An already cut plan at the given base is refused before branch creation."""
        atomic.write(self.clone / self.plan_path / "plan.toml", 'draft = "demo"\n')
        git(self.clone, "add", self.plan_path)
        git(self.clone, "commit", "-q", "-m", "Cut the plan")
        self._assert_refusal(self.plan_path,
                             f"plan.toml already exists at HEAD:{self.plan_path}/plan.toml",
                             base="HEAD")
        git(self.clone, "push", "-q", "origin", "main")
        self._assert_refusal(self.plan_path,
                             f"plan.toml already exists at origin/main:{self.plan_path}/plan.toml")
        self.assertFalse(self.worktree.exists())

    def test_refuses_origin_branch_after_fetch(self):
        """Discover an origin branch that was absent from the clone's tracking refs."""
        git(self.origin, "update-ref", f"refs/heads/{self.branch}",
            git(self.clone, "rev-parse", "HEAD"))
        self._assert_refusal(self.plan_path,
                             f"branch already exists: refs/remotes/origin/{self.branch}")
        self.assertFalse(self.worktree.exists())

    def test_refuses_local_only_branch(self):
        """Preserve a local integration branch even when origin lacks it."""
        git(self.clone, "branch", self.branch)
        self._assert_refusal(self.plan_path,
                             f"branch already exists: refs/heads/{self.branch}")
        self.assertFalse(self.worktree.exists())

    def test_refuses_existing_worktree_path(self):
        """Preserve directories, files and dangling symlinks at the destination."""
        self.worktree.parent.mkdir(parents=True)
        for kind in ("directory", "file", "symlink"):
            with self.subTest(kind=kind):
                if kind == "directory":
                    self.worktree.mkdir()
                elif kind == "file":
                    atomic.write(self.worktree, "keep\n")
                else:
                    self.worktree.symlink_to(self.home / "absent")
                self._assert_refusal(self.plan_path,
                                     f"worktree path already exists: {self.worktree}")
                if kind == "directory":
                    self.assertEqual(list(self.worktree.iterdir()), [])
                    self.worktree.rmdir()
                elif kind == "file":
                    self.assertEqual(self.worktree.read_text(), "keep\n")
                    self.worktree.unlink()
                else:
                    self.assertTrue(self.worktree.is_symlink())
                    self.worktree.unlink()

    def test_fetch_prunes_stale_origin_branch(self):
        """A tracking ref whose remote branch is gone does not block creation."""
        git(self.clone, "update-ref", f"refs/remotes/origin/{self.branch}",
            git(self.clone, "rev-parse", "HEAD"))
        self.assertEqual(trunk.make(self.plan_path), self.plan_dir)
        self._assert_published("origin/main", git(self.clone, "rev-parse", "origin/main"))

    def test_refused_push_exits_one_and_removes_local_creation(self):
        """A rejecting origin hook leaves neither branch nor registered worktree."""
        hook = self.origin / "hooks" / "pre-receive"
        atomic.write(hook, "#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(trunk.main(["make", self.plan_path]), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("fab trunk: git push", errors.getvalue())
        self.assertIn("pre-receive hook declined", errors.getvalue())
        self.assertFalse(self.worktree.exists())
        self.assertEqual(git(self.clone, "for-each-ref", f"refs/heads/{self.branch}"), "")
        self.assertEqual(git(self.origin, "for-each-ref", f"refs/heads/{self.branch}"), "")
        self.assertEqual(git(self.clone, "worktree", "list", "--porcelain").count("worktree "), 1)
        self.assertEqual(log.read(), [])

    def test_cli_refusal_exits_one(self):
        """ValueError refusals carry the command's prefix on stderr."""
        errors = io.StringIO()
        with redirect_stderr(errors):
            self.assertEqual(trunk.main(["make", "elsewhere/demo"]), 1)
        self.assertEqual(errors.getvalue(), "fab trunk: PLAN_PATH must be a relative "
                         "<prefix>docs/plan/<draft>: elsewhere/demo\n")


class TrunkRunnerTest(unittest.TestCase):
    """Check the command seam, ordering and failures without invoking services."""

    def setUp(self):
        """Give each command test a temporary HOME and a runner with absent refs."""
        self.home = self.enterContext(tmp_home())
        self.clone = str(log.home() / "repos" / "fabrig")
        self.worktree = str(log.home() / "integration" / "demo")
        self.fake = FakeRunner().on(["git", "cat-file"], Result(1))
        self.fake.on(["git", "show-ref"], Result(1))
        self.fake.on(["git", "rev-parse"], Result(0, "abc123\n"))

    def test_make_argv_and_cwd_in_order(self):
        """Fetch and every refusal probe precede creation, push and tip lookup."""
        self.assertEqual(trunk.make("docs/plan/demo", sh=self.fake),
                         Path(self.worktree) / "docs/plan/demo")
        self.assertEqual(self.fake.argvs(), [
            ["git", "fetch", "--prune", "origin"],
            ["git", "cat-file", "-e", "origin/main:docs/plan/demo/plan.toml"],
            ["git", "show-ref", "--verify", "--quiet", "refs/remotes/origin/demo/integration"],
            ["git", "show-ref", "--verify", "--quiet", "refs/heads/demo/integration"],
            ["git", "worktree", "add", "-b", "demo/integration", self.worktree, "origin/main"],
            ["git", "push", "-u", "--force-with-lease=refs/heads/demo/integration:",
             "origin", "demo/integration"],
            ["git", "rev-parse", "HEAD"],
        ])
        self.assertEqual([call.cwd for call in self.fake.calls],
                         [self.clone] * 5 + [self.worktree] * 2)
        self.assertEqual(log.read()[0]["tip"], "abc123")

    def test_push_failures_remove_worktree_then_branch_without_logging(self):
        """Both push exit failures and an unlaunchable git roll back local creation."""
        for failure in (Result(1, err="refused"), Result(128, err="unreachable"),
                        OSError("cannot launch git")):
            with self.subTest(failure=failure):
                fake = FakeRunner(rules=list(self.fake.rules))

                def push(call):
                    self.assertEqual(log.read(), [])
                    if isinstance(failure, OSError):
                        raise failure
                    return failure

                fake.on(["git", "push"], push)
                with self.assertRaises((Failed, OSError)):
                    trunk.make("docs/plan/demo", sh=fake)
                self.assertEqual(fake.argvs()[-2:], [
                    ["git", "worktree", "remove", "--force", self.worktree],
                    ["git", "branch", "-D", "demo/integration"],
                ])
                self.assertEqual([call.cwd for call in fake.calls[-2:]], [self.clone] * 2)
                self.assertEqual(log.read(), [])

    def test_fetch_failure_stops_before_creation(self):
        """A failed fetch cannot create a branch or log success."""
        self.fake.on(["git", "fetch"], Result(128, err="unreachable"))
        with self.assertRaises(Failed):
            trunk.make("docs/plan/demo", sh=self.fake)
        self.assertEqual(self.fake.argvs(), [["git", "fetch", "--prune", "origin"]])
        self.assertEqual(log.read(), [])

    def test_make_requires_plan_path(self):
        """Argparse reports a missing PLAN_PATH as usage error 2."""
        errors = io.StringIO()
        with redirect_stderr(errors), self.assertRaises(SystemExit) as exited:
            cli.main(["trunk", "make"])
        self.assertEqual(exited.exception.code, 2)
        self.assertIn("PLAN_PATH", errors.getvalue())
