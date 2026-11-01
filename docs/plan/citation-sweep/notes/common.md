# Every citation-sweep task

The standing rules of this plan's implementer. Read this, then
`docs/plan/citation-sweep/notes/decisions.md`, then your spec.

## Scope

- The request is `docs/plan/citation-sweep/inputs/request.md`. Build it as
  written; nothing past it.
- Change only your spec's `files`. A file you must touch outside them is a
  `Question:`, unless your spec pre-approves it.
- Comments and docstrings only: no behaviour, no test, and no string a test
  pins. Tidy nothing else on a line you rewrite.
- `docs/design/*.md` stays as it is. The one status file your spec names is
  the only design file you edit.

## Checks

- `bin/fab test` green within its budget.
- `bin/fab status docs/plan/citation-sweep` shows no plan problems.
- Your spec's greps give what it says.

## Commits and the report

- One commit, its message saying why, ending with the trailer your run's
  brief gives. No machine action is needed.
- Your report's first line: `Done: <what landed, one line>`, `Question:
  <what you need>` (with the options and your recommendation) or `Failed:
  <why>`. Then what your spec's Report section asks.
- Your base is main's tip; your branch lands on main through `bin/fab land`.
