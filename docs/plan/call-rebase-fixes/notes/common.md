# Every call-rebase-fixes task

The standing rules of this plan's implementers. Read this, then
`docs/plan/call-rebase-fixes/notes/decisions.md`, then your spec.

## Scope

- The request (`docs/plan/call-rebase-fixes/inputs/request.md`) fixes the
  acceptance review's three findings on plan `call-rebase`, which built
  `docs/design/calls.md`, 2, "A `fab land` refusal counts as a refusal of
  the chain". The design is right: bring the code and role texts to it.
  Nothing past the three findings.
- Change only your spec's `files`. A file you must touch outside them is a
  `Question:`, unless your spec pre-approves it.
- Leave `docs/design/calls.md` alone. Only `fab-fetch` words
  `docs/design/calls.status.md`, at the line the request names.

## Code

- Python 3.13 standard library only. Commands go through the injected
  runner (`sh: Runner`), never `subprocess`.
- Match the surrounding code and `fab/taste.md`; functions stay within the
  gates' 60-line cap (`fab/gates.py`).
- Role texts (`fab/roles/*.md`) keep their voice: short imperative
  sentences, wrapped as the file wraps.

## Tests

- Every behaviour your spec's acceptance names has a test in `fab/tests/`,
  with `fab.tests.support.tmp_home()` as HOME and commands through
  `fab.tests.support.FakeRunner`; never live state.
- Checks before you hand over: `bin/fab test` (`python3 -B -m
  fab.testrun`) green within its 30 s budget; `bin/fab status
  docs/plan/call-rebase-fixes` shows no plan problems.

## Commits and the report

- One commit, its message saying why, ending with the trailer your run's
  brief gives.
- Your report's first line: `Done: <what landed, one line>`, `Question:
  <what you need>` (with the options and your recommendation) or `Failed:
  <why>`. Then what you changed, by function or file, and the tests changed
  or added.
