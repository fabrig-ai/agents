# Every precheck-starved task

The standing rules of this plan's implementer. Read this, then
`docs/plan/precheck-starved/notes/decisions.md`, then your spec.

## Scope

- The request is `docs/plan/precheck-starved/inputs/request.md`; its
  design is `docs/design/landing.md` 2, "The selection and the steps are
  shared" (fixed 11-01) and "Starvation stays green in the gate". Build it
  as written; nothing past it.
- Change only your spec's `files`. A file you must touch outside them is a
  `Question:`, unless your spec pre-approves it.
- Leave `docs/design/` alone: the design is written, and the status files
  are the retire call's.

## Code

- Python 3.13 standard library only. Every command goes through the
  injected runner (`sh: Runner`, default `fab.sh.run`), never
  `subprocess`; files are written through `fab.atomic`.
- Match the surrounding code and `fab/taste.md`; functions stay within the
  gates' 60-line cap (`fab/gates.py`) and no 8-line block repeats another.
  Docstrings say what the code does as built.

## Tests

- Every behaviour the acceptance names has a test in `fab/tests/`, with
  `fab.tests.support.tmp_home()` as HOME and FAB_HOME and fake commands
  (`fab.tests.landing_checks.FakeNextest`, `fab.tests.support.FakeRunner`);
  git through `git_pair` and `GIT_ENV` as `fab/tests/test_precheck.py`
  already does. Never the machine's repositories, heavy or network.
- Checks before you hand over: `bin/fab test` green within its 30 s
  budget; `bin/fab status docs/plan/precheck-starved` shows no plan
  problems.

## Commits and the report

- One commit, its message saying why, ending with the trailer your run's
  brief gives. Machine action at landing: none by hand; the builders'
  installs follow main at the next run start (`docs/design/tick.md` 3).
- Your report's first line: `Done: <what landed, one line>`, `Question:
  <what you need>` (with the options and your recommendation) or `Failed:
  <why>`. Then what you changed, by function, the tests added, and what
  your spec's Report section asks.
- Your base is main's tip; your branch lands on main through the queue.
