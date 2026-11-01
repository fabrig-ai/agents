import unittest
from copy import deepcopy
from dataclasses import replace

from fab import buffer

from fab.tests.buffer_order import BufferTestCase, ids, sliced, spec, specs


class ExemplarTest(BufferTestCase):
    def test_consolidations_then_repairs_then_contracts_then_slices(self):
        the_plan = sliced(["early", "wire"], ["late"], contracts=["wire"])
        tasks = specs(spec("late-a", "late"), spec("early-a", "early"),
                      spec("wire-a", "wire"), spec("late-fix", "late"),
                      spec("merge", "late", consolidation=True), spec("early-b", "early"))
        self.assertOrder(the_plan, tasks,
                         ["merge", "late-fix", "wire-a", "early-a", "early-b", "late-a"],
                         refused=["late-fix"])
        # A refused consolidation stays a consolidation; candidates are only those given.
        self.assertOrder(the_plan, tasks, ["merge", "early-b", "late-a"],
                         refused=["merge"], candidates=ids("late-a", "early-b", "merge"))
        # Equal keys go in the specs' order, not the candidates' (rejected ones come first).
        self.assertOrder(the_plan, tasks, ["late-a", "late-fix"], refused=["late-a", "late-fix"],
                         candidates=ids("late-fix", "late-a"))


class GroupTest(BufferTestCase):
    def test_red_tasks_sort_as_repairs_ahead_of_contracts_and_slice_tasks(self):
        the_plan = sliced(["plain", "wire"], contracts=["wire"])
        red = spec("red-1", "after-landing", kind="red")
        tasks = specs(spec("plain", "plain"), spec("wire", "wire"), red,
                      spec("merge", "plain", consolidation=True))
        self.assertEqual(buffer.group(the_plan, red, False), "repair")
        self.assertOrder(the_plan, tasks, ["merge", "red-1", "wire", "plain"])

    def test_first_matching_group_wins(self):
        the_plan = sliced(["plain", "wire"], contracts=["wire"])
        cases = ((spec("merge", "wire", consolidation=True), True, "consolidation"),
                 (spec("merge", "plain", consolidation=True), False, "consolidation"),
                 (spec("fix", "wire"), True, "repair"),
                 (spec("wire", "wire"), False, "contract"),
                 (spec("plain", "plain"), False, "slice"),
                 (spec("outside", "outside"), False, "slice"))
        for task, refused, expected in cases:
            with self.subTest(task=task, refused=refused):
                self.assertEqual(buffer.group(the_plan, task, refused), expected)

    def test_repair_and_rebase_kinds_alone_are_not_refusals(self):
        the_plan = sliced(["plain"])
        for kind in ("repair", "rebase"):
            with self.subTest(kind=kind):
                self.assertEqual(buffer.group(the_plan, spec("again", "plain", kind=kind), False),
                                 "slice")


class OrderTest(BufferTestCase):
    def test_first_slice_ranks_a_part_in_two_slices(self):
        the_plan = sliced(["early"], ["late", "early"])
        tasks = specs(spec("late", "late"), spec("early", "early"))
        self.assertOrder(the_plan, tasks, ["early", "late"])

    def test_every_group_sorts_by_slice_then_plan_part_then_spec(self):
        # Reversing each slice's parts leaves plan.parts in its first-seen order.
        base = sliced(["first", "second"], ["late"])
        for name in buffer.GROUPS:
            with self.subTest(group=name):
                the_plan = replace(base, parts={key: replace(part, contract=name == "contract")
                                               for key, part in base.parts.items()},
                                   slices=tuple(replace(item, parts=tuple(reversed(item.parts)))
                                                for item in base.slices))
                tasks = specs(*(spec(task, part, consolidation=name == "consolidation")
                                for task, part in (("late", "late"), ("second", "second"),
                                                   ("first-a", "first"), ("first-b", "first"))))
                self.assertOrder(the_plan, tasks, ["first-a", "first-b", "second", "late"],
                                 refused=["late", "second", "first-a", "first-b"]
                                 if name == "repair" else (), candidates=reversed(tasks))

    def test_unsliced_and_unknown_parts_follow_every_slice(self):
        base = sliced(["unsliced"], ["early"], ["late"])
        the_plan = replace(base, slices=base.slices[1:])
        tasks = specs(spec("unknown", "unknown"), spec("unsliced", "unsliced"),
                      spec("late", "late"), spec("early", "early"))
        self.assertOrder(the_plan, tasks, ["early", "late", "unsliced", "unknown"])

    def test_inputs_are_unchanged_and_candidates_may_be_an_iterator(self):
        the_plan = sliced(["early"], ["late"])
        tasks = specs(spec("late", "late"), spec("early", "early"))
        candidates = list(tasks)
        refused = ids("early")
        before = deepcopy((the_plan, tasks, candidates, refused))
        self.assertEqual(buffer.order(the_plan, tasks, candidates, refused), ids("early", "late"))
        self.assertEqual((the_plan, tasks, candidates, refused), before)
        self.assertOrder(the_plan, tasks, ["early", "late"], candidates=iter(candidates))
        self.assertOrder(the_plan, tasks, [], candidates=())

    def test_missing_candidate_is_a_key_error(self):
        with self.assertRaises(KeyError) as caught:
            buffer.order(sliced(["early"]), specs(spec("early", "early")), ids("absent"))
        self.assertEqual(caught.exception.args, ("draft/absent",))


if __name__ == "__main__":
    unittest.main()
