"""Tier maps and commands in a temporary checkout, with no cargo or heavy processes."""

import io
import json
import os
import shlex
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from fab import tiers
from fab.gate import Step
from fab.sh import Result
from fab.tests.support import FakeRunner, tmp_home


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    sibling = path.with_name(path.name + ".new")
    sibling.write_text(text)
    sibling.replace(path)


def toml(value):
    if isinstance(value, dict):
        return "{" + ", ".join(f"{key} = {toml(item)}" for key, item in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(toml(item) for item in value) + "]"
    return json.dumps(value)


def listing(*tests, filtered=()):
    return json.dumps({"rust-suites": {"artifact-hash": {
        "package-name": "skein-a", "binary-id": "skein-a::integration",
        "testcases": {name: {"filter-match": {"status": status}}
                      for status, names in (("matches", tests), ("mismatch", filtered))
                      for name in names}}}})


class TiersTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.repo = self.home / "checkout"
        self.config = self.repo / tiers.NEXTEST_CONFIG
        self.map = self.repo / tiers.PACKAGE_MAPS[1]
        write(self.config, "[profile.default]\n[profile.qa-skein]\n"
              "[profile.browser-jig]\n[profile.process-temper]\n")
        self.packages = {"browser-jig": ["jig-browser-tests"],
                         "process-temper": ["temper-process-tests"],
                         "qa-skein": ["skein-a", "skein-b"]}
        self.binaries = {"browser-jig": [{"package": "jig-helper", "bin": "jig-test-daemon",
                                         "env": "JIG_TEST_DAEMON"}],
                         "process-temper": [{"package": "temper-helper", "bin": "temper-child"}],
                         "qa-skein": []}
        self.save_map()

    def save_map(self, path=None):
        lines = [f"{name} = {toml(value)}" for name, value in self.packages.items()]
        lines += ["[binaries]"] + [f"{name} = {toml(value)}" for name, value in self.binaries.items()]
        write(path or self.map, "\n".join(lines) + "\n")

    def chosen(self, profile="browser-jig"):
        return tiers.load(self.repo)[profile]

    def main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        previous = os.umask(0o022)
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = tiers.main(argv)
            self.assertEqual(os.umask(0o077), 0o077)
        finally:
            os.umask(previous)
        return code, out.getvalue(), err.getvalue()

    def test_load_pairs_split_at_last_hyphen_and_sort(self):
        write(self.config, self.config.read_text() + "[profile.qa-long-skein]\n")
        self.packages["qa-long-skein"] = ["pkg_1"]
        self.binaries["qa-long-skein"] = []
        self.save_map()
        pairs = tiers.load(self.repo)
        self.assertEqual(list(pairs), ["browser-jig", "process-temper", "qa-long-skein", "qa-skein"])
        self.assertEqual(pairs["qa-long-skein"],
                         tiers.Pair("qa-long-skein", "qa-long", "skein", ("pkg_1",), ()))
        self.assertEqual(pairs["browser-jig"].binaries,
                         (tiers.Binary("jig-helper", "jig-test-daemon", "JIG_TEST_DAEMON"),))
        self.assertEqual(pairs["process-temper"].binaries,
                         (tiers.Binary("temper-helper", "temper-child"),))
        self.assertEqual(pairs["qa-skein"].packages, ("skein-a", "skein-b"))

    def test_load_config_map_wins_without_falling_back_on_errors(self):
        self.packages["qa-skein"] = ["new-package"]
        new = self.repo / tiers.PACKAGE_MAPS[0]
        self.save_map(new)
        write(self.map, "broken = [")
        self.assertEqual(self.chosen("qa-skein").packages, ("new-package",))
        write(new, "broken = [")
        with self.assertRaises(tiers.TierError) as error:
            tiers.load(self.repo)
        self.assertIn(str(new), str(error.exception))

    def test_load_missing_and_malformed_files(self):
        for path in (self.config, self.map):
            content = path.read_text()
            for bad in (None, "broken = ["):
                with self.subTest(path=path, bad=bad):
                    if bad is None:
                        path.unlink()
                    else:
                        write(path, bad)
                    with self.assertRaises(tiers.TierError) as error:
                        tiers.load(self.repo)
                    self.assertIn(str(path), str(error.exception))
                    write(path, content)
        for text in ("", "profile = []\n"):
            with self.subTest(text=text):
                write(self.config, text)
                with self.assertRaisesRegex(tiers.TierError, "profile"):
                    tiers.load(self.repo)

    def test_load_invalid_package_lists(self):
        for value in (None, [], "pkg", ["b", "a"], ["a", "a"], ["bad.name"], [1], [["a"]]):
            with self.subTest(value=value):
                if value is None:
                    self.packages.pop("qa-skein", None)
                else:
                    self.packages["qa-skein"] = value
                self.save_map()
                with self.assertRaises(tiers.TierError) as error:
                    tiers.load(self.repo)
                self.assertIn(str(self.map), str(error.exception))
                self.assertIn("qa-skein", str(error.exception))

    def test_load_binaries_table_needs_exact_profiles(self):
        good = self.map.read_text()
        for text in (good.split("[binaries]")[0], good.replace("[binaries]", "binaries = []\n[unused]"),
                     good.replace("qa-skein = []\n", ""), good + "default = []\n"):
            with self.subTest(text=text):
                write(self.map, text)
                with self.assertRaisesRegex(tiers.TierError, "binaries.*configured profiles"):
                    tiers.load(self.repo)

    def test_load_invalid_binary_records(self):
        bad = ("not a list", [1], [{"package": "a"}], [{"bin": "a"}],
               [{"package": "a", "bin": "a", "other": "x"}],
               [{"package": "bad.name", "bin": "a"}], [{"package": 1, "bin": "a"}],
               [{"package": "a", "bin": "bad/bin"}], [{"package": "a", "bin": []}],
               [{"package": "a", "bin": "a", "env": "lower_test_value"}],
               [{"package": "a", "bin": "a", "env": 1}],
               [{"package": "z", "bin": "z"}, {"package": "a", "bin": "a"}],
               [{"package": "a", "bin": "a"}, {"package": "a", "bin": "a"}],
               [{"package": "a", "bin": "same"}, {"package": "b", "bin": "same"}],
               [{"package": "a", "bin": "a", "env": "A_TEST_BIN"},
                {"package": "b", "bin": "b", "env": "A_TEST_BIN"}])
        for records in bad:
            with self.subTest(records=records):
                self.binaries["qa-skein"] = records
                self.save_map()
                with self.assertRaises(tiers.TierError) as error:
                    tiers.load(self.repo)
                self.assertIn(str(self.map), str(error.exception))
                self.assertIn("qa-skein", str(error.exception))

    def test_pair_known_and_unknown_names_configured_profiles(self):
        pairs = tiers.load(self.repo)
        self.assertEqual(tiers.pair(pairs, "skein", "qa"), pairs["qa-skein"])
        with self.assertRaises(tiers.TierError) as error:
            tiers.pair(pairs, "skein", "browser")
        self.assertIn("unknown pair skein browser", str(error.exception))
        self.assertIn("browser-jig, process-temper, qa-skein", str(error.exception))

    def test_pair_honors_split_at_last_hyphen(self):
        target = tiers.Pair("qa-long-skein", "qa-long", "skein", ("tests",), ())
        pairs = {target.profile: target}
        self.assertEqual(tiers.pair(pairs, "skein", "qa-long"), target)
        with self.assertRaisesRegex(tiers.TierError, "unknown pair long-skein qa"):
            tiers.pair(pairs, "long-skein", "qa")

    def test_bundle_browser_and_qa_temper_only(self):
        self.assertEqual(tiers.bundle(self.chosen()), tiers.BUNDLES["jig"])
        temper = tiers.Pair("qa-temper", "qa", "temper", ("tests",), ())
        self.assertEqual(tiers.bundle(temper), tiers.BUNDLES["temper"])
        self.assertIsNone(tiers.bundle(self.chosen("qa-skein")))
        for profile, tier, tree in (("qa-jig", "qa", "jig"), ("browser-other", "browser", "other")):
            self.assertIsNone(tiers.bundle(tiers.Pair(profile, tier, tree, ("tests",), ())))

    def test_steps_browser_order_environment_bundle_and_extra_arguments(self):
        target = self.home / "target with spaces"
        steps = tiers.steps(self.repo, self.chosen(), ["-E", "test(a b)", "--retries", "2"], target)
        self.assertEqual([step.name for step in steps],
                         ["wasm module", "bundle tool", "browser bundle",
                          "binary jig-helper/jig-test-daemon", "nextest"])
        prefix = ("env", "NEXTEST_DOUBLE_SPAWN=0", f"JIG_TEST_BUNDLE={target}/jig-test-bundle",
                  f"JIG_TEST_DAEMON={target}/debug/jig-test-daemon")
        for step in steps:
            self.assertIsInstance(step, Step)
            self.assertEqual(step.cwd, str(self.repo))
            self.assertEqual(step.argv[:4], prefix)
        self.assertEqual(steps[0].argv[4:], ("heavy", "cargo", "build", "--target",
                         "wasm32-unknown-unknown", "-p", "jig-client-test-shell-web"))
        self.assertEqual(steps[1].argv[4:], ("heavy", "cargo", "build", "-p", "skein-ui-bundle"))
        self.assertEqual(steps[2].argv[4:], (
            f"{target}/debug/skein-ui-bundle", "--module",
            f"{target}/wasm32-unknown-unknown/debug/jig_client_test_shell_web.wasm",
            "--name", "jig_client_test_shell_web", "--prefix", "/bundle/",
            "--stylesheet", "jig/crates/jig-client-shell-web/jig.css",
            "--stylesheet", "jig/testing/jig-client-test-shell-web/jig_client_test_shell_web.css",
            "--pictures", "jig=jig/crates/jig-client-shell-web/pictures",
            "--pictures", "jig-test=jig/testing/jig-client-test-shell-web/pictures",
            "--files", "jig/testing/jig-client-test-shell-web/files",
            "--noscript", "jig needs WebAssembly and scripts.", "--out", f"{target}/jig-test-bundle"))
        self.assertEqual(steps[3].argv[4:], ("heavy", "cargo", "build", "-p", "jig-helper",
                                           "--bin", "jig-test-daemon"))
        self.assertEqual(steps[4].argv[4:], ("heavy", "cargo", "nextest", "run", "-p",
                         "jig-browser-tests", "--profile", "browser-jig", "--no-fail-fast",
                         "-E", "test(a b)", "--retries", "2"))

    def test_steps_qa_without_target_and_binary_without_environment(self):
        self.assertEqual(tiers.steps(self.repo, self.chosen("qa-skein"), [], None), [Step(
            "nextest", ("env", "NEXTEST_DOUBLE_SPAWN=0", "heavy", "cargo", "nextest", "run",
                        "-p", "skein-a", "-p", "skein-b", "--profile", "qa-skein", "--no-fail-fast"),
            str(self.repo))])
        steps = tiers.steps(self.repo, self.chosen("process-temper"), [], None)
        self.assertEqual([step.name for step in steps], ["binary temper-helper/temper-child", "nextest"])
        self.assertEqual(steps[0].argv, ("env", "NEXTEST_DOUBLE_SPAWN=0", "heavy", "cargo", "build",
                                       "-p", "temper-helper", "--bin", "temper-child"))

    def test_steps_requires_target_for_bundle_or_binary_environment(self):
        for target_pair in (self.chosen(), tiers.Pair("qa-jig", "qa", "jig", ("tests",),
                                (tiers.Binary("helper", "child", "JIG_TEST_CHILD"),))):
            with self.subTest(profile=target_pair.profile), self.assertRaisesRegex(ValueError, "target"):
                tiers.steps(self.repo, target_pair, [], None)

    def test_steps_preserves_given_target_and_temper_features(self):
        target_pair = tiers.Pair("qa-temper", "qa", "temper", ("tests",), ())
        steps = tiers.steps(self.repo, target_pair, [], Path("relative-target"))
        self.assertEqual(steps[0].argv[3:], ("heavy", "cargo", "build", "--target",
                         "wasm32-unknown-unknown", "--features", "loopback-navigation",
                         "-p", "temper-client-shell-web"))
        self.assertEqual(steps[0].argv[2], "TEMPER_TEST_BUNDLE=relative-target/temper-bundle")
        self.assertEqual(steps[2].argv[3], "relative-target/debug/skein-ui-bundle")

    def test_target_directory_is_direct_metadata_and_resolved(self):
        target = self.home / "build" / ".." / "target"
        sh = FakeRunner().on(["cargo", "metadata"], Result(0, json.dumps({"target_directory": str(target)})))
        self.assertEqual(tiers.target_directory(self.repo, sh=sh), self.home / "target")
        self.assertEqual(sh.argvs(), [["cargo", "metadata", "--format-version", "1", "--no-deps"]])
        self.assertEqual(sh.calls[0].cwd, str(self.repo))

    def test_target_directory_refuses_failure_or_bad_output(self):
        for answer in (Result(1, err="metadata failed"), Result(0, "{}"), Result(0, "no JSON"),
                       Result(0, '{"target_directory": 1}')):
            with self.subTest(answer=answer), self.assertRaisesRegex(tiers.TierError, "cargo metadata"):
                tiers.target_directory(self.repo, sh=FakeRunner().on(["cargo"], answer))

    def test_run_pair_returns_nextest_code_and_logs_every_step(self):
        target_pair = self.chosen()
        target = self.home / "target with spaces"
        commands = tiers.steps(self.repo, target_pair, ["--retries", "1"], target)
        for code in (0, 100):
            with self.subTest(code=code):
                log = self.home / "logs" / f"{code}.log"
                sh = FakeRunner().on(["cargo", "metadata"], Result(0, json.dumps({"target_directory": str(target)})))
                sh.on(commands[-1].argv, Result(code, "test output\n", "test error\n"))
                self.assertEqual(tiers.run_pair(self.repo, target_pair, ["--retries", "1"], log, sh=sh), code)
                self.assertEqual(sh.argvs()[1:], [list(step.argv) for step in commands])
                self.assertTrue(all(call.cwd == str(self.repo) for call in sh.calls))
                content = log.read_text()
                for step in commands:
                    self.assertIn(f"[{step.name}] {shlex.join(step.argv)} (cwd {self.repo})", content)
                self.assertIn("test output\ntest error\n", content)

    def test_run_pair_failed_prerequisite_stops_before_nextest(self):
        target_pair = self.chosen("process-temper")
        sh = FakeRunner().on(["env", "NEXTEST_DOUBLE_SPAWN=0", "heavy", "cargo", "build"],
                             Result(75, err="no disk\n"))
        log = self.home / "run.log"
        self.assertEqual(tiers.run_pair(self.repo, target_pair, [], log, sh=sh), tiers.REFUSED)
        self.assertEqual(len(sh.calls), 1)
        self.assertNotIn("nextest", sh.calls[0].argv)
        self.assertIn("no disk", log.read_text())

    def test_run_pair_metadata_failure_appends_error_and_runs_no_steps(self):
        log = self.home / "logs" / "run.log"
        write(log, "earlier log\n")
        sh = FakeRunner().on(["cargo", "metadata"], Result(1, err="bad metadata"))
        self.assertEqual(tiers.run_pair(self.repo, self.chosen(), [], log, sh=sh), tiers.REFUSED)
        self.assertEqual(len(sh.calls), 1)
        self.assertTrue(log.read_text().startswith("earlier log\n"))
        self.assertIn("cargo metadata", log.read_text())
        self.assertIn("bad metadata", log.read_text())

    def test_run_pair_binary_environment_without_bundle_loads_target(self):
        target_pair = tiers.Pair("qa-jig", "qa", "jig", ("tests",),
                                 (tiers.Binary("helper", "child", "JIG_TEST_CHILD"),))
        target = self.home / "target"
        sh = FakeRunner().on(["cargo", "metadata"], Result(0, json.dumps({"target_directory": str(target)})))
        self.assertEqual(tiers.run_pair(self.repo, target_pair, [], self.home / "native.log", sh=sh), 0)
        self.assertEqual(len(sh.calls), 3)
        self.assertEqual(sh.calls[1].argv[:3],
                         ["env", "NEXTEST_DOUBLE_SPAWN=0", f"JIG_TEST_CHILD={target}/debug/child"])
        self.assertEqual(sh.calls[1].argv[3:], ["heavy", "cargo", "build", "-p", "helper", "--bin", "child"])
        self.assertEqual(sh.calls[2].argv[3:7], ["heavy", "cargo", "nextest", "run"])

    def test_run_pair_plain_qa_skips_metadata(self):
        sh = FakeRunner()
        self.assertEqual(tiers.run_pair(self.repo, self.chosen("qa-skein"), [], self.home / "qa.log", sh=sh), 0)
        self.assertEqual(len(sh.calls), 1)
        self.assertEqual(sh.calls[0].argv[2:6], ["heavy", "cargo", "nextest", "run"])

    def test_listed_uses_last_listing_and_only_matching_tests(self):
        output = listing("earlier") + '\nheavy: evidence\n[]\n{}\n' + listing("chosen", filtered=("skip",)) + '\nheavy: done\n'
        self.assertEqual(tiers.listed(output), {("skein-a", "skein-a::integration", "chosen")})
        self.assertEqual(tiers.listed(listing(filtered=("skip",))), set())
        with self.assertRaisesRegex(ValueError, "listing"):
            tiers.listed("evidence\n{}\n[1]\n")

    def test_verify_missed_added_and_commands(self):
        sh = FakeRunner().on(["heavy", "cargo", "nextest", "list", "--workspace"], Result(0, listing("same", "missed")))
        sh.on(["heavy", "cargo", "nextest", "list", "-p"], Result(0, listing("same", "added", filtered=("skip",))))
        self.assertEqual(tiers.verify(self.repo, self.chosen("qa-skein"), sh=sh), (
            {("skein-a", "skein-a::integration", "missed")},
            {("skein-a", "skein-a::integration", "added")}))
        self.assertEqual(sh.argvs(), [
            ["heavy", "cargo", "nextest", "list", "--workspace", "--profile", "qa-skein", "--message-format", "json"],
            ["heavy", "cargo", "nextest", "list", "-p", "skein-a", "-p", "skein-b",
             "--profile", "qa-skein", "--message-format", "json"]])
        self.assertTrue(all(call.cwd == str(self.repo) for call in sh.calls))

    def test_verify_names_failed_listing(self):
        for scope, selection in (("workspace", "--workspace"), ("packages", "-p")):
            for answer in (Result(1, err="list failed"), Result(0, "not a listing")):
                with self.subTest(scope=scope, answer=answer):
                    sh = FakeRunner().on(["heavy", "cargo", "nextest", "list", selection], answer)
                    sh.on(["heavy"], Result(0, listing("test")))
                    with self.assertRaisesRegex(tiers.TierError, f"qa-skein: {scope} listing"):
                        tiers.verify(self.repo, self.chosen("qa-skein"), sh=sh)
                    self.assertEqual(len(sh.calls), 1 if scope == "workspace" else 2)

    def test_main_run_prints_log_before_execution_and_returns_code(self):
        for code in (0, 100):
            with self.subTest(code=code):
                def execute(repo, target_pair, extra, log):
                    self.assertEqual(repo, self.repo)
                    self.assertEqual(target_pair.profile, "qa-skein")
                    self.assertEqual(extra, ["-E", "test(foo)"])
                    self.assertEqual(log.parent, Path(os.environ["FAB_HOME"]) / "tiers")
                    self.assertRegex(log.name, r"^qa-skein-\d{8}T\d{6}Z\.log$")
                    self.assertTrue(out.getvalue().startswith(f"tiers: log {log}\n"))
                    write(log, "nextest output\n")
                    return code

                out, err = io.StringIO(), io.StringIO()
                previous = os.umask(0o022)
                try:
                    with patch.object(tiers, "run_pair", side_effect=execute), redirect_stdout(out), redirect_stderr(err):
                        actual = tiers.main(["run", "skein", "qa", "--repo", str(self.repo), "--", "-E", "test(foo)"])
                    self.assertEqual(os.umask(0o077), 0o077)
                finally:
                    os.umask(previous)
                self.assertEqual(actual, code)
                self.assertTrue(out.getvalue().endswith("\nnextest output\n"))
                self.assertEqual(err.getvalue(), "")

    def test_main_verify_all_continues_and_prints_sorted_differences(self):
        missed = {("z", "b", "last"), ("a", "b", "first")}
        with patch.object(tiers, "verify", side_effect=[(missed, {("x", "y", "added")}), (set(), set()), (set(), set())]) as verify:
            code, out, err = self.main(["verify", "--repo", str(self.repo)])
        self.assertEqual(code, 1)
        self.assertEqual([call.args[1].profile for call in verify.call_args_list],
                         ["browser-jig", "process-temper", "qa-skein"])
        self.assertEqual(out.splitlines(), [
            "tiers: browser-jig: 2 missed, 1 added", "tiers: browser-jig: missed a b first",
            "tiers: browser-jig: missed z b last", "tiers: browser-jig: added x y added",
            "tiers: process-temper: 0 missed, 0 added", "tiers: qa-skein: 0 missed, 0 added"])
        self.assertEqual(err, "")

    def test_main_verify_one_passes(self):
        with patch.object(tiers, "verify", return_value=(set(), set())) as verify:
            code, out, err = self.main(["verify", "skein", "qa", "--repo", str(self.repo)])
        self.assertEqual((code, out, err), (0, "tiers: qa-skein: 0 missed, 0 added\n", ""))
        self.assertEqual(verify.call_args.args, (self.repo, self.chosen("qa-skein")))

    def test_main_unknown_pair_returns_refused(self):
        with patch.object(tiers, "run_pair") as run_pair:
            code, out, err = self.main(["run", "skein", "unknown", "--repo", str(self.repo)])
        self.assertEqual((code, out), (2, ""))
        self.assertIn("configured profiles: browser-jig, process-temper, qa-skein", err)
        run_pair.assert_not_called()

    def test_main_verify_error_is_refused(self):
        with patch.object(tiers, "verify", side_effect=tiers.TierError("listing unavailable")):
            code, out, err = self.main(["verify", "--repo", str(self.repo)])
        self.assertEqual((code, out, err), (2, "", "listing unavailable\n"))

    def test_main_bad_arguments_exit_two(self):
        for argv in ([], ["run", "skein"], ["verify", "skein"],
                     ["verify", "--", "test"], ["run", "skein", "qa", "--extra"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit) as error:
                self.main(argv)
            self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
