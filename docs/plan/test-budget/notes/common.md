# Every test-budget task

The standing rules of this plan's implementer. Read this, then
`docs/plan/test-budget/notes/decisions.md`, then your spec.

## Scope

- The request is `docs/plan/test-budget/inputs/request.md`; its design is
  `docs/design/fab.md` 1 and 4, changed in the request's commit. Build it
  as written; nothing past it.
- Change only your spec's `files`. A file you must touch outside them is a
  `Question:`, unless your spec pre-approves it.
- Leave `docs/design/` alone: the design is written, and the status files
  are the retire call's.

## Code

- Python 3.13 standard library only. Match the surrounding code and
  `fab/taste.md`; functions stay within the gates' 60-line cap
  (`fab/gates.py`). Docstrings say what the code does as built.

## Tests

- No machine state: `os.times` and the clock are patched, and the suite
  `main` runs is a fake, never `fab/tests` itself.
- Checks before you hand over: `bin/fab test` green within its budget;
  `bin/fab status docs/plan/test-budget` shows no plan problems.

## Commits and the report

- One commit, its message saying why, ending with the trailer your run's
  brief gives. Machine action at landing: none by hand; the builders'
  installs follow main at the next run start (`docs/design/tick.md` 3).
- Your report's first line: `Done: <what landed, one line>`, `Question:
  <what you need>` (with the options and your recommendation) or `Failed:
  <why>`. Then what you changed, by function, the tests added, and what
  your spec's Report section asks.
- Your base is main's tip; your branch lands on main through the queue.
