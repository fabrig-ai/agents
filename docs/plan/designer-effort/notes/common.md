# Every designer-effort task

The standing rules of this plan's implementer. Read this, then
`docs/plan/designer-effort/notes/decisions.md`, then your spec.

## Scope

- The request is `docs/plan/designer-effort/inputs/request.md`. Build it as
  written; nothing past it.
- Change only your spec's `files`. A file you must touch outside them is a
  `Question:`, unless your spec pre-approves it.
- No other role changes, and no other role's effort. `docs/design/` already
  says this: leave it, its status files too, and never edit
  `docs/design/draft/`.

## Checks

- `bin/fab test` green within its budget.
- `bin/fab status docs/plan/designer-effort` shows no plan problems.
- Your spec's greps give what it says.

## Commits and the report

- One commit, its message saying why, ending with the trailer your run's
  brief gives. No machine action is needed: fab's next deploy carries it.
- Your report's first line: `Done: <what landed, one line>`, `Question:
  <what you need>` (with the options and your recommendation) or `Failed:
  <why>`. Then what your spec's Report section asks.
- Your base is main's tip; your branch lands on main through `bin/fab land`.
