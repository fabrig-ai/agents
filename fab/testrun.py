"""`fab test`: every test, in one process, within the budget (docs/design/fab.md, 4)."""

from __future__ import annotations

import argparse
import sys
import time
import unittest
from pathlib import Path

BUDGET_SECONDS = 30.0
SLOW_SECONDS = 0.5
ROOT = Path(__file__).resolve().parent.parent


class TimedResult(unittest.TextTestResult):
    """Records each test's wall time, so the slowest are named."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.times: list[tuple[float, str]] = []
        self._started = 0.0

    def startTest(self, test):
        self._started = time.monotonic()
        super().startTest(test)

    def stopTest(self, test):
        self.times.append((time.monotonic() - self._started, test.id()))
        super().stopTest(test)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="fab test", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-k", dest="patterns", action="append", help="only tests whose name contains this")
    args = parser.parse_args(argv)
    loader = unittest.TestLoader()
    if args.patterns:
        loader.testNamePatterns = [f"*{pattern}*" for pattern in args.patterns]
    started = time.monotonic()
    suite = loader.discover(str(ROOT / "fab" / "tests"), pattern="test_*.py", top_level_dir=str(ROOT))
    runner = unittest.TextTestRunner(stream=sys.stderr, verbosity=2 if args.verbose else 1, resultclass=TimedResult)
    result = runner.run(suite)
    elapsed = time.monotonic() - started
    slow = sorted((entry for entry in result.times if entry[0] >= SLOW_SECONDS), reverse=True)[:5]
    for seconds, name in slow:
        print(f"fab test: slow: {seconds:.2f} s {name}", file=sys.stderr)
    print(f"fab test: {result.testsRun} tests in {elapsed:.1f} s (budget {BUDGET_SECONDS:.0f} s)", file=sys.stderr)
    if not result.wasSuccessful():
        return 1
    if elapsed > BUDGET_SECONDS and not args.patterns:
        print("fab test: over budget: make the slow tests faster (docs/design/fab.md, 4)", file=sys.stderr)
        return 1
    return 0
