"""After-landing suspects use real git; test states and verdicts are pure decisions."""

import contextlib
import io
import json
import os
import shlex
import tomllib
import xml.etree.ElementTree as ET
import unittest
from pathlib import Path
from unittest.mock import patch

from fab import after_landing, atomic, cpu, hosts, log, nextest, slots, tiers
from fab.hosts import Host
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
        self.envs = []
        self.configured = {profile: tiers.Pair(profile, *profile.rsplit("-", 1), ("pkg",), ())
                           for profile in self.profiles}
        self.load = self.enterContext(patch.object(tiers, "load", return_value=self.configured))
        self.enterContext(patch.object(cpu, "run_pair", side_effect=self.run_pair))
        self.enterContext(patch.object(cpu, "build_wrapper", return_value=self.home / "wrapper"))
        self.wake_patch = patch.object(after_landing.events, "wake", return_value=True)
        self.wake = self.wake_patch.start()
        self.addCleanup(self.wake_patch.stop)
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

    def run_pair(self, repo, target, extra, path, *, sh, env=None, directory=None, wrapper=None, wall_hard_s=None):
        self.assertEqual(repo, self.repo)
        self.assertIs(sh, self.sh)
        self.assertIs(target, self.configured[target.profile])
        self.invocations.append((target.profile, extra, path))
        self.envs.append(env)
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
        if report.exists():
            atomic.write(directory / "junit.xml", report.read_text())
        measured = dict(suite=dict(cpu_s=0.0, wall_s=0.0, starved_run=False), tests=[], failures=[])
        # Invalid/missing JUnit is still rejected by cpu.cases, or the exit check.
        if not report.exists() and code == 0:
            raise ValueError("invalid/missing nextest JUnit")
        return code, measured

    def response(self, cases, *, profile="qa-skein", code=None, alone=None):
        expression = nextest.exact_filter(self.binary, alone) if alone else None
        if code is None:
            code = tiers.TEST_FAILED if any(result == "fail" for _, result in cases) else 0
        self.responses[profile, expression] = code, cases

    def records(self, event=None):
        return [entry for entry in log.read(self.runner.log_path)
                if (event is None or entry["ev"] == event)
                and entry.get("state") not in ("passing", "unobserved") and entry["ev"] != "pair"]

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
        self.assertRegex(Path(record["log"]).name, rf"^{tip[:12]}-\d{{8}}T\d{{12}}Z$")
        self.assertEqual(self.sh.argvs()[call_count:call_count + 4], [
            ["git", "fetch", "-q", "origin", "main"], ["git", "rev-parse", "origin/main"],
            ["git", "switch", "--detach", "--force", tip], ["git", "clean", "-fd"]])
        self.assertTrue(all(call.cwd == str(self.repo) for call in self.sh.calls))
        self.assertEqual(record["reds"], [])
        self.wake.assert_not_called()

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
        self.assertEqual(record["key"], nextest.Case("qa-skein", self.binary, "works", "", "").key)
        self.assertEqual(self.records("run")[-1]["reds"], [record["key"]])
        self.assertEqual(after_landing.imported(self.records("run")[-1])["reds"], [record["key"]])
        self.wake.assert_called_once_with(
            f"after-landing {first[:12]} new 1 unattributed 0 recovered 0",
            sh=self.sh, hosts=self.runner.known)
        self.wake.reset_mock()
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
        self.assertEqual(self.records("run")[-1]["reds"], [record["key"]])
        self.wake.assert_not_called()
        self.response([("works", "pass")])
        third = self.advance("draft/fix")
        self.runner.cycle()
        recovered = self.records("test")[-1]
        self.assertEqual((recovered["state"], recovered["rerun"]), ("recovered", ""))
        self.assertEqual(self.records("run")[-1]["recovered"], 1)
        self.assertEqual(self.records("run")[-1]["verdict"], "green")
        self.assertEqual(self.history(), {"result": "pass", "commit": third})
        self.assertEqual(self.records("run")[-1]["reds"], [])
        self.assertEqual(after_landing.imported(recovered), dict(
            ev="tiers.recovered", tip=third, key=record["key"],
            profile="qa-skein", binary=self.binary, test="works"))
        self.wake.assert_called_once_with(
            f"after-landing {third[:12]} new 0 unattributed 0 recovered 1",
            sh=self.sh, hosts=self.runner.known)

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
        self.runner.cycle()
        self.advance("draft/one")
        self.advance()
        self.advance("draft/two")
        self.response([("new_test", "fail"), ("unknown", "skipped")])
        self.response([("new_test", "fail")], alone="new_test")
        self.runner.cycle()
        record, = self.records("test")
        self.assertEqual((record["state"], record["good"]), ("unattributed", ""))
        self.assertEqual(self.records("run")[-1]["unattributed"], 1)
        self.assertEqual(self.records("run")[-1]["reds"], [record["key"]])
        self.assertEqual(record["branches"], ["draft/one", "draft/two"])
        red = after_landing.imported(record)
        self.assertEqual(red, dict(
            ev="tiers.red", tip=self.tip, key=record["key"], state="unattributed",
            profile="qa-skein", binary=self.binary, test="new_test", error="assertion failed",
            branches=["draft/one", "draft/two"], log=record["log"], rerun=record["rerun"]))
        self.wake.assert_called_once_with(
            f"after-landing {self.tip[:12]} new 0 unattributed 1 recovered 0",
            sh=self.sh, hosts=self.runner.known)
        self.assertEqual(self.history("new_test")["result"], "red")
        self.assertIsNone(self.history("unknown"))

    def test_new_red_wakes_dispatcher_over_ssh(self):
        self.wake_patch.stop()
        known = {"builder": Host("builder", "fake@builder", ("builder", "after-landing")),
                 "dispatcher": Host("dispatcher", "fake@dispatcher", ("dispatcher",))}
        self.runner = self.make_runner(known=known)
        self.runner.check(self.tip)
        self.response([("works", "fail")])
        self.response([("works", "fail")], alone="works")
        tip = self.advance("draft/bad")
        with patch.dict(os.environ, {"FAB_HOST": "builder"}):
            self.runner.check(tip)
        commands = [call.argv for call in self.sh.calls if call.argv[0] == "ssh"]
        reason = f"after-landing {tip[:12]} new 1 unattributed 0 recovered 0"
        self.assertEqual(commands, [["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
                                     "fake@dispatcher",
                                     "bash -lc " + shlex.quote(shlex.join(["fab", "wake", reason]))]])

    def test_mixed_run_wakes_once_after_records_and_history_are_saved(self):
        cases = [("new_red", "fail"), ("unknown_red", "fail"), ("fixed", "pass")]
        for name, result in (("new_red", "pass"), ("fixed", "red")):
            key = nextest.Case("qa-skein", self.binary, name, "", "").key
            self.runner.state["tests"][key] = dict(result=result, commit=self.base)
        self.response(cases)
        self.response([("new_red", "fail")], alone="new_red")
        self.response([("unknown_red", "fail")], alone="unknown_red")
        self.runner.known = {"builder": Host("builder", "free@builder", ("builder",))}

        observed = []

        def wake(reason, **kwargs):
            observed.append((list(log.read(self.runner.log_path))[-1],
                             json.loads(self.runner.state_path.read_text()),
                             self.history("fixed")["result"]))
            return True

        self.wake.side_effect = wake
        record = self.runner.check(self.tip)
        self.assertEqual((record["new"], record["unattributed"], record["recovered"]), (1, 1, 1))
        self.assertEqual(observed, [(record, self.runner.state, "pass")])
        self.assertEqual(record["reds"], [nextest.Case("qa-skein", self.binary, name, "", "").key
                                          for name in ("new_red", "unknown_red")])
        self.wake.assert_called_once_with(
            f"after-landing {self.tip[:12]} new 1 unattributed 1 recovered 1",
            sh=self.sh, hosts=self.runner.known)

    def test_standing_flake_unobserved_and_passing_tests_do_not_wake(self):
        key = nextest.Case("qa-skein", self.binary, "standing", "", "").key
        self.runner.state["tests"][key] = dict(result="red", commit=self.base)
        self.response([("standing", "fail"), ("flake", "fail"), ("unknown", "skipped")])
        self.response([("standing", "fail")], alone="standing")
        self.response([("flake", "pass")], alone="flake")
        record = self.runner.check(self.tip)
        self.assertEqual((record["standing"], record["flake"], record["unobserved"], record["passing"]),
                         (1, 1, 1, 1))
        self.assertEqual(record["reds"], [key])
        self.wake.assert_not_called()

    def test_wake_failure_is_printed_without_failing_or_losing_the_run(self):
        self.response([("works", "fail")])
        self.response([("works", "fail")], alone="works")
        for failure in (False, OSError("offline"), RuntimeError("wake broke")):
            with self.subTest(failure=failure):
                self.runner.state["tests"] = {}
                self.wake.reset_mock()
                self.wake.side_effect = failure if isinstance(failure, Exception) else None
                self.wake.return_value = False
                with contextlib.redirect_stderr(io.StringIO()) as errors:
                    record = self.runner.check(self.tip)
                self.wake.assert_called_once()
                self.assertEqual((record["verdict"], record["unattributed"]), ("red", 1))
                self.assertEqual(list(log.read(self.runner.log_path))[-1], record)
                self.assertEqual(json.loads(self.runner.state_path.read_text()), self.runner.state)
                self.assertEqual(self.runner.state["cursor"], self.tip)
                self.assertEqual(self.history()["result"], "red")
                expected = str(failure) if isinstance(failure, Exception) else (
                    f"not delivered: after-landing {self.tip[:12]} new 0 unattributed 1 recovered 0")
                self.assertEqual(errors.getvalue(), f"fab after-landing: wake: {expected}\n")

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
        self.assertEqual(self.records("run")[-1]["reds"], [])
        self.wake.assert_not_called()
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
        self.assertEqual(self.runner.pair("missing", self.tip, directory)["status"], "retired")
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
        original_write = atomic.write

        def write(path, text):
            if path == self.runner.state_path:
                self.assertEqual([entry["ev"] for entry in self.records()], ["test", "run"])
                raise OSError("state write failed")
            original_write(path, text)

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

    def live_runner(self, shelf, *, temper=False):
        """A --live runner on builder b1 whose `fab logins` calls to hel8 answer from shelf:
        borrow KIND -> the next id of shelf[KIND] (none left: refused), return -> ok unless
        the id is in shelf["stuck"]; the local refresh `fab logins account` answers
        shelf["refresh"] (default an account). temper adds a test-only pair to cover the
        chatgpt and claude-box login kinds while live-temper is out of --live."""
        if temper:
            self.enterContext(patch.object(after_landing, "LIVE", {
                "live-temper": (("TEMPER_LIVE_ACCOUNT", "chatgpt"), ("TEMPER_LIVE_CLAUDE", "claude-box")),
                **after_landing.LIVE,
            }))
        machines = {"hel8": Host("hel8", "free@hel8", ("dispatcher",)), "b1": Host("b1", "free@b1", ("builder",))}
        self.enterContext(patch.dict(os.environ, {"FAB_HOST": "b1"}))
        self.configured.update({profile: tiers.Pair(profile, *profile.rsplit("-", 1), ("pkg",), ())
                                for profile in after_landing.LIVE})
        atomic.write(self.repo / tiers.NEXTEST_CONFIG, self.config + "".join(
            f"[profile.{profile}]\nretries = 0\n" for profile in after_landing.LIVE))
        self.calls = []

        def shelf_call(call):
            self.assertEqual(call.argv[:-1], ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "free@hel8"])
            argv = shlex.split(call.argv[-1])[2:]
            argv = shlex.split(argv[0])[2:] if argv[0].startswith("fab ") else argv
            self.calls.append(argv)
            if argv[0] == "borrow":
                left = shelf[argv[1]]
                return Result(0, left.pop(0) + "\n") if left else Result(1, "", f"fab logins: no free {argv[1]} login\n")
            return Result(1, "", "fab logins: changed\n") if argv[1] in shelf.get("stuck", ()) else Result(0)

        self.sh.on(["ssh"], shelf_call)
        self.refreshes = []

        def refresh(call):
            self.refreshes.append(call.argv[3:])
            return shelf.get("refresh", Result(0, '{"email": "a@example.invalid"}\n'))

        self.sh.on(["fab", "logins", "account"], refresh)
        return AfterLanding(1, sh=self.sh, tier_set=self.profiles, live=True, known=machines)

    def test_live_adds_only_skein_and_advances_the_cursor_without_temper_logins(self):
        runner = self.live_runner({"codex": ["codex-7"], "claude": ["claude-9"]})
        self.assertEqual(runner.tier_set, (*self.profiles, "live-skein"))
        record = runner.check(self.tip)
        self.assertEqual((record["verdict"], record["faults"]), ("green", []))
        self.assertEqual([profile for profile, _, _ in self.invocations], list(runner.tier_set))
        self.assertEqual([call[1] for call in self.calls if call[0] == "borrow"], ["codex", "claude"])
        self.assertEqual(runner.state["cursor"], self.tip)

    def test_live_pairs_borrow_their_logins_from_the_dispatcher_and_return_them(self):
        runner = self.live_runner({"chatgpt": ["chatgpt-1"], "claude-box": ["claude-box-1", "claude-box-2"],
                                   "codex": ["codex-7"], "claude": ["claude-9"]}, temper=True)
        self.assertEqual(runner.tier_set, ("qa-skein", "qa-jig", "live-temper", "live-skein"))
        record = runner.check(self.tip)
        self.assertEqual(record["verdict"], "green")
        directory = Path(record["log"])
        temper, skein = self.envs[2], self.envs[3]
        self.assertEqual(self.envs[:2], [{}, {}])
        self.assertEqual(temper, {"TEMPER_LIVE_ACCOUNT": str(directory / "logins/TEMPER_LIVE_ACCOUNT/login"),
                                  "TEMPER_LIVE_CLAUDE": str(directory / "logins/TEMPER_LIVE_CLAUDE")})
        openai, anthropic = directory / "logins/SKEIN_TEST_LIVE_OPENAI_AUTH", \
            directory / "logins/SKEIN_TEST_LIVE_ANTHROPIC_CREDENTIALS"
        self.assertEqual(skein, {"SKEIN_TEST_LIVE_OPENAI_AUTH": str(openai / "auth.json"),
                                 "SKEIN_TEST_LIVE_ANTHROPIC_CREDENTIALS": str(anthropic / ".credentials.json"),
                                 "SKEIN_TEST_LIVE_OPENAI_MODEL": "gpt-6-luna",
                                 "SKEIN_TEST_LIVE_ANTHROPIC_MODEL": "claude-haiku-5-5"})
        self.assertEqual(self.refreshes, [["codex", "--home", str(openai), "--validate"],
                                          ["claude", "--home", str(anthropic), "--validate"]])
        holder = f"after-landing/{self.tip[:12]}/live-temper"
        self.assertEqual(self.calls, [
            ["borrow", "chatgpt", "b1", "--path", temper["TEMPER_LIVE_ACCOUNT"], "--holder", holder],
            ["borrow", "claude-box", "b1", "--path", temper["TEMPER_LIVE_CLAUDE"], "--holder", holder],
            ["return", "chatgpt-1"], ["return", "claude-box-1"],
            ["borrow", "codex", "b1", "--path", skein["SKEIN_TEST_LIVE_OPENAI_AUTH"], "--holder",
             f"after-landing/{self.tip[:12]}/live-skein"],
            ["borrow", "claude", "b1", "--path", skein["SKEIN_TEST_LIVE_ANTHROPIC_CREDENTIALS"], "--holder",
             f"after-landing/{self.tip[:12]}/live-skein"],
            ["return", "codex-7"], ["return", "claude-9"]])

    def test_a_live_login_that_does_not_refresh_faults_its_pair_and_is_returned(self):
        runner = self.live_runner({"chatgpt": [], "claude-box": [], "codex": ["codex-7"], "claude": ["claude-9"],
                                   "refresh": Result(0, '{"error": "not logged in"}\n')})
        record = runner.check(self.tip)
        self.assertIn("live-skein: logins: codex-7 did not refresh: not logged in", record["faults"])
        self.assertEqual(self.calls[-1], ["return", "codex-7"])
        self.assertNotIn("live-skein", [profile for profile, _, _ in self.invocations])

    def test_a_live_pair_without_its_logins_faults_and_returns_what_it_borrowed(self):
        runner = self.live_runner({"chatgpt": ["chatgpt-1"], "claude-box": [], "codex": [], "claude": [],
                                   "stuck": ["chatgpt-1"]}, temper=True)
        record = runner.check(self.tip)
        self.assertEqual(record["verdict"], "partial")
        self.assertEqual(record["faults"], ["live-temper: logins: fab logins: no free claude-box login",
                                            "live-skein: logins: fab logins: no free codex login"])
        self.assertEqual([profile for profile, _, _ in self.invocations], ["qa-skein", "qa-jig"])
        self.assertIn(["return", "chatgpt-1"], self.calls)
        self.assertEqual(self.records("error")[0]["error"], "login chatgpt-1 not returned: fab logins: changed")

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
            constructor.assert_called_once_with(1, live=False)
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


    def cpu_response(self, *, result="pass", used=1.0, wall=2.0, stopped=False,
                     later=None, rerun_result=None):
        def invoke(repo, target, extra, path, **kwargs):
            if later is not None:
                later.append(kwargs["wall_hard_s"])
            rerun = "-E" in extra
            outcome = rerun_result if rerun else result
            report = kwargs["directory"] / "junit.xml"
            failure = '<failure type="test timeout"/>' if outcome == "starved" else (
                '<failure>assertion failed</failure>' if outcome == "fail" else "")
            atomic.write(report, f'<testsuites><testsuite name="{self.binary}">'
                         f'<testcase name="works">{failure}</testcase></testsuite></testsuites>')
            return (100 if outcome == "fail" else 0), dict(
                suite=dict(cpu_s=used, wall_s=wall, starved_run=stopped),
                tests=[dict(binary_id=self.binary, test_name="works", cpu_s=used,
                            wall_s=wall, starved=int(outcome == "starved"), incomplete=int(stopped))],
                failures=[f"{self.binary} works"] if outcome == "fail" else [])
        return patch.object(cpu, "run_pair", side_effect=invoke)

    def test_starved_has_cpu_no_rerun_no_history_recovery_and_possible_hang(self):
        key = nextest.Case("qa-skein", self.binary, "works", "pass", "").key
        self.runner.state["tests"][key] = dict(result="red", commit="old")
        with self.cpu_response(result="starved", used=.01, wall=5) as invoke:
            record = self.runner.check(self.tip)
        self.assertEqual(invoke.call_count, 2)  # once per pair, no confirmation
        self.assertEqual((record["verdict"], record["starved"], record["cpu_s"], record["wall_s"]),
                         ("green", 2, .02, 10))
        self.assertEqual(self.history(), dict(result="red", commit="old"))
        self.assertEqual(record["reds"], [])
        self.assertEqual(len(record["possible_hangs"]), 2)
        tests = [row for row in log.read(self.runner.log_path) if row["ev"] == "test"]
        self.assertTrue(all(row["state"] == "starved" and row["cpu_s"] == .01 for row in tests))
        self.wake.assert_not_called()

    def test_total_wall_stops_later_pairs_without_fault_or_confirmation(self):
        atomic.write(self.repo / cpu.BUDGETS, '[after-landing]\nwall_hard_s=5\n')
        with self.cpu_response(result="starved", wall=5, stopped=True) as invoke:
            record = self.runner.check(self.tip)
        self.assertEqual(invoke.call_count, 1)
        self.assertEqual((record["verdict"], record["starved"], record["wall_starved"]), ("green", 1, True))
        self.assertEqual(record["faults"], [])
        pair = [row for row in log.read(self.runner.log_path) if row["ev"] == "pair"][-1]
        self.assertEqual((pair["profile"], pair["status"]), ("qa-jig", "unobserved"))
        self.assertIsNone(self.history())

    def test_remaining_total_wall_covers_pairs_and_reruns(self):
        atomic.write(self.repo / cpu.BUDGETS, '[after-landing]\nwall_hard_s=10\n')
        remaining = []
        with self.cpu_response(result="fail", used=1, wall=2, rerun_result="pass", later=remaining):
            record = self.runner.check(self.tip)
        self.assertEqual(remaining, [10, 8, 6, 4])
        self.assertEqual((record["cpu_s"], record["wall_s"], record["flake"]), (4, 8, 2))
        tests = [row for row in log.read(self.runner.log_path) if row["ev"] == "test"]
        self.assertTrue(all(row["cpu_s"] == 2 for row in tests))

    def test_final_pair_passing_during_cleanup_still_reports_total_wall_expiry(self):
        self.runner.tier_set = ("qa-skein",)
        atomic.write(self.repo / cpu.BUDGETS, '[after-landing]\nwall_hard_s=5\n')
        with self.cpu_response(result="pass", wall=5.1):
            record = self.runner.check(self.tip)
        self.assertEqual((record["verdict"], record["wall_starved"]), ("green", True))

    def test_observed_failure_survives_wall_stopped_confirmation(self):
        atomic.write(self.repo / cpu.BUDGETS, '[after-landing]\nwall_hard_s=5\n')
        with self.cpu_response(result="fail", wall=5, stopped=True) as invoke:
            record = self.runner.check(self.tip)
        self.assertEqual(invoke.call_count, 1)
        self.assertEqual((record["verdict"], record["unattributed"]), ("red", 1))
        key = nextest.Case("qa-skein", self.binary, "works", "", "").key
        self.assertIn(key, record["reds"])

    def test_starved_confirmation_cannot_clear_an_observed_failure(self):
        with self.cpu_response(result="fail", rerun_result="starved"):
            record = self.runner.check(self.tip)
        self.assertEqual((record["verdict"], record["unattributed"], record["starved"]), ("red", 2, 2))

    def test_pair_budgets_diagnostic_total_and_test_cpu_budgets_red_without_reruns(self):
        atomic.write(self.repo / cpu.BUDGETS, '[qa-skein]\ncpu_suite_s=0.1\n'
                     '[after-landing]\ncpu_total_s=1.5\ncpu_test_s=0.5\n')
        with self.cpu_response(used=1) as invoke:
            record = self.runner.check(self.tip)
        self.assertEqual(invoke.call_count, 2)
        self.assertEqual(record["verdict"], "red")
        self.assertEqual(len(record["over_budget"]), 3)
        self.assertIn("qa-skein pkg::bin works", record["over_budget"][1])
        atomic.write(self.repo / cpu.BUDGETS, '[qa-skein]\ncpu_suite_s=0.1\ncpu_test_s=0.1\nwall_hard_s=0.1\n')
        with self.cpu_response(used=1):
            self.assertEqual(self.runner.check(self.tip)["verdict"], "green")
        pairs = [row for row in log.read(self.runner.log_path) if row["ev"] == "pair"]
        self.assertIn("cpu_suite_s=0.1", pairs[-2]["budget"])

    def test_retired_pair_is_recorded_and_does_not_borrow_or_build(self):
        self.runner.tier_set = ("removed-tree",)
        with patch.object(cpu, "build_wrapper") as build, patch.object(self.runner, "borrow") as borrow:
            record = self.runner.check(self.tip)
        self.assertEqual((record["verdict"], record["faults"]), ("green", []))
        pair = list(log.read(self.runner.log_path))[0]
        self.assertEqual((pair["ev"], pair["status"]), ("pair", "retired"))
        build.assert_not_called()
        borrow.assert_not_called()

    def test_wrapper_build_once_per_tip_and_passing_cpu_records(self):
        with patch.object(cpu, "build_wrapper", return_value=self.home / "wrapper") as build, self.cpu_response():
            self.runner.check(self.tip)
            self.assertEqual(build.call_count, 1)
            self.runner.check(self.advance())
            self.assertEqual(build.call_count, 2)
        tests = [row for row in log.read(self.runner.log_path) if row["ev"] == "test"]
        self.assertTrue(all(row["state"] == "passing" and row["cpu_s"] == 1 for row in tests))


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.slots = self.home / "slots"
        (self.slots / "7").mkdir(parents=True)
        self.enterContext(patch.dict(os.environ, {"FAB_SLOTS": str(self.slots), "FAB_HOST": "b"}))
        self.directory = self.home / "units"
        self.known = {"b": hosts.Host("b", "free@b", ("builder", "after-landing"), slots=7,
                                      after_landing_slot=7)}

    def install(self, known=None, fake=None):
        return after_landing.install(sh=fake or FakeRunner(), directory=self.directory,
                                     known=known or self.known, checkout=Path("/i"))

    def test_the_role_claims_its_slot_and_runs_the_slow_tiers_there(self):
        line = self.install()
        self.assertTrue(line.endswith("fab-after-landing.service enabled and restarting"))
        self.assertEqual(slots.read_claim(7).run, after_landing.RUN)
        text = (self.directory / after_landing.UNIT).read_text()
        self.assertIn('ExecStart=/usr/bin/bash -lc "exec /i/bin/fab after-landing run --slot 7 --live"', text)
        self.assertIn("TimeoutStopSec=2h\n", text)
        self.assertIn("after-landing.stop", text)
        self.install()  # the claim it already holds is kept
        self.assertEqual(slots.read_claim(7).run, after_landing.RUN)

    def test_a_slot_held_by_a_run_installs_nothing(self):
        slots.claim(7, "draft/a-1", "draft/a")
        with self.assertRaisesRegex(ValueError, "held by draft/a-1"):
            self.install()
        self.assertFalse((self.directory / after_landing.UNIT).exists())

    def test_a_machine_without_the_role_claims_nothing(self):
        builder = {"b": hosts.Host("b", "free@b", ("builder",), slots=7)}
        self.assertIn("nothing to do", self.install(builder))
        self.assertIsNone(slots.read_claim(7))

    def test_main_install_prints_its_line(self):
        out = io.StringIO()
        with patch.object(after_landing, "install", return_value="done"), contextlib.redirect_stdout(out):
            self.assertEqual(after_landing.main(["install"]), 0)
        self.assertEqual(out.getvalue(), "done\n")



class ImportedTest(unittest.TestCase):
    def test_runs_keep_reds_and_leave_pair_details_on_the_machine(self):
        key = nextest.Case("qa-jig", "b", "t1", "", "").key
        run = {"ts": "t", "ev": "run", "tip": "x", "verdict": "red", "new": 0,
               "standing": 1, "reds": [key], "commits": 2, "pairs": ["p"], "freed": 3}
        self.assertEqual(after_landing.imported(run), {"ev": "tiers.run", "tip": "x",
                                                       "verdict": "red", "new": 0,
                                                       "standing": 1, "reds": [key], "commits": 2})

    def test_new_and_unattributed_reds_keep_their_evidence(self):
        key = nextest.Case("qa-jig", "b", "t1", "", "").key
        for state in ("new", "unattributed"):
            with self.subTest(state=state):
                red = dict(tip="x", key=key, state=state, profile="qa-jig", binary="b",
                           test="t1", error="assertion failed", branches=["d/a"], log="l", rerun="r")
                entry = dict(red, ev="test", ts="t", cpu_s=1, good="old")
                self.assertEqual(after_landing.imported(entry), dict(red, ev="tiers.red"))
                self.assertEqual(entry["ev"], "test")

    def test_recovered_tests_keep_only_their_identity(self):
        identity = dict(tip="x", key=nextest.Case("qa-jig", "b", "t1", "", "").key,
                        profile="qa-jig", binary="b", test="t1")
        entry = dict(identity, ev="test", state="recovered", branches=["d/a"], log="l",
                     rerun="", error="", cpu_s=1)
        self.assertEqual(after_landing.imported(entry), dict(identity, ev="tiers.recovered"))

    def test_older_records_omit_missing_fields(self):
        self.assertEqual(after_landing.imported(dict(ev="run", tip="x", verdict="green")),
                         dict(ev="tiers.run", tip="x", verdict="green"))
        for state, event in (("new", "tiers.red"), ("unattributed", "tiers.red"),
                             ("recovered", "tiers.recovered")):
            with self.subTest(state=state):
                entry = dict(ev="test", state=state, tip="x", profile="qa-jig", binary="b", test="t1")
                expected = dict(ev=event, tip="x", profile="qa-jig", binary="b", test="t1")
                if state != "recovered":
                    expected["state"] = state
                self.assertEqual(after_landing.imported(entry), expected)

    def test_other_records_stay_on_the_machine(self):
        for state in ("standing", "passing", "flake", "starved", "unobserved"):
            with self.subTest(state=state):
                self.assertIsNone(after_landing.imported(dict(ev="test", state=state)))
        for event in ("pair", "error"):
            with self.subTest(event=event):
                self.assertIsNone(after_landing.imported(dict(ev=event, error="boom")))


if __name__ == "__main__":
    unittest.main()
