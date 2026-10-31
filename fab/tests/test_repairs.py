import unittest
from dataclasses import replace

from fab import foreman, repairs
from fab.hosts import Host
from fab.plan import Task

# The vocabulary of fab.repairs' tests: a task, its refusal records and its foreman's, in
# log order. Each builder returns the records the fold reads, nothing more; ts strings
# compare in the order the test writes them.

TASK = Task("draft/task", "part", "feature", "agents", (), ("fab/x.py",), "high", 30,
            "# Task\n", "docs/plan/draft/tasks/task.md")
HOST = Host("builder", "worker@builder.invalid", ("builder",))
SPEC = "+++\nid = 'task'\n+++\n# Task\n\nFill x.\n"
FOREMAN = foreman.task_field(TASK.id)
RUN = FOREMAN + "-1"


def event(ev, ts, **fields):
    """One record with just the fields given."""
    return {"ev": ev, "ts": ts, **fields}


def task_run(ts, n=1, kind="implement", branch=TASK.id):
    """The task's own run n starting at ts."""
    return event("run.started", ts, run=f"{TASK.id}-{n}", task=TASK.id, kind=kind,
                 branch=branch)


def rejected(ts, step="test", tip="tip1", branch=TASK.id, **fields):
    """The landing refusing branch at tip; fields add log or findings."""
    return event("branch.rejected", ts, task=TASK.id, branch=branch, tip=tip, step=step,
                 **fields)


def foreman_run(ts, run_id=RUN, outcome=None, ended=None, tip="tip1"):
    """A refusal's foreman starting at ts and, with outcome, ending at ended."""
    records = [event("run.started", ts, run=run_id, task=FOREMAN, kind=repairs.KIND,
                     branch=TASK.id, refused=tip, step="test")]
    if outcome is not None:
        records.append(event("run.ended", ended or ts, run=run_id, task=FOREMAN,
                             outcome=outcome, report=f"/fab/runs/{run_id}/report.md"))
    return records


def settled(ts, verdict, run_id=RUN, section=""):
    """The tick's record of acting on run_id's verdict."""
    return event(repairs.SETTLED, ts, task=TASK.id, run=run_id, verdict=verdict,
                 reason="why", branch="", section=section)


def report(verdict, line, *body):
    """A foreman's report: `Done: <verdict>: <line>`, then body's lines."""
    return "\n".join([f"Done: {verdict}: {line}", *body]) + "\n"


def refusal(state="foreman", since="02", **fields):
    """The Refusal the fold gives for rejected("02") alone, with fields changed."""
    found = repairs.Refusal(TASK.id, TASK.id, "tip1", "test", "", "", "02", "repair",
                            "foreman", "02")
    return replace(found, state=state, since=since, **fields)


class RepairsTestCase(unittest.TestCase):
    def only(self, events):
        """The one open refusal of TASK after events."""
        found = repairs.refusals({TASK.id: TASK}, iter(events))
        self.assertEqual(len(found), 1, found)
        return found[0]

    def assertStands(self, events, state, since, **fields):
        """TASK's open refusal after events is in state since since, with fields."""
        found = self.only(events)
        self.assertEqual((found.state, found.since), (state, since))
        for name, value in fields.items():
            self.assertEqual(getattr(found, name), value, name)


class ExemplarTest(RepairsTestCase):
    @unittest.skip("pending: agents-rebuild/foreman-repairs")
    def test_a_red_goes_through_its_foreman_into_the_spec(self):
        events = [task_run("01"), rejected("02")]
        self.assertStands(events, "foreman", "02", kind="repair", retried=False)
        events += foreman_run("03")
        self.assertStands(events, "deciding", "03", foreman=RUN)
        events += foreman_run("03", outcome="done", ended="04")[1:]
        decided = self.only(events)
        self.assertEqual(decided, refusal("decided", "04", foreman=RUN,
                                          report=f"/fab/runs/{RUN}/report.md"))
        verdict, reason, body = repairs.remedy(
            decided, report("fix", "make x return 2", "test_x fails: 1 != 2", ""))
        self.assertEqual((verdict, reason), ("fix", "make x return 2"))
        self.assertEqual(body, "make x return 2\ntest_x fails: 1 != 2")
        text = repairs.section(decided, day="2026-10-31", run_id=RUN, body=body)
        self.assertTrue(text.startswith(f"## Repair (2026-10-31, step test, foreman {RUN})\n\n"))
        spec = repairs.with_section(SPEC, text, run_id=RUN)
        self.assertEqual(spec, SPEC + "\n" + text)
        self.assertEqual(repairs.with_section(spec, text, run_id=RUN), spec)
        events.append(settled("05", "fix", section=text))
        self.assertStands(events, "settled", "05", verdict="fix", section=text)
        self.assertEqual(repairs.refusals({TASK.id: TASK}, [*events, task_run("06", n=2)]), [])


if __name__ == "__main__":
    unittest.main()
