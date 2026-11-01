"""Probe real git's caught-up trees and failures (docs/design/fab-integration.md, 4)."""

import json
import os
import unittest
from unittest.mock import patch

from fab import atomic, log, overlaps
from fab.plan import Plan
from fab.sh import run
from fab.tests.support import GIT_ENV, git, git_pair, tmp_home


class OverlapsGitTest(unittest.TestCase):
    """Exercise merge-tree's path format and object validation in isolated repositories."""

    def setUp(self):
        """Push conflicting trunks, then advance main without catching up either trunk."""
        self.home = self.enterContext(tmp_home())
        self.enterContext(patch.dict(os.environ, GIT_ENV))
        _, self.clone = git_pair(self.home)
        self.path = self.home / "probe.jsonl"
        self.cache_path = log.home() / "overlaps.json"
        self.conflict = "docs/two words.md"
        self.loaded, self.tips = [], []
        for draft in ("a", "b"):
            plan = Plan(draft, "agents", (), 1, 2, {}, ())
            git(self.clone, "checkout", "-q", "-b", plan.trunk, "origin/main")
            atomic.write(self.clone / self.conflict, f"{draft} chooses this text\n")
            git(self.clone, "add", self.conflict)
            git(self.clone, "commit", "-q", "-m", f"Choose {draft}'s text")
            self.tips.append(git(self.clone, "rev-parse", "HEAD"))
            self.loaded.append((plan, {}, self.clone / "plans" / draft, self.clone))
        git(self.clone, "push", "-q", "origin", "a/integration", "b/integration")
        git(self.clone, "checkout", "-q", "main")
        atomic.write(self.clone / "main-only.md", "Main moved ahead\n")
        git(self.clone, "add", "main-only.md")
        git(self.clone, "commit", "-q", "-m", "Advance main independently")
        git(self.clone, "push", "-q", "origin", "main")
        git(self.clone, "fetch", "-q", "origin")
        self.main = git(self.clone, "rev-parse", "origin/main")

    def _probe(self):
        """Run the real probe with its preceding log records, returning printed lines."""
        return overlaps.probe(self.loaded, log.read(self.path), True,
                              sh=run, log_path=self.path)

    def test_spaced_path_survives_catch_up_and_repeat_probe_is_silent(self):
        """Log the literal conflict path and trunk tips once after main advances."""
        self.assertEqual(self._probe(), ["overlap a b 1"])
        events = log.read(self.path)
        self.assertEqual(len(events), 1)
        self.assertEqual({key: events[0][key] for key in
                          ("ev", "drafts", "tips", "files", "more", "reason")},
                         dict(ev="trunks.overlap", drafts=["a", "b"], tips=self.tips,
                              files=[self.conflict], more=0, reason="probe"))
        cache = json.loads(self.cache_path.read_text())
        self.assertEqual(len(cache["trees"]), 2)
        for tree in cache["trees"].values():
            self.assertEqual(git(self.clone, "show", f"{tree}:main-only.md"),
                             "Main moved ahead")
        self.assertEqual(self._probe(), [])
        self.assertEqual(log.read(self.path), events)

    def test_missing_cached_tree_is_a_pair_failure_without_an_overlap(self):
        """A first-format cache's absent object produces one failure line and note."""
        missing = "f" * len(self.main)
        self.assertFalse(run(["git", "cat-file", "-e", missing],
                             cwd=str(self.clone)).ok)
        key = json.dumps(["agents", str(self.clone), self.main, self.tips[0]])
        atomic.write(self.cache_path, json.dumps({"trees": {key: missing}, "pairs": {}}))
        lines = self._probe()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("trunks.overlap a b: exit "), lines)
        events = log.read(self.path)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["ev"], "note")
        self.assertEqual(events[0]["text"], lines[0])
        self.assertEqual([event for event in events if event["ev"] == "trunks.overlap"], [])
