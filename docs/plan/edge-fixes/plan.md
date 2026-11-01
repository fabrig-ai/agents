# edge-fixes: the plan

One direct part, `edge-cases`, of two tasks, as the request says. They share
no file and no code, so both start at once:

1. `inputs-ignored` (item 1; `docs/design/integration.md` 3): `_check_paths`
   adds `--ignored`, so a local input a `.gitignore` hides is refused before
   the fast-forward overwrites it.
2. `retire-spelling` (item 2; `docs/design/calls.md` 3): `_retire_plan` finds
   the assignment through `designer._plan_header` and `tomllib`, whatever the
   key's spelling, and parses its final text before anything is committed.

The specs are in `tasks/`; the standing rules in `notes/common.md`, the
decisions and the critical path in `notes/decisions.md`. Each task edits the
one status file the request names; no design document changes.

## Overlaps with drafts beside this one

`acceptance-fixes/trunk-landed` changes `fab/dispatch.py`,
`fab/tests/test_dispatch.py` and `docs/design/integration.status.md`. None of
these overlaps could be avoided, and their hunks are disjoint, so whichever
lands second merges cleanly:

- `retire-spelling` must change `_retire_plan` (`fab/dispatch.py` ~859) and the
  tests that pin it (`fab/tests/test_dispatch.py` ~5342-5363).
  `trunk-landed` is at ~1666, ~1756 and ~2043 and at ~4606-5817 in the tests.
- `inputs-ignored` edits `docs/design/integration.status.md` ~84-85.
  `trunk-landed` edits ~31 and ~150.

`acceptance-fixes/precheck-receipt` shares no file with this plan.
