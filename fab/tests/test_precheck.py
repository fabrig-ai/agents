"""Precheck merges and restoration with real git; check commands use the fake runner."""

import io
import json
import os
import shutil
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from fab import atomic, gate, nextest, precheck
from fab.sh import Result, run
from fab.tests.landing_checks import FakeNextest
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
    @classmethod
    def setUpClass(cls):
        cls.fixture = cls.enterClassContext(tmp_home())
        _, slot = git_pair(cls.fixture)
        write(slot / ".config/nextest.toml", '[profile.default]\n[profile.fuzzy]\n')
        git(slot, "add", ".config/nextest.toml")
        git(slot, "commit", "-qm", "Configure fake nextest")
        git(slot, "push", "-q", "origin", "HEAD:main")

    def setUp(self):
        self.home = self.enterContext(tmp_home())
        root = shutil.copytree(self.fixture, self.home / "git", symlinks=True)
        self.origin, self.slot = root / "origin.git", root / "clone"
        git(self.slot, "remote", "set-url", "origin", str(self.origin))
        self.base = git(self.slot, "rev-parse", "HEAD")
        self.branch = "draft/task"
        git(self.slot, "checkout", "-qb", self.branch)
        self.checks = FakeRunner()
        self.nextest = FakeNextest({None: [("b", "ok", "pass")]}, fallback=self.checks)
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
        return self.nextest(argv, **kwargs)

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
        self.assertEqual(set(receipt), {"tip", "main", "selection", "steps", "outcome", "starved", "log", "at"})
        self.assertIs(type(receipt["starved"]), int)
        self.assertGreaterEqual(receipt["starved"], 0)
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
        self.assertEqual(receipt["starved"], 0)
        self.assertEqual(loaded, [self.slot])
        self.assertEqual([step.rsplit(":", 2)[0] for step in receipt["steps"]],
                         ["ratchet:skein", "fmt", "clippy", "build", "default", "fuzzy"])
        self.assertEqual(len(set(observed)), 1)
        calls = self.checks.argvs()
        self.assertNotIn("--write", calls[0])
        self.assertEqual(calls[1], ["cargo", "fmt", "--check", "-p", "core"])
        for call in calls[2:] + self.nextest.calls:
            self.assertEqual(call[:2], ["heavy", "cargo"])
            self.assertNotIn("--gate", call)
            start = call.index("-p")
            self.assertEqual(call[start:start + 4], ["-p", "core", "-p", "dependent"])
        self.assertIn("fake check output", Path(receipt["log"]).read_text())
        self.assertFalse((self.slot / "main.md").exists())
        self.assertFalse((self.slot / "generated").exists())
        self.assert_restored(tip)

    def _global_timeout_checks(self, *, assertion=False):
        cases = [("b", "cancelled-a", "fail"), ("b", "cancelled-b", "fail"),
                 ("b", "ok", "pass")]
        if assertion:
            cases.append(("b", "assertion", "fail"))
        self.nextest = FakeNextest({None: cases}, codes={None: 100}, fallback=self.checks)
        original = self.nextest.collect

        def collect(request, repo):
            result = original(request, repo)
            path = Path(request["directory"]) / "summary.json"
            measured = json.loads(path.read_text())
            for test in measured["tests"]:
                test["starved"] = int(test["test_name"].startswith("cancelled-"))
            measured["failures"] = ["b assertion"] if assertion else []
            measured["suite"] = dict(starved_run=True, starved=2)
            atomic.write(path, json.dumps(measured))
            return Result(result.code, err="Cancelling due to global timeout\n")

        self.nextest.collect = collect

    def test_global_timeout_starvation_green_counted_and_named_in_build_lane(self):
        tip = self.commit("Cargo.toml", "workspace input\n")
        self._global_timeout_checks()
        receipt = self.check(tip)
        self.assert_receipt(receipt, tip, self.base)
        self.assertEqual(receipt["outcome"], "green")
        self.assertEqual(receipt["starved"], 4)
        self.assertEqual([step.split(":")[:2] for step in receipt["steps"]][-2:],
                         [["default", "100"], ["fuzzy", "100"]])
        content = Path(receipt["log"]).read_text()
        lines = [line for line in content.splitlines() if ": starved " in line]
        self.assertEqual(lines, [f"{profile}: starved b cancelled-{suffix}"
                                 for profile in ("default", "fuzzy") for suffix in ("a", "b")])
        self.assertGreater(content.index(lines[0]), content.index("fuzzy/smith: CPU"))
        directory = Path(receipt["log"]).with_suffix("")
        raw = nextest.junit(directory / "default/junit.xml", "default")
        self.assertEqual([case.result for case in raw], ["fail", "fail", "pass"])
        for command in self.commands + self.nextest.calls:
            self.assertNotIn("--gate", command)
        self.assertTrue(any(command[:2] == ["heavy", "cc"] for command in self.commands))
        self.assert_restored(tip)

    def test_assertion_beside_global_timeout_stays_red_and_stops_before_fuzzy(self):
        tip = self.commit("Cargo.toml", "workspace input\n")
        self._global_timeout_checks(assertion=True)
        receipt = self.check(tip)
        self.assert_receipt(receipt, tip, self.base)
        self.assertEqual((receipt["outcome"], receipt["starved"]), ("red", 2))
        self.assertEqual(receipt["steps"][-1].split(":")[:2], ["default", "100"])
        self.assertFalse(any(step.startswith("fuzzy:") for step in receipt["steps"]))
        self.assertEqual(len(self.nextest.calls), 1)
        content = Path(receipt["log"]).read_text()
        self.assertIn("default: starved b cancelled-a\n", content)
        self.assertIn("default: starved b cancelled-b\n", content)
        self.assertNotIn("starved b assertion", content)
        self.assert_restored(tip)

    def test_onto_checks_fetched_trunk_sha_and_restores_branch(self):
        tip = self.commit("docs/task.md", "task\n")
        trunk = "component-kit/integration"
        git(self.slot, "checkout", "-qb", trunk, "main")
        onto = self.commit("docs/trunk.md", "trunk\n")
        git(self.slot, "push", "-q", "origin", f"HEAD:{trunk}")
        git(self.slot, "checkout", "-q", self.branch)
        git(self.slot, "update-ref", f"refs/remotes/origin/{trunk}", self.base)
        receipt = self.check(tip, onto=f"origin/{trunk}")
        self.assert_receipt(receipt, tip, onto)
        self.assertEqual(receipt["outcome"], "green")
        self.assertIn(["git", "rev-parse", "--verify", f"origin/{trunk}^{{commit}}"], self.commands)
        self.assertIn(["git", "checkout", "--detach", "--force", onto], self.commands)
        self.assertIn(["git", "diff", "--name-only", "--no-renames", "-z", onto, "HEAD", "--"], self.commands)
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
        self.assertEqual(receipt["starved"], 0)
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
        self.assertEqual(receipt["starved"], 0)
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
        self.assertEqual(receipt["starved"], 0)
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

    def test_repeated_check_replaces_collector_directory_and_log(self):
        tip = self.commit("Cargo.toml", "workspace input\n")
        self.checks.on([], Result(0, "first output\n"))
        self.nextest.results = {None: [("b", "old", "starved")]}
        first = self.check(tip)
        directory = Path(first["log"]).with_suffix("")
        atomic.write(directory / "stale", "old collector output\n")
        self.nextest.results = {None: [("b", "new", "pass")]}
        self.checks.rules.clear()
        self.checks.on([], Result(0, "second output\n"))
        second = self.check(tip)
        self.assertEqual(first["log"], second["log"])
        self.assertEqual((first["starved"], second["starved"]), (2, 0))
        self.assertFalse((directory / "stale").exists())
        self.assertTrue((directory / "default/gate-junit.xml").is_file())
        content = Path(second["log"]).read_text()
        self.assertNotIn("first output", content)
        self.assertIn("second output", content)
        self.assert_restored(tip)


class PrecheckFullTest(unittest.TestCase):
    def test_full_checks_all_available_ratchets_regardless_of_paths(self):
        for absent, paths in ((None, ""), (None, "docs/guide.md\0"),
                              (None, "skein/core/src/lib.rs\0"), (gate.TREES[0], "")):
            with self.subTest(absent=absent, paths=paths), tmp_home() as home:
                slot = home / "slot"
                for tree in gate.TREES:
                    if tree != absent:
                        atomic.write(slot / tree / "scripts/old_forms.py", "# fake service\n")
                atomic.write(slot / "outside/scripts/old_forms.py", "# outside TREES\n")
                atomic.write(slot / ".config/nextest.toml", '[profile.default]\n[profile.fuzzy]\n')
                fake = (FakeRunner().on(["git", "rev-parse", "HEAD"], Result(0, "original\n"))
                        .on(["git", "rev-parse", "--verify", "origin/component-kit/integration^{commit}"],
                            Result(0, "trunk-sha\n"))
                        .on(["git", "rev-parse", "--verify", "--end-of-options"], Result(0, "tip-sha\n"))
                        .on(["git", "diff"], Result(0, paths)))
                receipt = precheck.precheck(slot, "tip", onto="origin/component-kit/integration",
                                            full=True, sh=FakeNextest({None: []}, fallback=fake),
                                            load=lambda _: self.fail("full loaded metadata"))
                trees = sorted(tree for tree in gate.TREES if tree != absent)
                self.assertEqual(receipt["main"], "trunk-sha")
                self.assertEqual(receipt["selection"], "full")
                self.assertEqual(receipt["outcome"], "green")
                self.assertEqual([step.rsplit(":", 2)[0] for step in receipt["steps"]],
                                 [*(f"ratchet:{tree}" for tree in trees),
                                  "fmt", "clippy", "build", "default", "fuzzy"])
                checks = [call for call in fake.calls if call.argv[0] != "git"]
                for call, tree in zip(checks, trees):
                    self.assertEqual(call.argv, ["python3", "-I", "-B",
                                                  str(slot / tree / "scripts/old_forms.py")])
                    self.assertEqual(call.cwd, str(slot / tree))
                self.assertEqual(checks[len(trees)].argv, ["cargo", "fmt", "--all", "--check"])
                for call in checks[len(trees) + 1:]:
                    self.assertEqual(call.argv[:2], ["heavy", "cargo"])
                    self.assertIn("--workspace", call.argv)
                self.assertEqual(fake.argvs()[-3:], [["git", "reset", "--hard", "original"],
                                 ["git", "checkout", "--detach", "--force", "original"],
                                 ["git", "clean", "-fd"]])


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
                    check.assert_called_once_with(home / "slot", "tip", onto="origin/main", full=False)
                    self.assertEqual(output.getvalue(), f"{log_path.with_suffix('.json')}: {outcome}\n")

    def test_main_passes_onto_and_full(self):
        with tmp_home() as home:
            receipt = {"log": str(home / "precheck/tip.log"), "outcome": "green"}
            with patch.object(precheck, "precheck", return_value=receipt) as check:
                with redirect_stdout(io.StringIO()):
                    code = precheck.main([str(home / "slot"), "tip",
                                          "--onto", "origin/component-kit/integration", "--full"])
            self.assertEqual(code, 0)
            check.assert_called_once_with(home / "slot", "tip",
                                          onto="origin/component-kit/integration", full=True)
