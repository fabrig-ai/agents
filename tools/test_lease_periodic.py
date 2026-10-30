"""Repeated real competing-writer schedules; isolated periodic coverage."""
from test_lease import *


class PeriodicLeaseTests(LeaseTests):
    def test_two_concurrent_takes_leave_one_holder(self):
        # Repeat with a fresh directory so creation and lock acquisition race too.
        for iteration in range(5):
            with self.subTest(iteration=iteration):
                processes = [subprocess.Popen(self.command("take", owner, "race", A), env=self.env,
                                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                             for owner in ("s/a", "s/b")]
                for process in processes:
                    output, errors = process.communicate(timeout=20)
                    self.assertIn(process.returncode, (0, 1), output + errors)
                self.assertEqual(sorted(p.returncode for p in processes), [0, 1])
                self.assertEqual(len(self.rows()), 1)
                self.run_lease("release", self.record()["owner"], A)



def load_tests(loader, tests, pattern):
    return unittest.TestSuite(PeriodicLeaseTests(name) for name in PeriodicLeaseTests.__dict__
                              if name.startswith('test_'))
