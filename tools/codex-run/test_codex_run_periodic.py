"""Periodic tier: the full launcher process and failure suite."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from codex_run_fixtures import run_suite


class LauncherPeriodicTests(unittest.TestCase):
    def test_bash_suite(self):
        run_suite(self)


if __name__ == "__main__":
    unittest.main()
