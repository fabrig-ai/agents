"""What each draft owns and what plans share in one tick (docs/design/fab-tick.md, 5)."""

import unittest
from copy import deepcopy

from fab import dispatch, drafts, flow, plan
from fab.tests.support import (call_ended, call_started, run_ended, run_started, tmp_home,
                               write_plan)


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

    def test_under_requires_a_complete_draft_prefix_and_a_string(self):
        for name, expected in [("one", True), ("one/core", True), ("one/a/foreman", True),
                               ("one-more/x", False), ("on", False), (None, False),
                               (42, False), (["one/core"], False)]:
            with self.subTest(name=name):
                self.assertEqual(drafts.under("one", name), expected)

    def test_owned_uses_review_task_as_root_call_and_preserves_order(self):
        task = run_started("one/a")
        foreman = run_started("one/a/foreman", kind="foreman")
        review = run_started("root", kind="review", call="other-amend")
        events = [call_started("root", "skeleton", "one/core"), call_ended("root"),
                  call_started("other", "contract", "two/core"),
                  call_started("other-amend", "amend", "two/core"),
                  call_started("one-amend", "amend", "one/core"),
                  {"ev": "call.started", "subject": "one/core"},
                  {"ev": "call.started", "call": "no-subject"},
                  {"ev": "call.started", "call": "bad-subject", "subject": 3},
                  {"ev": "call.ended", "call": "not-started", "subject": "one/core"},
                  task, run_started("two/a"), review,
                  run_started("other", kind="review", call="one-amend"),
                  run_started("missing", kind="review"),
                  run_started("not-started", kind="review"),
                  run_started("no-subject", kind="review"),
                  run_started("bad-subject", kind="review"),
                  run_started("root"), foreman, run_started("one-more/a"),
                  {"ev": "run.started", "run": "no-task", "kind": "review"},
                  {"ev": "run.started", "run": "bad-task", "task": [], "kind": "review"}]
        before = deepcopy(events)
        selected = drafts.owned("one", iter(dispatch.in_flight(events)), iter(events))
        self.assertEqual(selected, [task, review, foreman])
        self.assertIs(selected[1], review)
        self.assertEqual(events, before)

    def test_strays_reads_iterables_once_and_keeps_unowned_runs_in_order(self):
        events = [run_started("one/a"), call_started("root", "contract", "two/core"),
                  run_started("root", kind="review"), run_started("gone/x"),
                  run_started("unknown", kind="review")]
        flight = dispatch.in_flight(events)
        self.assertEqual(drafts.strays(iter(["one", "two"]), iter(flight), iter(events)),
                         flight[2:])
        self.assertEqual(drafts.strays(["one", "two"], iter(flight[:2]), iter(events)), [])
        self.assertEqual(drafts.strays([], iter(flight), iter(events)), flight)

    def test_spend_copies_calm_and_marks_every_started_builder(self):
        calm = {"builder": True, "other": True, "busy": False}
        before = calm.copy()
        self.assertEqual(drafts.spend(None, ["builder"]), {})
        self.assertEqual(drafts.spend(calm, iter(["builder", "unmeasured"])),
                         {"builder": False, "other": True, "busy": False, "unmeasured": False})
        self.assertEqual(calm, before)
        self.assertIsNot(drafts.spend(calm, []), calm)

    def test_unit_replaces_each_character_outside_ascii_letters_digits_and_hyphen(self):
        for role, key, expected in [
            ("contract", "one/shared", "fab-call-contract-one_shared"),
            ("amend", "root-20261031-ABC123", "fab-call-amend-root-20261031-ABC123"),
            ("answer", "One_a.b:@ é中９!", "fab-call-answer-One_a_b_______"),
        ]:
            with self.subTest(role=role, key=key):
                self.assertEqual(drafts.unit(role, key), expected)

    def test_unit_rejects_an_empty_role_or_key(self):
        for role, key in [("", "one"), ("skeleton", ""), ("", "")]:
            with self.subTest(role=role, key=key), self.assertRaises(ValueError):
                drafts.unit(role, key)


class DesignCallsTest(unittest.TestCase):
    def setUp(self):
        home = self.enterContext(tmp_home())
        self.plan, _ = plan.load(write_plan(
            home / "one", "one", {name: () for name in ("core", "shared", "next", "later", "last")},
            contracts=["shared"]))
        self.fresh = list(self.plan.parts)

    def test_starts_up_to_start_in_fresh_order_with_each_parts_role(self):
        self.assertEqual(drafts.design_calls(self.plan, self.fresh, iter([])),
                         [("core", "skeleton"), ("shared", "contract")])
        self.assertEqual(drafts.design_calls(self.plan, ["shared", "later", "core"], []),
                         [("shared", "contract"), ("later", "skeleton")])

    def test_full_window_landings_grow_design_call_capacity(self):
        events = [run_started("one/seed-a"), run_started("one/seed-b"),
                  run_ended("one/seed-a"), {"ev": "branch.landed", "task": "one/seed-a"},
                  run_started("one/seed-c"), run_started("one/seed-d"),
                  run_ended("one/seed-b"), {"ev": "branch.landed", "task": "one/seed-b"},
                  run_ended("one/seed-c"), run_ended("one/seed-d")]
        self.assertEqual(flow.target("one", events), 4)
        self.assertEqual(drafts.design_calls(self.plan, self.fresh, iter(events)),
                         [("core", "skeleton"), ("shared", "contract"),
                          ("next", "skeleton"), ("later", "skeleton")])

    def test_skeleton_and_contract_share_the_limit_including_root_subject(self):
        events = [call_started("c1", "skeleton", "one/core"),
                  call_started("c2", "contract", "one")]
        self.assertEqual(drafts.design_calls(self.plan, ["next", "later"], events), [])
        events.append(call_started("c3", "contract", "one/shared"))
        self.assertEqual(drafts.design_calls(self.plan, ["next", "later"], events), [])

    def test_ended_call_releases_its_place_and_subject_for_any_outcome(self):
        for outcome in ("done", "question", "infra", "failed"):
            with self.subTest(outcome=outcome):
                events = [call_started("c1", "skeleton", "one/core"),
                          call_started("c2", "contract", "one/shared"),
                          call_ended("c1", outcome)]
                self.assertEqual(drafts.design_calls(self.plan, self.fresh, events),
                                 [("core", "skeleton")])

    def test_only_this_drafts_design_roles_use_capacity_or_reserve_parts(self):
        events = [call_started("other", "skeleton", "two/core"),
                  call_started("prefix", "contract", "one-more/shared"),
                  call_started("answer", "answer", "one"),
                  call_started("review", "review", "one/core"),
                  call_started("amend", "amend", "one/shared")]
        self.assertEqual(drafts.design_calls(self.plan, self.fresh, events),
                         [("core", "skeleton"), ("shared", "contract")])

    def test_skips_subject_in_flight_and_unknown_part_without_using_a_place(self):
        events = [call_started("active", "contract", "one/shared")]
        fresh = ["unknown", "shared", "later", "core"]
        before = deepcopy((self.plan, fresh, events))
        self.assertEqual(drafts.design_calls(self.plan, fresh, events), [("later", "skeleton")])
        self.assertEqual((self.plan, fresh, events), before)

    def test_no_eligible_parts_start_nothing(self):
        self.assertEqual(drafts.design_calls(self.plan, [], []), [])
        self.assertEqual(drafts.design_calls(self.plan, ["unknown"], []), [])


if __name__ == "__main__":
    unittest.main()
