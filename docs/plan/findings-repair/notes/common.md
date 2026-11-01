# Every findings-repair task

The standing rules of this plan's implementers. Read this, then
`docs/plan/findings-repair/notes/fix.md`, then your spec.

## Scope

- The design is `docs/design/qa.md`, 2 (QA findings): "On the path is
  a Fix-mode repair through the reds' foreman path" to "One repair per
  finding", and "The tick, each round"; the red path it shares is
  `docs/design/after-landing.md`, 2 and `docs/design/calls.md`, 2.
  The request (`docs/plan/findings-repair/inputs/request.md`) says what this
  plan builds: `fab/fix.py`, `fab/fixes.py` with
  `fab/roles/foreman-finding.md`, the tick's steps, and the `finding-<n>`
  signal. **Not** walks run by fab, **not** "Then it holds" (qa.md 3):
  build neither, and no hook for them.
- `fab/findings.py` already folds every repair state (foreman, deciding,
  decided, repairing, landed, left, fixed, unfixed) from the records this
  plan writes (findings-loop's decision 3). Write the records; do not
  change the fold. A fold that cannot read what you write is a
  `Question:`.
- Change only your spec's `files`. A file you must touch outside them is a
  `Question:`, unless your spec pre-approves it.
- Names, signatures and record fields bound in your spec or in
  `notes/fix.md` are binding: other tasks are written against them in
  parallel. Private helpers are yours to name.
- Follow the design. Where the code shows the design cannot hold as
  written, change `docs/design/qa.md` 2 (and the line of
  `docs/design/qa.status.md` that says it) in the same branch, say so
  in your report, and keep the change to that point. Otherwise leave the
  designs and their status files alone: they are the designer's.

## Code

- Python 3.13 standard library only. Write files through `fab.atomic.write`.
  Pure functions take the log's records (`list[dict]`, as `fab.log.read`
  gives them) and return values; only `main`s and the tick's steps write.
- Log through `fab.log.append` (flat fields: scalars or lists of scalars).
- Match the surrounding code: docstrings that say what a function returns
  and cite the design section, as `fab/tier_reds.py` does; module
  constants with a comment. The taste file `fab/taste.md` applies.
- Red's behaviour stays as it is: its records, its fields, its page lines.
  Every test in `fab/tests/test_tier_reds.py` passes unchanged; a test
  elsewhere that pins a red name this plan renames (`examine-red`,
  `remedy-red`) changes only that name.

## Tests

- Every behaviour your spec's acceptance names has a test in `fab/tests/`,
  with `fab.tests.support.tmp_home()` as HOME and
  `fab.tests.support.FakeRunner` for every command; never live state.
- QA records come from `fab/tests/qa_records.py` and ladder plans from
  `fab/tests/ladder_plans.py` (findings-loop's vocabulary). Do not change
  them; keep any builder you add in your own test module.
- Checks before you hand over: `bin/fab test` (`python3 -B -m
  fab.testrun`) green, the whole suite under its 30 s budget (no sleeps, no
  real git unless the module's tests already use `support.git_pair`);
  `bin/fab status docs/plan/findings-repair` shows no plan problems.

## Commits and the report

- One or a few commits, each message saying why, ending with the trailer
  your run's brief gives.
- Your report's first line: `Done: <what landed, one line>`, `Question:
  <what you need>` (with the options and your recommendation) or `Failed:
  <why>`. Then: what you built, by function; the tests added; any default
  your spec pre-approved that you took, and any departure from the design
  with the doc change that records it.
