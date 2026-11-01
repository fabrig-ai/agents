# Every start-commands task

The standing rules of this plan's implementers. Read this, then
`docs/plan/start-commands/notes/decisions.md`, then your spec.

## Scope

- The request is `docs/plan/start-commands/inputs/request.md`; each item's
  design is the contract, already written (marked "the user, 11-01" or
  "fixed 11-01"). Build it as written: its refusals, its order, its
  records' fields. Nothing past it.
- Change only your spec's `files`. A file you must touch outside them is a
  `Question:`, unless your spec pre-approves it.
- Leave `docs/design/` alone: the designs are written, and the status
  files are the retire call's.
- `brief-park` then `retired-import` change `fab/dispatch.py` and
  `fab/tests/test_dispatch.py`. Change only the functions your spec names,
  and put new tests beside the existing tests of the function you change,
  never at the end of a file, so the next rebase stays clean. The same
  holds for `fab/cli.py`: add only your own `COMMANDS` entry, where your
  spec says.

## Code

- Python 3.13 standard library only. Every command goes through the
  injected runner (`sh: Runner`, default `fab.sh.run`), never
  `subprocess`; files are written through `fab.atomic.write` (a copied
  input directory may use `shutil.copytree` into the temporary worktree).
- Match the surrounding code and `fab/taste.md`; functions stay within the
  gates' 60-line cap (`fab/gates.py`) and no 8-line block repeats another.
  New public functions carry docstrings saying what they do as built.
- fab's own commits use `git -c user.name=fab -c user.email=fab@localhost`
  (as `fab/dispatch.py` `FAB_GIT`).

## Tests

- Every behaviour your spec's acceptance names has a test in `fab/tests/`,
  with `fab.tests.support.tmp_home()` as HOME and FAB_HOME, fixture logs,
  and commands through `fab.tests.support.FakeRunner`, except where the
  spec asks for real git: then a temporary directory, `git_pair` and
  `GIT_ENV` from `fab.tests.support`, as `fab/tests/test_overlaps_git.py`
  does. Never the machine's repositories, systemd or network.
- Checks before you hand over: `bin/fab test` green within its 30 s
  budget (keep a real-git test file under about 2 s);
  `bin/fab status docs/plan/start-commands` shows no plan problems.

## Commits and the report

- One commit, its message saying why, ending with the trailer your run's
  brief gives. No machine action is needed at landing: fab follows main at
  each tick, and the two commands are the operator's to run.
- Your report's first line: `Done: <what landed, one line>`, `Question:
  <what you need>` (with the options and your recommendation) or `Failed:
  <why>`. Then what you changed, by function, the tests added, and what
  your spec's Report section asks.
- Your base is main's tip once your needs have landed; your branch lands
  on main through the queue.
