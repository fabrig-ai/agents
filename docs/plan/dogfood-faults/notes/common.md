# Every dogfood-faults task

The standing rules of this plan's implementers. Read this, then
`docs/plan/dogfood-faults/notes/decisions.md`, then your spec.

## Scope

- The request (`docs/plan/dogfood-faults/inputs/request.md`) fixes the fab
  faults dogfood/design found. The designs already say what fab should do,
  each fix marked "fixed 11-01": build them as designed. Your spec names
  the request's item and the design's section; nothing past them.
- Change only your spec's `files`. A file you must touch outside them is a
  `Question:`, unless your spec pre-approves it.
- Leave `docs/design/*.md` alone: the designs are already written. Status
  files are the retire call's, except `status-current`'s two.
- Several tasks change `fab/dispatch.py` and `fab/tests/test_dispatch.py`,
  one after another (`needs`). Change only the functions your spec names,
  and put new tests beside the existing tests of the function you change,
  never at the end of the file, so the next task's rebase stays clean.

## Code

- Python 3.13 standard library only. Commands go through the injected
  runner (`sh: Runner`), never `subprocess`.
- Match the surrounding code and `fab/taste.md`; functions stay within the
  gates' 60-line cap (`fab/gates.py`). A docstring that describes what you
  change says it as built.
- Role texts (`fab/roles/*.md`) keep their voice: short imperative
  sentences, wrapped as the file wraps.

## Tests

- Every behaviour your spec's acceptance names has a test in `fab/tests/`,
  with `fab.tests.support.tmp_home()` as HOME, commands through
  `fab.tests.support.FakeRunner` and fixture logs; never live state.
- Checks before you hand over: `bin/fab test` (`python3 -B -m
  fab.testrun`) green within its 30 s budget; `bin/fab status
  docs/plan/dogfood-faults` shows no plan problems.

## Commits and the report

- One commit, its message saying why, ending with the trailer your run's
  brief gives. No machine action is needed for any task of this plan: fab
  follows main at each tick.
- Your report's first line: `Done: <what landed, one line>`, `Question:
  <what you need>` (with the options and your recommendation) or `Failed:
  <why>`. Then what you changed, by function or file, and the tests changed
  or added, and what your spec's Report section asks.
- Your base is main's tip once your needs have landed; your branch lands on
  main through `bin/fab land`.
