+++
id = "plan-inputs"
part = "plan-inputs"
kind = "feature"
needs = []
files = ["fab/inputs.py", "fab/cli.py", "fab/tests/test_inputs.py"]
effort = "high"
minutes = 60
+++
# `fab plan inputs PLAN_DIR FILE... [--replace]`

Read first: `docs/plan/start-commands/notes/common.md`,
`docs/plan/start-commands/notes/decisions.md` (2, 3), then
`docs/design/integration.md` 3, "The plan lives on its trunk", the `fab
plan inputs` item whole.

The request's item 2: today `inputs/` is written and committed by hand.

## What to build

- **`fab/inputs.py`** (new): `add(plan_dir, files, *, replace=False,
  sh=run, log_path=None) -> list[str]` and `main(argv)` for `fab plan
  inputs PLAN_DIR FILE... [--replace]`, printing the returned repository
  paths (`<plan path>/inputs/<name>`, for `fab call cut --source`) and,
  for a fabrig ready ref, that the cut waits for its `queue.landed` and
  for the checkout to hold the files.
  - The checkout is `git rev-parse --show-toplevel` from PLAN_DIR's
    nearest existing ancestor; its kind from `fab.designer.repository`
    and `git rev-parse --abbrev-ref --symbolic-full-name @{upstream}`
    (detached: `git symbolic-ref -q HEAD` fails); the draft PLAN_DIR's
    name; `<trunk>` `<draft>/integration` for a checkout tracking
    `origin/<draft>/integration`, else `main`.
  - Every refusal of the design, a ValueError before any commit: plan.toml
    in PLAN_DIR, or PLAN_DIR listed (`fab.channel.plan_dirs()`); a FILE
    missing, or two sharing a name; `inputs/<name>` at `origin/<trunk>`
    without `--replace` (`git cat-file -e`), or untracked or changed in
    the checkout (`git status --porcelain -- <path>`); the branch or ready
    ref it would push already on origin (`git ls-remote --exit-code`),
    except `--replace` over its own `ready/inputs/<draft>`; the draft
    `inputs`; a checkout tracking any other branch (agents: only
    `origin/main`; fabrig: `origin/main`, `origin/<draft>/integration` or
    detached).
  - After `git fetch origin`: a temporary worktree, `git worktree add
    --detach <tmp> origin/<trunk>`, the files copied (directories whole;
    with `--replace` the old one removed first) to
    `<plan path>/inputs/<name>`, `git add`, the commit `<draft>: inputs`
    as fab, the push, and `git worktree remove --force <tmp>` in a
    `finally`, so every outcome leaves no commit, file or local branch in
    the checkout. Never a commit in the checkout itself.
  - The push per kind: a trunk checkout `HEAD:refs/heads/<draft>/integration`
    (no force); agents `HEAD:refs/heads/inputs/<draft>`, then
    `fab.land.main([f"inputs/{draft}"])`, and on its refusal `git push
    origin --delete inputs/<draft>` and a ValueError naming the step (the
    last `branch.rejected` of the branch in the log); fabrig otherwise
    `HEAD:refs/heads/ready/inputs/<draft>` (forced only with `--replace`).
  - After a trunk push or a landing, under `FAB_HOME/tick.lock`
    (`fcntl.flock`, as `fab/dispatch.py` `tick` ~1047): `git fetch
    origin` and `git merge --ff-only @{upstream}` in the checkout. A
    detached checkout is not moved; print that the operator moves it.
- **`fab/cli.py`:** `"plan": ("fab.inputs", "a plan's inputs: commit them
  on its trunk or land them")`, right after `"status"` (decision 2).

## Acceptance

In `fab/tests/test_inputs.py`, on real git (`git_pair`, `GIT_ENV`), each
outcome checking the checkout has no new commit, no stray file and no
temporary worktree left (`git worktree list`):

- A trunk checkout (tracking `origin/d/integration`): a file and a
  directory reach `origin/d/integration` in one commit `d: inputs`, the
  checkout is fast-forwarded to it, the paths printed.
- An agents checkout: `inputs/d` pushed and `fab.land.main` run with
  `fab.land.land` patched; landed: the checkout fast-forwarded; refused:
  `inputs/d` deleted from origin, exit 1 with the step.
- A fabrig checkout tracking `origin/main`: `ready/inputs/d` pushed, the
  checkout not moved, the waiting line printed; `--replace` replaces it.
- A detached fabrig checkout: pushed, the checkout left, the line printed.
- Each refusal of the design changes nothing on origin or in the checkout.
- `bin/fab test` green.

## Pre-approved defaults

- `fab.designer.repository` reads `fab.run.REMOTES`: the tests patch
  `REMOTES` so the temporary origin's URL is `agents` or `fabrig`.
- `fab.land.main` clones when `FAB_HOME/repos/agents` is missing and
  `land()` runs `bin/fab test`: the tests create that directory and patch
  `fab.land.land` to return a `fab.land.Outcome`.
- The temporary worktree lives under `tempfile.TemporaryDirectory()`.

## Report

The argv of each push kind, in order, the refusals' messages, and the
tests added.
