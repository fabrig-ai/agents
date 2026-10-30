+++
id = "flow"
part = "flow"
kind = "feature"
needs = ["gates-tick"]
files = ["fab/flow.py", "fab/dispatch.py", "fab/tests/test_flow.py", "fab/tests/test_dispatch.py"]
effort = "high"
minutes = 45
+++
# The flow grows with clean landings; places are hints

Fill `fab/flow.py` (`target`, `calm`, `measure`) as its docstrings say, and
make the dispatcher use them as the amended docstrings of `fab.dispatch.places`,
`decide`, `tick` and `main` say. Design: `docs/design/fab.md`, 13.2 and 7.
From this change on a plan keeps at most its target of runs in flight: 2 at
its start, one more per task landed on its first attempt while the target was
in use, one less per rejection or infra outcome, never below 1. A builder with
no free place takes one more run per tick while it is calm. It reuses
`fab.report.heavy_waits`, `Window`, `stamp` and `moment`, `fab.run.remote_home`
and `fab.sh.ssh`, all on main.

This task waits for `gates-tick`, which also changes `fab/dispatch.py` and
turns the gates on. `decide` and `tick` are already longer than 60 lines, so
the `size` gate rejects any change to them that leaves them that long: split
each to at most 60 lines with private functions (`_starts` for decide's step
3; for tick, the queue import and the bodies of `take`'s longer cases, `take`
itself at most 60 lines). Behaviour other than the flow stays as it is, and
the existing tests that pin it stay, adjusted only for the flow action and the
target.

## Acceptance

- `fab/tests/test_flow.py` covers `target` as a pure function over hand-built
  events: START with no events; growth on a first-attempt landing whose run
  ended with the window full; no growth when the run ended with fewer in
  flight than the target, after a second run, after a rejection of the task,
  or on a repeated branch.landed; drops on branch.rejected and on infra, held
  at FLOOR; other drafts' events and unknown types ignored; a record missing a
  field skipped.
- `calm` over hand-written PROBE outputs: calm; loaded (at LOAD_LOW exactly is
  not calm); lane and disk waits summed against WAIT_LOW; a disk refusal
  (fab.heavy.EX_TEMPFAIL); records older than WAIT_MINUTES ignored; a torn
  heavy line skipped; no heavy lines; an unparsable load or count, and a
  count of 0, not calm.
- `measure` with `support.FakeRunner`: one ssh per builder in name order with
  PROBE and the heavy path, a failed ssh False while the next is measured,
  non-builders left out.
- `fab/tests/test_dispatch.py`: `places` giving 1 to a full calm builder, 0
  to a full builder that is not calm or has as many runs as slots, and the
  hint ignored with calm None; `decide` starting no more than the target
  (rejected tasks first, parks not counted), counting only the draft's runs,
  using a calm builder's extra place once per decide, and emitting the flow
  action first; `tick` passing measure's calm to decide (its ssh scripted on
  the FakeRunner) and printing the flow line; `--dry-run` measuring nothing.
- `bin/fab test` passes; `test_flow.py` takes under a second and
  `test_dispatch.py` stays within its budget.

## Options, settled up front

- The constants are as `fab/flow.py` writes them (START 2, FLOOR 1, LOAD_LOW
  0.7 per CPU on the 5-minute load, WAIT_MINUTES 30, WAIT_LOW 5.0 minutes).
- tick measures every tick, before decide, even when every builder has a free
  place: one ssh per builder is cheap and keeps tick simple.
- The design step (decide's step 4) still compares against the builders' total
  `places`, not the target: the buffer is sized by the hint.
- The target is not logged; the printed flow line is its record until the
  code report shows it (`docs/design/fab.md`, 14).
