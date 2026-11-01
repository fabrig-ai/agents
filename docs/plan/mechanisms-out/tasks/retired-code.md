+++
id = "retired-code"
part = "retired-code"
kind = "feature"
needs = []
files = ["fab/dispatch.py", "fab/tests/test_dispatch.py", "fab/roles/retire.md", "fab/roles/consistency.md", "fab/designer.py"]
effort = "high"
minutes = 50
+++
# `retired = true` is code's

Read first: `docs/plan/mechanisms-out/notes/common.md`,
`docs/plan/mechanisms-out/notes/decisions.md` (2, 3, 4).

The request, item 1. Design: `docs/design/calls.md`, 3, "retire"
("**`retired = true` is code's** (the user, 11-01 ...)").

## What to build

- `fab/dispatch.py`, a private `_pre_deliver(action, plan, plan_dir,
  checkout, *, sh, log_path)`, called in `_take`'s `finish` case (~1012)
  before `_deliver`. For a finish whose `run_kind` is `retire` (a chain
  that ended done), with the guards of decision 2 and only when the
  branch's plan.toml does not already parse `retired` True (`tomllib`), it
  commits with `fab.spec_edit.commit_path(<plan dir>/plan.toml, checkout,
  edit, branch=action.branch, trunk=action.branch, worktree=log.home() /
  "retire" / action.task, message=f"{plan.draft}: retired", sh=sh)`. The
  edit replaces a `retired = false` line, or inserts `retired = true`
  before the first table line; an edit finding no plan.toml (empty text)
  raises.
- `_take` (~973): a failure in `_pre_deliver` logs a note and records no
  `call.finished` (`finally` -> `_record_finish` runs only once the
  delivery ran); the next tick tries again.
- `_queue_branch` (~814): also re-readies when origin's tip differs from
  the last `branch.ready`'s `tip`, besides a later `call.ended` on the
  branch (decision 4).
- `fab/roles/retire.md` (~19): drop the `retired = true` bullet; say fab
  sets it when the call ends done, and that the call does not touch
  plan.toml.
- `fab/roles/consistency.md`: drop "and marked the plan retired" (~5) and
  the "The plan not retired" bullet (~20).
- `fab/designer.py`'s module docstring (~8): retire brings the status files
  current; fab marks the plan retired. No code change in `designer.py`.

## Acceptance

- dispatch: a finish of a done retire chain of a queue plan (repo agents,
  `_land_branch` patched) commits `retired = true` on `calls/<root>` from
  the worktree `FAB_HOME/retire/<root>`, then delivers; the commit comes
  first in the runner's calls.
- dispatch: the edit replaces `retired = false`; inserts before the first
  table line when absent; a plan.toml already retired, a branch a
  `branch.landed` names, or one gone from origin makes no commit and the
  delivery runs as today.
- dispatch: a failing commit or push logs a note and no `call.finished`;
  a fabrig plan's `_queue_branch` readies the committed tip.
- dispatch: `_queue_branch` re-readies when origin's tip moved since the
  last `branch.ready` with no later `call.ended`; same tip, no re-ready.
- `bin/fab test` green.

## Pre-approved defaults

- An integration plan's retire before its trunk landed takes the same
  commit on its branch; `_deliver` then merges that tip.
- Write `_pre_deliver` so `plan-options` can add its restore beside the
  retire commit (one guard, one note path); its name and parameters are
  free, the docstring says what runs.

## Report

The helper as built, the guards and where each is read, the
`_take`/`_record_finish` change, and the tests added.
