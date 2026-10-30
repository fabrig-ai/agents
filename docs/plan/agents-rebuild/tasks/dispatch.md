+++
id = "dispatch"
part = "dispatch"
kind = "feature"
needs = []
files = ["fab/dispatch.py", "fab/tests/test_dispatch.py", "fab/cli.py"]
effort = "high"
minutes = 30
+++
# The dispatcher's tick

Fill the bodies of `fab/dispatch.py` as their docstrings say. Design:
`docs/design/fab.md`, sections 3-6 and 10. It does what a person does today by
hand: collect ended runs, land or ready what is done, start what is runnable
on free places, park what keeps failing, say when design runs low. It uses
`fab.state.fold`, `fab.run` (start, collect), `fab.land.main` and
`fab.hosts`, all on main.

## Acceptance

- `fab/tests/test_dispatch.py` covers `decide` as a pure function over small
  hand-built plans, tasks, events and hosts: each of its four steps, the order
  of actions, rejected before runnable, the builder with most free places
  first, places never exceeded, rebase against repair for rejections, repair
  after an infra outcome, park at MAX_RUNS, the design detail listing only
  parts whose needs have landed and that have no specs, no design action when
  the buffer is full.
- `in_flight` and `places` directly.
- `tick` with `support.FakeRunner` and patched `fab.run.start`,
  `fab.run.collect` and `fab.land.main` (record their calls): the queue import
  (a fake `fab queue log` answer turned into branch events, not imported
  twice), each action carried out, a failing action logged as a note while
  the next one still runs, the second concurrent tick exiting at once, and
  `--dry-run` taking no action.
- `bin/fab test` passes; `test_dispatch.py` takes under a second.

## Options, settled up front

- `main` registers as `fab tick` in `fab/cli.py`'s COMMANDS: you may add that
  one line to `fab/cli.py`.
- Printed lines are `<kind> <task> <detail>`, one per action.
- When `plan_dir` is not a git checkout, `tick` skips the fetch.
