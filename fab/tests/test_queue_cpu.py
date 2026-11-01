"""Queue CPU accounting against temporary HOME, fake nextest JUnit and records."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from fab import atomic, cpu, gate, log, nextest, queue, queue_cpu
from fab.sh import Result
from fab.tests.landing_checks import FakeNextest, MAIN, TIP
from fab.tests.support import FakeRunner, tmp_home


class QueueCpuTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.repo = self.home / "repo"
        atomic.write(self.repo / ".config/nextest.toml", '[profile.default]\n[profile.fuzzy]\n')
        self.detail = self.home / "queue/batch.log"

    def steps(self, full=False):
        return gate.check_steps(self.repo, "full" if full else {"smith-codecs-world", "jig-store-world"},
                                [], None, lane="gate")

    def run_checks(self, cases, *, full=False, code=None, steps=None):
        self.fake = FakeNextest({None: cases}, codes={} if code is None else {None: code})
        self.record = {"selection": "full" if full else ["smith-codecs-world", "jig-store-world"]}
        return queue_cpu.run_steps(self.steps(full) if steps is None else steps,
                                   self.detail, self.record, sh=self.fake)

    def groups(self):
        return [json.loads(value) for value in self.record["cpu_trees"]]

    def test_starved_green_both_profiles_original_selection_lane_and_one_wrapper(self):
        with patch.object(cpu, "build_wrapper", wraps=cpu.build_wrapper) as build:
            outcomes, reports = self.run_checks([("not-a-package::suite", "slow", "starved"),
                                                ("not-a-package::suite", "ok", "pass")])
        self.assertEqual(build.call_count, 1)
        self.assertEqual(build.call_args.kwargs["lane"], "gate")
        self.assertTrue(all(step.green for step in outcomes))
        self.assertEqual([step.name for step in outcomes], ["clippy", "build", "default", "fuzzy"])
        self.assertEqual(set(reports), {"default", "fuzzy"})
        for command in self.fake.calls:
            self.assertEqual(command[:5], ["heavy", "--gate", "cargo", "nextest", "run"])
            self.assertIn("smith-codecs-world", command)
            self.assertIn("jig-store-world", command)
        smith = [g for g in self.groups() if g["tree"] == "smith"]
        self.assertEqual([(g["cpu_s"], g["test_wall_s"], g["tests"], g["passed"], g["starved"], g["full"])
                          for g in smith], [(4, 8, 2, 1, 1, False)] * 2)
        self.assertTrue(all(g["verdict"] is None and not g["budget"] for g in self.groups()))
        self.assertIn("starved 1", self.detail.read_text())
        self.assertEqual(len(list(self.detail.with_suffix("").glob("*/summary.json"))), 2)
        # The actual wrapper invocation is checked separately against the runner seam.
        fake = FakeRunner()
        cpu.build_wrapper(self.repo, self.home, lane="gate", sh=fake)
        self.assertEqual(fake.calls[0].argv[:3], ["heavy", "--gate", "cc"])

    def test_failure_red_even_alongside_starvation_and_no_fuzzy_after_red(self):
        outcomes, reports = self.run_checks([("b", "slow", "starved"), ("b", "assertion", "fail")])
        self.assertFalse(outcomes[-1].green)
        self.assertEqual(outcomes[-1].code, 100)
        self.assertEqual(set(reports), {"default"})
        smith = next(g for g in self.groups() if g["tree"] == "smith")
        self.assertEqual((smith["failed"], smith["starved"]), (1, 1))

    def test_other_exit_red_even_with_starvation(self):
        outcomes, _ = self.run_checks([("b", "slow", "starved")], code=102)
        self.assertFalse(outcomes[-1].green)
        self.assertEqual(outcomes[-1].code, 102)

    def test_collector_starved_success_policy_is_counted_without_junit_timeout(self):
        fake = FakeNextest({None: [("b", "slow", "pass")]})
        original = fake.collect
        def collect(request, repo):
            result = original(request, repo)
            path = Path(request["directory"]) / "summary.json"
            measured = json.loads(path.read_text())
            measured["tests"][0]["starved"] = 1
            atomic.write(path, json.dumps(measured))
            return result
        fake.collect = collect
        record = {"selection": "full"}
        outcomes, _ = queue_cpu.run_steps(self.steps(True), self.detail, record, sh=fake)
        self.assertTrue(all(step.green for step in outcomes))
        smith = next(json.loads(g) for g in record["cpu_trees"] if json.loads(g)["tree"] == "smith")
        self.assertEqual((smith["passed"], smith["starved"]), (0, 1))

    def test_set_budget_full_total_and_partial_test_report_over_both_stay_green(self):
        atomic.write(self.repo / cpu.BUDGETS, '[gate.smith.default]\ncpu_suite_s = 1\n'
                     '[gate.smith.fuzzy]\ncpu_test_s = 1\n')
        for full in (False, True):
            with self.subTest(full=full):
                detail = self.detail.with_name(f"batch-{full}.log")
                self.detail = detail
                outcomes, _ = self.run_checks([("b", "t", "pass")], full=full)
                self.assertTrue(all(step.green for step in outcomes))
                groups = {g["profile"]: g for g in self.groups() if g["tree"] == "smith"}
                self.assertEqual(groups["default"]["verdict"], "over" if full else None)
                self.assertEqual(bool(groups["default"]["over"]), full)
                self.assertEqual(groups["fuzzy"]["verdict"], "over")
                self.assertIn("over test b t", detail.read_text())
                if full:
                    self.assertIn("over suite", detail.read_text())

    def test_red_classifier_report_uses_reconciled_starvation_and_keeps_raw_junit(self):
        fake = FakeNextest({None: [("b", "cancelled", "fail"), ("b", "assertion", "fail")]})
        original = fake.collect
        def collect(request, repo):
            result = original(request, repo)
            path = Path(request["directory"]) / "summary.json"
            measured = json.loads(path.read_text())
            measured["failures"] = ["b assertion"]
            measured["tests"][0]["starved"] = 1
            measured["suite"]["starved_run"] = True
            atomic.write(path, json.dumps(measured))
            return result
        fake.collect = collect
        outcomes, reports = queue_cpu.run_steps(self.steps(True), self.detail, {"selection": "full"}, sh=fake)
        self.assertFalse(outcomes[-1].green)
        cases = nextest.junit(reports["default"], "default")
        self.assertEqual([(c.test, c.result) for c in cases], [("cancelled", "starved"), ("assertion", "fail")])
        raw = nextest.junit(reports["default"].with_name("junit.xml"), "default")
        self.assertTrue(all(c.result == "fail" for c in raw))

    def test_empty_selections_keep_nextest_no_tests_green(self):
        outcomes, _ = self.run_checks([], code=4)
        self.assertTrue(all(step.green for step in outcomes))
        self.assertEqual([step.name for step in outcomes][-2:], ["default", "fuzzy"])
        self.assertTrue(all(g["tests"] == 0 for g in self.groups()))

    def test_cancelled_run_with_no_started_tests_green_without_invented_passes(self):
        fake = FakeNextest({None: []})
        original = fake.collect
        def collect(request, repo):
            original(request, repo)
            directory = Path(request["directory"])
            atomic.write(directory / "inventory.json", '[["smith", "b", "not-started"]]')
            atomic.write(directory / "summary.json", json.dumps(dict(tests=[], failures=[],
                         suite=dict(starved_run=True, starved=0))))
            return Result(100)
        fake.collect = collect
        record = {"selection": "full"}
        outcomes, _ = queue_cpu.run_steps(self.steps(True), self.detail, record, sh=fake)
        self.assertTrue(all(step.green for step in outcomes))
        for value in record["cpu_trees"]:
            group = json.loads(value)
            if group["tree"] == "smith":
                self.assertEqual((group["tests"], group["passed"], group["unobserved"]), (0, 0, 1))

    def test_all_tree_patterns_new_packages_and_explicit_boundaries(self):
        packages = {"skein-a-new-crate": "skein", "forgejo-conformance": "skein",
                    "github-conformance": "skein", "smith": "smith", "smith-new": "smith",
                    "jig": "jig", "jig-new": "jig", "temper": "temper", "temper-new": "temper",
                    "git-transcripts": "temper", "fabrig-boundary": "fabrig"}
        for package, expected in packages.items():
            self.assertEqual(queue_cpu.tree(package), expected)
        for package in ("skein", "smithereens", "jigsaw", "temperature", "fabrig-other"):
            with self.assertRaisesRegex(ValueError, "no gate tree"):
                queue_cpu.tree(package)

    def test_mapping_uses_inventory_top_ten_and_unstarted_never_pass(self):
        directory = self.home / "measured"
        inventory = [["jig-new", "unrelated-id", str(i)] for i in range(12)]
        inventory += [["forgejo-conformance", "another-id", "pending"]]
        atomic.write(directory / "inventory.json", json.dumps(inventory))
        tests = [dict(binary_id="unrelated-id", test_name=str(i), cpu_s=i, wall_s=i + 1,
                      starved=0, incomplete=0) for i in range(12)]
        groups = queue_cpu.summarize(directory, "default", dict(tests=tests, failures=[]), True, {})
        jig = next(g for g in groups if g["tree"] == "jig")
        self.assertEqual((jig["cpu_s"], jig["test_wall_s"], jig["tests"]), (66, 78, 12))
        self.assertEqual([t["cpu_s"] for t in jig["top_cpu"]], list(range(11, 1, -1)))
        # Missing JUnit on a stopped run does not invent a pass for measured tests.
        self.assertEqual((jig["passed"], jig["starved"]), (0, 12))
        skein = next(g for g in groups if g["tree"] == "skein")
        self.assertEqual((skein["tests"], skein["unobserved"]), (0, 1))

    def test_invalid_optional_budgets_are_refused_without_touching_other_namespaces(self):
        atomic.write(self.repo / cpu.BUDGETS, '[after-landing]\ncpu_total_s = 10\n[browser-skein]\ncpu_suite_s = 5\n')
        self.assertEqual(queue_cpu.budgets(self.repo), {})
        for text in ('[gate.unknown.default]\n', '[gate.smith.qa]\n',
                     '[gate.smith.default]\nwall_hard_s = 2\n',
                     *('[gate.smith.default]\ncpu_test_s = ' + value for value in
                       ('0', '-1', 'true', '"10"', 'nan', 'inf'))):
            atomic.write(self.repo / cpu.BUDGETS, text)
            with self.subTest(text=text), self.assertRaises(ValueError):
                queue_cpu.budgets(self.repo)

    def test_no_wrapper_after_earlier_red_or_docs_and_non_test_exit_checks_unchanged(self):
        for name, code, green in (("clippy", 4, False), ("build", 4, True), ("fmt", 1, False)):
            fake = FakeRunner().on(["check"], Result(code))
            record = {"selection": "docs"}
            outcomes, reports = queue_cpu.run_steps([gate.Step(name, ("check",), str(self.repo))],
                                                   self.detail, record, sh=fake)
            self.assertEqual(outcomes[0].green, green)
            self.assertEqual(len(fake.calls), 1)
            self.assertEqual(reports, {})
            self.assertNotIn("cpu_trees", record)
        outcomes, _ = queue_cpu.run_steps([], self.detail, {}, sh=FakeRunner())
        self.assertEqual(outcomes, [])

    def test_queue_batch_record_keeps_cpu_fields_on_starvation_and_rejects_failure(self):
        for result, expected in (("starved", "green"), ("fail", "red")):
            with self.subTest(result=result):
                home = self.home / result
                fake = FakeNextest({None: [("b", "t", result)]},
                    fallback=FakeRunner().on(["git", "rev-parse"], Result(0, MAIN + '\n')))
                q = queue.Queue(self.repo, home=home, full_every=1, sh=fake)
                branch = queue.Branch("draft/task", TIP, 0)
                with patch('fab.queue.build_batch', return_value=([branch], [])), \
                        patch('fab.gate.changed_paths', return_value=['Cargo.toml']):
                    green = q.attempt([branch])
                self.assertEqual(green, result == "starved")
                batch = next(r for r in log.read(q.log_path) if r["ev"] == "batch")
                self.assertEqual(batch["outcome"], expected)
                smith = next(json.loads(g) for g in batch["cpu_trees"] if json.loads(g)["tree"] == "smith")
                self.assertEqual(smith["starved"], int(result == "starved"))
                self.assertEqual(smith["failed"], int(result == "fail"))
