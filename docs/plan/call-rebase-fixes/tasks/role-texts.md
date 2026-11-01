+++
id = "role-texts"
part = "land-refusal-fixes"
kind = "feature"
needs = []
files = ["fab/roles/settle.md", "fab/roles/amender.md"]
effort = "medium"
minutes = 20
+++
# Settle never lands a refused tip; the amender rebases at `test`

Read first: `docs/plan/call-rebase-fixes/notes/common.md`,
`docs/plan/call-rebase-fixes/notes/decisions.md` (4).

The request, findings 2 and 3 (minor). Design: `docs/design/calls.md`, 2,
"A `fab land` refusal counts as a refusal of the chain", its amend-brief and
hold sub-bullets. The settle brief already says land is not an option on a
`fab land` hold (`fab/call_review.py` ~449); the role text must agree.

## What to build

- `fab/roles/settle.md`, the `Done: land` and `Done: amend` lines (~7-10):
  add, verbatim, "When the brief says land would land a tip `fab land`
  refused, land is not an option: choose amend, or user when the brief says
  user only." Place it so it reads with both lines (after the `Done: amend`
  line's existing "When the brief says amend is no longer an option, ..."
  sentence, or as its own line after the list's `Done: amend` item).
- `fab/roles/amender.md`, the bullet "A refusal headed `fab land` refused
  at" (~15-23): at `test`, first `git fetch origin` and rebase the branch
  onto `origin/main` as at `rebase` (since `fab land` tested the branch
  rebased onto main), then reproduce and fix what the log names, run the
  checks and push with `git push --force-with-lease origin HEAD`. `paths`
  keeps "fix what the log names". "Ending" (~29-33): the rebase-and-force-
  push rule covers `test` as well as `rebase`.

## Acceptance

- Both files read as above; `bin/fab test` green; `bin/fab status
  docs/plan/call-rebase-fixes` shows no plan problems.

## Report

The two texts as they read now.
