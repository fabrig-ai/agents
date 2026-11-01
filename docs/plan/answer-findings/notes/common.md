# Every answer-findings task

The standing rules of this plan's implementer. Read this, then
`docs/plan/answer-findings/notes/decisions.md`, then your spec.

## Scope

- The request (`docs/plan/answer-findings/inputs/request.md`) fixes one
  live fault: the tick decides on an answer call over a wider task set than
  the answer call builds its brief from. The designs already say what fab
  should do (`docs/design/qa.md`, 2: a finding's repair "gets two runs,
  then the answerer"; `docs/design/calls.md`, 2, the answer call): build
  that, nothing past it.
- Change only your spec's `files`. A file you must touch outside them is a
  `Question:`, unless your spec pre-approves it.
- Leave `docs/design/*.md` and the status files alone; they are the retire
  call's.
- `dogfood-faults` tasks change `fab/dispatch.py` and
  `fab/tests/test_dispatch.py` beside you. Change only the functions your
  spec names, and put new tests beside the existing tests your spec names,
  never at the end of the file, so either side's rebase stays clean.

## Code

- Python 3.13 standard library only. Commands go through the injected
  runner (`sh: Runner`), never `subprocess`.
- Match the surrounding code and `fab/taste.md`; functions stay within the
  gates' 60-line cap (`fab/gates.py`). A docstring that describes what you
  change says it as built.

## Tests

- Every behaviour your spec's acceptance names has a test in `fab/tests/`,
  with `fab.tests.support.tmp_home()` as HOME, commands through
  `fab.tests.support.FakeRunner` and fixture logs; never live state.
- Checks before you hand over: `bin/fab test` (`python3 -B -m
  fab.testrun`) green within its 30 s budget; `bin/fab status
  docs/plan/answer-findings` shows no plan problems.

## Commits and the report

- One commit, its message saying why, ending with the trailer your run's
  brief gives. No machine action is needed: fab follows main at each tick.
- Your report's first line: `Done: <what landed, one line>`, `Question:
  <what you need>` (with the options and your recommendation) or `Failed:
  <why>`. Then what you changed, by function or file, the tests changed or
  added, and what your spec's Report section asks.
- Your base is main's tip; your branch lands on main through fab's queue.
