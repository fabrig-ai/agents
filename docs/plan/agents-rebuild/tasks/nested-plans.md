+++
id = "nested-plans"
part = "fabrig-calls"
kind = "feature"
needs = ["fabrig-calls-brief"]
files = ["fab/designer.py", "fab/calls.py", "fab/tests/test_designer.py", "fab/tests/test_calls.py"]
effort = "high"
minutes = 30
+++
# The designer's calls take a plan nested in its repository

docs/design/fab.md 13.11 ("A fabrig plan": a plan directory at any depth,
such as fabrig's `skein/docs/plan/<draft>`). Today `fab call cut --plan
<fabrig>/skein/docs/plan/component-kit` fails: `fab/designer.py` requires
PLAN_DIR to be `<root>/docs/plan/<draft>` and writes `docs/plan/<draft>/...`
paths into its briefs.

## What to change

- A plan directory is any `<root>/<prefix>docs/plan/<draft>` (prefix empty
  or a relative directory such as `skein/`). Derive the plan's repository
  path from PLAN_DIR relative to the checkout root once, and use it wherever
  `fab/designer.py` and `fab/calls.py` now build `docs/plan/<draft>/...`
  (the cut's "Plan: write ..." line, the Plans list of existing plans, which
  also globs nested `*/docs/plan/*/plan.toml`, retire's added-plan lookup,
  the decision and answer briefs' spec paths). Agents plans keep their
  paths byte for byte.
- Sources stay relative files under the checkout root, as now.
- Report any other module that assumes `docs/plan/<draft>` at the root
  (for instance `fab/call_review.py`'s plan path) without changing it: the
  task after optimistic-start fixes those.

## Acceptance

- Tests with a fake checkout: `fab call cut --brief-only` with a nested
  PLAN_DIR compiles a brief naming `skein/docs/plan/<draft>/plan.toml`;
  a PLAN_DIR outside any `docs/plan/` is still refused; agents briefs are
  unchanged.
- `bin/fab test` passes within the 30 s budget.
