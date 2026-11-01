+++
id = "tick-triage"
part = "tick"
kind = "feature"
needs = ["triage-decisions", "rungs-fold", "ladder-plan"]
files = ["fab/dispatch.py", "fab/tests/test_dispatch.py"]
effort = "high"
minutes = 45
+++
# The tick starts triage, records its decisions and a rung's pass

Read first: `docs/plan/findings-loop/notes/common.md`,
`docs/plan/findings-loop/notes/fold.md`,
`docs/plan/findings-loop/notes/triage.md`,
`docs/plan/findings-loop/notes/tick.md`.

The request: "the tick's triage steps: starting the call when due,
recording its decisions" and item 4's pass recorded
(`docs/plan/findings-loop/notes/decisions.md`, 1). Design:
`docs/design/fab.md`, 13.15, "When", "Code records the decisions", "A pass
is recorded by the tick" and "The tick, each round".

## What to build

In `fab/dispatch.py`:
- `call_actions` (near line 58): for a plan with rungs, when
  `fab.triage.due(plan, events, now)`, `Action("call",
  task=fab.triage.subject(plan.draft), run_kind="triage")`. `_call` (near
  line 680) then runs `fab call triage --plan <dir>` as a unit named by
  `fab.drafts.unit`; check it does, and change it only if not.
- `_tick_plan` (near line 895), for a plan with rungs, before `decide`:
  log `fab.triage.decisions(plan, events, reports)` (reports read from
  `FAB_HOME/calls/<call>/report.md` for the plan's ended triage calls),
  then `fab.findings.passes(plan, events, editions)` as `rung.passed`,
  editions from `fab.walks.editions(plan, directory)` (a ValueError: one
  note, no passes this round). Print one line per step that logged
  something, as the other steps print.

## Acceptance

Tests in `fab/tests/test_dispatch.py` (13.15's "Tests", the tick cases),
through `tick(...)`:
- a failed walk's finding starts one triage call at once; a passing
  walk's finding starts none until four or thirty minutes; an open triage
  question starts none; a triage call in flight starts no second;
- an ended triage call's report logs its decisions once across two ticks;
- a rerun's pass logs one `rung.passed`, and none on the next tick;
- a plan without rungs: the existing tests pass unchanged.

## Pre-approved defaults

- The editions read once per round and shared by the steps of the round
  (the backlog step, next task, reads none).

## Report

The steps added and where in `_tick_plan`, and whether `_call` needed a
change.
