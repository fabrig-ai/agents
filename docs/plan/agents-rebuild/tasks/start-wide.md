+++
id = "start-wide"
part = "wide-start"
kind = "feature"
needs = ["flow"]
files = ["fab/flow.py", "fab/tests/test_flow.py", "fab/dispatch.py", "docs/design/fab.md"]
effort = "high"
minutes = 40
+++
# Start wide: the flow target starts at the plan's places and halves on a failure

docs/design/fab.md 13.11 ("Start wide") replaces 13.2's start of 2 and its
drop of one.

## What to change

- `fab.flow.target(draft, events, start)`: the fold starts at `start`, the
  sum of the plan's builders' `places`; a first-attempt landing with the
  window full grows it by one (as now); a rejection (not a rebase or merge
  conflict) or an `infra` outcome halves it, rounded down, never below
  FLOOR. Update the docstring.
- In `fab/dispatch.py`, change only the one `flow.target(...)` call in
  `decide`, to pass the places of the builders the plan can use (the hosts
  with the builder role). Another task owns the rest of dispatch.py: touch
  nothing else there.
- In docs/design/fab.md 13.2, change the first bullet's "starts at 2" and
  "drops by one" to point at 13.11; nothing else in the design.

## Acceptance

- Tests in `fab/tests/test_flow.py`: a fresh plan's target equals its
  places; two rejections from 8 give 2; an infra outcome from 3 gives 1, and
  the target is never 0; a rebase conflict halves nothing; growth by one as
  before.
- `bin/fab test` passes within the 30 s budget.

## Answers

- 2026-10-31, the designer (supersedes the earlier answer): give
  `flow.target` a keyword `start` defaulting to today's START, so
  `fab.drafts.design_calls` and its tests stay unchanged (design calls keep
  starting at 2 for now). In dispatch.py, pass the builders' places at the
  one `flow.target(...)` call in `decide` only; compute the sum there from
  the hosts `decide` already has. No other signature changes. Do not ask
  again: within this, the choices are yours.
