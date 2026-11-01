+++
id = "inputs-ignored"
part = "edge-cases"
kind = "feature"
needs = []
files = ["fab/inputs.py", "fab/tests/test_inputs.py", "docs/design/integration.status.md"]
effort = "medium"
minutes = 20
+++
# `fab plan inputs` refuses an ignored destination

Read first: `docs/plan/edge-fixes/notes/common.md`,
`docs/plan/edge-fixes/notes/decisions.md` (3-5), then
`docs/design/integration.md` 3, the `fab plan inputs` refusals (~179).

The request's item 1. The design refuses an `inputs/<name>` that "exists
untracked or changed in the checkout", but `git status --porcelain` hides
ignored files, so a local input hidden by a `.gitignore` is overwritten by the
fast-forward.

## What to build

- `fab/inputs.py`, `_check_paths` (~66): add `--ignored` to the `git status`
  call. The check of its output and the message stay.
- `docs/design/integration.status.md`, "The start commands" (~85): after "the
  refusals of 3 before any commit", say that `_check_paths` refuses any output
  of `git status --porcelain --ignored`, an ignored file included, and cite
  plan `docs/plan/edge-fixes`. Remove anything else there this makes too broad.

## Acceptance

In `fab/tests/test_inputs.py`, beside
`test_refuses_untracked_input_with_or_without_replace` (~231), on real git
through `_refused`, whose `_snapshot` already compares remote refs, HEAD and
worktrees:

- A pushed `.gitignore` hides `inputs/`, and the local file at `self.path` does
  not show in `git status --porcelain`. It is refused with `replace` false and
  true, and after each its bytes are unchanged.
- The same for a directory input: `files=[self.reviews]`, with a local ignored
  file under its destination, for both settings, its bytes unchanged.
- `bin/fab test` green.

## Pre-approved defaults

- `_seed_input`'s `git add .` commits the input too: seed the `.gitignore` in
  your own helper, moving `self.base` as `_seed_input` does.
- `_snapshot`'s `git status --porcelain` hides these files, so compare the
  bytes in the test. Adding them to `_snapshot` is not needed.
- A happy-path test that now refuses because a fixture left an ignored file at
  a destination is a `Question:`.

## Report

The site changed; the tests added; that they fail without `--ignored`. Machine
action: none.
