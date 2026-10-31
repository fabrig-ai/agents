"""Acceptance tasks from the plan, its specs and the log (docs/design/fab.md, 13.1)."""

import os
import unittest
from unittest.mock import patch

from fab import acceptance, state
from fab.tests import support
from fab.tests.support import History, build_part, build_plan, build_task


class PendingTest(unittest.TestCase):
    def test_pending_skips_unless_its_subject_is_listed(self):
        with patch.dict(os.environ, {support.PENDING: "draft/other"}):
            @support.pending("draft/core")
            class Marked(unittest.TestCase):
                def test_it(self):
                    pass

        result = unittest.TestResult()
        Marked("test_it").run(result)
        self.assertEqual(result.skipped, [(result.skipped[0][0], "pending: draft/core")])
        with patch.dict(os.environ, {support.PENDING: "draft/other,draft/core"}):
            @support.pending("draft/core")
            class Listed(unittest.TestCase):
                def test_it(self):
                    pass

        result = unittest.TestResult()
        Listed("test_it").run(result)
        self.assertEqual((result.testsRun, result.skipped), (1, []))


class BranchTest(unittest.TestCase):
    def test_a_run_branch_is_apart_from_a_spec_task_named_after_its_part(self):
        history = History()
        runs = [history.run("draft/core/tests", kind="tests"),
                history.run("draft/core/accept-1", kind="accept")]
        branches = [event["branch"] for event in history.events]
        self.assertEqual(branches, [acceptance.BRANCH.format(run) for run in runs])
        self.assertEqual(branches, ["accept/draft/core/tests-1", "accept/draft/core/accept-1-1"])
        for branch in branches:  # git cannot hold the spec's `draft/core` and a ref under it
            self.assertFalse(branch == "draft/core" or branch.startswith("draft/core/"))


@support.pending("agents-rebuild/acceptance")
class StoryTest(unittest.TestCase):
    """A part and its slice, from the skeleton landing to the slice done."""

    def test_a_part_is_accepted_after_a_red_round_and_its_slice_is_done(self):
        plan = build_plan(build_part("core"), build_part("old", done=True),
                          slices=[(1, ["core", "old"])])
        specs = {task.id: task for task in (
            build_task("fill", part="core", files=["fab/core.py", "fab/tests/test_core.py"]),
        )}
        history = History()

        def current():
            return {**specs, **acceptance.tasks(plan, specs, history.events, report=history.report)}

        tasks = current()
        self.assertEqual(list(tasks), ["draft/fill", "draft/core/tests", "draft/core/accept-1",
                                       "draft/slice-1/tests", "draft/slice-1/accept-1"])
        self.assertEqual(tasks["draft/core/tests"].files,
                         ("fab/tests/test_accept_draft_core.py",))
        self.assertEqual(tasks["draft/core/accept-1"].needs, ("draft/core/tests", "draft/fill"))
        self.assertEqual(tasks["draft/slice-1/accept-1"].needs,
                         ("draft/slice-1/tests", "draft/core/accept-1"))
        views = state.fold(tasks, history.events)
        self.assertEqual(state.runnable(views),
                         ["draft/fill", "draft/core/tests", "draft/slice-1/tests"])

        # The tests and the code land; the first accept run is red and lands a fix spec.
        history.landed_all("draft/core/tests", "draft/slice-1/tests", "draft/fill")
        history.run("draft/core/accept-1", kind="accept", outcome="done",
                    report="Done: red, draft/core-fix-1\n")
        history.landed("draft/core/accept-1")
        self.assertEqual(acceptance.accept_round("draft/core", tasks["draft/core/accept-1"].needs,
                                                 history.events, report=history.report), (2, False))
        specs["draft/core-fix-1"] = build_task("core-fix-1", part="core", kind="repair",
                                               files=acceptance.fix_files(
                                                   acceptance.units(plan, specs, history.events)[0],
                                                   specs))
        tasks = current()
        self.assertNotIn("draft/core/accept-1", tasks)
        self.assertEqual(tasks["draft/core/accept-2"].needs,
                         ("draft/core/tests", "draft/fill", "draft/core-fix-1"))
        self.assertEqual(specs["draft/core-fix-1"].files, ("fab/core.py", "fab/tests/test_core.py"))

        # The fix lands; the second round is green, then the slice's.
        history.landed_all("draft/core-fix-1")
        history.run("draft/core/accept-2", kind="accept", outcome="done", report="Done: accepted\n")
        history.landed("draft/core/accept-2")
        tasks = current()
        views = state.fold(tasks, history.events)
        self.assertEqual({key: views[key].status for key, task in tasks.items() if task.part == "core"},
                         dict.fromkeys(["draft/fill", "draft/core-fix-1", "draft/core/tests",
                                        "draft/core/accept-2"], "landed"))
        self.assertEqual(acceptance.slices_done(plan, specs, history.events, report=history.report), [])
        history.run("draft/slice-1/accept-1", kind="accept", outcome="done", report="Done: accepted\n")
        history.landed("draft/slice-1/accept-1")
        self.assertEqual(acceptance.slices_done(plan, specs, history.events, report=history.report), [1])
        history.add("slice.done", draft="draft", slice=1, task="draft/slice-1/accept-1")
        self.assertEqual(acceptance.slices_done(plan, specs, history.events, report=history.report), [])
