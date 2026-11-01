"""CPU-budget and timing output checks with an empty suite and fake clocks."""

from __future__ import annotations

import contextlib
import io
import itertools
import os
import tempfile
import unittest
from unittest.mock import patch

from fab import testrun


class TestrunTests(unittest.TestCase):
    """Keep budget decisions independent of machine load and CPU usage."""

    def setUp(self):
        """Isolate HOME and FAB_HOME for each invocation."""
        home = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, {"HOME": home, "FAB_HOME": home}))

    def _run(self, cpu_end, wall_seconds, *, cpu_start=(0, 0, 0, 0, 0), argv=()):
        stderr = io.StringIO()
        wall_end = 100.0 + wall_seconds
        clock = itertools.chain((100.0, wall_end), itertools.repeat(wall_end))
        with (
            contextlib.redirect_stderr(stderr),
            patch.object(unittest.TestLoader, "discover", return_value=unittest.TestSuite()),
            patch.object(testrun.os, "times", side_effect=(os.times_result(cpu_start), os.times_result(cpu_end))),
            patch.object(testrun.time, "monotonic", side_effect=clock),
        ):
            status = testrun.main(list(argv))
        return status, stderr.getvalue()

    def test_cpu_over_budget_fails_with_short_wall_time(self):
        """CPU use exceeding 45 seconds fails even when wall time is short."""
        status, output = self._run((46, 0, 0, 0, 0), 1)
        self.assertEqual(status, 1)
        self.assertIn("over budget", output)

    def test_wall_over_budget_passes_with_short_cpu_time(self):
        """Waiting or machine load cannot exhaust the CPU budget."""
        status, output = self._run((11, 22, 33, 44, 9000), 46, cpu_start=(10, 20, 30, 40, 1000))
        self.assertEqual(status, 0)
        self.assertNotIn("over budget", output)

    def test_cpu_delta_includes_all_four_fields(self):
        """Subtract a nonzero start and include both children's CPU fields."""
        status, output = self._run((18, 29, 45, 56, 9000), 1, cpu_start=(10, 20, 30, 40, 1000))
        self.assertEqual(status, 1)
        self.assertIn("48.0 s CPU", output)
        self.assertIn("over budget", output)

    def test_summary_prints_wall_and_cpu_seconds(self):
        """The summary names both clocks and the CPU budget exactly."""
        status, output = self._run((4, 3, 6, 4.8, 9000), 19.5)
        self.assertEqual(status, 0)
        summaries = [line for line in output.splitlines() if line.startswith("fab test:")]
        self.assertEqual(summaries, ["fab test: 0 tests in 19.5 s wall, 17.8 s CPU (budget 45 s CPU)"])

    def test_filtered_suite_is_exempt_from_cpu_budget(self):
        """A name-filtered run keeps its budget exemption."""
        status, output = self._run((31, 0, 0, 0, 0), 1, argv=("-k", "selected"))
        self.assertEqual(status, 0)
        self.assertNotIn("over budget", output)

    def test_failed_suite_returns_before_budget_check(self):
        """An unsuccessful suite fails without reporting a budget failure."""
        with patch.object(testrun.TimedResult, "wasSuccessful", return_value=False):
            status, output = self._run((31, 0, 0, 0, 0), 1)
        self.assertEqual(status, 1)
        self.assertNotIn("over budget", output)
