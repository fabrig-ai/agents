# citation-sweep: the plan

One direct part, `sweep`, of one task: 21 lines in `fab/` and `bin/`, each
rewritten to the design and section it now means by `docs/design/fab.md` 6's
second table, and the `docs/design/qa.status.md` bullet that records four of
them as stale. Comments and docstrings only.

The spec is `tasks/sweep.md`; the standing rules are in `notes/common.md`, and
the decisions and the critical path in `notes/decisions.md`.

## Overlaps with drafts beside this one

- `dogfood-faults`, which the request runs after, has landed every task and
  retired.
- `acceptance-fixes` changed `fab/dispatch.py` and `fab/tests/test_dispatch.py`,
  which this plan also changes. Both its tasks have landed, so `sweep` starts
  from them and no overlap remains.
