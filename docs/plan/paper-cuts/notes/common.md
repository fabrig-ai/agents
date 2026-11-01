# Every paper-cuts task

The standing rules of this plan's implementers. Read this, then your spec's
family note (the overlap tasks: `docs/plan/paper-cuts/notes/overlaps.md`),
then your spec.

## Scope

- The request (`docs/plan/paper-cuts/inputs/request.md`) builds three
  paper cuts, as already designed: `docs/design/calls.md`, 3, "retire";
  `docs/design/integration.md`, 4, "The overlap probe" (its cache and
  "A malformed record is ignored, never fatal"); and a real-git test of the
  probe. Nothing past them: not the park of calls.md 5 (Later), no
  change to the probe's pairs, events or page beyond what your spec says.
- Change only your spec's `files`. A file you must touch outside them is a
  `Question:`, unless your spec pre-approves it.
- Names, signatures and formats bound in your spec or the family note are
  binding: another task is written against them. Private helpers are yours
  to name.
- Follow the design. Where the code shows the design cannot hold as
  written, change its section (calls.md 3 or integration.md 4) in
  the same branch, say so in your report, and keep the change to that
  point. Otherwise leave the designs and their status files alone: they
  are the designer's (retire brings the status files current).

## Code

- Python 3.13 standard library only. Write files through `fab.atomic.write`.
  Commands go through the injected runner (`sh: Runner`, `fab.sh.run` by
  default), never `subprocess` directly.
- Match the surrounding code: docstrings that say what a function returns
  and cite the design section, as `fab/overlaps.py` and `fab/designer.py`
  do; module constants with a comment. The taste file `fab/taste.md`
  applies. Functions stay within the gates' 60-line cap (`fab/gates.py`);
  an existing long function must not grow.
- `fab.dispatch` imports `fab.designer`: nothing `fab.designer` imports at
  module level may import `fab.dispatch`.

## Tests

- Every behaviour your spec's acceptance names has a test in `fab/tests/`,
  with `fab.tests.support.tmp_home()` as HOME. Commands through
  `fab.tests.support.FakeRunner`, except where a module's tests already use
  real git in a temporary directory (`fab/tests/test_designer.py`'s
  repositories, `fab.tests.support.git_pair()`); never live state.
- Checks before you hand over: `bin/fab test` (`python3 -B -m
  fab.testrun`) green, the whole suite under its 30 s budget (no sleeps);
  `bin/fab status docs/plan/paper-cuts` shows no plan problems.

## Commits and the report

- One or a few commits, each message saying why, ending with the trailer
  your run's brief gives.
- Your report's first line: `Done: <what landed, one line>`, `Question:
  <what you need>` (with the options and your recommendation) or `Failed:
  <why>`. Then: what you built, by function; the tests added; any default
  your spec pre-approved that you took, and any departure from the design
  with the doc change that records it.
