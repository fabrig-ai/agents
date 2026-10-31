+++
id = "cut-early"
part = "replay"
kind = "feature"
needs = ["light-merges", "run-texts"]
files = ["fab/dispatch.py", "fab/integration.py", "fab/tests/test_dispatch.py", "fab/tests/test_integration.py"]
effort = "high"
minutes = 35
+++
# The cut releases its first specs early

docs/design/fab.md 13.12 ("The cut releases its first specs early"). The
cut's text (`fab/roles/cut-run.md`) tells it to push consistent batches
and run `fab wake cut <call>`.

## What to change, in `fab/dispatch.py` and `fab/integration.py`

- **Merging an in-flight cut:** each tick, for an integration plan whose
  reviews are off, when the plan's cut call is in flight (a `call.started`
  with role cut and subject `<draft>/cut` and no `call.ended`) and
  `origin/calls/<call>` exists and is not an ancestor of
  `origin/<trunk>`, merge it with `_merge_branch` (task the branch's
  name). Its `branch.landed` is logged as any merge; the call's end later
  merges the rest and finishes the chain as today. A merge that fails is
  retried next tick; a conflict is the cut's to resolve and only noted.
- **A direct part is never sent to a design call:** the design step lists
  no part whose mode is direct (the cut designs it).
- **The end check waits while the plan's cut is in flight**
  (`fab.integration.next_step` returns None then).
- **The spec path:** `_start` passes the plan's checkout root to
  `fab.run.start` (task `run-texts`'s keyword) so briefs name specs
  repository-relative.

## Acceptance

Tests in `fab/tests/test_dispatch.py` and `fab/tests/test_integration.py`
(fake runner; real git for the merge):
- an in-flight cut whose pushed branch is ahead of the trunk is merged,
  once, and its tasks become runnable and start from the trunk;
- a plan with a direct part without specs starts no design call;
- next_step is None while the cut is in flight, even with every listed
  task merged;
- `bin/fab test` passes within its budget.
