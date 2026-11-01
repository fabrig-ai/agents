+++
id = "trunk-make"
part = "trunk-make"
kind = "feature"
needs = []
files = ["fab/trunk.py", "fab/cli.py", "fab/tests/test_trunk.py"]
effort = "medium"
minutes = 45
+++
# `fab trunk make PLAN_PATH [--base REV]`

Read first: `docs/plan/start-commands/notes/common.md`,
`docs/plan/start-commands/notes/decisions.md` (2, 3), then
`docs/design/integration.md` 3, "The plan lives on its trunk", the `fab
trunk make` item whole.

The request's item 1: today an operator branches, pushes and adds the
worktree by hand.

## What to build

- **`fab/trunk.py`** (new): `make(plan_path, *, base="origin/main", sh=run,
  log_path=None) -> Path` and `main(argv)` for `fab trunk make PLAN_PATH
  [--base REV]`, printing the returned plan directory (the path to give
  `fab plan inputs` and `fab call cut --plan`). The clone is
  `FAB_HOME/repos/fabrig`; the worktree `FAB_HOME/integration/<draft>`,
  the draft PLAN_PATH's last segment. In the design's order:
  1. `git fetch --prune origin` in the clone;
  2. the refusals, each a ValueError changing nothing: PLAN_PATH not a
     relative `<prefix>docs/plan/<draft>` (the same test as
     `fab/designer.py` `_prepare` ~548, `parts[-3:-1] == ("docs",
     "plan")`); `REV:PLAN_PATH/plan.toml` exists (`git cat-file -e`);
     `<draft>/integration` exists on origin (`refs/remotes/origin/...`,
     the fetch just pruned) or as a local branch; the worktree path
     exists;
  3. `git worktree add -b <draft>/integration <worktree> <REV>`;
  4. from the worktree, `git push -u
     --force-with-lease=refs/heads/<draft>/integration: origin
     <draft>/integration`; when it fails (refused or not), `git worktree
     remove --force <worktree>` and `git branch -D <draft>/integration` in
     the clone, then the error;
  5. only then `log.append("trunk.made", draft=..., base=<REV as given>,
     tip=<the worktree's HEAD sha>)`.
- **`fab/cli.py`:** `"trunk": ("fab.trunk", "make a plan's integration
  trunk and its worktree")`, right after `"check"` (decision 2).

## Acceptance

In `fab/tests/test_trunk.py`, on real git (a bare origin and the clone as
`FAB_HOME/repos/fabrig`, `git_pair`):

- A make from `origin/main` creates the worktree on `<draft>/integration`
  tracking `origin/<draft>/integration`, pushes the branch, logs one
  `trunk.made` with the base and tip, prints the plan directory; `--base`
  with another commit uses it.
- Each refusal leaves no worktree, local branch, origin branch or log
  record: a PLAN_PATH not under `docs/plan/` (and an absolute one); REV
  holding `PLAN_PATH/plan.toml`; the branch on origin; the branch only
  local; the worktree path present.
- A refused push (a `pre-receive` hook in the bare origin that exits 1)
  leaves no worktree, no local branch and no `trunk.made`; exit 1.
- `fab trunk make` with no PLAN_PATH: exit 2.
- `bin/fab test` green.

## Pre-approved defaults

- The real-git tests set FAB_HOME through `tmp_home()`; nothing reads the
  machine's fabrig clone.
- The tip is read with `git rev-parse HEAD` in the worktree after the push.

## Report

The argv of a make, in order, the refusals' messages, and the tests added.
