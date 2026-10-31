import unittest

from fab import gate, reds
from fab.tests.landing_checks import ChecksTestCase, FakeNextest, alone, receipt
from fab.tests.support import tmp_home

BATCH = "20261031T000000Z"
WIRE = ("pkg::wire", "round_trip")
DEFAULT = gate.Step("default", ("heavy", "--gate", "cargo", "nextest", "run", "-p", "pkg",
                                "--no-fail-fast"), "/repo")


class ExemplarTest(ChecksTestCase):
    @unittest.skip("pending: agents-rebuild/landing-checks")
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


if __name__ == "__main__":
    unittest.main()
