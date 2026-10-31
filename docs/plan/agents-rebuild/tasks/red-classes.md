+++
id = "red-classes"
part = "landing-checks"
kind = "feature"
needs = ["receipts"]
files = ["fab/reds.py", "fab/queue.py", "fab/landing_report.py", "fab/tests/test_reds.py", "fab/tests/test_queue.py", "fab/tests/test_landing_report.py", "fab/tests/landing_checks.py"]
effort = "high"
minutes = 55
+++
# The queue classes a red before anyone hears it

Today any red rejects the branch (a batch of one) or bisects the batch,
even when a test failed only under the gate's load. Fill `fab/reds.py` as
its docstrings say and make the queue retry such a red's failed tests alone
before it bisects or rejects: all passing, the red is collateral and the
batch goes again, counting against nobody. Then the landing report shows
what the queue absorbed. Design: `docs/design/fab.md`, 13.8 and 10.

## What to build

- **`fab/reds.py`:** every body (`overlay_text`, `with_junit`, `suspect`,
  `retry_step`, `classify`), through `fab.nextest` (`overlay`, `junit`,
  `exact_filter`), `fab.receipts.covers`, `fab.gate.run_steps` and
  `fab.tiers.NEXTEST_CONFIG` and `TEST_FAILED`.
- **The classing in `Queue.attempt` and `Queue.cycle`,** as their
  docstrings say ("Otherwise the test steps write their JUnit ..." and the
  collateral attempt not bisected). `Queue` gains `last_outcome`, set at
  the end of every attempt, and `state["collateral"]`, defaulting to `{}`
  as `tried` does. A collateral attempt rejects nothing and marks nothing
  tried, but a conflict in the same batch is rejected as always.
- **The landing report** (`fab/landing_report.py`): FIGURES gains, after
  `false_red_rate`, `("retried", "branches retried after a collateral
  red")` and `("reused", "batches landed on a precheck receipt")`.
  `figures`: retried counts the window's `collateral` records; reused the
  window's batch records with a `receipt` field and outcome green. A
  collateral batch counts in `batches` and none of green, red, conflict or
  error. `signals` gains, right after the collateral one: retried above 0,
  `<n> branches retried after a collateral red`; "a flake goes to its
  owner"; "ops, the test's owner". Update both docstrings.

## Acceptance

- `fab/tests/test_reds.py`, in the vocabulary of
  `fab/tests/landing_checks.py` (`receipt`, `junit_xml`, `alone`,
  `FakeNextest`, `ChecksTestCase.assertCollateral` and `assertStands`):
  - the exemplar test runs: remove its skip;
  - `overlay_text`: the repository's config with the junit table; a
    missing config and one without a default profile still give a default
    profile; a fuzzy profile missing is a ValueError;
  - `with_junit`: only `default` and `fuzzy` gain `--config-file`, order
    kept, a stale report removed, overlays written; a config that does not
    parse leaves the step as it was with no report;
  - `retry_step`: the step's own `--config-file` replaced, its scope and
    profile kept; an unsafe test name is a ValueError;
  - `classify`, one test per reason it stands (each with nothing run where
    the docstring says so), two failed tests both retried and passing, the
    first failing alone stopping before the second, a retry whose JUnit
    names another test, and every retry's output in the detail log;
- `fab/tests/test_queue.py`, in `GitTest` with real git, `check_steps`
  patched to return a `default` step and the queue's runner a
  `FakeNextest` falling back to the real one:
  - a batch of one whose test fails, then passes alone, with a covering
    receipt: outcome collateral, a `collateral` record, no `rejected`,
    nothing tried, the retry in the record's steps; the next cycle lands
    it;
  - the same tip collateral `LIMIT` times, then red: the red stands and the
    branch is rejected; its `collateral` entry gone;
  - a batch of three whose red is collateral is not bisected (one batch
    record); a test failing alone again bisects as today, the record
    carrying `stands`;
  - no receipt: the red stands at once, no retry run;
  - the existing tests pass unchanged.
- `fab/tests/test_landing_report.py`: retried and reused counted; a
  collateral batch in batches only; the new signal and its absence at 0.
- `bin/fab test` passes; `test_reds.py` takes under a second and
  `test_queue.py` stays under three seconds.

## Options, settled up front

- The overlays and reports sit beside the batch's detail log in
  FAB_HOME/queue, named after the batch id; the attempt's sweep does not
  touch them, and nothing removes them for now.
- A retry's JUnit with exit 0 and its one case skipped is `retry:`, never a
  pass.
- A red full batch whose red is collateral does not force full checks for
  the rest of the cycle; one whose red stands does, as today.
- `Queue._checks` and `_batch` may change their private signatures and
  split further; each function stays within 60 lines (the `size` gate).
  A second copy of the overlay-and-run block of `classify` is a defect (the
  `clones` gate refuses it).
