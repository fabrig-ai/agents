+++
id = "rebase-trunk"
part = "rebase-trunk"
kind = "interface"
needs = ["stop-lift"]
files = ["fab/call_review.py", "fab/tests/test_call_review.py", "fab/dispatch.py", "fab/tests/test_dispatch.py"]
effort = "medium"
minutes = 25
+++
# A rebase onto the trunk consumes the amendment

Read first: `docs/plan/dogfood-faults/notes/common.md`,
`docs/plan/dogfood-faults/notes/decisions.md` (5).

The request, item 4. Design: `docs/design/integration.md`, 2, "Optimistic
start" ("a completed rebase run ... with base `origin/<trunk>` consumes the
amendment").

## What to build

- `fab/call_review.py`, `task_rebase` (~528): gains a keyword `trunk: str
  = "main"`; a completed rebase run counts when its base is
  `f"origin/{trunk}"`. Kind `interface` for the parameter.
- `fab/dispatch.py` (~1884): passes `trunk=plan.trunk`.

## Acceptance

- call_review: with `trunk="<draft>/integration"` (`Plan.trunk` of an
  integration plan), a done rebase run with base
  `origin/<trunk>` after the finish consumes the amendment; one with base
  `origin/main` does not; the default keeps today's behaviour.
- dispatch: an integration plan's task with an amended skeleton and a done
  rebase run based on its trunk is merged, not rebased again.
- `bin/fab test` green.

## Report

The signature as built and the tests added.
