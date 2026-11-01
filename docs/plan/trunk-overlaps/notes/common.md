# Every trunk-overlaps task

The standing rules of this plan's implementers. Read this, then your spec's
family note, then your spec.

## Scope

- The design is `docs/design/fab.md`, 13.17 (drafts beside each other), with
  the sections your spec names. The request
  (`docs/plan/trunk-overlaps/inputs/request.md`) builds 13.17 whole and
  nothing past it: **report only**. Nothing waits on an overlap and nothing
  is started by one. Build none of 13.17's Later items (a build of the
  merged trees, landing at slice boundaries) and no hook for them.
- Change only your spec's `files`. A file you must touch outside them is a
  `Question:`, unless your spec pre-approves it.
- Names, signatures and record fields bound in your spec or the family note
  are binding: other tasks are written against them. Private helpers are
  yours to name.
- Follow the design. Where the code shows the design cannot hold as
  written, change `docs/design/fab.md` 13.17 (and the line in
  `docs/design/fab.status.md` that says it) in the same branch, say so in
  your report, and keep the change to that point. Otherwise do not edit the
  design or its status file: the status is the designer's.

## Code

- Python 3.13 standard library only. Write files through `fab.atomic.write`.
  Pure functions take the log's records (`list[dict]`, as `fab.log.read`
  gives them) and return values; only `main`s and the tick's steps write.
- Log through `fab.log.append` (flat fields: scalars or lists of scalars).
  Record types and fields are fab.md section 3's table, exactly:
  `trunks.overlap` with `drafts`, `tips`, `files`, `more`, `reason`.
- Match the surrounding code: docstrings that say what a function returns
  and cite the design section, as `fab/tier_reds.py` and `fab/channel.py`
  do; module constants with a comment. `fab.dispatch` imports
  `fab.designer`, so nothing imported by `fab.designer` at module level may
  import `fab.dispatch`.
- The taste file `fab/taste.md` applies.

## Tests

- Every behaviour your spec's acceptance names has a test in
  `fab/tests/`, with `fab.tests.support.tmp_home()` as HOME and
  `fab.tests.support.FakeRunner` for every command; never live state, never
  a real `git merge-tree`.
- Checks before you hand over: `python3 -B -m fab.testrun` (`bin/fab test`)
  green, the whole suite under its 30 s budget (no sleeps);
  `bin/fab status docs/plan/trunk-overlaps` shows no plan problems.

## Commits and the report

- One or a few commits, each message saying why, ending with the trailer
  your run's brief gives.
- Your report's first line: `Done: <what landed, one line>`, `Question:
  <what you need>` (with the options and your recommendation) or `Failed:
  <why>`. Then: what you built, by function; the tests added; any default
  your spec pre-approved that you took, and any departure from the design
  with the doc change that records it.
