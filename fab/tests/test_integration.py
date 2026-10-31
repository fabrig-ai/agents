"""Integration decisions over events and the builder command through fakes (fab.md, 8)."""

import io
import json
import unittest
from contextlib import redirect_stdout
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import patch

from fab import atomic, cli, integration, log
from fab.plan import Plan, Task
from fab.sh import Result
from fab.tests.support import FakeRunner, run_ended, run_started, tmp_home


PLAN = Plan("demo", "fabrig", (), 1, 2, {}, (), landing="integration")
TASK = Task("demo/a", "core", "feature", "fabrig", (), (), "high", 20, "", "task.md")


def merged(tip="tip", task="demo/a"):
    return dict(ev="branch.landed", task=task, into=PLAN.trunk, main=tip, tip="branch-tip")


def checked(n=1, outcome="done", tip="tip"):
    return [run_started("demo/integration", n, kind="check", base=tip),
            run_ended("demo/integration", n, outcome)]


class IntegrationTest(unittest.TestCase):
    def test_trunk_tip_uses_only_last_merge_into_own_trunk(self):
        self.assertIsNone(integration.trunk_tip(PLAN, []))
        events = [merged(), merged("new"), {**merged("foreign"), "into": "other/integration"},
                  {**merged("main"), "into": None}]
        self.assertEqual(integration.trunk_tip(PLAN, events), "new")

    def test_repair_tasks_order_contract_and_report_limit(self):
        events = [merged()] + checked(1, "failed") + checked(2, "done") + checked(3, "failed", "new")
        events += [run_started("foreign/integration", kind="check"), run_ended("foreign/integration", outcome="failed")]
        reports = {"demo/integration-1": "\n".join(f"line {n}" for n in range(130)),
                   "demo/integration-3": "Failed: fmt red\nfmt:1:0.1"}
        tasks = integration.repair_tasks(PLAN, events, reports)
        self.assertEqual(list(tasks), ["demo/repair-1", "demo/repair-2"])
        first, second = tasks.values()
        self.assertEqual((first.part, first.kind, first.repo, first.files, first.effort, first.minutes, first.path),
                         ("integration", "repair", "fabrig", ("**",), "high", 20, ""))
        self.assertIn("`tip`", first.body)
        self.assertIn("`demo/integration-1`", first.body)
        self.assertIn("line 119\n", first.body)
        self.assertNotIn("line 120", first.body)
        for fragment in ("trunk with this change", "narrowest checks first", "failing step itself"):
            self.assertIn(fragment, first.body)
        self.assertIn("`new`", second.body)
        self.assertIn(reports["demo/integration-3"], second.body)
        self.assertEqual(integration.repair_tasks(replace(PLAN, landing="queue"), events, reports), {})
        self.assertEqual(len(integration.repair_tasks(PLAN, events, {})), 2)

    def test_a_check_before_any_task_merged_is_ignored(self):
        cut = merged("cut-tip", task="calls/cut-1")
        self.assertIsNone(integration.next_step(PLAN, {}, [cut]))
        early = [cut, *checked(1, "failed", tip="cut-tip")]
        self.assertEqual(integration.repair_tasks(PLAN, early, {}), {})
        events = early + [merged()]
        self.assertEqual(integration.repair_tasks(PLAN, events, {}), {})
        self.assertEqual(integration.next_step(PLAN, {TASK.id: TASK}, events),
                         integration.Step("check", "tip", "tip"))

    def test_next_step_waits_for_merge_and_tasks_and_check(self):
        tasks = {TASK.id: TASK}
        self.assertIsNone(integration.next_step(replace(PLAN, landing="queue"), {}, [merged()]))
        self.assertIsNone(integration.next_step(PLAN, {}, []))
        self.assertIsNone(integration.next_step(PLAN, tasks, [merged(task="demo/other")]))
        events = [merged()]
        step = integration.next_step(PLAN, tasks, events)
        self.assertEqual(step, integration.Step("check", "tip", "tip"))
        with self.assertRaises(FrozenInstanceError):
            step.kind = "ready"
        self.assertIsNone(integration.next_step(PLAN, tasks, events + checked()[:1]))
        self.assertEqual(integration.next_step(PLAN, tasks, events + checked(tip="old")), step)

    def test_next_step_green_readies_once_or_stops_without_ready(self):
        events = [merged()] + checked()
        self.assertEqual(integration.next_step(PLAN, {}, events), integration.Step("ready", "tip", "tip"))
        self.assertIsNone(integration.next_step(replace(PLAN, ready=False), {}, events))
        events.append(dict(ev="branch.ready", task="foreign/integration"))
        self.assertIsNotNone(integration.next_step(PLAN, {}, events))
        events.append(dict(ev="branch.ready", task="demo/integration"))
        self.assertIsNone(integration.next_step(PLAN, {}, events))

    def test_next_step_red_waits_for_repair_then_checks_new_tip_and_third_red_stops(self):
        events = [merged()] + checked(outcome="failed")
        tasks = integration.repair_tasks(PLAN, events, {})
        self.assertIsNone(integration.next_step(PLAN, {}, events))
        self.assertIsNone(integration.next_step(PLAN, tasks, events))
        events.append(merged("fixed", "demo/repair-1"))
        self.assertEqual(integration.next_step(PLAN, tasks, events), integration.Step("check", "fixed", "fixed"))
        events += checked(2, "failed", "fixed") + checked(3, "failed", "fixed")
        self.assertEqual(integration.next_step(PLAN, integration.repair_tasks(PLAN, events, {}), events),
                         integration.Step("stop", "fixed", "red 3 times; needs judgement"))

    def test_baselines_accepts_only_known_baseline_paths(self):
        self.assertEqual(integration.baselines(["smith/scripts/old-forms.txt", "skein/scripts/old-forms.txt"]),
                         ["skein", "smith"])
        for paths in ([], ["scripts/old-forms.txt"], ["unknown/scripts/old-forms.txt"],
                      ["skein/scripts/old-forms.txt", "skein/src/lib.rs"]):
            self.assertEqual(integration.baselines(paths), [])

    def test_recount_commands_and_failure(self):
        fake = FakeRunner()
        integration.recount(Path("/checkout"), ["skein"], sh=fake)
        self.assertEqual(fake.argvs(), [["git", "checkout", "--ours", "--", "skein/scripts/old-forms.txt"],
                                      ["python3", "-I", "-B", "scripts/old_forms.py", "--write"],
                                      ["git", "add", "--", "skein/scripts/old-forms.txt"]])
        self.assertEqual([call.cwd for call in fake.calls], ["/checkout", "/checkout/skein", "/checkout"])


class IntegrationCommandTest(unittest.TestCase):
    def setUp(self):
        self.home = self.enterContext(tmp_home())
        self.brief, self.report = self.home / "brief.md", self.home / "report.md"
        atomic.write(self.brief, "Check the trunk.\n")
        self.fake = FakeRunner()
        self.enterContext(patch.object(integration, "run", self.fake))
        self.output = io.StringIO()
        self.enterContext(redirect_stdout(self.output))

    def start(self):
        with patch.object(integration.codex, "new_id", return_value="check-id"):
            self.assertEqual(cli.main(["check", "start", "--tip", "tip", "--onto", "origin/demo/integration",
                                       str(self.brief), str(self.home), str(self.report)]), 0)
        return log.home() / "check/check-id"

    def test_start_unit_contract(self):
        directory = self.start()
        self.assertEqual(self.output.getvalue(), f"check-id {directory}\n")
        meta = json.loads((directory / "meta.json").read_text())
        self.assertEqual((meta["tip"], meta["onto"], meta["report"]),
                         ("tip", "origin/demo/integration", str(self.report)))
        argv, = self.fake.argvs()
        self.assertIn("fab-check-check-id", argv)
        self.assertIn("--property=UMask=0077", argv)
        self.assertTrue(any("ExecStopPost=-" in arg and arg.endswith("wake codex check-id") for arg in argv))
        self.assertEqual(argv[-3:], ["check", "_exec", "check-id"])
        self.assertFalse((directory / "ended").exists())

    def test_exec_report_result_ended_order_for_green_red_and_conflict(self):
        for outcome, steps, first in (("green", ["fmt:0:0.1"], "Done: green tip"),
                                      ("red", ["fmt:0:0.1", "gate:ratchet:1:0.2"], "Failed: gate:ratchet red"),
                                      ("conflict", [], "Failed: conflict red")):
            with self.subTest(outcome=outcome):
                directory = log.home() / "check/check-id"
                atomic.write(directory / "meta.json", json.dumps(dict(dir=str(self.home), tip="tip",
                             onto="origin/demo/integration", report=str(self.report))))
                writes = []
                save = atomic.write
                def record(path, text):
                    writes.append(Path(path).name)
                    save(path, text)
                receipt = dict(outcome=outcome, steps=steps, log="/check.log")
                with patch.object(integration.precheck, "precheck", return_value=receipt) as precheck, \
                        patch.object(integration.atomic, "write", side_effect=record):
                    self.assertEqual(cli.main(["check", "_exec", "check-id"]), int(outcome != "green"))
                precheck.assert_called_once_with(self.home, "tip", onto="origin/demo/integration", full=True)
                self.assertEqual(writes, ["report.md", "result.json", "ended"])
                self.assertEqual(self.report.read_text().splitlines(), [first, *steps, "/check.log"])
                result = json.loads((directory / "result.json").read_text())
                self.assertEqual(result["exit"], int(outcome != "green"))
                self.assertIsInstance(result["ended"], str)
                self.assertTrue((directory / "ended").exists())

    def test_exec_exception_still_completes_contract(self):
        directory = self.start()
        with patch.object(integration.precheck, "precheck", side_effect=OSError("no checkout")):
            self.assertEqual(cli.main(["check", "_exec", "check-id"]), 1)
        self.assertIn("no checkout", self.report.read_text())
        self.assertEqual(json.loads((directory / "result.json").read_text())["exit"], 1)
        self.assertTrue((directory / "ended").is_file())
