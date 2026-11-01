+++
id = "overlaps-records"
part = "probe-cuts"
kind = "feature"
needs = ["overlaps-cache"]
files = ["fab/overlaps.py", "fab/tests/test_overlaps.py", "fab/serve.py", "fab/tests/test_serve.py"]
effort = "medium"
minutes = 35
+++
# A malformed trunks.overlap is ignored, never fatal

Read first: `docs/plan/paper-cuts/notes/common.md`,
`docs/plan/paper-cuts/notes/overlaps.md` ("A well-formed
`trunks.overlap`"), `docs/plan/paper-cuts/notes/decisions.md` (6).

The request (2): "**A malformed record is ignored, never fatal** (the
probe's folds and `fab/serve.py`'s overlaps)". Design:
`docs/design/integration.md`, 4, "A malformed record is ignored, never
fatal".

## What to build

- `fab/overlaps.py`: one public predicate, `well_formed(event: dict) ->
  bool`, true for a `trunks.overlap` whose fields are as the family note
  says. `is_news` (near line 68) reads the pair's last well-formed record;
  `open_pairs` (near line 80) folds only well-formed records (replacing its
  `drafts`-only check), so `gone_pairs` and the page read only them.
- `fab/serve.py`, `_public_overlaps` (near line 195): reads `open_pairs`
  as now; change it only if a test shows a malformed record can still reach
  it or break `render`.

## Acceptance

Tests in `fab/tests/test_overlaps.py`:
- `well_formed` refuses, each alone: `drafts` of one or three items or a
  non-string, `tips` missing or not two strings, `files` not a list or
  holding a non-string, `more` negative, a `bool`, a string or missing;
- a malformed record after a well-formed one for the same pair: `is_news`
  and `open_pairs` read the well-formed one; `gone_pairs` closes from it;
- `probe` over a log holding a malformed record completes and logs as if
  it were absent.

Tests in `fab/tests/test_serve.py`: `snapshot` and `render` over a log
holding malformed `trunks.overlap` records (each malformation above) do not
raise, and show only the well-formed pairs; the existing tests pass
unchanged.

## Report

The predicate's checks as built, and whether `fab/serve.py` changed.
