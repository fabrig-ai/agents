"""Survey runs before design calls, their reports in the briefs (docs/design/fab.md, 13.10)."""

import unittest

from fab import log, plan, run, surveys
from fab.hosts import Host
from fab.tests.support import (call_ended, call_started, launcher, survey_ended, survey_started,
                               tmp_home, write_plan, write_report)

HOST = Host("builder", "worker@builder.invalid", ("builder",))
NOW = "2026-10-31T12:00:00.000Z"


@unittest.skip("skeleton: the task agents-rebuild/surveys fills fab/surveys.py")
class SurveysTest(unittest.TestCase):
    def test_a_part_is_surveyed_once_before_its_call_and_the_report_reaches_the_brief(self):
        subject = "one/core"
        self.assertEqual(surveys.due(subject, "skeleton", [], NOW), ("primitives",))

        with tmp_home() as home:
            one, _ = plan.load(write_plan(home / "one", "one"))
            fake = launcher()
            run_id = surveys.start(one, subject, "primitives", home, HOST, [], part="core", sh=fake)
            self.assertEqual(run_id, "one/core/survey-1")
            started = log.read()[-1]
            self.assertEqual((started["task"], started["kind"], started["topic"], started["branch"]),
                             ("one/core/survey", "survey", "primitives", "main"))
            launch = next(call for call in fake.calls if "fab codex start" in call.argv[-1])
            self.assertIn("--effort medium", launch.argv[-1])
            self.assertIn("--read-only", launch.argv[-1])

            started = {**started, "ts": "2026-10-31T11:50:00.000Z"}
            self.assertEqual(surveys.due(subject, "skeleton", [started], NOW), ())
            self.assertFalse(surveys.ready(subject, "skeleton", [started], NOW))

            events = [started, survey_ended(subject, ts="2026-10-31T11:58:00.000Z")]
            self.assertTrue(surveys.ready(subject, "skeleton", events, NOW))
            write_report(run_id, "Done: two primitives\n\n- `fab.atomic.write` replaces a file whole\n")
            text = surveys.section(subject, "skeleton", events)
        self.assertTrue(text.startswith("## primitives (one/core/survey-1, done)\n\nDone: two primitives"))
        self.assertIn("fab.atomic.write", text)

        asked = [*events, call_started("c1", "skeleton", subject), call_ended("c1", "question")]
        self.assertEqual(surveys.due(subject, "skeleton", asked, NOW), ("primitives",))
        amended = [*events, call_started("c2", "amend", subject)]
        self.assertTrue(surveys.ready(subject, "skeleton", amended, NOW))
        stale = [survey_started(subject), survey_ended(subject, ts="2026-10-31T10:30:00.000Z")]
        self.assertEqual(surveys.due(subject, "skeleton", stale, NOW), ("primitives",))
        self.assertEqual(surveys.due("one/cut", "cut", [survey_started("one/cut", topic="tests")], NOW),
                         ("readers", "primitives"))
        self.assertEqual(run.next_run(surveys.task_field(subject), events), "one/core/survey-2")


if __name__ == "__main__":
    unittest.main()
