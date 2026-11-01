+++
id = "call-env"
part = "paper-cuts"
kind = "feature"
needs = ["rebase-trunk"]
files = ["fab/dispatch.py", "fab/tests/test_dispatch.py"]
effort = "medium"
minutes = 15
+++
# Call units start with the tick's FAB_HOME

Read first: `docs/plan/dogfood-faults/notes/common.md`,
`docs/plan/dogfood-faults/notes/decisions.md` (5).

The request, item 7's second paper cut.

## What to build

- `fab/dispatch.py`, `_call` (~896): the `systemd-run --user` argv carries
  `--setenv=FAB_HOME=<fab.log.home()>` before the unit's command, so a
  tick with a non-default `FAB_HOME` (a replay's) starts calls that write
  to it.

## Acceptance

- The tests that pin `_call`'s argv carry the `--setenv` with the test's
  home; one test sets a non-default `FAB_HOME` and finds it in the argv.
- `bin/fab test` green.

## Report

The argv as built and the tests changed.
