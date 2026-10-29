"""Wall-clock budgets run after the gate's bulk files, with the same fixtures."""
import time
import unittest

import test_session_start as fixture


class OwnershipLatencyTests(fixture.Sandbox):
    def test_ownership_latency_below_100ms(self):
        durations = []
        for _ in range(3):
            begin = time.perf_counter()
            result = self.command("start", "owns", "lead/jig")
            durations.append(time.perf_counter() - begin)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.assertLess(sorted(durations)[1], 0.1, durations)


class InventoryLatencyTests(fixture.InventoryTests):
    def test_inventory_latency_under_150ms(self):
        durations = []
        for _ in range(3):
            begin = time.perf_counter()
            result = self.command("start", "names", "--json")
            durations.append(time.perf_counter() - begin)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(sorted(durations)[1], 0.15, durations)
        self.assertEqual(self.all_calls(), [])


def load_tests(loader, tests, pattern):
    # Inventory's functional tests belong to test_session_start.py.
    return unittest.TestSuite(cls(name) for cls in (OwnershipLatencyTests, InventoryLatencyTests)
                              for name in cls.__dict__ if name.startswith("test_"))


if __name__ == "__main__":
    unittest.main()
