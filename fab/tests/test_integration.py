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
from fab.tests.support import FakeRunner, call_ended, call_started, run_ended, run_started, tmp_home


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

    def test_a_repairs_answers_fold_into_its_body(self):
        events = [merged()] + checked(1, "failed")
        events += [dict(ev="question.answered", task="demo/repair-1", answer="Update the journeys."),
                   dict(ev="question.answered", task="demo/repair-1"),
                   dict(ev="question.answered", task="demo/other", answer="Not this one.")]
        body = integration.repair_tasks(PLAN, events, {})["demo/repair-1"].body
        self.assertTrue(body.endswith("## Answers\n\n- Update the journeys.\n"))
        self.assertNotIn("Not this one", body)
        self.assertNotIn("## Answers", integration.repair_tasks(PLAN, events[:-3], {})["demo/repair-1"].body)

    def test_checks_along_the_way(self):
        tasks = {f"demo/t{n}": replace(TASK, id=f"demo/t{n}") for n in range(12)}
        def landed(n, ts):
            return dict(merged(f"tip{n}", task=f"demo/t{n}"), ts=ts)
        ten = [landed(n, f"2026-11-01T10:{n:02d}:00Z") for n in range(10)]
        step = integration.next_step(PLAN, tasks, ten)
        self.assertEqual((step.kind, step.tip), ("mid-check", "tip9"))
        self.assertIsNone(integration.next_step(PLAN, tasks, ten[:3]))
        later = ten[:3] + [dict(ev="note", ts="2026-11-01T10:50:00Z")]
        self.assertEqual(integration.next_step(PLAN, tasks, later).kind, "mid-check")
        # A mid check's reds never stop the plan, and its repair says what is not merged yet.
        reds = list(ten)
        for n in range(1, 4):
            reds += [dict(run_started("demo/integration", n, kind="check", base=f"tip{9}", mid=True,
                                      ts="2026-11-01T10:20:00Z")), run_ended("demo/integration", n, "failed")]
        self.assertIsNone(integration.next_step(PLAN, tasks, reds))  # repairs are open, not a stop
        repair = integration.repair_tasks(PLAN, reds, {}, tasks)["demo/repair-1"]
        self.assertIn("## Not merged yet", repair.body)
        self.assertIn("- demo/t11:", repair.body)
        self.assertNotIn("- demo/t3:", repair.body)

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

    def test_next_step_waits_for_own_cut_until_it_ends(self):
        tasks = {TASK.id: TASK}
        events = [merged()]
        cut = call_started("cut", "cut", "demo/cut")
        step = integration.Step("check", "tip", "tip")
        for reviews in (False, True):
            with self.subTest(reviews=reviews):
                the_plan = replace(PLAN, reviews=reviews)
                self.assertIsNone(integration.next_step(the_plan, tasks, [cut, *events]))
                self.assertEqual(integration.next_step(the_plan, tasks,
                                                       [cut, *events, call_ended("cut")]), step)
        for role, subject in (("cut", "other/cut"), ("skeleton", "demo/cut"),
                              ("cut", "demo/cut-more")):
            with self.subTest(role=role, subject=subject):
                self.assertEqual(integration.next_step(PLAN, tasks,
                                                       [call_started("other", role, subject), *events]), step)
        self.assertIsNone(integration.next_step(PLAN, tasks, [cut, *events, *checked()]))
        self.assertIsNone(integration.next_step(PLAN, tasks,
                                               [cut, *events, *checked(1, "failed"),
                                                *checked(2, "failed"), *checked(3, "failed")]))

    def test_next_step_green_readies_once_or_stops_without_ready(self):
        events = [merged()] + checked()
        self.assertEqual(integration.next_step(PLAN, {}, events), integration.Step("ready", "tip", "tip"))
        self.assertIsNone(integration.next_step(replace(PLAN, ready=False), {}, events))
        events.append(dict(ev="branch.ready", task="foreign/integration", tip="tip"))
        self.assertIsNotNone(integration.next_step(PLAN, {}, events))
        events.append(dict(ev="branch.ready", task="demo/integration", tip="tip"))
        self.assertIsNone(integration.next_step(PLAN, {}, events))

    def test_a_queue_rejection_checks_again_then_readies_and_a_landing_ends(self):
        ready = dict(ev="branch.ready", task="demo/integration", tip="tip")
        rejected = dict(ev="branch.rejected", task="demo/integration", tip="tip", step="default",
                        queue_ts="t1")
        events = [merged(), *checked(), ready]
        self.assertIsNone(integration.next_step(PLAN, {}, events))
        events.append(rejected)
        self.assertEqual(integration.next_step(PLAN, {}, events),
                         integration.Step("check", "tip", "queue rejected default: catch up and check again"))
        events += checked(2)
        self.assertEqual(integration.next_step(PLAN, {}, events), integration.Step("ready", "tip", "tip"))
        events.append(ready)
        self.assertIsNone(integration.next_step(PLAN, {}, events))
        landed = dict(ev="branch.landed", task="demo/integration", tip="tip", main="m", queue_ts="t2")
        self.assertIsNone(integration.next_step(PLAN, {}, [*events, rejected, landed]))

    def test_a_trunk_caught_up_with_main_is_readied_at_its_new_tip(self):
        events = [merged(), *checked(), dict(ev="branch.ready", task="demo/integration", tip="tip"),
                  dict(ev="branch.rejected", task="demo/integration", tip="tip", step="merge", queue_ts="t1"),
                  dict(ev="branch.landed", task="demo/integration", branch="main", into=PLAN.trunk,
                       main="caught", tip="main-tip")]
        self.assertEqual(integration.next_step(PLAN, {}, events), integration.Step("check", "caught", "caught"))
        events += checked(2, tip="caught")
        self.assertEqual(integration.next_step(PLAN, {}, events), integration.Step("ready", "caught", "caught"))

    def test_three_queue_rejections_or_a_catch_up_conflict_stop(self):
        rejections = [dict(ev="branch.rejected", task="demo/integration", tip="tip", step="default",
                           queue_ts=f"t{n}") for n in range(integration.QUEUE_LIMIT)]
        step = integration.next_step(PLAN, {}, [merged(), *checked(), *rejections])
        self.assertEqual(step.kind, "stop")
        conflict = dict(ev="branch.rejected", task="demo/integration", tip="tip",
                        step=integration.CATCH_UP, branch="main")
        self.assertEqual(integration.next_step(PLAN, {}, [merged(), conflict]),
                         integration.Step("stop", "tip", "main conflicts with the trunk; needs judgement"))
        self.assertEqual(integration.next_step(PLAN, {}, [merged(), conflict, merged("fixed")]).kind, "check")

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
                precheck.assert_called_once_with(self.home, "tip", onto="origin/demo/integration", full=True, without=())
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
