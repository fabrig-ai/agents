# Every mechanisms-out task

The standing rules of this plan's implementers. Read this, then
`docs/plan/mechanisms-out/notes/decisions.md`, then your spec.

## Scope

- The request (`docs/plan/mechanisms-out/inputs/request.md`) moves three
  mechanisms the LLM calls do today into code: an LLM for judgement, code
  for mechanisms. The designs already say how, each marked "the user,
  11-01": build them as designed, with the role texts in step. Your spec
  names the request's item and the design's section; nothing past them.
- Change only your spec's `files`. A file you must touch outside them is a
  `Question:`, unless your spec pre-approves it.
- Leave `docs/design/*.md` and the status files alone: the designs are
  written, the status files are the retire call's.
- The three tasks change `fab/dispatch.py` and `fab/tests/test_dispatch.py`
  one after another (`needs`). Change only the functions your spec names,
  and put new tests beside the existing tests of the function you change,
  never at the end of the file.
- Other north-star breaches you find on the way are not for this plan
  (agents/loop lists them): name them in your report, change nothing.

## Code

- Python 3.13 standard library only. Commands go through the injected
  runner (`sh: Runner`), never `subprocess`. Commits fab makes are authored
  `git -c user.name=fab -c user.email=fab@localhost` (`FAB_GIT` in
  `fab/dispatch.py`).
- Match the surrounding code and `fab/taste.md`; functions stay within the
  gates' 60-line cap (`fab/gates.py`). A docstring that describes what you
  change says it as built.
- Role texts (`fab/roles/*.md`) keep their voice: short imperative
  sentences, wrapped as the file wraps.

## Tests

- Every behaviour your spec's acceptance names has a test in `fab/tests/`,
  with `fab.tests.support.tmp_home()` as HOME, commands through
  `fab.tests.support.FakeRunner` and fixture logs, as the touched modules'
  tests are; never live state.
- A test the request names as changing pin changes to the new behaviour;
  say which in your report.
- Checks before you hand over: `bin/fab test` (`python3 -B -m
  fab.testrun`) green within its 30 s budget; `bin/fab status
  docs/plan/mechanisms-out` shows no plan problems.

## Commits and the report

- One commit, its message saying why, ending with the trailer your run's
  brief gives. No machine action is needed for any task of this plan: fab
  follows main at each tick.
- Your report's first line: `Done: <what landed, one line>`, `Question:
  <what you need>` (with the options and your recommendation) or `Failed:
  <why>`. Then what you changed, by function or file, the tests changed or
  added, and what your spec's Report section asks.
- Your base is main's tip once your needs have landed; your branch lands on
  main through `bin/fab land`.
