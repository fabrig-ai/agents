"""Fast authority and local lifetime contracts; full recovery is periodic."""

from pathlib import Path
import runpy
import unittest


CONTRACTS = runpy.run_path(str(Path(__file__).with_name("test_recovery_periodic.py")))


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for name in ("AuthorityEndpointTests", "ProcessClassificationTests"):
        suite.addTests(loader.loadTestsFromTestCase(CONTRACTS[name]))
    for name in ("test_real_lifetime_lock_blocks_reclaim_and_invalidates_ack",
                 "test_exclusive_maintenance_blocks_real_launcher_before_report_reservation"):
        suite.addTest(CONTRACTS["RecoveryTests"](name))
    return suite


if __name__ == "__main__":
    unittest.main()
