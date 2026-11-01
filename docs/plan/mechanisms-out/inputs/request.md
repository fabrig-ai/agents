# Request: mechanisms out of the LLM calls

From the user via the director, 2026-11-01 (the lab page's proposal 3,
approved): an LLM for judgement, code for mechanisms. Three mechanisms
that calls do today move to code; the designs now say how, each marked
"the user, 11-01". Build them as designed, with the role texts in step:

1. **`retired = true` is code's** (`docs/design/calls.md` 3, "retire").
   Today the retire call writes it (`fab/roles/retire.md`, "What you
   write"). Build: at the finish of a retire call that ended done
   (`fab/dispatch.py`, `_take` "finish"), before `_deliver`, commit
   `retired = true` into the plan's plan.toml on the call's branch
   (`fab.spec_edit.commit_path`), push, then deliver; skip when already
   set; a failure is a note and retried next tick. Remove the bullet from
   `fab/roles/retire.md` and say there that fab sets it.
2. **Plan options written by code** (`docs/design/integration.md` 3, "The
   cut's inputs"). Today `fab.designer._cut_role_options` tells the cut to
   write the `--set` keys verbatim. Build: `fab call cut` (`fab/designer.py`
   `main`, through `fab.calls.start` or just after its worktree exists and
   before Claude starts) commits a plan.toml holding only those keys under
   the design's comment, on the call's branch; the `Plan options` brief
   section says the file exists and to write the plan below the lines,
   leaving them; before each delivery of a cut's branch (`_merge_branch`
   for an integration plan's early releases, `_deliver` otherwise) the tick
   restores missing or changed keys from call.started's `options` by a
   code commit.
3. **`fab land` refusals: code first** (`docs/design/calls.md` 2, "A `fab
   land` refusal counts as a refusal of the chain"). Build:
   - `fetch`/`push`: no amend call; the finish is tried again next round, up
     to `LAND_TRIES` (3) refusals at that step for that tip, then the chain
     parks (`call.parked`, reason `fab land refused at <step> 3 times`);
     these do not count toward the chain's amend (`fab/call_review.py`
     `_fold_review` and `land_refusal`, `fab/dispatch.py` `_finish_outcome`
     and the amend start);
   - `test`: before the amend call, the tick rebases the call's branch onto
     `origin/main` in a worktree of its own and pushes it with
     `--force-with-lease`; the amend brief (`fab/call_review.py`
     `amend_brief`) says whether that rebase went through;
   - `fab/roles/amender.md`: `fetch` and `push` no longer reach it; at
     `test` the branch comes rebased (rebase first only when the brief says
     the tick's rebase conflicted); `rebase` and `paths` as today.

Other north-star breaches found on the way are not for this plan; agents/loop
lists them in its README.

The user's rule: dogfood. Built by fab's loop (landed through `bin/fab
land`); the plan's landing is `queue` (the cut is started with `--set
'landing="queue"'`). Three independent tasks, each with its tests in
`fab/tests/` (fakes and fixture logs, as the touched modules' tests are).
Run after `docs/plan/dogfood-faults` has landed its tasks (both touch
`fab/dispatch.py` and `fab/roles/`).
