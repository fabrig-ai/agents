+++
id = "trunk-landed"
part = "trunk-landed"
kind = "feature"
needs = ["precheck-receipt"]
files = ["fab/dispatch.py", "fab/tests/test_dispatch.py", "docs/design/integration.status.md"]
effort = "medium"
minutes = 45
+++
# A settle, and a task started from main, after a trunk landed

Read first: `docs/plan/acceptance-fixes/notes/common.md`,
`docs/plan/acceptance-fixes/notes/decisions.md` (7-9), then
`docs/design/integration.md` 3, "Retire waits for main".

The request's items 3, 4 and 5. Once the queue deleted `<draft>/integration`
and the clone pruned `origin/<trunk>`, a foreman's answer or a repair's
section fails at `worktree add` each tick, and a task started from main
fails each tick at `_merge_branch`'s reset, or never consumes its rebase.

## What to build

In `fab/dispatch.py`, these lines only:

- **`_settle`** (~1666): `foreman.commit(..., trunk=integration.call_base(plan,
  events))`.
- **`_remedy`** (~1756): `repairs.commit(..., trunk=integration.call_base(plan,
  events))`.
- **`_landing_actions`:**
  - ~2043: `call_review.task_rebase(tasks[identifier], events,
    trunk=integration.call_base(plan, events))`, so a rebase run from
    `origin/main` after the landing consumes the amendment.
  - ~2048: add `and not integration.trunk_landed(plan, events)` to the `merge`
    condition, so the task takes `land` or `ready` as a queue plan's does.

In `docs/design/integration.status.md`:

- Delete the gap bullet "A foreman's answer or a repair's section after the
  landing still commits from the trunk" (~150).
- In "Every call works from main once the trunk has landed" (~31): name
  `_settle` and `_remedy`, and the case of a task started from main after the
  landing, which `_landing_actions` lands or readies and whose rebase is
  compared with `origin/main`; add this plan to the bullet's plans.

## Acceptance

In `fab/tests/test_dispatch.py`:

- `test_answer_and_repair_specs_use_trunk_and_settle_only_after_merge`
  (~5817), item 3: landed subtests, `branch.landed` for `draft/integration`
  with `queue_ts` in the history as `test_foremen_start_on_trunk_then_main_after_queue_landing`
  does: `commit`'s `trunk` is `main`, `_merge_branch` is not called, and the
  branch goes through `_queue_branch`.
- Item 4, in `OptimisticStartTest` beside
  `test_integration_task_holds_merge_until_checked_skeleton_finishes` (~4606):
  with an integration plan whose trunk landed, `dispatch.decide` gives the
  done task `land`, not `merge`, and `ready` for a task whose repo is
  `fabrig`. Before the landing it stays `merge`.
- Item 4's rebase, beside `test_amended_skeleton_requires_rebase_with_its_diff_then_lands`:
  after the landing, an amended skeleton's completed `rebase` run with
  `base="origin/main"` is consumed, and the task lands; one with
  `base="origin/<trunk>"` is not.
- Item 5, beside `test_foremen_start_on_trunk_then_main_after_queue_landing`
  (~5801): a fix-kind task (`kind` from `fix.FIX_KINDS`, by
  `replace` on `self.tasks`) starts its foreman with `trunk="main"` both
  before and after the landing. Before the landing is the case that fails
  without `_foreman`'s fix-kind branch.
- `bin/fab test` green.

## Pre-approved defaults

- The test's closing `self.queue.assert_not_called()` holds for the subtests
  before the landing only: keep it there, and let the landed subtests
  assert `_queue_branch` was called. Patching `_queue_branch` in them, or
  logging its `branch.landed` with `queue_ts`, is fine.
- The plan in `IntegrationDeliveryTest` is `fabrig`; item 3's test needs no
  `agents` case.
- A test that pins `merge` or `plan.trunk` after a trunk landed, other than
  those named here, is updated and named in your report.

## Report

The sites changed, by function; the tests added. Machine action: none; the
tick follows main.
