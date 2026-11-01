+++
id = "overlaps-git"
part = "probe-git"
kind = "feature"
needs = []
files = ["fab/tests/test_overlaps_git.py"]
effort = "medium"
minutes = 40
+++
# The overlap probe against real git

Read first: `docs/plan/paper-cuts/notes/common.md`,
`docs/plan/paper-cuts/notes/overlaps.md`,
`docs/plan/paper-cuts/notes/decisions.md` (4 and 5).

The request (3): "A test of the probe against real git
(`fab.tests.support.git_pair()`): two trunks off main with one conflicting
path containing a space, main moved ahead; the probe logs that path; a bad
tree is a failure, not an overlap." Design:
`docs/design/integration.md`, 4, "The overlap probe" ("Each trunk as if
caught up", "The pair's merge").

## What to build

A new module `fab/tests/test_overlaps_git.py`, under `tmp_home()`, on
`git_pair()` (with `fab.tests.support.git` and `GIT_ENV`):
- in the clone, two integration trunks `<a>/integration` and
  `<b>/integration` off main, each changing one path with a space (for
  example `docs/two words.md`) differently, pushed to origin; then main
  moved ahead with an unrelated commit, pushed; the clone fetched;
- two ready integration plans for them (`fab.plan` values, or plans
  written as `fab/tests/test_overlaps.py` builds them), loaded with the
  clone as their checkout, passed to `fab.overlaps.probe(..., sh=fab.sh.run,
  log_path=...)` with the real runner.

## Acceptance

- The probe logs one `trunks.overlap` for the pair whose `files` is
  exactly `["docs/two words.md"]` (the path as written, space included),
  `more` 0, `tips` the trunks' tips; a second probe logs nothing.
- **A bad tree:** with `overlaps.json` written in the cache's first format
  holding, under the key the probe looks up for one trunk, a full-length
  hex tree id that is not in the object store, the probe logs no
  `trunks.overlap` for the pair, prints a failure line and logs one
  `note` with the pair's failure prefix.
- The module runs in well under a second of the suite's 30 s budget.

## Pre-approved defaults

- If real git shows the probe wrong (a path mangled, a merge refused), do
  not change `fab/overlaps.py`: report `Question:` with the failing case,
  git's output and the fix you recommend (decision 5).
- The cache key is built as `fab/overlaps.py`'s docstring says (a JSON
  list of repository, checkout, main's sha, tip); read the key from a
  first probe's file if that is simpler than building it.

## Report

The git version the test ran with, the commands the probe ran, and the
time the module takes.
