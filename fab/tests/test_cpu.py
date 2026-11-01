"""CPU integration uses temporary records/config and fake services, never a build."""
import json
import signal
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fab import atomic, cpu, nextest, tiers, channel, after_landing
from fab.sh import Result
from fab.tests.support import FakeRunner, tmp_home


# The collector seam: its summary function calls its global summarizer just as the
# checkout API does. These tests exercise fab's reconciliation, without importing a
# particular checkout or compiling its C collector.
COLLECTOR = '''
import json
from pathlib import Path

def summarize_records(items, pair, limits, run, timeouts, failures):
    return dict(timeouts=sorted(timeouts), failures=failures, run=run, limits=limits)

def summary(directory, limits=None, pair=None):
    data = json.loads((Path(directory) / 'fixture.json').read_text())
    run = json.loads((Path(directory) / 'run.json').read_text())
    return summarize_records(data['items'], pair, limits, run,
                             {tuple(key) for key in data['timeouts']}, data['failures'])
'''


class CpuTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.repo = self.home / "repo"
        self.repo.mkdir()
        self.directory = self.home / "cpu"
        self.directory.mkdir()
        self.collector = {}
        exec(COLLECTOR, self.collector)

    def fixture(self, items, *, output="", failures=(), timeouts=(), starved=False):
        atomic.write(self.directory / "fixture.json", json.dumps(dict(items=items, failures=failures, timeouts=timeouts)))
        atomic.write(self.directory / "run.json", json.dumps(dict(starved=starved, wall_s=5)))
        atomic.write(self.directory / "heavy-output.txt", output)

    def item(self, name="one", **extra):
        return dict(profile="qa-tree", binary_id="binary", test_name=name, attempt=1,
                    pending=False, signal=None, exit_code=0, **extra)

    def test_global_timeout_stopped_attempt_starves_observed_assertion_stays_red(self):
        stopped = self.item("stopped")
        stopped.update(signal=signal.SIGTERM, exit_code=None)
        failed = self.item("assertion")
        failed["exit_code"] = 1
        self.fixture([stopped, failed], output="  Cancelling due to global timeout: 2 tests still running\n",
                     failures=["binary stopped", "binary assertion"])
        result = cpu.read(self.directory, "qa-tree", self.collector)
        self.assertTrue(result["global_timeout"])
        self.assertTrue(result["run"]["starved"])
        self.assertEqual(result["timeouts"], [("qa-tree", "binary", "stopped", 1)])
        self.assertEqual(result["failures"], ["binary assertion"])
        self.assertEqual(result["limits"], {})

    def test_pending_retry_cannot_erase_observed_failure_for_same_test(self):
        first = self.item()
        first["exit_code"] = 1
        pending = self.item()
        pending.update(attempt=2, pending=True, exit_code=None)
        self.fixture([first, pending], failures=["binary one"], starved=True)
        result = cpu.read(self.directory, "qa-tree", self.collector)
        self.assertEqual(result["failures"], ["binary one"])
        self.assertIn(("qa-tree", "binary", "one", 2), result["timeouts"])

    def test_bad_exit_without_cancellation_is_not_starved(self):
        stopped = self.item()
        stopped.update(signal=signal.SIGTERM, exit_code=None)
        self.fixture([stopped], output="test output mentioning global timeout\n", failures=["binary one"])
        result = cpu.read(self.directory, "qa-tree", self.collector)
        self.assertEqual(result["timeouts"], [])
        self.assertEqual(result["failures"], ["binary one"])
        self.assertFalse(result["global_timeout"])

    def test_timeout_junit_and_collector_starved_pass_and_unstarted_inventory(self):
        atomic.write(self.directory / "junit.xml", '''<testsuites><testsuite name="binary">
          <testcase name="timeout"><failure type="test timeout"/></testcase>
          <testcase name="pass-policy"/>
          <testcase name="assertion"><failure>assertion</failure></testcase>
          </testsuite></testsuites>''')
        atomic.write(self.directory / "inventory.json", json.dumps([
            ["pkg", "binary", name] for name in ("timeout", "pass-policy", "assertion", "not-started")]))
        measured = dict(tests=[dict(binary_id="binary", test_name="pass-policy", starved=1),
                               dict(binary_id="binary", test_name="assertion", starved=1)],
                        failures=["binary assertion"])
        cases = {case.test: case.result for case in cpu.cases(self.directory, "qa-tree", measured)}
        self.assertEqual(cases, {"timeout": "starved", "pass-policy": "starved",
                                 "assertion": "fail", "not-started": "skipped"})

    def test_without_junit_only_started_attempts_are_starved_not_passed(self):
        measured = dict(tests=[dict(binary_id="binary", test_name="started", starved=1)], failures=[])
        self.assertEqual(cpu.cases(self.directory, "qa-tree", measured)[0].result, "starved")

    def test_timeout_junit_needs_no_confirmation(self):
        for tag in ("failure", "error"):
            atomic.write(self.home / "junit.xml", f'<testsuites><testsuite name="b"><testcase name="t">'
                         f'<{tag} type="test timeout"/></testcase></testsuite></testsuites>')
            case, = nextest.junit(self.home / "junit.xml", "qa")
            self.assertEqual(case.result, "starved")
            self.assertEqual(after_landing.state(case.result, None, None), "starved")

    def test_budget_optional_values_validate_no_defaults_and_keep_retired_diagnostics(self):
        self.assertEqual(cpu.budgets(self.repo), ({}, {}))
        path = self.repo / cpu.BUDGETS
        atomic.write(path, '[retired-tree]\ncpu_suite_s=2\n[after-landing]\ncpu_total_s=3\n')
        self.assertEqual(cpu.budgets(self.repo), ({"cpu_total_s": 3}, {"retired-tree": {"cpu_suite_s": 2}}))
        for key in cpu.TOTAL_KEYS:
            for value in ("0", "-1", "true", "inf", "nan", '"3"', "[]"):
                atomic.write(path, f'[after-landing]\n{key}={value}\n')
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    cpu.budgets(self.repo)
        atomic.write(path, '[after-landing]\ncpu_suite_s=1\n')
        with self.assertRaises(ValueError):
            cpu.budgets(self.repo)

    def test_wall_cap_keeps_shorter_existing_limit_and_slow_timeout(self):
        path = self.home / "nextest.toml"
        text = '[profile.default]\nglobal-timeout="2m"\n[profile.qa-tree]\nslow-timeout={period="4s",terminate-after=3}\n'
        # Only serialization is fake: capture the actual data the worker writes.
        data = []
        def serialize(value):
            data.append(value)
            return "private serialized config"
        fake = dict(toml_config=serialize)
        for cap, expected in ((5, "5.000000000s"), (300, "120.000000000s")):
            atomic.write(path, text)
            cpu.cap_wall(path, "qa-tree", cap, fake)
            self.assertEqual(data[-1]["profile"]["qa-tree"]["global-timeout"], expected)
            self.assertEqual(data[-1]["profile"]["qa-tree"]["slow-timeout"]["terminate-after"], 3)
        atomic.write(path, text)
        cpu.cap_wall(path, "qa-tree", None, fake)
        self.assertEqual(path.read_text(), text)
        self.assertEqual(cpu.seconds("1m 2.5s"), 62.5)

    def test_collect_is_scoped_by_caller_no_implicit_timeout_and_requires_summary(self):
        sh = FakeRunner()
        def done(call):
            request = json.loads(call.input)
            self.assertEqual(request["command"], ["heavy", "--gate", "cargo", "nextest", "run", "-p", "pkg"])
            self.assertEqual(request["profile"], "fuzzy")
            atomic.write(self.directory / "summary.json", '{"suite": {"cpu_s": 1}}')
            return Result(0, "accounted\n")
        sh.on([cpu.sys.executable], done)
        code, result = cpu.collect(self.repo, "fuzzy", ["heavy", "--gate", "cargo", "nextest", "run", "-p", "pkg"],
                                   self.directory, self.home / "wrapper", sh=sh)
        self.assertEqual((code, result["suite"]["cpu_s"]), (0, 1))
        self.assertIn("-B", sh.calls[0].argv)
        (self.directory / "summary.json").unlink()
        with self.assertRaisesRegex(ValueError, "CPU collector exit 75"):
            cpu.collect(self.repo, "fuzzy", [], self.directory, self.home / "wrapper",
                        sh=FakeRunner().on([cpu.sys.executable], Result(75, err="disk")))

    def test_page_import_keeps_newest_cpu_counts_budgets_and_possible_hangs(self):
        record = dict(ev="run", tip="tip", verdict="green", cpu_s=2, wall_s=5, starved=1,
                      wall_starved=True, possible_hangs=["qa b t"], budget=["wall_hard_s=5s"],
                      over_budget=[])
        event = after_landing.imported(record)
        lines = channel.landing_lines([dict(ev="tiers.run", cpu_s=900), event])
        self.assertIn("CPU 2.000s, wall 5.000s, starved 1", lines[0])
        self.assertIn("wall limit: starved", lines[0])
        self.assertEqual(lines[1:], ["budget: wall_hard_s=5s", "possible hang: qa b t"])

    def test_prior_bad_signal_stays_red_when_another_test_hits_global_timeout(self):
        earlier, stopped = self.item("earlier"), self.item("stopped")
        for item in (earlier, stopped):
            item.update(signal=signal.SIGKILL, exit_code=None)
        self.fixture([earlier, stopped], failures=["binary earlier", "binary stopped"],
                     output="     SIGKILL [  1.000s] (1/2) binary earlier\n"
                            "  Cancelling due to global timeout: 1 test still running\n"
                            "     SIGKILL [  5.000s] (2/2) binary stopped\n")
        result = cpu.read(self.directory, "qa-tree", self.collector)
        self.assertEqual(result["failures"], ["binary earlier"])
        self.assertEqual(result["timeouts"], [("qa-tree", "binary", "stopped", 1)])

    def test_stale_collector_directory_is_refused_before_starting_a_command(self):
        atomic.write(self.directory / "summary.json", '{"suite":{"cpu_s":999}}')
        fake = FakeRunner()
        with self.assertRaisesRegex(ValueError, "CPU directory must be empty"):
            cpu.collect(self.repo, "fuzzy", [], self.directory, self.home / "wrapper", sh=fake)
        self.assertEqual(fake.calls, [])

    def test_wrapper_build_is_heavy_and_a_failed_build_is_explicit(self):
        fake = FakeRunner()
        wrapper = cpu.build_wrapper(self.repo, self.directory, sh=fake)
        self.assertEqual(fake.calls[0].argv, ["heavy", "cc", "-std=c11", "-O2", "-static",
                         "-Wall", "-Wextra", "-Werror", "tools/tiers/cpu-wrapper.c", "-o", str(wrapper)])
        with self.assertRaisesRegex(ValueError, "CPU wrapper: exit 75"):
            cpu.build_wrapper(self.repo, self.directory, sh=FakeRunner().on(["heavy"], Result(75)))

    def test_prerequisite_failure_prevents_cpu_execution(self):
        pair = tiers.Pair("qa-tree", "qa", "tree", ("pkg",), (tiers.Binary("pkg", "helper"),))
        fake = FakeRunner().on(["env"], Result(75, err="disk"))
        with patch.object(cpu, "collect") as collect:
            code, measured = cpu.run_pair(self.repo, pair, [], self.home / "pair.log",
                directory=self.directory, wrapper=self.home / "wrapper", wall_hard_s=None, sh=fake)
        self.assertEqual((code, measured), (2, {}))
        collect.assert_not_called()

    def test_worker_uses_prepare_inventory_execute_and_verified_read_without_budgets(self):
        namespace = dict(atomic=atomic)
        exec(COLLECTOR, namespace)
        exec('''
def prepare(directory, profile, wrapper, config):
    directory.mkdir()
    atomic.write(directory / 'repository.toml', config.read_text())
    return ['--config-file', str(directory / 'repository.toml')]

def execute(command, env, directory, profile, limits):
    assert limits == {}
    assert '--retries' in command and command[command.index('--retries') + 1] == '0'
    assert command[:4] == ['heavy', 'cargo', 'nextest', 'run']
    atomic.write(directory / 'run.json', json.dumps(dict(starved=starved, wall_s=2, returncode=returncode)))
    atomic.write(directory / 'fixture.json', json.dumps(dict(items=[], timeouts=[], failures=[])))
    atomic.write(directory / 'heavy-output.txt', '')
    summary(directory, {}, profile)  # execute calls the installed adapter, too
    return 0
''', namespace)
        def summarize(items, pair, limits, run, timeouts, failures):
            return dict(suite=dict(cpu_s=1, wall_s=2, starved_run=namespace["starved"], starved=0),
                        tests=[], failures=namespace["failures"], over_budget=[])
        namespace['summarize_records'] = summarize
        config = self.home / "config.toml"
        atomic.write(config, '[profile.qa-tree]\n')
        listing = SimpleNamespace(returncode=0, stdout=json.dumps({"rust-suites": {"binary": {
            "package-name": "pkg", "binary-id": "b", "testcases": {
                "t": {"filter-match": {"status": "matches"}}}}}}), stderr="")
        directory = self.home / "fresh-cpu"
        request = dict(profile="qa-tree", directory=str(directory), wrapper=str(self.home / "wrapper"),
                       wall_hard_s=None, command=["heavy", "cargo", "nextest", "run", "-p", "pkg",
                                                "--config-file", str(config), "--no-fail-fast"])
        for raw, starved, failures, expected in ((0, False, [], 0), (100, True, [], 0),
                (75, True, [], 75), (102, True, [], 102), (100, True, ["b t"], 100)):
            namespace.update(returncode=raw, starved=starved, failures=failures)
            request["directory"] = str(self.home / f"fresh-{raw}-{bool(failures)}")
            with self.subTest(raw=raw, failures=failures), \
                    patch.object(cpu.runpy, "run_path", return_value=namespace), \
                    patch.object(cpu.subprocess, "run", return_value=listing) as service:
                self.assertEqual(cpu.worker(request), expected)
        directory = Path(request["directory"])
        self.assertEqual(json.loads((directory / "summary.json").read_text())["suite"]["cpu_s"], 1)
        self.assertEqual(json.loads((directory / "inventory.json").read_text()), [["pkg", "b", "t"]])
        self.assertEqual(service.call_args.args[0][:4], ["heavy", "cargo", "nextest", "list"])
