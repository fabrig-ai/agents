# Every edge-fixes task

The standing rules of this plan's implementers. Read this, then
`docs/plan/edge-fixes/notes/decisions.md`, then your spec.

## Scope

- The request is `docs/plan/edge-fixes/inputs/request.md`. Build your item as
  written; nothing past it. Its line numbers are older than main's: your
  spec's are from the cut, and `acceptance-fixes` may land before you, so find
  a site by its text.
- Change only your spec's `files`. A file you must touch outside them is a
  `Question:`, unless your spec pre-approves it.
- `docs/design/*.md` stays as it is: the designs stand. Your spec names the
  one status file you edit.

## Code

- Python 3.13 standard library only. Match the surrounding code and
  `fab/taste.md`; functions stay within the gates' 60-line cap
  (`fab/gates.py`). Docstrings say what the code does as built.

## Tests

- Temporary HOME and fake services; never live state. Run Python with `-B`.
- Each new test must fail without your fix: run it once against the old line
  and say so in your report.
- Checks before you hand over: `bin/fab test` green within its budget;
  `bin/fab status docs/plan/edge-fixes` shows no plan problems.

## Commits and the report

- One commit, its message saying why, ending with the trailer your run's
  brief gives.
- Your report's first line: `Done: <what landed, one line>`, `Question:
  <what you need>` (with the options and your recommendation) or `Failed:
  <why>`. Then what you changed, by function, the tests added, and what your
  spec's Report section asks.
- Your base is main's tip; your branch lands on main through `bin/fab land`.
