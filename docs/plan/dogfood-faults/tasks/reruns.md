+++
id = "reruns"
part = "reruns"
kind = "feature"
needs = []
files = ["fab/run.py", "fab/tests/test_run.py", "fab/tests/test_dispatch.py"]
effort = "high"
minutes = 50
+++
# A rerun continues from its pushed work, or starts from the base

Read first: `docs/plan/dogfood-faults/notes/common.md`,
`docs/plan/dogfood-faults/notes/decisions.md` (10).

The request, item 5 and item 7's first paper cut. Design:
`docs/design/tick.md`, 3 ("The rerun (kind `repair`) continues from the
branch the run pushed, or starts from the task's base when the run pushed
nothing", and "A rerun continues from the work its earlier run pushed").

## What to build

`fab/run.py`, `_prepare_and_launch` (~300-350), sharing one check of
whether `refs/remotes/origin/<branch>` exists after the fetch (the slot
path's `rev-parse -q --verify` today, ~328):

- Slot path: a `repair` start uses `origin/<branch>` when it exists and
  the base otherwise (today `origin/<branch>` always).
- Worktree path (repositories without slots, this one): `repair` as above;
  `implement` continues from `origin/<branch>` when it exists and merges
  the base in, aborting the merge on a conflict and leaving it for the run,
  as the slot path does; otherwise both start at the base (`worktree add
  -B <branch> <worktree> <base>`, as today).
- `start`'s docstring says so for both paths.

## Acceptance

- A repair start whose `origin/<branch>` is absent switches (slot) or
  adds the worktree (worktree) at the base; present, at `origin/<branch>`.
- A worktree implement rerun with `origin/<branch>` present starts there
  and runs the base merge; a conflicting merge is aborted and the start
  goes on; absent, it starts at the base as today.
- The slot path's implement continuation is unchanged.
- `bin/fab test` green.

## Pre-approved defaults

- `review` and `rebase` starts keep their bases.
- A test pinning today's worktree argv changes only where the rule changes.

## Report

The check as shared, each path's source by kind, and the tests added or
changed.

## Answers

2026-11-01. May this task update `fab/tests/test_dispatch.py` so
`OptimisticStartTest.remote` reports an absent task branch for the new
probe? Yes: its own acceptance (`bin/fab test` green) needs it. Make that
fixture return `Result(1)` for `rev-parse -q --verify` (the first start has
pushed nothing) and keep its skeleton-base assertion; change nothing else in
that file. `files` now lists it.
