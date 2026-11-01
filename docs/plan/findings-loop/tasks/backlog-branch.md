+++
id = "backlog-branch"
part = "tick"
kind = "feature"
needs = ["tick-triage", "triage-decisions"]
files = ["fab/dispatch.py", "fab/spec_edit.py", "fab/tests/test_dispatch.py", "fab/tests/test_spec_edit.py"]
effort = "high"
minutes = 50
+++
# The backlog readied as a fab branch, and its landing home

Read first: `docs/plan/findings-loop/notes/common.md`,
`docs/plan/findings-loop/notes/triage.md`,
`docs/plan/findings-loop/notes/tick.md`.

The request: "rendering and readying the backlog"; off the path, "the
backlog". Design: `docs/design/fab.md`, 13.15, "Off the path is the tree's
backlog" ("Readied as a fab branch", "Its landing comes home", the two
rejections), and 13.8 (fab's branch forms kept out of `queue.*`).

## What to build

- `fab.spec_edit.commit_path(path: str, checkout, edit, *, branch,
  message, worktree, sh=run, trunk="main") -> str | None`: `commit` with a
  repository path instead of a task; a file missing at `origin/<trunk>`
  reads as "" and is added (`git add -- <path>` before the commit). `commit`
  becomes `commit_path` of the task's path, its argvs unchanged (its tests
  pass as they are).
- `fab.dispatch._queue_branch(..., **fields)`: passed through to
  `branch.ready` (`section` stays as it is).
- `_import_queue` (near line 389): owners include each
  `ladder/<draft>/backlog-<n>` with a `branch.ready`, mapped to its draft;
  `ladder/` joins the fab branch forms kept out of `queue.*`.
- The backlog step in `_tick_plan` for a plan with rungs, after
  tick-triage's steps: render `fab.triage.backlog_text(plan, events)`;
  when it differs from `plan.ladder.backlog` at `origin/main` of the plan's
  checkout, no backlog branch of the plan is readied and not yet landed or
  rejected, and `fab.triage.backlog_held(plan, events,
  render_key(render))` is None: commit it with `commit_path` on
  `ladder/<draft>/backlog-<n>` (n one more than the plan's backlog
  branches with a `branch.ready`), and ready it with `_queue_branch(...,
  render=render_key(render))`. A commit that fails: a note, tried again on
  a later round.

## Acceptance

Tests in `fab/tests/test_dispatch.py` and `fab/tests/test_spec_edit.py`
(13.15's "Tests", the backlog cases):
- the backlog is readied as `ladder/<draft>/backlog-1` when it differs
  from main, and not again while that branch is pending;
- its queue `landed` imports as `branch.landed` with task the branch, and
  advances the draft's cursor; a later decision readies `backlog-2`;
- a rejection readies the next n; a second rejection of the same render
  readies none, until the render changes or `backlog:<draft>` is cleared;
- an unchanged render readies nothing;
- `commit_path` creates a missing file; `commit`'s argvs are unchanged.

## Pre-approved defaults

- The commit message: `ladder <draft>: the backlog from the log
  (<k> findings)`.
- The worktree under `FAB_HOME/backlog/<draft>-<n>`.

## Report

The step, the import's change, and `commit_path`'s argvs.

## Repair (2026-11-01, step gate:size, foreman findings-loop/backlog-branch/foreman-1)

Extract queue-record classification from `_import_queue` to meet the 60-line cap.
`gate:size` reports `fab/dispatch.py:468`: `_import_queue` is 79 lines (cap 60).
In `fab/dispatch.py`, extract the per-entry classification and field construction into a private helper, from branch validation through the owned/unowned fields.
Return the event kind and fields, or None for skipped records; keep cursor selection, fetching, deduplication and appending in `_import_queue`.
Keep both functions within the size cap without compressing statements.
Preserve docs/design/fab.md §13.15: readied backlog branches belong to their draft, import with task equal to the branch, and landed records retain `into=""`.
Preserve §13.8 filtering, collateral handling, string-only test names and deduplication.
Keep this a behavior-preserving refactor within `fab/dispatch.py`; retain the existing queue-import and backlog tests in `fab/tests/test_dispatch.py`.
Run `python3 -B -m fab.testrun` and the size gate before handing back the branch.
