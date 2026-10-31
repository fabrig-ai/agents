+++
id = "integration-merge"
part = "replay"
kind = "feature"
needs = ["replay-options", "replay-trunk"]
files = ["fab/dispatch.py", "fab/tests/test_dispatch.py"]
effort = "high"
minutes = 50
+++
# The tick merges an integration plan's branches into its trunk

docs/design/fab.md 13.12 ("The plan lives on its trunk", "Merging, not
landing", "reviews"). `fab.plan.Plan` has `landing`, `ready`, `reviews`,
`direct` and `trunk`, and `fab.plan.parse_options` (task `replay-options`);
`fab.run.start`, `fab.rust_gates.screen`, `fab.foreman.start|commit` and
`fab.repairs.start|commit` take `trunk=` (task `replay-trunk`).

## What to change, all in `fab/dispatch.py`

- **The uncut stand-in** (`_load_plan` without plan.toml): its options are
  `parse_options` of the newest cut `call.started` of the draft's
  `options` (none: the defaults), passed to `designer.uncut`.
- **A checkout that tracks a branch follows it** (`_checkout`): after the
  fetch, when `git rev-parse --abbrev-ref --symbolic-full-name @{upstream}`
  succeeds in the checkout, `git merge --ff-only @{upstream}` (check=True: a
  failure is the plan's load failure, as a failed fetch is). Once per
  checkout, as the fetch.
- **Merging** (decide's landing step): for a plan whose landing is
  integration, a done task's action is `Action("merge", task, branch=...)`
  instead of land or ready (the optimistic-start hold stays as it is).
  Carrying it out: `rust_gates.screen(task, events, trunk=plan.trunk)`
  (findings: printed `rejected gate:...` as `_screen_ready` does), then
  `_merge_branch(branch, plan, checkout, task=<task id>)`:
  - in the plan's checkout: `git fetch origin`; `git reset -q --hard
    origin/<trunk>`; the branch's tip (`rev-parse` of
    `refs/remotes/origin/<branch>^{commit}`); `git -c user.name=fab -c
    user.email=fab@localhost merge --no-ff --no-edit <tip>`;
  - a failed merge: `git merge --abort`, then log `branch.rejected` (task,
    branch, tip, step `merge`, `findings` the merge output's last 40
    lines); return False;
  - a merge: `git push origin HEAD:refs/heads/<trunk>` (a plain push:
    origin refuses anything but a fast-forward; a refusal raises and the
    action fails, to be retried next tick), then log `branch.landed`
    (task, branch, tip, main = the new HEAD, into = the trunk); return True.
  - Idempotent: a branch already logged `branch.landed` with `into` the
    trunk returns True at once.
- **Every branch an integration plan delivers goes the same way:**
  `finish` of a call chain merges `calls/<id>` (task the branch's name),
  `_settle` merges `answers/<run>` and `_remedy` merges `repairs/<run>`,
  instead of `fab land` or `_queue_branch`. Put the choice in one helper,
  `_deliver(branch, plan, checkout) -> bool` (True once the branch is on the
  trunk): agents plans `fab land`, fabrig queue plans `_queue_branch`,
  integration plans `_merge_branch`. The spec commits pass
  `trunk=plan.trunk`.
- **Every run and foreman of the plan starts on the trunk:** `_start`,
  `_foreman` and `_examine` pass `trunk=plan.trunk` (thread `plan` through
  `_take` as it already is).
- **Reviews off:** with `plan.reviews` false, `_chain_actions` turns a
  chain in state `review` into `finish` (no review run), and
  `call_actions` starts no structure review call. Nothing else changes.

## Acceptance

Tests in `fab/tests/test_dispatch.py` (fake runner; real git only for the
merge itself, with the support fixture and a bare origin):
- decide gives `merge` for a done task of an integration plan, `ready` and
  `land` as before otherwise;
- a merge pushes the trunk and logs `branch.landed` with `into`; the
  task's dependent becomes runnable and its start's base is
  `origin/<trunk>`;
- a conflicting branch logs `branch.rejected` step `merge` with findings,
  and the trunk does not move;
- a cut chain of an uncut plan with `options` `reviews=false` and
  `landing="integration"` finishes without a review run and is merged into
  the trunk;
- a checkout tracking a branch is fast-forwarded after the fetch.
- `bin/fab test` passes within its budget.
