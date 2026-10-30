"""After-landing suspects use real git; test states and verdicts are pure decisions."""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fab.after_landing import Suspect, state, suspects, verdict
from fab.sh import Failed, Result
from fab.tests.support import FakeRunner, GIT_ENV, git, git_pair, tmp_home


class SuspectsTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.enterContext(patch.dict(os.environ, GIT_ENV))
        _, self.repo = git_pair(self.home)
        self.base = git(self.repo, "rev-parse", "HEAD")

    def commit(self, subject):
        git(self.repo, "commit", "-q", "--allow-empty", "-m", subject)
        return git(self.repo, "rev-parse", "HEAD")

    def merge(self, branch, subject):
        git(self.repo, "switch", "-qc", branch)
        branch_tip = self.commit("Merge hidden/task")
        git(self.repo, "switch", "-q", "main")
        git(self.repo, "merge", "-q", "--no-ff", "-m", subject, branch)
        return branch_tip, git(self.repo, "rev-parse", "HEAD")

    def test_first_parent_suspects_name_queue_merges_oldest_first(self):
        # A queue-shaped subject on a plain commit must not name a branch.
        plain = self.commit("Merge plain/task")
        hidden, current = self.merge("drafty/task-a", "Merge drafty/task-a")
        _, old = self.merge("drafty/task-b", "Merge ready/drafty/task-b")
        _, other = self.merge("topic", "Merge a topic")
        _, suffix = self.merge("drafty/task-c", "Merge drafty/task-c extra")
        expected = [Suspect(plain, "Merge plain/task", None),
                    Suspect(current, "Merge drafty/task-a", "drafty/task-a"),
                    Suspect(old, "Merge ready/drafty/task-b", "drafty/task-b"),
                    Suspect(other, "Merge a topic", None),
                    Suspect(suffix, "Merge drafty/task-c extra", None)]
        found = suspects(self.repo, self.base, suffix)
        self.assertEqual(found, expected)
        self.assertNotIn(hidden, [suspect.commit for suspect in found])
        self.assertEqual(suspects(self.repo, current, suffix), expected[2:])
        self.assertEqual(suspects(self.repo, suffix, suffix), [])
        self.assertEqual(suspects(self.repo, None, suffix), [])

    def test_no_previous_does_not_run_git(self):
        sh = FakeRunner()
        self.assertEqual(suspects(Path("unused"), None, "tip", sh=sh), [])
        self.assertEqual(sh.calls, [])

    def test_git_failures_propagate(self):
        sh = FakeRunner().on(["git", "rev-list"], Result(128, err="bad revision"))
        with self.assertRaises(Failed):
            suspects(self.repo, "missing", self.base, sh=sh)
        sh = FakeRunner().on(["git", "rev-list"], Result(0, self.base + "\n"))
        sh.on(["git", "show"], Result(128, err="missing commit"))
        with self.assertRaises(Failed):
            suspects(self.repo, "previous", self.base, sh=sh)


class StateTest(unittest.TestCase):
    def test_every_history_and_result(self):
        histories = [None, {"result": "pass", "commit": "good"},
                     {"result": "red", "commit": "bad"}]
        rows = [("skipped", None, ["unobserved"] * 3),
                ("pass", None, ["passing", "passing", "recovered"]),
                ("fail", "pass", ["flake"] * 3),
                ("fail", "fail", ["unattributed", "new", "standing"])]
        for first, rerun, expected in rows:
            for last, result in zip(histories, expected):
                with self.subTest(first=first, rerun=rerun, last=last):
                    self.assertEqual(state(first, rerun, last), result)

    def test_invalid_reruns(self):
        for first, rerun in [("fail", None), ("pass", "pass"), ("pass", "fail"),
                             ("skipped", "pass"), ("skipped", "fail")]:
            with self.subTest(first=first, rerun=rerun):
                with self.assertRaises(ValueError):
                    state(first, rerun, None)


class VerdictTest(unittest.TestCase):
    def test_red_overrides_faults(self):
        for confirmed in ["new", "standing", "unattributed"]:
            for faulted in [False, True]:
                with self.subTest(confirmed=confirmed, faulted=faulted):
                    self.assertEqual(verdict(iter(["passing", confirmed]), faulted), "red")

    def test_partial_green_and_empty(self):
        for states in [[], ["passing", "unobserved", "flake", "recovered"]]:
            for faulted, expected in [(True, "partial"), (False, "green")]:
                with self.subTest(states=states, faulted=faulted):
                    self.assertEqual(verdict(iter(states), faulted), expected)
