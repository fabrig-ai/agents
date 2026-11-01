+++
id = "retired-import"
part = "retired-import"
kind = "feature"
needs = ["brief-park"]
files = ["fab/dispatch.py", "fab/tests/test_dispatch.py"]
effort = "medium"
minutes = 45
+++
# A retired plan's last landing is imported

Read first: `docs/plan/start-commands/notes/common.md`,
`docs/plan/start-commands/notes/decisions.md` (6, 7), then
`docs/design/tick.md` 5, "A plan that cannot load", and
`docs/design/landing.md` 3 (the queue's import).

The request's item 4, found by the probe `phase-case`: the queue landed
its retire (`calls/retire-2c39…`) on fabrig main, but the tick read
`retired = true` and skipped the plan in `_load_plans`; its draft left
`plan_drafts`, so `_import_queue` never owned the record: no
`branch.landed`, no `call.finished`.

## What to build

- **`_load_plans`** (~1187): the `retired=` keyword (decision 6); its
  return and its other callers (`fab/designer.py` `_compile`) unchanged.
- **`_round`** (~1100) and **`_reconcile_reds`** (~1060): the retired
  plans' drafts join `plan_drafts` for `_import_queue` (owners and
  cursor), and nowhere else; after the import, whether or not any plan
  loaded, the retired finish (decision 7) runs for each retired plan.
- **One new private function** for the finish (decision 7), beside
  `_record_finish` (~958).
- Docstrings of `_load_plans` and `_round` say so as built.

## Acceptance

In `fab/tests/test_dispatch.py`, beside the existing `_round` and
`_load_plans` tests, with a fixture log and a fake queue record (the
`fab queue log` reply through FakeRunner, as the import tests do):

- A fabrig plan with `retired = true` whose log holds the retire's
  `call.started` (branch `calls/retire-…`), `call.ended` done, a
  `call.checked` and `branch.ready`, and the queue a `landed` record for
  that branch: one tick logs `branch.landed` (with `queue_ts`) then
  `call.finished` (role `retire`, outcome `done`, the checked tip); a
  second tick logs neither again.
- The same with the retired plan the only listed one (no plan loads).
- Nothing else runs for it: no `call.started`, no run, no `merge`, no
  overlap record, `retired <draft>` still printed.
- A retired plan whose retire already has `call.finished` gets nothing new.
- `bin/fab test` green.

## Pre-approved defaults

- Rebase over `brief-park`'s `_call` and `_parked_subjects` changes; yours
  are in the functions above only.

## Report

The functions changed, the records a tick writes for a retired plan, and
the tests added.

## Rebase (2026-11-01, step rebase, foreman start-commands/retired-import/foreman-1)

retain both independently added test classes when rebasing over main
The rebase of ce7c302 conflicts in `fab/tests/test_dispatch.py`.
Main commit 3806c34adfffc75b0995df20e816f8133cf793fc adds `CutOptionsFinishTest` at the same insertion point where this branch adds `RetiredFinishTest`, between `RetireFinishTest` and `IntegrationDeliveryTest`.
Resolve by retaining both complete classes, each with its own `setUp` and methods.
Preserve main’s `tomllib` import and cut-option tests, plus this branch’s retired-plan import and finish tests.
`fab/dispatch.py` auto-merged; preserve both sets of changes without expanding this task’s scope.
Stage the resolved test file, continue the rebase, and run `bin/fab test`.
