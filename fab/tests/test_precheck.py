"""Precheck merges and restoration with real git; check commands use the fake runner."""

import io
import json
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from fab import precheck
from fab.sh import Result, run
from fab.tests.support import FakeRunner, GIT_ENV, git, git_pair, tmp_home


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    sibling = path.with_name(path.name + ".new")
    sibling.write_text(text)
    sibling.replace(path)


def metadata(repo):
    return {"workspace_root": str(repo), "workspace_members": ["core", "dependent"],
            "packages": [{"id": name, "name": name, "version": "1.0.0",
                          "manifest_path": str(repo / directory / "Cargo.toml")}
                         for name, directory in [("core", "skein/core"),
                                                 ("dependent", "dependent")]],
            "resolve": {"nodes": [{"id": "core", "dependencies": []},
                                  {"id": "dependent", "dependencies": ["core"]}]}}


class PrecheckGitTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.origin, self.slot = git_pair(self.home)
        self.base = git(self.slot, "rev-parse", "HEAD")
        self.branch = "draft/task"
        git(self.slot, "checkout", "-qb", self.branch)
        self.checks = FakeRunner()
        self.commands = []

    def commit(self, path, text):
        write(self.slot / path, text)
        git(self.slot, "add", "--", path)
        git(self.slot, "commit", "-qm", "Change " + path)
        return git(self.slot, "rev-parse", "HEAD")

    def advance_main(self, path="main.md", text="main update\n"):
        git(self.slot, "checkout", "-q", "main")
        main = self.commit(path, text)
        git(self.slot, "push", "-q", "origin", "HEAD:main")
        git(self.slot, "checkout", "-q", self.branch)
        # Make precheck's fetch responsible for updating origin/main.
        git(self.slot, "update-ref", "refs/remotes/origin/main", self.base)
        return main

    def runner(self, argv, **kwargs):
        self.commands.append(list(argv))
        if argv[0] == "git":
            return run(argv, env={**os.environ, **GIT_ENV}, **kwargs)
        return self.checks(argv, **kwargs)

    def check(self, tip, **kwargs):
        return precheck.precheck(self.slot, tip, sh=self.runner, **kwargs)

    def assert_restored(self, original, *, detached=False):
        self.assertEqual(git(self.slot, "rev-parse", "HEAD"), original)
        self.assertEqual(git(self.slot, "status", "--porcelain"), "")
        expected = "## HEAD (no branch)" if detached else "## " + self.branch
        self.assertEqual(git(self.slot, "status", "--porcelain", "--branch"), expected)
        self.assertEqual(git(self.slot, "rev-parse", self.branch), original)
        self.assertFalse((self.slot / ".git/MERGE_HEAD").exists())

    def assert_receipt(self, receipt, tip, main, *, home=None):
        directory = (home or self.home / "fab") / "precheck"
        self.assertEqual(set(receipt), {"tip", "main", "selection", "steps", "outcome", "log", "at"})
        self.assertEqual(receipt["tip"], tip)
        self.assertEqual(receipt["main"], main)
        self.assertEqual(receipt["log"], str(directory / f"{tip}.log"))
        self.assertTrue(Path(receipt["log"]).is_file())
        self.assertRegex(receipt["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
        self.assertEqual(json.loads((directory / f"{tip}.json").read_text()), receipt)
        for step in receipt["steps"]:
            name, code, seconds = step.rsplit(":", 2)
            self.assertTrue(name)
            int(code)
            self.assertGreaterEqual(float(seconds), 0)

    def test_green_checks_merge_with_fetched_main_and_restores_branch(self):
        tip = self.commit("skein/core/src/lib.rs", "branch source\n")
        main = self.advance_main()
        observed = []

        def check(call):
            observed.append(git(self.slot, "rev-parse", "HEAD"))
            if len(observed) == 1:
                self.assertEqual(git(self.slot, "show", "-s", "--format=%P", "HEAD").split(),
                                 [main, tip])
                self.assertEqual((self.slot / "main.md").read_text(), "main update\n")
                self.assertEqual((self.slot / "skein/core/src/lib.rs").read_text(), "branch source\n")
            write(self.slot / "README.md", "check changed tracked file\n")
            write(self.slot / "generated/output", "check output\n")
            return Result(0, "fake check output\n")

        self.checks.on([], check)
        loaded = []

        def load(repo):
            loaded.append(repo)
            return metadata(repo)

        receipt = self.check(self.branch, load=load)
        self.assert_receipt(receipt, tip, main)
        self.assertEqual(receipt["outcome"], "green")
        self.assertEqual(receipt["selection"], ["core", "dependent"])
        self.assertEqual(loaded, [self.slot])
        self.assertEqual([step.rsplit(":", 2)[0] for step in receipt["steps"]],
                         ["ratchet:skein", "fmt", "clippy", "build", "default", "fuzzy"])
        self.assertEqual(len(set(observed)), 1)
        calls = self.checks.argvs()
        self.assertNotIn("--write", calls[0])
        self.assertEqual(calls[1], ["cargo", "fmt", "--check", "-p", "core"])
        for call in calls[2:]:
            self.assertEqual(call[:2], ["heavy", "cargo"])
            self.assertNotIn("--gate", call)
            start = call.index("-p")
            self.assertEqual(call[start:start + 4], ["-p", "core", "-p", "dependent"])
        self.assertIn("fake check output", Path(receipt["log"]).read_text())
        self.assertFalse((self.slot / "main.md").exists())
        self.assertFalse((self.slot / "generated").exists())
        self.assert_restored(tip)

    def test_full_selection_skips_metadata_and_uses_build_lane(self):
        tip = self.commit("Cargo.toml", "workspace input\n")
        receipt = self.check(tip, load=lambda _: self.fail("full loaded metadata"))
        self.assertEqual(receipt["selection"], "full")
        self.assertEqual(receipt["outcome"], "green")
        self.assertEqual(self.checks.argvs()[0], ["cargo", "fmt", "--all", "--check"])
        self.assertIn("--workspace", self.checks.argvs()[1])
        self.assert_restored(tip)

    def test_docs_receipt_with_explicit_home_and_no_checks(self):
        tip = self.commit("docs/guide.md", "guide\n")
        home = self.home / "other-runtime"
        receipt = self.check(tip, home=home, load=lambda _: self.fail("docs loaded metadata"))
        self.assert_receipt(receipt, tip, self.base, home=home)
        self.assertEqual(receipt["selection"], "docs")
        self.assertEqual(receipt["steps"], [])
        self.assertEqual(receipt["outcome"], "green")
        self.assertEqual(self.checks.calls, [])
        self.assert_restored(tip)

    def test_red_records_failing_step_and_stops(self):
        tip = self.commit("Cargo.toml", "workspace input\n")
        self.checks.on(["heavy", "cargo", "clippy"], Result(7, "lint failure\n"))
        receipt = self.check(tip)
        self.assert_receipt(receipt, tip, self.base)
        self.assertEqual(receipt["outcome"], "red")
        self.assertEqual([step.split(":")[:2] for step in receipt["steps"]],
                         [["fmt", "0"], ["clippy", "7"]])
        self.assertEqual(len(self.checks.calls), 2)
        self.assertIn("lint failure", Path(receipt["log"]).read_text())
        self.assert_restored(tip)

    def test_red_ratchet_stops_before_build_checks(self):
        tip = self.commit("skein/README.md", "guide\n")
        self.checks.on(["python3"], Result(1, "ratchet failure\n"))
        receipt = self.check(tip)
        self.assertEqual(receipt["outcome"], "red")
        self.assertEqual(len(receipt["steps"]), 1)
        self.assertTrue(receipt["steps"][0].startswith("ratchet:skein:1:"))
        self.assertEqual(len(self.checks.calls), 1)
        self.assert_restored(tip)

    def test_conflict_receipt_and_restoration(self):
        tip = self.commit("README.md", "branch version\n")
        main = self.advance_main("README.md", "main version\n")
        receipt = self.check(tip)
        self.assert_receipt(receipt, tip, main)
        self.assertEqual(receipt["outcome"], "conflict")
        self.assertEqual(receipt["steps"], [])
        self.assertEqual(self.checks.calls, [])
        self.assertIn("CONFLICT", Path(receipt["log"]).read_text())
        self.assert_restored(tip)
        self.assertEqual((self.slot / "README.md").read_text(), "branch version\n")

    def test_step_exception_propagates_after_restoration(self):
        tip = self.commit("Cargo.toml", "workspace input\n")

        def explode(call):
            write(self.slot / "README.md", "changed\n")
            write(self.slot / "generated", "output\n")
            raise RuntimeError("step raised")

        self.checks.on([], explode)
        with self.assertRaisesRegex(RuntimeError, "step raised"):
            self.check(tip)
        self.assert_restored(tip)
        self.assertFalse((self.slot / "generated").exists())

    def test_metadata_exception_restores_slot(self):
        tip = self.commit("skein/core/src/lib.rs", "source\n")

        def explode(repo):
            raise ValueError("metadata raised")

        with self.assertRaisesRegex(ValueError, "metadata raised"):
            self.check(tip, load=explode)
        self.assert_restored(tip)

    def test_restores_detached_head_when_checking_a_different_tip(self):
        tip = self.commit("README.md", "candidate\n")
        git(self.slot, "checkout", "--detach", "-q", self.base)
        receipt = self.check(tip)
        self.assertEqual(receipt["outcome"], "green")
        self.assertEqual(git(self.slot, "rev-parse", "HEAD"), self.base)
        self.assertEqual(git(self.slot, "status", "--porcelain", "--branch"), "## HEAD (no branch)")
        self.assertEqual(git(self.slot, "rev-parse", self.branch), tip)

    def test_repeated_check_replaces_log_instead_of_appending(self):
        tip = self.commit("Cargo.toml", "workspace input\n")
        self.checks.on([], Result(0, "first output\n"))
        first = self.check(tip)
        self.checks.rules.clear()
        self.checks.on([], Result(0, "second output\n"))
        second = self.check(tip)
        self.assertEqual(first["log"], second["log"])
        content = Path(second["log"]).read_text()
        self.assertNotIn("first output", content)
        self.assertIn("second output", content)
        self.assert_restored(tip)


class PrecheckMainTest(unittest.TestCase):
    def test_main_prints_receipt_path_and_outcome_with_exit_codes(self):
        with tmp_home() as home:
            for outcome, code in [("green", 0), ("red", 1), ("conflict", 1)]:
                with self.subTest(outcome=outcome):
                    log_path = home / "fab/precheck/tip.log"
                    receipt = {"log": str(log_path), "outcome": outcome}
                    with patch.object(precheck, "precheck", return_value=receipt) as check:
                        with redirect_stdout(io.StringIO()) as output:
                            self.assertEqual(precheck.main([str(home / "slot"), "tip"]), code)
                    check.assert_called_once_with(home / "slot", "tip")
                    self.assertEqual(output.getvalue(), f"{log_path.with_suffix('.json')}: {outcome}\n")
