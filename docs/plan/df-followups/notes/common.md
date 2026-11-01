# Every df-followups task

The standing rules of this plan's implementers. Read this, then
`docs/plan/df-followups/notes/decisions.md`, then your spec.

## Scope

- The request is `docs/plan/df-followups/inputs/request.md`: the
  acceptance review of `docs/plan/dogfood-faults` found these. Build what
  your spec's items ask, as the request words them, and nothing past them.
  The design (`docs/design/integration.md` 3, "Retire waits for main") is
  already widened on main.
- Change only your spec's `files`. A file you must touch outside them is a
  `Question:`, unless your spec pre-approves it.
- Leave `docs/design/*.md` alone. Only `small-fixes` edits status files,
  and only the two lines its item 4 names; the rest of each status file is
  the retire call's.
- `start-commands` and `mechanisms-out` run beside this plan on
  `fab/calls.py`, `fab/designer.py`, `fab/triage.py`, `fab/dispatch.py`
  and their tests (`docs/plan/df-followups/plan.md`). Change only the
  lines your spec names, and put new tests beside the existing tests of
  the function you change, never at the end of a file.
- Other faults you find on the way are not for this plan: name them in
  your report, change nothing.

## Code

- Python 3.13 standard library only. Commands go through the injected
  runner (`sh: Runner`), never `subprocess`; a command's failure is
  `fab.sh.Failed(argv, result)`.
- Match the surrounding code and `fab/taste.md`; functions stay within the
  gates' 60-line cap (`fab/gates.py`) and no 8-line block repeats another.
  A docstring that describes the changed behaviour says it as built.

## Tests

- Every behaviour your spec's acceptance names has a test in `fab/tests/`,
  with `fab.tests.support.tmp_home()` as HOME and FAB_HOME, fixture logs,
  and commands through `fab.tests.support.FakeRunner` (or
  `patch.object(calls, "start")`, as the existing tests of the same `main`
  do). Never the machine's repositories, systemd or network.
- Checks before you hand over: `bin/fab test` green within its 30 s
  budget; `bin/fab status docs/plan/df-followups` shows no plan problems.

## Commits and the report

- One commit, its message saying why, ending with the trailer your run's
  brief gives. No machine action is needed at landing: fab follows main at
  each tick.
- Your report's first line: `Done: <what landed, one line>`, `Question:
  <what you need>` (with the options and your recommendation) or `Failed:
  <why>`. Then what you changed, by function, the tests added, and what
  your spec's Report section asks.
- Your base is main's tip once your needs have landed; your branch lands
  on main through the queue.
