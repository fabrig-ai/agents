+++
id = "plan-options"
part = "plan-options"
kind = "interface"
needs = ["retired-code"]
files = ["fab/calls.py", "fab/tests/test_calls.py", "fab/designer.py", "fab/tests/test_designer.py", "fab/dispatch.py", "fab/tests/test_dispatch.py", "fab/roles/cut.md", "fab/roles/cut-fabrig.md", "fab/roles/cut-run.md"]
effort = "high"
minutes = 60
+++
# Plan options written by code

Read first: `docs/plan/mechanisms-out/notes/common.md`,
`docs/plan/mechanisms-out/notes/decisions.md` (2, 5, 6).

The request, item 2. Design: `docs/design/integration.md`, 3, "The cut's
inputs" ("Code writes them, not the cut (the user, 11-01)").

## What to build

- `fab/calls.py` `start` (~477): `seed: Mapping[str, str] = {}`
  (repository path -> text). After `worktree add` and before
  `call.started`, write each path in the worktree, `git add` it and commit
  as fab, `<draft>: plan options` (decision 5). An empty seed runs nothing
  new.
- `fab/designer.py`: the seed renderer and the restore helper (decision
  6). `main` (~466) seeds every cut's `<plan_path>/plan.toml` (not with
  `--brief-only`), options under the comment only when `--set` gave any.
- `fab/designer.py` `cut_brief` (~320): the `The draft` line becomes the
  design's "- Plan: `<path>/plan.toml` exists on your branch with `draft`,
  `repo`, `sources` (and fab's plan options); add `[buffer]` and the
  tables below those lines, never repeating or changing them".
  `_cut_role_options` (~251): the `Plan options` text says fab wrote these
  keys at the top of plan.toml and they stay as they are, not "Write ...
  verbatim". Both docstrings follow.
- Role texts: `fab/roles/cut.md` drops its `draft`, `repo`, `sources`
  bullet (keeps `[buffer]`); `fab/roles/cut-fabrig.md` drops "set `repo =
  \"fabrig\"`"; `fab/roles/cut-run.md`'s "What you write" first bullet
  (~87) becomes "`plan.toml` exists on your branch with `draft`, `repo`,
  `sources` and fab's plan options; add below them:", and its template
  drops its `draft`/`repo`/`sources` lines and `# the plan options,
  verbatim` (~93).
- `fab/dispatch.py`, the restore, against the root cut's `call.started`
  `options` (`parse_options`), comparing by parsed value:
  - integration plan: in `_merge_branch` (~698), after a clean merge of
    the cut's branch and before the push, rewrite the trunk's plan.toml in
    the checkout and commit `<draft>: plan options restored` (`FAB_GIT`);
    never on the cut's branch;
  - queue plan: in `_pre_deliver`, for a cut's finish, a
    `fab.spec_edit.commit_path` on the cut's branch (`trunk=` the branch,
    worktree `log.home() / "options" / <root>`), with retire's guards and
    open finish; a missing plan.toml makes no restore and raises nothing.

## Acceptance

- calls: `start(..., seed={path: text})` writes, adds and commits the path
  after `worktree add` and before `call.started`; no seed, no commit.
- designer: a cut seeds `draft`, `repo`, `sources`; with `--set` also the
  comment and one `<key> = <json>` line per option; `--brief-only` seeds
  nothing; the brief's fact line and `Plan options` text as above.
- designer: the request's pins change: `fab/tests/test_designer.py` ~574,
  ~612, ~885, ~888 and ~965 (the plan fact line and the `Plan options`
  text).
- dispatch: an integration cut's clean merge whose plan.toml lost or
  changed an option commits the restore on the trunk before the push; same
  values in another spelling, no commit; the cut's branch untouched.
- dispatch: a queue cut's finish restores on its branch before
  `_deliver`; no plan.toml, no restore and the delivery runs; a failing
  restore leaves the finish open.
- `bin/fab test` green.

## Pre-approved defaults

- A restore removes every top-level line assigning an option key and
  writes them under the comment, putting the comment back before the
  first table line when the cut removed it.
- A cut without `options` in its `call.started` gets no restore.
- `fab call cut`'s `_prepare` check that PLAN_DIR/plan.toml does not exist
  stays: it reads the checkout, not the branch.

## Report

`start`'s seed as built, the two helpers, each restore's site and guard,
the role-text changes, and the pins changed.
