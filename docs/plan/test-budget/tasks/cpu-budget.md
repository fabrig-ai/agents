+++
id = "cpu-budget"
part = "cpu-budget"
kind = "feature"
needs = []
files = ["fab/testrun.py", "fab/tests/test_testrun.py", "fab/cli.py"]
effort = "medium"
minutes = 30
+++
# `bin/fab test`'s budget is CPU time

Read first: `docs/plan/test-budget/notes/common.md`,
`docs/plan/test-budget/notes/decisions.md`, then `docs/design/fab.md` 4.

The request: `fab/testrun.py` fails the suite past 30 s of wall time, so a
busy machine fails a fast suite, and `fab land` runs the same check, so a
loaded machine can refuse a good branch at `test`.

## What to build

- **`fab/testrun.py`:**
  - A private helper, the process's CPU seconds so far: `os.times()`'s
    `user + system + children_user + children_system`.
  - `main` (~33): take the CPU start beside `started` (decision 5). The
    over-budget check (~52) compares the CPU delta with `BUDGET_SECONDS`,
    which stays 30.0; `-k` runs stay exempt, the failed-suite return stays
    first. The over-budget line stays (decision 3).
  - The summary (~50) prints both, in this form:
    `fab test: 2135 tests in 19.5 s wall, 17.8 s CPU (budget 30 s CPU)`.
  - `TimedResult` and the slow-test lines are unchanged: wall times name
    the slow tests.
  - The module docstring says the budget is CPU time.
- **`fab/cli.py`** (~13): the help reads `run every test; fail past the
  30 s CPU budget` (decision 4).

## Acceptance

In a new `fab/tests/test_testrun.py`, calling `testrun.main([])` with stderr
captured, `unittest.TestLoader.discover` patched to return an empty
`unittest.TestSuite`, and `os.times` and `time.monotonic` patched:

- Over budget by CPU, under by wall: returns 1, prints `over budget`.
- Over 30 s of wall, under by CPU: returns 0, no `over budget`.
- The CPU delta sums all four fields from a non-zero start: a case over
  budget only with the children's time counted fails.
- The summary line is exact, as above, for the fake figures.

`bin/fab test` green.

## Pre-approved defaults

- `main` calling `sys.stderr` at call time is what lets
  `contextlib.redirect_stderr` capture it; change nothing in `main` for
  the tests' sake beyond the helper.
- `os.times_result` takes a 5-tuple; a `time.monotonic` fake that repeats
  its last value is fine if something else reads the clock.
- The suite's real CPU figure past 30 s, or close enough to fail here, is a
  `Question:` with the figures; never raise `BUDGET_SECONDS`.

## Report

The functions changed, the summary line from a real `bin/fab test`, and the
tests added.
