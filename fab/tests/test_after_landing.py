"""After-landing suspects use real git; test states and verdicts are pure decisions."""

import contextlib
import io
import json
import os
import tomllib
import xml.etree.ElementTree as ET
import unittest
from pathlib import Path
from unittest.mock import patch

from fab import after_landing, atomic, log, nextest, slots, tiers
from fab.after_landing import AfterLanding, Suspect, state, suspects, verdict
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


class AfterLandingTest(unittest.TestCase):
    profiles = ("qa-skein", "qa-jig")
    binary = "pkg::bin"

    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.enterContext(patch.dict(os.environ, GIT_ENV))
        self.enterContext(patch.dict(os.environ, {"FAB_SLOTS": str(self.home / "slots")}))
        self.repo = slots.slots_dir() / "1"
        self.config = "".join(f"[profile.{profile}]\nretries = 0\n" for profile in self.profiles)
        atomic.write(self.repo / tiers.NEXTEST_CONFIG, self.config)
        self.base = "0" * 40
        slots.claim(1, "after-landing", "after-landing")
        self.tip = self.base
        self.timeline = [self.base]
        self.subjects = {}
        self.sh = FakeRunner().on(["git", "rev-parse"], lambda call: Result(0, self.tip + "\n"))
        self.sh.on(["git", "rev-list"], self.rev_list)
        self.sh.on(["git", "show"], lambda call: Result(0, self.subjects[call.argv[-1]]))
        self.responses = {}
        self.invocations = []
        self.configured = {profile: tiers.Pair(profile, *profile.rsplit("-", 1), ("pkg",), ())
                           for profile in self.profiles}
        self.load = self.enterContext(patch.object(tiers, "load", return_value=self.configured))
        self.enterContext(patch.object(tiers, "run_pair", side_effect=self.run_pair))
        self.runner = self.make_runner()

    def make_runner(self, **kwargs):
        return AfterLanding(1, sh=self.sh, tier_set=self.profiles, **kwargs)

    def advance(self, branch=None):
        previous = self.tip
        self.tip = f"{len(self.timeline):040x}"
        self.timeline.append(self.tip)
        self.subjects[self.tip] = (f"{previous} other\nMerge {branch}\n" if branch else
                                   f"{previous}\nA plain commit\n")
        return self.tip

    def rev_list(self, call):
        previous, tip = call.argv[-1].split("..")
        commits = self.timeline[self.timeline.index(previous) + 1:self.timeline.index(tip) + 1]
        return Result(0, "\n".join(commits))

    def run_pair(self, repo, target, extra, path, *, sh):
        self.assertEqual(repo, self.repo)
        self.assertIs(sh, self.sh)
        self.assertIs(target, self.configured[target.profile])
        self.invocations.append((target.profile, extra, path))
        self.assertEqual(extra[0], "--config-file")
        overlay = Path(extra[1])
        data = tomllib.loads(overlay.read_text())
        report = overlay.with_suffix(".xml")
        self.assertEqual(data["profile"][target.profile]["junit"]["path"], str(report))
        self.assertEqual(data["profile"][target.profile]["retries"], 0)
        expression = extra[3] if len(extra) > 2 else None
        if expression is not None:
            self.assertEqual(extra[2], "-E")
        response = self.responses.get((target.profile, expression), (0, [("works", "pass")]))
        if isinstance(response, Exception):
            raise response
        code, cases = response
        atomic.write(path, f"fake pair exit {code}\n")
        if isinstance(cases, str):
            atomic.write(report, cases)
        elif cases is not None:
            root = ET.Element("testsuites", tests=str(len(cases)))
            suite = ET.SubElement(root, "testsuite", name=self.binary)
            for name, result in cases:
                case = ET.SubElement(suite, "testcase", name=name)
                if result == "fail":
                    ET.SubElement(case, "failure").text = "assertion failed\nmore details"
                elif result == "skipped":
                    ET.SubElement(case, "skipped")
            atomic.write(report, ET.tostring(root, encoding="unicode"))
        return code

    def response(self, cases, *, profile="qa-skein", code=None, alone=None):
        expression = nextest.exact_filter(self.binary, alone) if alone else None
        if code is None:
            code = tiers.TEST_FAILED if any(result == "fail" for _, result in cases) else 0
        self.responses[profile, expression] = code, cases

    def records(self, event=None):
        return [entry for entry in log.read(self.runner.log_path)
                if event is None or entry["ev"] == event]

    def history(self, name="works", profile="qa-skein"):
        return self.runner.state["tests"].get(nextest.Case(profile, self.binary, name, "pass", "").key)

    def test_slot_must_exist_and_belong_to_this_run_and_task(self):
        with self.assertRaisesRegex(ValueError, "does not exist"):
            AfterLanding(2, sh=self.sh)
        claim = slots.slots_dir() / "1.claim"
        claim.unlink()
        with self.assertRaisesRegex(ValueError, "not claimed"):
            self.make_runner()
        for run, task in [("another", "after-landing"), ("after-landing", "another")]:
            slots.claim(1, run, task)
            with self.assertRaisesRegex(ValueError, "not claimed"):
                self.make_runner()
            claim.unlink()
        self.assertEqual(self.sh.calls, [])
        self.load.assert_not_called()

    def test_green_saves_history_suspects_and_sweeps_target(self):
        self.assertEqual(self.runner.state, {"cursor": None, "last": None, "tests": {}})
        self.assertTrue(self.runner.cycle())
        self.advance("draft/one")
        self.advance()
        tip = self.advance("draft/two")
        incremental = self.repo / "target/debug/incremental"
        atomic.write(incremental / "stale", "old output")
        stale = self.repo / "target/debug/deps/stale-test"
        fresh = stale.with_name("fresh-test")
        for path, stamp in [(stale, 1), (fresh, 300)]:
            atomic.write(path, "test executable")
            path.chmod(0o700)
            os.utime(path, ns=(stamp, stamp))
        freed = sum(path.stat().st_blocks * 512 for path in [incremental, incremental / "stale", stale])
        call_count = len(self.sh.calls)
        with patch.object(after_landing.time, "time_ns", return_value=200) as start:
            self.assertTrue(self.runner.cycle())
        start.assert_called_once_with()
        record = self.records("run")[-1]
        self.assertEqual((record["tip"], record["previous"], record["verdict"]), (tip, self.base, "green"))
        self.assertEqual((record["branches"], record["commits"]), (["draft/one", "draft/two"], 3))
        self.assertEqual(record["faults"], [])
        for profile, summary in zip(self.profiles, record["pairs"], strict=True):
            self.assertRegex(summary, rf"^{profile}:ran:1:0:\d+\.\d$")
        self.assertEqual(record["freed"], freed)
        self.assertFalse(incremental.exists())
        self.assertFalse(stale.exists())
        self.assertTrue(fresh.exists())
        self.assertEqual([entry["ev"] for entry in self.records()], ["run", "run"])
        self.assertEqual(self.runner.state["cursor"], tip)
        self.assertEqual(self.runner.state["last"], {"tip": tip, "verdict": "green"})
        self.assertEqual(self.history(), {"result": "pass", "commit": tip})
        self.assertEqual(self.make_runner().state, self.runner.state)
        self.assertEqual(json.loads(self.runner.state_path.read_text()), self.runner.state)
        self.assertRegex(Path(record["log"]).name, rf"^{tip[:12]}-\d{{8}}T\d{{6}}Z$")
        self.assertEqual(self.sh.argvs()[call_count:call_count + 4], [
            ["git", "fetch", "-q", "origin", "main"], ["git", "rev-parse", "origin/main"],
            ["git", "switch", "--detach", "--force", tip], ["git", "clean", "-fd"]])
        self.assertTrue(all(call.cwd == str(self.repo) for call in self.sh.calls))

    def test_new_red_standing_and_recovered_follow_own_history(self):
        self.runner.cycle()
        self.response([("works", "fail")])
        self.response([("works", "fail")], alone="works")
        first = self.advance("draft/bad")
        self.runner.cycle()
        record, = self.records("test")
        self.assertEqual({key: record[key] for key in ("tip", "profile", "binary", "test", "state", "good",
                                                     "branches", "commits", "error")},
                         {"tip": first, "profile": "qa-skein", "binary": self.binary, "test": "works",
                          "state": "new", "good": self.base, "branches": ["draft/bad"], "commits": 1,
                          "error": "assertion failed"})
        self.assertEqual(Path(record["log"]).name, "qa-skein.log")
        self.assertEqual(Path(record["rerun"]).name, "qa-skein-1.log")
        self.assertEqual(self.records("run")[-1]["new"], 1)
        self.assertEqual(self.records("run")[-1]["verdict"], "red")
        self.assertEqual(self.runner.state["cursor"], first)
        self.assertEqual(self.history(), {"result": "red", "commit": first})
        second = self.advance("draft/still")
        self.runner.cycle()
        standing = self.records("test")[-1]
        self.assertEqual((standing["state"], standing["good"]), ("standing", ""))
        self.assertNotIn("branches", standing)
        self.assertEqual(self.history(), {"result": "red", "commit": second})
        self.assertEqual(self.records("run")[-1]["standing"], 1)
        self.response([("works", "pass")])
        third = self.advance("draft/fix")
        self.runner.cycle()
        recovered = self.records("test")[-1]
        self.assertEqual((recovered["state"], recovered["rerun"]), ("recovered", ""))
        self.assertEqual(self.records("run")[-1]["recovered"], 1)
        self.assertEqual(self.records("run")[-1]["verdict"], "green")
        self.assertEqual(self.history(), {"result": "pass", "commit": third})

    def test_new_red_attributes_since_its_last_execution_not_cursor(self):
        self.runner.cycle()
        self.advance("draft/skipped")
        self.response([("works", "skipped")])
        self.runner.cycle()
        cursor = self.tip
        self.assertEqual(self.history()["commit"], self.base)
        self.advance("draft/failure")
        self.response([("works", "fail")])
        self.response([("works", "fail")], alone="works")
        self.runner.cycle()
        self.assertEqual(self.records("test")[-1]["branches"], ["draft/skipped", "draft/failure"])
        self.assertEqual(self.records("test")[-1]["commits"], 2)
        self.assertEqual(self.records("run")[-1]["previous"], cursor)
        self.assertEqual(self.records("run")[-1]["branches"], ["draft/failure"])

    def test_flake_is_recorded_green_and_advances_passing_history(self):
        self.response([("works", "fail")])
        self.response([("works", "pass")], alone="works")
        self.runner.cycle()
        record, = self.records("test")
        self.assertEqual((record["state"], record["good"]), ("flake", ""))
        self.assertEqual(self.records("run")[0]["flake"], 1)
        self.assertEqual(self.records("run")[0]["verdict"], "green")
        self.assertEqual(self.history(), {"result": "pass", "commit": self.base})
        self.assertEqual(self.runner.state["cursor"], self.base)

    def test_unattributed_and_skipped_tests(self):
        self.response([("new_test", "fail"), ("unknown", "skipped")])
        self.response([("new_test", "fail")], alone="new_test")
        self.runner.cycle()
        record, = self.records("test")
        self.assertEqual((record["state"], record["good"]), ("unattributed", ""))
        self.assertEqual(self.records("run")[0]["unattributed"], 1)
        self.assertEqual(self.history("new_test")["result"], "red")
        self.assertIsNone(self.history("unknown"))

    def test_pair_faults_preserve_cursor_and_history_and_skip_same_partial_tip(self):
        self.runner.cycle()
        before = self.history().copy()
        failures = [(2, None, None, "exit 2"),
                    (0, None, None, "junit:"),
                    (100, [("works", "fail")], [("works", "fail"), ("other", "pass")], "rerun:")]
        for code, cases, rerun, reason in failures:
            with self.subTest(reason=reason):
                self.advance("draft/fault")
                self.responses["qa-skein", None] = code, cases
                if rerun:
                    self.response(rerun, alone="works")
                self.assertTrue(self.runner.cycle())
                record = self.records("run")[-1]
                self.assertEqual(record["verdict"], "partial")
                self.assertEqual(len(record["faults"]), 1)
                self.assertTrue(record["faults"][0].startswith(f"qa-skein: {reason}"))
                self.assertEqual(self.runner.state["cursor"], self.base)
                self.assertEqual(self.runner.state["last"], {"tip": self.tip, "verdict": "partial"})
                self.assertEqual(self.history(), before)
                self.assertEqual(self.history(profile="qa-jig")["commit"], self.tip)
                self.assertEqual(record["commits"], self.timeline.index(self.tip))
                calls = len(self.invocations)
                self.assertFalse(self.runner.cycle())
                self.assertEqual(len(self.invocations), calls)
                self.assertEqual(self.make_runner().state, self.runner.state)
        self.assertEqual(self.records("test"), [])
        self.advance("draft/healthy")
        self.response([("works", "pass")])
        self.runner.cycle()
        self.assertEqual(self.records("run")[-1]["branches"], ["draft/fault"] * 3 + ["draft/healthy"])
        self.assertEqual(self.runner.state["cursor"], self.tip)

    def test_red_with_another_fault_keeps_cursor_and_updates_only_ran_pair(self):
        self.runner.cycle()
        self.advance("draft/bad")
        self.response([("works", "fail")])
        self.response([("works", "fail")], alone="works")
        self.responses["qa-jig", None] = 75, None
        self.runner.cycle()
        record = self.records("run")[-1]
        self.assertEqual((record["verdict"], record["new"]), ("red", 1))
        self.assertEqual(record["faults"], ["qa-jig: exit 75"])
        self.assertEqual(self.runner.state["cursor"], self.base)
        self.assertEqual(self.history(), {"result": "red", "commit": self.tip})
        self.assertEqual(self.history(profile="qa-jig"), {"result": "pass", "commit": self.base})

    def test_rerun_fault_discards_every_case_in_its_pair(self):
        self.runner.cycle()
        before = dict(self.runner.state["tests"])
        self.advance()
        self.response([("passed", "pass"), ("works", "fail"), ("later", "fail")])
        self.response([("works", "fail")], alone="works")
        self.response([("wrong", "pass")], alone="later")
        self.runner.cycle()
        self.assertEqual(self.records("test"), [])
        self.assertEqual(self.history(), before[nextest.Case("qa-skein", self.binary, "works", "", "").key])
        self.assertIsNone(self.history("passed"))
        self.assertIsNone(self.history("later"))
        self.assertEqual(self.records("run")[-1]["verdict"], "partial")
        self.assertEqual([path.name for _, _, path in self.invocations[-4:]],
                         ["qa-skein.log", "qa-skein-1.log", "qa-skein-2.log", "qa-jig.log"])

    def test_pair_rejects_inconsistent_results_and_bad_junit(self):
        invalid = [(0, [], "inconsistent"), (100, [("works", "pass")], "inconsistent"),
                   (0, [("works", "fail")], "inconsistent"),
                   (0, "<broken", "JUnit"), (0, "<testsuites tests='1'/>", "counts")]
        for code, cases, reason in invalid:
            with self.subTest(code=code, cases=cases):
                self.responses["qa-skein", None] = code, cases
                pair = self.runner.pair("qa-skein", self.tip, self.home / "reports")
                self.assertEqual((pair["status"], pair["cases"]), ("faulted", []))
                self.assertIn("junit:", pair["reason"])
                self.assertIn(reason, pair["reason"])
        self.assertEqual(self.runner.state["tests"], {})

    def test_rerun_requires_the_same_executed_test_and_consistent_exit(self):
        self.response([("works", "fail")])
        invalid = [(2, None), (0, None), (0, [("wrong", "pass")]),
                   (0, [("works", "skipped")]), (0, [("works", "fail")]),
                   (100, [("works", "pass")])]
        for code, cases in invalid:
            with self.subTest(code=code, cases=cases):
                self.responses["qa-skein", nextest.exact_filter(self.binary, "works")] = code, cases
                pair = self.runner.pair("qa-skein", self.tip, self.home / "reports")
                self.assertEqual((pair["status"], pair["cases"]), ("faulted", []))
                self.assertTrue(pair["reason"].startswith("rerun:"))

    def test_pair_config_tier_and_io_errors_fault_without_results(self):
        directory = self.home / "reports"
        with patch.object(tiers, "load", side_effect=ValueError("bad map")):
            self.assertIn("bad map", self.runner.pair("qa-skein", self.tip, directory)["reason"])
        self.responses["qa-skein", None] = OSError("cannot run")
        self.assertIn("cannot run", self.runner.pair("qa-skein", self.tip, directory)["reason"])
        self.assertEqual(self.runner.pair("missing", self.tip, directory)["status"], "faulted")
        atomic.write(self.repo / tiers.NEXTEST_CONFIG, "bad toml [")
        self.assertEqual(self.runner.pair("qa-skein", self.tip, directory)["status"], "faulted")

    def test_unsafe_test_identity_faults_before_running_a_filter(self):
        self.response([("unsafe(name)", "fail")])
        pair = self.runner.pair("qa-skein", self.tip, self.home / "reports")
        self.assertEqual((pair["status"], pair["cases"]), ("faulted", []))
        self.assertTrue(pair["reason"].startswith("rerun:"))
        self.assertEqual(len(self.invocations), 1)

    def test_replayed_pair_removes_stale_junit_and_measures_invocations(self):
        directory = self.home / "reports"
        self.response([("works", "fail")])
        self.response([("works", "pass")], alone="works")
        with patch.object(after_landing.time, "monotonic", side_effect=[1, 1.25, 2, 2.5]):
            pair = self.runner.pair("qa-skein", self.tip, directory)
        self.assertEqual(pair["seconds"], 0.75)
        self.responses["qa-skein", None] = 0, None
        pair = self.runner.pair("qa-skein", self.tip, directory)
        self.assertEqual(pair["status"], "faulted")
        self.assertIn("missing", pair["reason"])

    def test_cycle_does_nothing_at_cursor(self):
        self.runner.cycle()
        count = len(self.invocations)
        self.assertFalse(self.runner.cycle())
        self.assertEqual(len(self.invocations), count)
        self.assertEqual(self.sh.argvs()[-2:], [["git", "fetch", "-q", "origin", "main"],
                                               ["git", "rev-parse", "origin/main"]])

    def test_sweep_start_is_taken_before_checkout(self):
        def checkout(call):
            self.assertEqual(start.call_count, 1)
            return Result(0)

        self.sh.on(["git", "switch"], checkout)
        with patch.object(after_landing.time, "time_ns", return_value=123) as start, \
                patch.object(slots, "sweep_plan", return_value=[]) as sweep:
            self.runner.check(self.tip)
        sweep.assert_called_once_with(self.repo / "target", 123)

    def test_failed_state_save_retries_whole_run_without_advancing_memory(self):
        before = json.loads(json.dumps(self.runner.state))

        write_file = atomic.write

        def write(path, text):
            if path == self.runner.state_path:
                self.assertEqual([entry["ev"] for entry in self.records()], ["test", "run"])
                raise OSError("state write failed")
            write_file(path, text)

        self.response([("works", "fail")])
        self.response([("works", "pass")], alone="works")
        with patch("fab.atomic.write", side_effect=write):
            with self.assertRaisesRegex(OSError, "state write failed"):
                self.runner.cycle()
        self.assertEqual(self.runner.state, before)
        self.assertEqual(self.make_runner().state, before)
        self.assertTrue(self.runner.cycle())
        self.assertEqual([entry["ev"] for entry in self.records()], ["test", "run", "test", "run"])

    def test_run_stops_at_file_and_records_cycle_exceptions(self):
        stop = self.home / "stop"
        outcomes = [True, False, RuntimeError("fetch refused"), True]
        sleeps = []

        def cycle():
            result = outcomes.pop(0)
            if not outcomes:
                atomic.write(stop, "")
            if isinstance(result, Exception):
                raise result
            return result

        with patch.object(self.runner, "cycle", side_effect=cycle) as called:
            self.runner.run(stop=stop, idle=0.25, sleep=sleeps.append)
        self.assertEqual(called.call_count, 4)
        self.assertEqual(sleeps, [0.25, 0.25])
        self.assertEqual(self.records("error")[0]["error"], "fetch refused")
        with patch.object(self.runner, "cycle", side_effect=AssertionError("already stopped")):
            self.runner.run(stop=stop)

    def test_main_log_since_and_unclaimed_once(self):
        stamps = ["2026-10-29T00:00:00.000Z", "2026-10-30T00:00:00.000Z", "2026-10-31T00:00:00.000Z"]
        for stamp in stamps:
            log.append("run", path=self.runner.log_path, ts=stamp, verdict="green")
        atomic.write(self.runner.log_path, self.runner.log_path.read_text() + "{torn")
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(after_landing.main(["log", "--since", stamps[1]]), 0)
        self.assertEqual([json.loads(line)["ts"] for line in output.getvalue().splitlines()], stamps[1:])
        (slots.slots_dir() / "1.claim").unlink()
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(after_landing.main(["once", "--slot", "1"]), 1)
        self.assertIn("fab after-landing: slot 1 is not claimed", errors.getvalue())

    def test_main_run_once_arguments_and_refusals(self):
        with patch.object(after_landing, "AfterLanding", return_value=self.runner) as constructor, \
                patch.object(self.runner, "cycle") as cycle, patch.object(self.runner, "run") as run_loop:
            self.assertEqual(after_landing.main(["once", "--slot", "1"]), 0)
            constructor.assert_called_once_with(1)
            cycle.assert_called_once_with()
            self.assertEqual(after_landing.main(["run", "--slot", "1"]), 0)
            run_loop.assert_called_once_with(stop=self.runner.home / "after-landing.stop")
            for error in [OSError("io"), RuntimeError("git"), ValueError("state")]:
                cycle.side_effect = error
                with contextlib.redirect_stderr(io.StringIO()) as errors:
                    self.assertEqual(after_landing.main(["once", "--slot", "1"]), 1)
                self.assertIn(f"fab after-landing: {error}", errors.getvalue())
        for args in [[], ["once"], ["run", "--slot", "no"], ["log", "--slot", "1"],
                     ["once", "--slot", "1", "--since", "now"]]:
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(after_landing.main(args), 2)


if __name__ == "__main__":
    unittest.main()
