"""Inputs publication through isolated real git repositories (docs/design/integration.md, 3)."""

import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from fab import atomic, cli, inputs, land, log
from fab import run as runs
from fab.sh import Failed, Result, run
from fab.tests.support import FakeRunner, GIT_ENV, git, git_pair, tmp_home


class InputsTest(unittest.TestCase):
    """Check the three push paths, refusals and worktree cleanup without live services."""

    def setUp(self):
        """Build one clone, an uncut plan and external inputs under a temporary HOME."""
        self.home = self.enterContext(tmp_home())
        self.enterContext(patch.dict(os.environ, GIT_ENV))
        self.origin, self.clone = git_pair(self.home)
        self.enterContext(patch.dict(runs.REMOTES, {"fabrig": str(self.origin)}, clear=True))
        self.plan = self.clone / "prefix/docs/plan/d"
        self.request = self.home / "request.md"
        atomic.write(self.request, "the user's request\n")
        self.reviews = self.home / "reviews"
        atomic.write(self.reviews / "nested/review.md", "review\n")
        self.path = "prefix/docs/plan/d/inputs/request.md"
        self.base = git(self.clone, "rev-parse", "HEAD")
        self.runner = FakeRunner().on(["git"], lambda call: run(call.argv, cwd=call.cwd))
        self.output, self.errors = io.StringIO(), io.StringIO()
        self.enterContext(redirect_stdout(self.output))
        self.enterContext(redirect_stderr(self.errors))

    def _trunk(self):
        git(self.clone, "checkout", "-q", "-b", "d/integration")
        git(self.clone, "push", "-q", "-u", "origin", "d/integration")

    def _agents(self):
        runs.REMOTES.clear()
        runs.REMOTES["agents"] = str(self.origin)
        (log.home() / "repos/agents").mkdir(parents=True)

    def _main(self, *args):
        with patch.object(inputs, "run", self.runner):
            return inputs.main(["inputs", str(self.plan), str(self.request), *args])

    def _pushes(self):
        return [argv for argv in self.runner.argvs() if argv[:2] == ["git", "push"]]

    def _snapshot(self):
        return (git(self.origin, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads"),
                git(self.clone, "rev-parse", "HEAD"), git(self.clone, "status", "--porcelain"),
                git(self.clone, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads"),
                git(self.clone, "worktree", "list", "--porcelain"))

    def _clean(self, moved=False):
        self.assertEqual(git(self.clone, "status", "--porcelain"), "")
        tip = git(self.clone, "rev-parse", "HEAD")
        if not moved:
            self.assertEqual(tip, self.base)
            self.assertFalse((self.plan / "inputs").exists())
        else:
            self.assertEqual(tip, git(self.clone, "rev-parse", "@{upstream}"))
            self.assertTrue((self.plan / "inputs/request.md").is_file())
        trees = git(self.clone, "worktree", "list", "--porcelain")
        self.assertEqual(trees.count("worktree "), 1)
        self.assertNotIn("fab-inputs-", trees)
        self.assertEqual(git(self.clone, "for-each-ref", "--format=%(refname:short)", "refs/heads"),
                         "d/integration\nmain" if moved and "d/integration" in trees else "main")

    def _refused(self, message, files=None, replace=False):
        before = self._snapshot()
        with self.assertRaisesRegex(ValueError, message):
            inputs.add(self.plan, [self.request] if files is None else files,
                       replace=replace, sh=self.runner)
        self.assertEqual(self._snapshot(), before)
        self.assertFalse(any("commit" in argv or argv[:3] == ["git", "worktree", "add"]
                             for argv in self.runner.argvs()))
        self.assertEqual(self._pushes(), [])

    def _seed_input(self, *, directory=False):
        destination = self.clone / self.path
        if directory:
            atomic.write(destination / "old.txt", "old directory\n")
        else:
            atomic.write(destination, "old input\n")
        git(self.clone, "add", ".")
        git(self.clone, "commit", "-q", "-m", "Seed inputs")
        git(self.clone, "push", "-q", "origin", "HEAD:main")
        self.base = git(self.clone, "rev-parse", "HEAD")

    def _seed_ignore(self):
        atomic.write(self.clone / ".gitignore", "inputs/\n")
        git(self.clone, "add", ".gitignore")
        git(self.clone, "commit", "-q", "-m", "Ignore local inputs")
        git(self.clone, "push", "-q", "origin", "HEAD:main")
        self.base = git(self.clone, "rev-parse", "HEAD")

    def test_trunk_file_and_directory_in_one_commit_and_printed_paths(self):
        """The trunk advances once, and its checkout follows without a local branch."""
        self._trunk()
        with patch.object(inputs, "run", self.runner):
            self.assertEqual(inputs.main(["inputs", str(self.plan), str(self.request), str(self.reviews)]), 0)
        self.assertEqual(self._pushes(), [["git", "push", "origin", "HEAD:refs/heads/d/integration"]])
        self.assertEqual(git(self.origin, "show", f"d/integration:{self.path}"), "the user's request")
        review = "prefix/docs/plan/d/inputs/reviews/nested/review.md"
        self.assertEqual(git(self.origin, "show", f"d/integration:{review}"), "review")
        self.assertEqual(git(self.origin, "log", "-1", "--format=%s", "d/integration"), "d: inputs")
        self.assertEqual(git(self.origin, "log", "-1", "--format=%an", "d/integration"), "fab")
        self.assertEqual(git(self.origin, "rev-list", "--count", f"{self.base}..d/integration"), "1")
        self.assertEqual(self.output.getvalue().splitlines(), [self.path, "prefix/docs/plan/d/inputs/reviews"])
        self._clean(moved=True)

    def test_agents_lands_through_main_and_follows_under_tick_lock(self):
        """Use the landing CLI and a stubbed landing action that advances the fixture origin."""
        self._agents()
        def landed(checkout, branch):
            self.assertEqual(checkout, log.home() / "repos/agents")
            self.assertEqual(branch, "inputs/d")
            tip = git(self.origin, "rev-parse", branch)
            git(self.origin, "update-ref", "refs/heads/main", tip)
            git(self.origin, "update-ref", "-d", "refs/heads/inputs/d")
            return land.Outcome(True, "landed", "Landed", tip, tip)
        def checked(call):
            if call.argv[:2] == ["git", "merge"]:
                with open(log.home() / "tick.lock", "a") as competing:
                    with self.assertRaises(BlockingIOError):
                        inputs.fcntl.flock(competing, inputs.fcntl.LOCK_EX | inputs.fcntl.LOCK_NB)
                self.assertEqual(self.runner.argvs()[-2], ["git", "fetch", "origin"])
            return run(call.argv, cwd=call.cwd)
        self.runner.rules.insert(0, (["git"], checked))
        with patch.object(land, "land", side_effect=landed) as action:
            self.assertEqual(self._main(), 0)
        action.assert_called_once()
        self.assertEqual(self._pushes(), [["git", "push", "origin", "HEAD:refs/heads/inputs/d"]])
        self.assertEqual(log.read()[-1]["ev"], "branch.landed")
        self._clean(moved=True)

    def test_agents_refusal_deletes_branch_and_prints_last_matching_step(self):
        """A land refusal leaves main alone and removes the offered branch."""
        self._agents()
        log.append("branch.rejected", branch="inputs/d", step="paths")
        log.append("branch.rejected", branch="inputs/other", step="push")
        with patch.object(land, "land", return_value=land.Outcome(False, "test", "red")):
            self.assertEqual(self._main(), 1)
        self.assertIn("fab land inputs/d refused at test", self.errors.getvalue())
        self.assertEqual(self._pushes(), [["git", "push", "origin", "HEAD:refs/heads/inputs/d"],
                                         ["git", "push", "origin", "--delete", "inputs/d"]])
        self.assertEqual(git(self.origin, "for-each-ref", "--format=%(refname:short)", "refs/heads"), "main")
        self._clean()

    def test_fabrig_ready_waits_and_replace_forces_only_its_ref(self):
        """Replacing a ready ref rebuilds from main and leaves the checkout untouched."""
        self.assertEqual(self._main(), 0)
        first = git(self.origin, "rev-parse", "ready/inputs/d")
        atomic.write(self.request, "replacement\n")
        self.assertEqual(self._main("--replace"), 0)
        self.assertNotEqual(git(self.origin, "rev-parse", "ready/inputs/d"), first)
        self.assertEqual(git(self.origin, "show", f"ready/inputs/d:{self.path}"), "replacement")
        self.assertEqual(self._pushes(), [["git", "push", "origin", "HEAD:refs/heads/ready/inputs/d"],
                                         ["git", "push", "--force", "origin", "HEAD:refs/heads/ready/inputs/d"]])
        self.assertIn("queue.landed", self.output.getvalue())
        self.assertIn("checkout to hold the files", self.output.getvalue())
        self.assertIn(self.path, self.output.getvalue())
        self._clean()

    def test_detached_fabrig_tells_operator_to_move_checkout(self):
        """Detached fabrig checkouts publish a ready ref and stay at their original tip."""
        git(self.clone, "checkout", "-q", "--detach")
        self.assertEqual(self._main(), 0)
        self.assertIn("operator must move", self.output.getvalue())
        self.assertIn("queue.landed", self.output.getvalue())
        self._clean()

    def test_replace_removes_old_directory_before_copying_file(self):
        """An existing directory at an input name may become a file on the trunk."""
        self._seed_input(directory=True)
        self._trunk()
        self.assertEqual(inputs.add(self.plan, [self.request], replace=True, sh=self.runner), [self.path])
        self.assertEqual((self.plan / "inputs/request.md").read_text(), self.request.read_text())
        self.assertNotIn("--force", self._pushes()[0])
        self._clean(moved=True)

    def test_replace_directory_drops_files_absent_from_new_source(self):
        """Replacing a directory removes its old children rather than merging trees."""
        atomic.write(self.clone / "prefix/docs/plan/d/inputs/reviews/old.md", "old\n")
        git(self.clone, "add", ".")
        git(self.clone, "commit", "-q", "-m", "Seed reviews")
        git(self.clone, "push", "-q", "origin", "HEAD:main")
        inputs.add(self.plan, [self.reviews], replace=True, sh=self.runner)
        tree = git(self.origin, "ls-tree", "-r", "--name-only", "ready/inputs/d")
        self.assertIn("reviews/nested/review.md", tree)
        self.assertNotIn("old.md", tree)
        self.base = git(self.clone, "rev-parse", "HEAD")
        self.assertEqual(git(self.clone, "status", "--porcelain"), "")
        self.assertEqual(git(self.clone, "worktree", "list", "--porcelain").count("worktree "), 1)

    def test_binary_file_keeps_its_bytes(self):
        """Opaque inputs are copied without a text decode or newline conversion."""
        source = self.home / "picture.bin"
        sibling = source.with_name(".picture.bin.new")
        sibling.write_bytes(bytes([0, 255, 13, 10]))
        sibling.replace(source)
        inputs.add(self.plan, [source], sh=self.runner)
        self.assertEqual(git(self.origin, "rev-parse", "ready/inputs/d:prefix/docs/plan/d/inputs/picture.bin"),
                         git(self.clone, "hash-object", str(source)))
        self._clean()

    def test_refuses_plan_toml(self):
        """An already cut plan owns its inputs."""
        atomic.write(self.plan / "plan.toml", "draft = 'd'\n")
        self._refused("plan.toml already exists")

    def test_refuses_listed_plan_before_directory_exists(self):
        """Listing alone marks a plan as already owned by its cut."""
        atomic.write(log.home() / "plans", str(self.plan) + "\n")
        self._refused("plan directory is already listed")

    def test_refuses_missing_input(self):
        """No worktree or branch is created for a nonexistent source."""
        self._refused("input does not exist", [self.home / "missing"])

    def test_refuses_duplicate_names(self):
        """Sources from different directories cannot overwrite each other by basename."""
        duplicate = self.home / "other/request.md"
        atomic.write(duplicate, "duplicate\n")
        self._refused("inputs share a name: request.md", [self.request, duplicate])

    def test_refuses_existing_input_on_fetched_trunk(self):
        """Fetch detects inputs even when the checkout has not followed origin yet."""
        self._seed_input()
        git(self.clone, "reset", "-q", "--hard", "HEAD^")
        self._refused("input already exists at origin/main")

    def test_refuses_untracked_input_with_or_without_replace(self):
        """Replace cannot overwrite a checkout's untracked input."""
        atomic.write(self.clone / self.path, "untracked\n")
        self._refused("input is untracked or changed")
        self._refused("input is untracked or changed", replace=True)

    def test_refuses_ignored_input_with_or_without_replace(self):
        """An ignored local file is preserved even when replacement is requested."""
        self._seed_ignore()
        destination = self.clone / self.path
        atomic.write(destination, "ignored input\n")
        for replace in (False, True):
            with self.subTest(replace=replace):
                self.assertEqual(git(self.clone, "status", "--porcelain"), "")
                self._refused("input is untracked or changed", replace=replace)
                self.assertEqual(destination.read_bytes(), b"ignored input\n")

    def test_refuses_ignored_directory_input_with_or_without_replace(self):
        """Ignored children of a directory input survive either replacement setting."""
        self._seed_ignore()
        destination = self.plan / "inputs/reviews/nested/local.md"
        atomic.write(destination, "ignored review\n")
        for replace in (False, True):
            with self.subTest(replace=replace):
                self.assertEqual(git(self.clone, "status", "--porcelain"), "")
                self._refused("input is untracked or changed", files=[self.reviews], replace=replace)
                self.assertEqual(destination.read_bytes(), b"ignored review\n")

    def test_refuses_modified_and_staged_input(self):
        """Tracked modifications and staged changes both block following the trunk."""
        self._seed_input()
        atomic.write(self.clone / self.path, "changed\n")
        self._refused("input is untracked or changed", replace=True)
        git(self.clone, "add", self.path)
        self._refused("input is untracked or changed", replace=True)

    def test_refuses_existing_ready_ref_without_replace(self):
        """A pending or rejected ready ref needs an explicit replacement."""
        git(self.clone, "push", "-q", "origin", "HEAD:refs/heads/ready/inputs/d")
        self._refused("branch already exists on origin: ready/inputs/d")

    def test_refuses_existing_agents_branch_even_with_replace(self):
        """Replace never forces an agents landing branch."""
        self._agents()
        git(self.clone, "push", "-q", "origin", "HEAD:refs/heads/inputs/d")
        self._refused("branch already exists on origin: inputs/d", replace=True)

    def test_refuses_draft_inputs(self):
        """The ready-ref namespace reserves the draft name inputs."""
        self.plan = self.plan.with_name("inputs")
        self._refused("draft must not be named inputs")

    def test_refuses_other_upstreams(self):
        """Only the plan's own integration branch or main may be followed."""
        for repo, upstream in (("fabrig", "other"), ("fabrig", "another/integration"),
                               ("agents", "d/integration")):
            with self.subTest(repo=repo, upstream=upstream):
                runs.REMOTES.clear()
                runs.REMOTES[repo] = str(self.origin)
                git(self.clone, "push", "-q", "origin", f"HEAD:refs/heads/{upstream}")
                git(self.clone, "fetch", "-q", "origin")
                git(self.clone, "branch", "--set-upstream-to", f"origin/{upstream}")
                self._refused(f"{repo} checkout must track origin/main")

    def test_refuses_agents_detached_or_without_upstream(self):
        """Agents requires a checkout tracking main, including when no upstream is set."""
        self._agents()
        git(self.clone, "branch", "--unset-upstream")
        self._refused("agents checkout must track origin/main")
        git(self.clone, "checkout", "-q", "--detach")
        self._refused("agents checkout must track origin/main")

    def test_landing_refusal_uses_selected_log_and_last_matching_branch(self):
        """The supplied log selects the refusal step, excluding later unrelated branches."""
        self._agents()
        path = self.home / "fixture.jsonl"
        log.append("branch.rejected", path=path, branch="inputs/d", step="paths")
        log.append("branch.rejected", path=path, branch="inputs/d", step="gate:size")
        log.append("branch.rejected", path=path, branch="inputs/other", step="test")
        with patch.object(land, "main", return_value=1) as landing:
            with self.assertRaisesRegex(ValueError, "refused at gate:size"):
                inputs.add(self.plan, [self.request], sh=self.runner, log_path=path)
        landing.assert_called_once_with(["inputs/d"])
        self.assertEqual(git(self.origin, "for-each-ref", "--format=%(refname:short)", "refs/heads"), "main")
        self._clean()

    def test_worktree_creation_failure_keeps_its_error_and_checkout(self):
        """A failed worktree add needs no removal and retains its original failure message."""
        self.runner.rules.insert(0, (["git", "worktree", "add"], Result(1, err="worktree add failed")))
        before = self._snapshot()
        self.assertEqual(self._main(), 1)
        self.assertIn("worktree add failed", self.errors.getvalue())
        self.assertEqual(self._snapshot(), before)
        self.assertEqual(self._pushes(), [])
        self._clean()

    def test_push_failure_removes_worktree_and_leaves_checkout(self):
        """A failed push cannot leak the prepared commit into the operator's checkout."""
        self.runner.rules.insert(0, (["git", "push"], Result(1, err="refused push")))
        before = self._snapshot()
        with self.assertRaises(Failed):
            inputs.add(self.plan, [self.request], sh=self.runner)
        self.assertEqual(self._snapshot(), before)
        self._clean()

    def test_copy_and_commit_failures_remove_worktree(self):
        """The worktree is removed after copy or commit errors, before any push."""
        before = self._snapshot()
        with patch.object(inputs, "_copy", side_effect=OSError("copy failed")):
            self.assertEqual(self._main(), 1)
        self.assertIn("copy failed", self.errors.getvalue())
        self.assertEqual(self._snapshot(), before)
        self.runner.rules.insert(0, (["git", "-c"], Result(1, err="commit failed")))
        self.assertEqual(self._main(), 1)
        self.assertIn("commit failed", self.errors.getvalue())
        self.assertEqual(self._snapshot(), before)
        self.assertEqual(self._pushes(), [])
        self._clean()

    def test_usage_and_cli_registration(self):
        """The plan subcommand follows status and requires inputs, a plan and sources."""
        commands = list(cli.COMMANDS)
        self.assertEqual(commands[commands.index("status") + 1], "plan")
        self.assertEqual(cli.COMMANDS["plan"][0], "fab.inputs")
        for argv in ([], ["inputs"], ["other"], ["inputs", str(self.plan)]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit) as error:
                inputs.main(argv)
            self.assertEqual(error.exception.code, 2)
