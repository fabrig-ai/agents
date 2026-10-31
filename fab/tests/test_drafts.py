"""What each draft owns and what plans share in one tick (docs/design/fab.md, 13.4)."""

import unittest

from fab import dispatch, drafts, flow, plan
from fab.tests.support import (call_ended, call_started, run_ended, run_started, tmp_home,
                               write_plan)


@unittest.skip("skeleton: the task agents-rebuild/drafts fills fab/drafts.py")
class DraftsTest(unittest.TestCase):
    def test_two_drafts_own_their_runs_and_design_up_to_the_target(self):
        events = [
            run_started("one/a"), run_started("one/a/foreman", kind="foreman"),
            call_started("c1", "skeleton", "one/core"), call_ended("c1"),
            run_started("c1", kind="review"),
            run_started("two/b", host="other"),
            call_started("c9", "skeleton", "gone/x"), call_ended("c9"),
            run_started("c9", kind="review"),
            run_started("one/z"), run_ended("one/z"),
            call_started("c2", "skeleton", "one/next"),
        ]
        flight = dispatch.in_flight(events)
        self.assertEqual([r["run"] for r in drafts.owned("one", flight, events)],
                         ["one/a-1", "one/a/foreman-1", "c1-1"])
        self.assertEqual([r["run"] for r in drafts.owned("two", flight, events)], ["two/b-1"])
        self.assertEqual([r["run"] for r in drafts.strays(["one", "two"], flight, events)], ["c9-1"])

        with tmp_home() as home:
            one, _ = plan.load(write_plan(home / "one", "one",
                                          {"core": (), "next": (), "shared": (), "later": ()},
                                          contracts=["shared"]))
        self.assertEqual(flow.target("one", events), flow.START)
        self.assertEqual(drafts.design_calls(one, ["next", "shared", "later"], events),
                         [("shared", "contract")])

        self.assertEqual(drafts.spend({"builder": True, "other": True}, ["builder"]),
                         {"builder": False, "other": True})
        self.assertEqual(drafts.unit("skeleton", "one/shared"), "fab-call-skeleton-one_shared")


if __name__ == "__main__":
    unittest.main()
