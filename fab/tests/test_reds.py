import tomllib
import unittest
from dataclasses import replace
from unittest.mock import patch

from fab import atomic, gate, nextest, reds, tiers
from fab.tests.landing_checks import ChecksTestCase, FakeNextest, alone, junit_xml, receipt
from fab.sh import Result
from fab.tests.support import tmp_home

BATCH = "20261031T000000Z"
WIRE = ("pkg::wire", "round_trip")
DEFAULT = gate.Step("default", ("heavy", "--gate", "cargo", "nextest", "run", "-p", "pkg",
                                "--no-fail-fast"), "/repo")


class ExemplarTest(ChecksTestCase):
    def test_a_test_its_precheck_passed_fails_in_the_batch_and_passes_alone(self):
        with tmp_home() as home:
            repo, directory = home / "repo", home / "fab" / "queue"
            repo.mkdir()
            detail = directory / f"{BATCH}.log"
            steps, reports = reds.with_junit([DEFAULT], repo, directory, BATCH)
            config = directory / f"{BATCH}-default.toml"
            self.assertEqual(steps[0].argv, (*DEFAULT.argv, "--config-file", str(config)))
            self.assertEqual(reports, {"default": directory / f"{BATCH}-default.xml"})
            nextest = FakeNextest({None: [(*WIRE, "fail"), ("pkg", "unit", "pass")],
                                   alone(*WIRE): [(*WIRE, "pass")]})
            failed, = gate.run_steps(steps, detail, sh=nextest)
            self.assertFalse(failed.green)

            verdict = reds.classify(repo, failed, reports["default"], [receipt()], detail,
                                    name=BATCH, sh=nextest)
            self.assertCollateral(verdict, "pkg::wire round_trip")
            retry, = verdict.retries
            self.assertEqual((retry.name, retry.green), ("retry:default", True))
            self.assertEqual(nextest.calls[-1][-4:], [
                "--config-file", str(directory / f"{BATCH}-default-1.toml"), "-E", alone(*WIRE)])

            # A precheck that never selected the package says nothing of the test.
            verdict = reds.classify(repo, failed, reports["default"],
                                    [receipt(selection=("other",))], detail, name=BATCH,
                                    sh=nextest)
            self.assertStands(verdict, "pkg::wire round_trip not prechecked",
                              "pkg::wire round_trip")
            self.assertEqual(len(nextest.calls), 2)


CONFIG = """[profile.default]
retries = 0
[[profile.default.overrides]]
filter = 'test(slow)'
threads-required = 2
[profile.fuzzy]
retries = 1
"""


class RedsTest(ChecksTestCase):
    def setUp(self):
        context = tmp_home()
        self.home = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        self.repo = self.home / "repo"
        self.repo.mkdir()
        self.directory = self.home / "queue"
        self.report = self.directory / "batch-default.xml"
        self.detail = self.directory / "batch.log"
        self.failed = gate.StepResult("default", DEFAULT.argv, tiers.TEST_FAILED, False, 1.0)
        self.case = nextest.Case("default", *WIRE, "fail", "assertion failed")

    def _config(self, text=CONFIG):
        atomic.write(self.repo / tiers.NEXTEST_CONFIG, text)

    def _classify(self, cases=((*WIRE, "fail"),), *, runner=None, receipts=None, failed=None):
        atomic.write(self.report, junit_xml(cases))
        return reds.classify(self.repo, failed or self.failed, self.report,
                             [receipt()] if receipts is None else receipts, self.detail,
                             name="batch", sh=runner or self.runner)

    def _stands(self, reason, cases=((*WIRE, "fail"),), **kwargs):
        self.runner = FakeNextest({})
        verdict = self._classify(cases, **kwargs)
        self.assertStands(verdict, reason,
                          *(f"{binary} {test}" for binary, test, result in cases if result == "fail"))
        self.assertEqual((self.runner.calls, verdict.retries), ([], ()))

    def test_overlay_preserves_repository_config_and_adds_junit(self):
        self._config()
        actual = tomllib.loads(reds.overlay_text(self.repo, "fuzzy", self.report))
        expected = tomllib.loads(CONFIG)
        expected["profile"]["fuzzy"]["junit"] = {
            "path": str(self.report), "store-success-output": False, "store-failure-output": True}
        self.assertEqual(actual, expected)

    def test_overlay_adds_default_when_config_is_missing(self):
        actual = tomllib.loads(reds.overlay_text(self.repo, "default", self.report))
        self.assertEqual(actual["profile"]["default"]["junit"]["path"], str(self.report))

    def test_overlay_adds_default_when_only_fuzzy_is_configured(self):
        self._config('[profile.fuzzy]\nretries = 1\n')
        actual = tomllib.loads(reds.overlay_text(self.repo, "default", self.report))
        self.assertEqual(actual["profile"]["fuzzy"], {"retries": 1})
        self.assertIn("junit", actual["profile"]["default"])

    def test_overlay_refuses_missing_fuzzy_profile(self):
        with self.assertRaisesRegex(ValueError, "unknown nextest profile: fuzzy"):
            reds.overlay_text(self.repo, "fuzzy", self.report)

    def test_with_junit_preserves_order_and_only_changes_test_steps(self):
        self._config()
        atomic.write(self.report, "stale")
        fmt = gate.Step("fmt", ("fmt",), str(self.repo))
        fuzzy = gate.Step("fuzzy", (*DEFAULT.argv, "--profile", "fuzzy"), str(self.repo))
        steps, reports = reds.with_junit([fmt, DEFAULT, fuzzy], self.repo, self.directory, "batch")
        self.assertEqual([step.name for step in steps], ["fmt", "default", "fuzzy"])
        self.assertEqual(steps[0], fmt)
        self.assertFalse(self.report.exists())
        self.assertEqual(set(reports), {"default", "fuzzy"})
        for step in steps[1:]:
            config = self.directory / f"batch-{step.name}.toml"
            expected = DEFAULT if step.name == "default" else fuzzy
            self.assertEqual(step.argv, (*expected.argv, "--config-file", str(config)))
            self.assertEqual(step.cwd, expected.cwd)
            text = tomllib.loads(config.read_text())
            self.assertEqual(text["profile"][step.name]["junit"]["path"], str(reports[step.name]))

    def test_with_junit_leaves_unparseable_config_steps_without_reports(self):
        self._config('[')
        atomic.write(self.report, "stale")
        steps, reports = reds.with_junit([DEFAULT], self.repo, self.directory, "batch")
        self.assertEqual((steps, reports), ([DEFAULT], {}))
        self.assertFalse(self.report.exists())
        self.assertFalse(self.report.with_suffix(".toml").exists())

    def test_suspect_requires_every_branch_to_cover_the_case(self):
        self.assertTrue(reds.suspect(self.case, "default", [receipt(), receipt(selection="full")]))
        for values in ([], [None], [receipt(), receipt(selection=("other",))],
                       [receipt(steps=("fuzzy",))], [receipt(outcome="red")]):
            with self.subTest(receipts=values):
                self.assertFalse(reds.suspect(self.case, "default", values))

    def test_retry_replaces_own_config_preserving_scope_profile_and_lane(self):
        argv = (*DEFAULT.argv, "--profile", "fuzzy", "--config-file", "/old.toml")
        failed = replace(self.failed, name="fuzzy", argv=argv)
        step = reds.retry_step(self.repo, failed, self.case, self.report.with_suffix(".toml"))
        self.assertEqual(step, gate.Step("retry:fuzzy", (*argv[:-2], "--config-file",
                         str(self.report.with_suffix(".toml")), "-E", alone(*WIRE)), str(self.repo)))

    def test_retry_refuses_unsafe_identity(self):
        with self.assertRaisesRegex(ValueError, "identity not expressible"):
            reds.retry_step(self.repo, self.failed, replace(self.case, test="bad(name)"), self.report)

    def test_non_test_step_stands_without_reading_junit(self):
        with patch("fab.reds.nextest.junit", side_effect=AssertionError("JUnit read")):
            self._stands("step fmt", cases=(), failed=replace(self.failed, name="fmt"))

    def test_non_test_failure_exit_stands_without_reading_junit(self):
        with patch("fab.reds.nextest.junit", side_effect=AssertionError("JUnit read")):
            self._stands("exit 124", cases=(), failed=replace(self.failed, code=124))

    def test_missing_junit_path_stands_without_running(self):
        runner = FakeNextest({})
        verdict = reds.classify(self.repo, self.failed, None, [receipt()], self.detail,
                                name="batch", sh=runner)
        self.assertStands(verdict, "no junit")
        self.assertEqual((runner.calls, verdict.retries), ([], ()))

    def test_unreadable_junit_stands_without_running(self):
        runner = FakeNextest({})
        verdict = reds.classify(self.repo, self.failed, self.report, [receipt()], self.detail,
                                name="batch", sh=runner)
        self.assertTrue(verdict.reason.startswith("junit: invalid/missing nextest JUnit:"))
        self.assertEqual((verdict.tests, runner.calls, verdict.retries), ((), [], ()))

    def test_no_failed_tests_stands(self):
        self._stands("no failed test", cases=((*WIRE, "pass"),))

    def test_more_than_retry_limit_stands(self):
        cases = [("pkg", f"test_{n}", "fail") for n in range(reds.RETRIES + 1)]
        self._stands(f"{len(cases)} tests failed", cases=cases)

    def test_no_receipts_stands_without_running(self):
        self._stands("pkg::wire round_trip not prechecked", receipts=[])

    def test_one_uncovered_branch_stands_before_any_retry(self):
        self._stands("pkg::wire round_trip not prechecked",
                     receipts=[receipt(), receipt(selection=("other",))])

    def test_later_uncovered_test_stands_before_any_retry(self):
        self._stands("other unit not prechecked", cases=((*WIRE, "fail"), ("other", "unit", "fail")))

    def test_both_failed_tests_pass_alone_and_outputs_join_detail_log(self):
        second = ("pkg", "unit")
        fake = FakeNextest({alone(*WIRE): [(*WIRE, "pass")], alone(*second): [(*second, "pass")]})
        atomic.write(self.detail, "batch output\n")
        atomic.write(self.directory / "batch-default-1.xml", "stale")

        def runner(argv, **kwargs):
            result = fake(argv, **kwargs)
            return Result(result.code, f"output {argv[-1]}\n", f"stderr {argv[-1]}\n")

        verdict = self._classify([(*WIRE, "fail"), (*second, "fail")], runner=runner)
        self.assertCollateral(verdict, "pkg::wire round_trip", "pkg unit")
        self.assertEqual(len(verdict.retries), 2)
        self.assertEqual([argv[-1] for argv in fake.calls], [alone(*WIRE), alone(*second)])
        content = self.detail.read_text()
        self.assertTrue(content.startswith("batch output\n"))
        for expression in (alone(*WIRE), alone(*second)):
            self.assertIn(f"output {expression}\n", content)
            self.assertIn(f"stderr {expression}\n", content)

    def test_first_test_failing_alone_stops_before_second(self):
        fake = FakeNextest({alone(*WIRE): [(*WIRE, "fail")]})
        verdict = self._classify([(*WIRE, "fail"), ("pkg", "unit", "fail")], runner=fake)
        self.assertStands(verdict, "pkg::wire round_trip failed alone", "pkg::wire round_trip", "pkg unit")
        self.assertEqual((len(fake.calls), len(verdict.retries)), (1, 1))

    def test_retry_with_another_identity_stands(self):
        fake = FakeNextest({alone(*WIRE): [("pkg", "other", "pass")]})
        verdict = self._classify(runner=fake)
        self.assertStands(verdict, "retry: pkg::wire round_trip: different test", "pkg::wire round_trip")
        self.assertEqual(len(verdict.retries), 1)

    def test_retry_with_another_case_count_stands(self):
        fake = FakeNextest({alone(*WIRE): []})
        verdict = self._classify(runner=fake)
        self.assertStands(verdict, "retry: pkg::wire round_trip: 0 cases", "pkg::wire round_trip")

    def test_retry_with_another_exit_stands(self):
        fake = FakeNextest({}, codes={alone(*WIRE): 124})
        verdict = self._classify(runner=fake)
        self.assertStands(verdict, "retry: pkg::wire round_trip: exit 124", "pkg::wire round_trip")
        self.assertEqual(len(verdict.retries), 1)

    def test_retry_with_missing_junit_stands(self):
        atomic.write(self.directory / "batch-default-1.xml", junit_xml([(*WIRE, "pass")]))
        fake = FakeNextest({})
        verdict = self._classify(runner=fake)
        self.assertTrue(verdict.reason.startswith("retry: pkg::wire round_trip: invalid/missing"))
        self.assertEqual(len(verdict.retries), 1)

    def test_retry_skipped_with_exit_zero_stands(self):
        fake = FakeNextest({alone(*WIRE): [(*WIRE, "skipped")]})
        verdict = self._classify(runner=fake)
        self.assertStands(verdict, "retry: pkg::wire round_trip: exit 0, skipped", "pkg::wire round_trip")

    def test_retry_inconsistent_exit_and_case_stands(self):
        for code, result in ((0, "fail"), (tiers.TEST_FAILED, "pass")):
            with self.subTest(code=code, result=result):
                fake = FakeNextest({alone(*WIRE): [(*WIRE, result)]}, codes={alone(*WIRE): code})
                verdict = self._classify(runner=fake)
                self.assertStands(verdict, f"retry: pkg::wire round_trip: exit {code}, {result}",
                                  "pkg::wire round_trip")

    def test_retry_config_value_error_stands_without_running(self):
        self._config('[')
        fake = FakeNextest({})
        verdict = self._classify(runner=fake)
        self.assertTrue(verdict.reason.startswith("retry: pkg::wire round_trip:"))
        self.assertEqual((fake.calls, verdict.retries), ([], ()))

    def test_retry_unsafe_filter_stands_without_running(self):
        fake = FakeNextest({})
        verdict = self._classify([("pkg", "bad(name)", "fail")], runner=fake)
        self.assertStands(verdict, "retry: pkg bad(name): identity not expressible as an exact filter",
                          "pkg bad(name)")
        self.assertEqual((fake.calls, verdict.retries), ([], ()))


if __name__ == "__main__":
    unittest.main()
