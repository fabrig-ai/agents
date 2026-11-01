# Every hel8-units task

The standing rules of this plan's implementers. Read this, then
`docs/plan/hel8-units/notes/decisions.md`, then your spec.

## Scope

- The request is `docs/plan/hel8-units/inputs/request.md`; the design is
  `docs/design/machines.md`, section 4, the contract. Build it as written:
  the texts byte for byte, the install's order, the CLI's messages and exit
  codes. Nothing past it.
- Change only your spec's `files`. A file you must touch outside them is a
  `Question:`, unless your spec pre-approves it.
- Leave `docs/design/` alone: the designs are already written, and the
  status files are the retire call's.
- `fab.units.Service`, `text` and `install` and their callers (the queue,
  after-landing) stay unchanged, as do `fab.wake`'s units.
- No unit fetches or moves `FAB_HOME/install`: the tick alone does.

## Code

- Python 3.13 standard library only. Every command goes through the
  injected runner (`sh: Runner`, default `fab.sh.run`), never `subprocess`;
  files are written through `fab.atomic.write`.
- Match the surrounding code and `fab/taste.md`; functions stay within the
  gates' 60-line cap, and no block of 8 lines repeats another (the clones
  gate): the four `--install`s share `fab.units`' code, never copy it.
- New public functions carry docstrings saying what they do as built.

## Tests

- Every behaviour your spec's acceptance names has a test, with
  `fab.tests.support.tmp_home()` as HOME and FAB_HOME, commands through
  `fab.tests.support.FakeRunner`, a `directory=` under the temporary HOME
  and `known=` hosts; never the machine's systemd, git or loginctl.
- The installer's tests are in `fab/tests/test_units.py` (new: `fab.units`
  has none of its own today); each command's CLI tests beside that
  command's existing tests.
- Checks before you hand over: `bin/fab test` green within its 30 s budget;
  `bin/fab status docs/plan/hel8-units` shows no plan problems.

## Commits and the report

- One commit, its message saying why, ending with the trailer your run's
  brief gives. Its machine action: none at landing; ops runs the four
  `--install`s on hel8 afterwards (machines.md 4, "Deployment"), which is
  not this plan's.
- Your report's first line: `Done: <what landed, one line>`, `Question:
  <what you need>` (with the options and your recommendation) or `Failed:
  <why>`. Then what you changed, by function, the tests added, and what
  your spec's Report section asks.
- Your base is main's tip once your needs have landed; your branch lands
  through the queue.
