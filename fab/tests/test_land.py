import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from fab import land as landing, log, wake
from fab.sh import run
from fab.tests.support import GIT_ENV, git, git_pair, tmp_home
from fab.tests.wakes import WakeTestCase


class LandPureTest(unittest.TestCase):
    def test_outside_obeys_directory_and_exact_boundaries(self):
        allowed = ["fab/a.py", "fab/tests/a.py", "bin/fab", "docs/design/fab.md",
                   "docs/design/fab.status.md", "docs/plan/a/tasks/b.md",
                   "docs/design/fab-tick.md", "docs/design/fab-after-landing.status.md"]
        forbidden = ["fab", "fabric/a.py", "bin/fab-extra", "docs/design/fab.md.bak",
                     "docs/plan", "README.md", "docs/design/fab-tick.md.bak",
                     "docs/design/fab-x/y.md", "docs/design/fabx.md", "docs/design/fab-.md"]
        self.assertEqual(landing.outside(iter(allowed + forbidden)), sorted(forbidden))
        self.assertEqual(landing.outside([]), [])

    def test_task_of_branch_and_rebase_branch(self):
        for branch, task in [("draft/task", "draft/task"), ("draft/task-r12", "draft/task"),
                             ("draft/a-b-r0", "draft/a-b"), ("draft/task-rx", "draft/task-rx")]:
            with self.subTest(branch=branch):
                self.assertEqual(landing.task_of(branch), task)
        for branch in ["main", "", "/task", "draft/", "a/b/c", "draft/a b", "draft/task\n"]:
            with self.subTest(branch=branch):
                self.assertIsNone(landing.task_of(branch))


class LandGitTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.enterContext(patch.dict(os.environ, GIT_ENV))
        self.origin, self.clone = git_pair(self.home)
        self.base = git(self.origin, "rev-parse", "main")
        self.branch = "draft/task"

    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        sibling = path.with_name(path.name + ".tmp")
        sibling.write_text(text)
        sibling.replace(path)

    def commit(self, path="fab/change.py", text="branch\n", *, checkout=None):
        checkout = checkout or self.clone
        self.write(checkout / path, text)
        git(checkout, "add", "--", path)
        git(checkout, "commit", "-qm", "Change " + path)
        return git(checkout, "rev-parse", "HEAD")

    def branch_commit(self, path="fab/change.py", text="branch\n"):
        git(self.clone, "checkout", "-qb", self.branch)
        tip = self.commit(path, text)
        git(self.clone, "push", "-q", "origin", "HEAD:refs/heads/" + self.branch)
        return tip

    def main_commit(self, path="fab/main.py", text="main\n"):
        git(self.clone, "checkout", "-q", "main")
        tip = self.commit(path, text)
        git(self.clone, "push", "-q", "origin", "HEAD:main")
        return tip

    def assert_clean_detached(self):
        self.assertEqual(git(self.clone, "status", "--porcelain", "--branch"), "## HEAD (no branch)")
        self.assertFalse((self.clone / ".git" / "rebase-merge").exists())
        self.assertFalse((self.clone / ".git" / "rebase-apply").exists())

    def assert_landed(self, outcome):
        self.assertTrue(outcome.landed, outcome)
        self.assertEqual(outcome.step, "landed")
        self.assertEqual(outcome.tip, git(self.origin, "rev-parse", "main"))
        self.assertEqual(outcome.main, outcome.tip)
        self.assertEqual(git(self.origin, "branch", "--list", self.branch), "")
        self.assert_clean_detached()

    def assert_refused(self, outcome, step, main=None):
        self.assertFalse(outcome.landed, outcome)
        self.assertEqual(outcome.step, step)
        self.assertEqual(git(self.origin, "rev-parse", "main"), main or self.base)
        self.assertNotEqual(git(self.origin, "branch", "--list", self.branch), "")
        self.assert_clean_detached()

    def test_branch_rebased_and_landed(self):
        original = self.branch_commit()
        main = self.main_commit()
        real_land, outcomes = landing.land, []

        def land(checkout, branch):
            outcome = real_land(checkout, branch, test=["true"])
            outcomes.append(outcome)
            return outcome

        with patch("fab.land.REMOTE", str(self.origin)), patch("fab.land.land", side_effect=land), \
                redirect_stdout(io.StringIO()) as output:
            self.assertEqual(landing.main([self.branch]), 0)
        self.clone = self.home / "fab/repos/agents"
        outcome, = outcomes
        self.assert_landed(outcome)
        self.assertNotEqual(outcome.tip, original)
        self.assertEqual(git(self.origin, "merge-base", main, outcome.tip), main)
        self.assertEqual(git(self.clone, "show", "HEAD:fab/change.py"), "branch")
        self.assertEqual(git(self.clone, "show", "HEAD:fab/main.py"), "main")
        record, = log.read()
        self.assertEqual({key: value for key, value in record.items() if key != "ts"}, {
            "ev": "branch.landed", "task": "draft/task", "branch": self.branch,
            "tip": outcome.tip, "main": outcome.tip,
        })
        self.assertIn("landed", output.getvalue())
        self.assertTrue((self.home / "fab/land-agents.lock").exists())

    def test_conflict_aborts_and_preserves_main(self):
        self.branch_commit("fab/same.py", "branch\n")
        main = self.main_commit("fab/same.py", "main\n")
        outcome = landing.land(self.clone, self.branch, test=["true"])
        self.assert_refused(outcome, "rebase", main)
        self.assertIn("CONFLICT", outcome.detail)

    def test_path_outside_allowed_is_named(self):
        tip = self.branch_commit("README.md", "changed\n")
        real_land = landing.land
        with patch("fab.land.land", side_effect=lambda checkout, branch: real_land(checkout, branch, test=["true"])), \
                redirect_stdout(io.StringIO()) as output:
            self.assertEqual(landing.main([self.branch, "--task", "plan/other", "--checkout", str(self.clone)]), 1)
        record, = log.read()
        self.assertEqual(record["ev"], "branch.rejected")
        self.assertEqual(record["task"], "plan/other")
        self.assertEqual(record["branch"], self.branch)
        self.assertEqual(record["tip"], tip)
        self.assertEqual(record["step"], "paths")
        self.assertIn("README.md", record["log"])
        self.assertIn("paths", output.getvalue())
        self.assertEqual(git(self.origin, "rev-parse", "main"), self.base)
        self.assertNotEqual(git(self.origin, "branch", "--list", self.branch), "")
        self.assert_clean_detached()

    def test_rename_from_outside_allowed_is_refused(self):
        git(self.clone, "checkout", "-qb", self.branch)
        (self.clone / "fab").mkdir()
        git(self.clone, "mv", "README.md", "fab/moved.md")
        git(self.clone, "commit", "-qm", "Move readme")
        git(self.clone, "push", "-q", "origin", "HEAD:refs/heads/" + self.branch)
        outcome = landing.land(self.clone, self.branch, test=["true"])
        self.assert_refused(outcome, "paths")
        self.assertIn("README.md", outcome.detail)

    def test_red_test_keeps_last_twenty_lines_and_cleans_output(self):
        self.branch_commit()
        code = ("from pathlib import Path; import sys; "
                "p = Path('fab/change.py'); t = p.with_suffix('.tmp'); "
                "t.write_text('dirty'); t.replace(p); Path('output').write_text('new'); "
                "print(''.join(f'line {i}\\n' for i in range(30)), end='', file=sys.stderr); sys.exit(1)")
        command = [sys.executable, "-B", "-c", code]
        with patch("fab.land.run", wraps=run) as runner:
            outcome = landing.land(self.clone, self.branch, test=command, sh=runner)
        runner.assert_any_call(command, cwd=str(self.clone), timeout=120)
        self.assert_refused(outcome, "test")
        self.assertEqual(outcome.detail.splitlines(), [f"line {i}" for i in range(10, 30)])
        self.assertFalse((self.clone / "output").exists())
        self.assertEqual((self.clone / "fab/change.py").read_text(), "branch\n")

    def moving_main_test(self):
        other = self.home / "other"
        git(self.home, "clone", "-q", str(self.origin), str(other))
        counter = self.home / "test-count"
        code = (
            "from pathlib import Path; import subprocess; "
            f"other = {str(other)!r}; counter = Path({str(counter)!r}); "
            "n = int(counter.read_text()) + 1 if counter.exists() else 1; "
            "sibling = counter.with_suffix('.tmp'); sibling.write_text(str(n)); sibling.replace(counter); "
            "n == 1 and subprocess.run(['git', 'commit', '--allow-empty', '-qm', 'Advance main'], cwd=other, check=True); "
            "n == 1 and subprocess.run(['git', 'push', '-q', 'origin', 'HEAD:main'], cwd=other, check=True)"
        )
        return [sys.executable, "-B", "-c", code], counter

    def test_main_moves_once_then_lands_on_retry(self):
        # Two real rebases and pushes, plus the competing push, exercise the retry.
        self.branch_commit()
        command, counter = self.moving_main_test()
        outcome = landing.land(self.clone, self.branch, test=command)
        self.assert_landed(outcome)
        self.assertEqual(counter.read_text(), "2")
        competing_tip = git(self.home / "other", "rev-parse", "HEAD")
        self.assertEqual(git(self.origin, "merge-base", competing_tip, outcome.tip), competing_tip)

    def test_already_contained_branch_lands_as_noop(self):
        tip = self.branch_commit()
        git(self.clone, "push", "-q", "origin", "HEAD:main")
        outcome = landing.land(self.clone, self.branch, test=["true"])
        self.assert_landed(outcome)
        self.assertEqual(outcome.tip, tip)
        self.assertIn("Already contained", outcome.detail)

    def test_failed_branch_delete_is_landed_with_detail(self):
        self.branch_commit()
        hook = self.origin / "hooks" / "update"
        self.write(hook, "#!/bin/sh\ncase $1 in refs/heads/draft/task) echo 'keep branch' >&2; exit 1;; esac\n")
        hook.chmod(0o755)
        outcome = landing.land(self.clone, self.branch, test=["true"])
        self.assertTrue(outcome.landed, outcome)
        self.assertEqual(outcome.tip, git(self.origin, "rev-parse", "main"))
        self.assertIn("branch delete failed", outcome.detail)
        self.assertIn("keep branch", outcome.detail)
        self.assert_clean_detached()

    def test_fetch_failure_leaves_clean_detached_checkout(self):
        self.branch_commit()
        git(self.clone, "remote", "set-url", "origin", str(self.home / "missing"))
        self.write(self.clone / "README.md", "dirty\n")
        outcome = landing.land(self.clone, self.branch, test=["true"])
        self.assert_refused(outcome, "fetch")
        self.assertIn("missing", outcome.detail)

    def test_main_cannot_be_deleted_as_landing_branch(self):
        outcome = landing.land(self.clone, "main", test=["true"])
        self.assertFalse(outcome.landed)
        self.assertEqual(outcome.step, "fetch")
        self.assertEqual(git(self.origin, "rev-parse", "main"), self.base)
        self.assert_clean_detached()


class LandWakeTest(WakeTestCase):
    def test_landing_and_refusal_wake_after_logging_with_the_logged_task(self):
        checkout = self.home / "checkout"
        checkout.mkdir()
        cases = [
            ("draft/task-r2", [], "draft/task", landing.Outcome(True, "landed", "ok")),
            ("draft/task", ["--task", "other/task"], "other/task", landing.Outcome(False, "paths", "outside")),
            ("calls", [], None, landing.Outcome(False, "test", "red")),
        ]
        want = wake.want
        for branch, options, task, outcome in cases:
            expected = f"land {task if task is not None else '-'} {outcome.step}"

            def note(reason):
                record = log.read()[-1]
                self.assertEqual(record["task"], task)
                self.assertEqual(record["ev"], "branch.landed" if outcome.landed else "branch.rejected")
                self.assertEqual(reason, expected)
                return want(reason)

            with self.subTest(task=task), patch.object(landing, "land", return_value=outcome), \
                    patch.object(wake, "want", side_effect=note), redirect_stdout(io.StringIO()):
                self.assertEqual(landing.main([branch, "--checkout", str(checkout), *options]),
                                 0 if outcome.landed else 1)
            self.assertWanted(expected)
            wake.take()
