# call-rebase: the cut's decisions

1. **One part, two tasks, in order.** `land-chain` (fab/call_review.py,
   fab/calls.py, fab/roles/amender.md) and `land-finish` (fab/dispatch.py).
   The draft says keep the plan small; the dispatch side reads the hold
   reason and predicate the chain side defines, so `land-finish` needs
   `land-chain`. No shared-contract part: the two items it reads are bound
   here and in the specs.
2. **What a `fab land` refusal is** (binding for both tasks):
   `fab.call_review.land_refusal(refusal: str) -> dict | None` takes one of
   `Chain.refusals` and returns the `branch.rejected` record when it is
   `fab land`'s: a `queue:` refusal whose record has no `queue_ts` (fabrig's
   queue rejections carry one, `fab.dispatch._import_queue`) and whose
   `step` is one of `fab land`'s steps, `fetch`, `rebase`, `paths`, `test`,
   `push` (a module constant; the integration trunk's `merge` and catch-up
   steps are not). None otherwise, review runs included.
3. **The hold reason is a constant:** `fab.call_review.LAND_HOLD =
   "refused by fab land after its amendment"`, the hold's reason when the
   chain's last refusal is a `fab land` refusal and it already has an amend
   call since its reset (otherwise `refused after its amendment`, as now).
   `hold_reason` (legacy parks held again) is left alone: no park predates
   this reason.
4. **The retire's extra designs** are computed only for a retire chain whose
   last refusal is a `fab land` refusal: `fab.designer.changed_designs` at
   `origin/main` less those at `origin/<chain.branch>`, after one `git fetch
   origin` in the repository `_chain_call` is given. A fabrig plan's retire
   is refused by its queue, never by `fab land`, so it never computes them.
5. **No `branch.rejected` logged during the finish** (an exception before or
   inside `fab land` that logged nothing) keeps today's `call.finished`
   failed: the design's rule reads the step of the rejection, and without
   one there is no step to read.
6. **The amender's other `fab land` steps:** the role text says that for a
   refusal at `fetch` or `push` that the branch did not cause, the amender
   changes nothing and ends `Done:` saying so (the design's "one amend that
   finds nothing to change and ends done"); for `paths` and `test` it fixes
   what the log names, as for any finding.
7. **Landed by hand is delivered.** A finish whose branch a `branch.landed`
   already names runs `_finish` before `call.finished` done, as a landing
   would: an answer chain's answers are on main, so its `question.answered`
   records are due; without them its questions would queue again.

## Critical path

`land-chain` (50 min) then `land-finish` (45 min): 95 implementer-minutes,
the longest task plus the one it builds on.
