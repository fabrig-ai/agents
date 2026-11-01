# Every call-rebase task

The standing rules of this plan's implementers. Read this, then
`docs/plan/call-rebase/notes/decisions.md`, then your spec.

## Scope

- The request (`docs/plan/call-rebase/inputs/request.md`) builds one bullet
  of `docs/design/calls.md`, 2: **A `fab land` refusal counts as a refusal
  of the chain**, all its sub-bullets, as designed. Nothing past it: calls
  landing through fabrig's queue or merged into an integration trunk keep
  their paths; chains already finished stay finished (nothing replays them).
- Change only your spec's `files`. A file you must touch outside them is a
  `Question:`, unless your spec pre-approves it.
- Names, signatures and strings bound in your spec or in decisions.md are
  binding: the other task is written against them. Private helpers are
  yours to name.
- Follow the design. Where the code shows it cannot hold as written, change
  calls.md 2 in the same branch, say so in your report, and keep the change
  to that point. Otherwise leave the designs and their status files alone:
  they are the designer's (retire brings `docs/design/calls.status.md`
  current).

## Code

- Python 3.13 standard library only. Commands go through the injected
  runner (`sh: Runner`, `fab.sh.run` by default), never `subprocess`.
- Match the surrounding code: docstrings that say what a function returns
  and cite the design section; module constants with a comment. The taste
  file `fab/taste.md` applies. Functions stay within the gates' 60-line cap
  (`fab/gates.py`); an existing long function (`fab.dispatch._take`,
  `fab.call_review.chains`) must not grow: move the new branch into a
  private helper.
- `fab.call_review` must not import `fab.dispatch` or `fab.land`; `fab.calls`
  imports `fab.call_review` only inside functions, as `_chain_call` does.

## Tests

- Every behaviour your spec's acceptance names has a test in `fab/tests/`,
  with `fab.tests.support.tmp_home()` as HOME, commands through
  `fab.tests.support.FakeRunner`, log folds over literal events; never live
  state.
- Checks before you hand over: `bin/fab test` (`python3 -B -m
  fab.testrun`) green within its 30 s budget (no sleeps); `bin/fab status
  docs/plan/call-rebase` shows no plan problems.

## Commits and the report

- One or a few commits, each message saying why, ending with the trailer
  your run's brief gives.
- Your report's first line: `Done: <what landed, one line>`, `Question:
  <what you need>` (with the options and your recommendation) or `Failed:
  <why>`. Then: what you built, by function; the tests added; any default
  your spec pre-approved that you took, and any departure from the design
  with the doc change that records it.
