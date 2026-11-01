# test-budget: the plan

One direct part, one task, as the request asks:

- `cpu-budget` (`docs/design/fab.md` 4, already saying so): `fab/testrun.py`
  measures the process's CPU time, children included, checks the budget
  against it and prints wall and CPU in its summary. `BUDGET_SECONDS` stays
  30.0; `TimedResult`'s per-test wall times stay.

The spec is `tasks/cpu-budget.md`; the standing rules are in
`notes/common.md`, the decisions and the critical path in
`notes/decisions.md`. The task leaves `docs/design/` alone: the design was
written in the request's commit, and its status line is the retire call's.

## Overlaps with drafts beside this one

- `mechanisms-out` changes `fab/dispatch.py`, `fab/calls.py`,
  `fab/call_review.py`, `fab/designer.py`, their tests and role texts. This
  task changes `fab/testrun.py`, `fab/cli.py` and the new
  `fab/tests/test_testrun.py`: no shared file, so no overlap to avoid.
