+++
id = "tick-split"
part = "dispatch"
kind = "feature"
needs = ["gates-tick", "atomic-write"]
files = ["fab/dispatch.py", "fab/plan.py", "fab/log.py", "fab/report.py", "fab/tests/test_dispatch.py", "fab/tests/test_plan.py", "fab/tests/test_log.py"]
effort = "high"
minutes = 45
+++
# The tick reads as its steps

`fab.dispatch.tick` is 159 lines. It locks, fetches, loads the plan,
imports the queue's record, decides, and then takes every kind of action
in one nested `take` (80 lines, a `match` of seven cases). `decide` is 67
lines. Once `gates-tick` lands, the size gate rejects any change to either,
and the coming parts (flow, plans, call-review, accounting) all change
them. Two pieces of the tick are also repeated elsewhere:

- **Loading a plan.** `load_plan`, `load_tasks`, then `problems` raised as a
  `PlanError`, is written out in `tick`, `dispatch.main --dry-run`,
  `report.main`'s `load` and `state.main`.
- **Reading records sent over ssh.** `tick` runs `json.loads` on each line
  of `fab queue log`, so one line that does not parse fails the whole tick.
  `report.gather` reads the same output and skips such lines, as
  `fab.log.iterate` does.

Design: `docs/design/fab.md`, sections 3, 4 and 13.

## What changes

- `fab/plan.py` gains `load(plan_dir: Path) -> tuple[Plan, dict[str, Task]]`:
  plan.toml and tasks/ under plan_dir, with a PlanError naming plan_dir and
  listing `problems` when there are any. `tick`, `dispatch.main` and
  `report.main` call it. `state.main` keeps its own loading: it prints
  problems after the statuses rather than raising. `calls.main` loads
  without the check and stays as it is.
- `fab/log.py` gains `records(text: str) -> list[dict]`: the lines of text
  that parse as a JSON object with a string ts, in order. `report.gather`'s
  `read_remote` and the tick's queue import both use it.
- `tick` keeps its signature and docstring. Its body becomes calls to
  private functions of the module, each under 60 lines: the queue import
  (`_import_queue`), one function per action kind (`_collect`, `_land`,
  `_ready`, `_start`, `_call`, `_finish`, `_park`) dispatched from a small
  `take`, and one `_land_branch(argv)` for the `fab.land.main` call with
  captured output that `land` and `finish` both make today. The screen that
  `gates-tick` adds stays inside `_land`.
- `decide` keeps its signature and docstring. The choice of a start's
  kind and rejection, and the design action, move to private functions.
- In `tick`, the list of gate host names is no longer called `gates`, the
  name of the imported module `fab.gates`.

## Acceptance

- `fab/tests/test_plan.py`: `load` returns a sound plan and its tasks, and
  raises a PlanError naming the directory and each problem for an unsound one.
- `fab/tests/test_log.py`: `records` skips blank lines, lines that do not
  parse, non-objects and objects without a string ts.
- `fab/tests/test_dispatch.py`: a queue log line that does not parse is
  skipped, and the next record is still imported. Every existing test passes
  unchanged.
- `fab.digest.functions` over `fab/dispatch.py` finds no function over 60
  lines.
- `bin/fab test` passes; `test_dispatch.py` stays under two seconds.

## Options, settled up front

- The action functions take what they need as arguments (the action, the
  tasks, the hosts, `sh`, `log_path`, `home`, `plan_dir`). They are not
  methods of a new class.
- Skipping an unparseable queue line is the one change in behaviour here.
  It matches what `report.gather` and `fab.log.iterate` already do.
