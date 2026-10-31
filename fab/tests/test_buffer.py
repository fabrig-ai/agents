import unittest

from fab.tests.buffer_order import BufferTestCase, ids, sliced, spec, specs


class ExemplarTest(BufferTestCase):
    @unittest.skip("pending: agents-rebuild/buffer-order")
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


if __name__ == "__main__":
    unittest.main()
