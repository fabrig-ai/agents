# acceptance-fixes: the plan

Two direct parts, one task each, in the request's order:

1. `precheck-receipt` (items 1-2; `docs/design/landing.md` 3, changed in the
   request's commit): the receipt counts `unobserved` beside `starved`,
   `fab.receipts.reusable` refuses a receipt with either, and `_checks`
   removes each profile's `records` directory from the builder. Item 1's
   fault is live now, and its fix reaches the queue only once
   `fab-queue.service` restarts on the new code (`notes/decisions.md` 3).
2. `trunk-landed` (items 3-5; `docs/design/integration.md` 3, "Retire waits
   for main"): `_settle` and `_remedy` commit from `integration.call_base`, a
   task started from main after the landing lands or readies instead of
   merging, `task_rebase` compares with the same base, and `_foreman`'s
   fix-kind base gets its test.

The specs are in `tasks/`; the standing rules in `notes/common.md`, the
decisions and the critical path in `notes/decisions.md`. Each task edits the
status file the request names; no design document changes.

## Overlaps with drafts beside this one

- `test-budget` changes `fab/testrun.py`, `fab/tests/test_testrun.py` and
  `fab/cli.py`. This plan changes none of them: no overlap to avoid.
