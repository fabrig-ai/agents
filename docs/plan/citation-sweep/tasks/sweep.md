+++
id = "sweep"
part = "sweep"
kind = "feature"
needs = []
files = ["fab/dispatch.py", "fab/wake.py", "fab/calls.py", "fab/spec_edit.py", "fab/forge.py", "bin/heavy", "fab/tests/test_dispatch.py", "docs/design/qa.status.md"]
effort = "medium"
minutes = 15
+++
# Pre-split citations name the design and section they now mean

Read first: `docs/plan/citation-sweep/notes/common.md`,
`docs/plan/citation-sweep/notes/decisions.md`, then `docs/design/fab.md` 6.

The request: rewrite each citation to the design and section it now means, by
section 6's second table, checking that the cited text is there. Comments and
docstrings only.

## What to build

Replace only the citation on each line; line numbers are approximate.

- **`fab/dispatch.py`:**

| Line | Now | Becomes |
|---|---|---|
| ~1 | `docs/design/fab.md, 6` | `docs/design/tick.md, 1` |
| ~73 | `docs/design/fab-gates.md, 2; fab-calls.md, 2; fab-tick.md, 5` | `docs/design/gates.md, 2; calls.md, 2; tick.md, 5` |
| ~244 | `docs/design/fab-calls.md, 2` | `docs/design/calls.md, 2` |
| ~385 | `docs/design/fab-tick.md, 4` | `docs/design/tick.md, 4` |
| ~403 | `fab-integration.md 3` | `integration.md 3` |
| ~488 | `docs/design/fab-integration.md, 3` | `docs/design/integration.md, 3` |
| ~599 | `docs/design/fab-landing.md, 3` | `docs/design/landing.md, 3` |
| ~659 | `docs/design/fab.md, 13.8 and 13.15` | `docs/design/landing.md, 3; qa.md, 2` |
| ~1173 | `docs/design/fab-tick.md, 6` | `docs/design/tick.md, 6` |
| ~1210 | `docs/design/fab-landing.md, 3` | `docs/design/landing.md, 3` |
| ~1411 | `docs/design/fab.md, 13.15` | `docs/design/qa.md, 2` |
| ~1419 | `docs/design/fab.md, 13.15` | `docs/design/qa.md, 2` |
| ~1455 | `docs/design/fab-qa.md, 2` | `docs/design/qa.md, 2` |
| ~1484 | `docs/design/fab-qa.md, 2` | `docs/design/qa.md, 2` |
| ~2049 | `fab-integration.md 3` | `integration.md 3` |

- **`fab/wake.py` ~1:** `docs/design/fab-tick.md, 6` becomes
  `docs/design/tick.md, 6`.
- **`fab/calls.py` ~1:** `docs/design/fab.md, 6` becomes
  `docs/design/calls.md, 1`.
- **`fab/spec_edit.py` ~48:** `docs/design/fab.md, 13.15` becomes
  `docs/design/qa.md, 2`.
- **`fab/forge.py` ~63:** `(13.6)` becomes `(docs/design/channel.md, 3)`.
- **`bin/heavy` ~2:** `docs/design/fab.md, 7` becomes
  `docs/design/machines.md, 2`. Keep the file's mode.
- **`fab/tests/test_dispatch.py` ~6653:** `docs/design/fab-integration.md, 3`
  becomes `docs/design/integration.md, 3`.
- **`docs/design/qa.status.md` ~73:** delete the "Stale citations" bullet.

## Acceptance

- `grep -rnE "fab-[a-z-]+\.md" fab/ bin/` gives only
  `fab/tests/test_dispatch.py` ~665.
- `grep -rnE "fab\.md, ?([6-9]|1[0-9])|fab\.md [0-9]+\.[0-9]+|\(13\.[0-9]+\)" fab/ bin/`
  gives nothing.
- `git diff --numstat main` shows equal insertions and deletions for every
  file but `docs/design/qa.status.md`, 21 lines in all.
- `bin/fab test` green.

## Pre-approved defaults

- A line has moved: find it by its text. Main's new lines may hold a citation
  this table lacks; rewrite one that is an old name by the same rule and list
  it in the report.
- The cited text is not in the section this table gives: cite the section that
  holds it and say so in the report. If no section does, leave the line and
  say so.
- A rewritten line runs over a limit: rewrap within the docstring. That breaks
  the equal-lines check for that file; say so in the report.
- Citations that stay (decisions 2, 6-10): do not touch them. A test that
  fails over a rewritten citation is a `Question:` (the cut found none).

## Report

The number of lines rewritten, and any departure from the table. Name the
citations left, each with why: `fab/atomic.py`'s `fab.md, 2`, whose text is in
no design, and `fab/tests/test_dispatch.py` ~665, a test's string. No machine
action.
