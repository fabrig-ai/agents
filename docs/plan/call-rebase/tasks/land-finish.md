+++
id = "land-finish"
part = "land-refusal"
kind = "feature"
needs = ["land-chain"]
files = ["fab/dispatch.py", "fab/tests/test_dispatch.py"]
effort = "high"
minutes = 45
+++
# The tick's finish path and settle verdict on a `fab land` refusal

Read first: `docs/plan/call-rebase/notes/common.md`,
`docs/plan/call-rebase/notes/decisions.md` (2, 3, 5 and 7).

The request: "the tick's finish path (`fab/dispatch.py`: no
`call.finished` when `fab land` refuses a call's branch, at any step) [...]
and `_judge_chain`'s land verdict on it (`fab/call_review.py`,
`fab/dispatch.py`)". Design: `docs/design/calls.md`, 2, "A `fab land`
refusal counts as a refusal of the chain", its first and third sub-bullets.
`land-chain` has merged `fab.call_review.LAND_HOLD` and `land_refusal`; the
chain fold then turns a refusal into an amend or a hold by itself.

## What to build

- `_take` (`fab/dispatch.py` line 930), the `finish` case and its `finally`
  (near line 983), for a plan that lands through `fab land` (`plan.repo !=
  "fabrig" and plan.landing != "integration"`, `_deliver`'s last branch):
  when `_deliver` raises, find the `branch.rejected` with `branch` equal to
  `action.branch` and no `queue_ts` that the log gained during this finish
  (count the log's records before `_deliver`). Then:
  - none was logged: `call.finished` failed, as now (decision 5);
  - a `branch.landed` already names `action.branch` (landed by hand): treat
    it as delivered: `_finish` as on success, `call.finished` done
    (decision 7);
  - step `fetch` and the branch gone from origin (`git ls-remote
    --exit-code origin refs/heads/<branch>` in `checkout` through `sh`,
    check=False, not ok): `call.finished` failed;
  - otherwise, any step: no `call.finished`. The refusal note (`finish
    <task> failed: ...`) is logged as now.
  Fabrig and integration plans keep their path unchanged. `_take` must not
  grow: move the decision into a private helper returning the outcome to
  log, or None for none.
- `_judge_chain` (line 1587): a `land` verdict on a chain whose hold reason
  is `call_review.LAND_HOLD` is not valid, so it parks with `settle
  failed`; amend (first attempt only) and user keep their rules. Its
  docstring says so.

## Acceptance

Tests in `fab/tests/test_dispatch.py`, with `fab.land.main` patched as the
finish tests near line 2480 do, the fake logging a `branch.rejected`
(task, branch, tip, step, log) through `fab.log.append` and returning 1:
- step `rebase`: no `call.finished`; the next tick starts the amend
  (`Action("call", task=<root>, run_kind="amend")`); after the amend ends
  done and its review approves, the next finish lands and logs
  `call.finished` done.
- refused again by `fab land` after that amend: the tick holds the chain
  for settle (a settle call action), and the chain's reason is
  `LAND_HOLD`.
- each of `fetch` (branch present at origin), `paths`, `test` and `push`
  logs no `call.finished`; `fetch` with `ls-remote` failing logs
  `call.finished` failed; a `branch.landed` naming the branch before the
  refusal logs `call.finished` done.
- a refusal that logs no `branch.rejected` still logs `call.finished`
  failed (the existing test near line 2480 passes unchanged).
- `_judge_chain` on a `LAND_HOLD` hold: `Done: land` parks with `settle
  failed` and logs no `chain.settled`; `Done: amend` on the first attempt
  logs `chain.settled` amend; on the second attempt only `Done: user` is
  valid.

## Pre-approved defaults

- Tests may build the chain's events literally (`call.started`,
  `call.ended`, a review `run.started`/`run.ended`) as the chain tests near
  line 784 do, rather than through a full tick.
- A test pinning today's `call.finished` failed for a `fab land` refusal
  that logged a `branch.rejected` changes to the new rule; say which in
  your report.

## Report

The helper's name and the outcome it gives each case, and the tests added.
