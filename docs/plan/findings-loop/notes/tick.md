# The tick family

For `tick-triage` and `backlog-branch`, both in `fab/dispatch.py`, in that
order.

- **Red-routing builds in `fab/dispatch.py` at the same time**
  (`red_actions`, red tasks in `_tick_plan`). If its wiring is on main when
  you start, build on it; if it lands while you work, rebase and keep both.
  Touch no red behaviour.
- A plan with rungs (`plan.rungs`) has no parts and no tasks in this plan:
  every ladder step in `_tick_plan` runs only when `plan.rungs` is not
  empty, and a plan without rungs behaves exactly as before (its tests
  unchanged).
- The order in `_tick_plan` for a ladder plan (13.15 "The tick, each
  round"): the decisions of ended triage calls, then `rung.passed`, then
  the backlog's branch, then the existing steps (`decide`, settlements,
  `call_actions`, which starts the triage call when due).
- `finding.triaged` and `rung.passed` need no further tick (13.9): add
  neither to `fab.wake.AGAIN`.
- A step that cannot read what it needs (an edition's `git show`, a report)
  logs one `note` naming it and lets the round go on, as the queue import
  does.
- Tests in `fab/tests/test_dispatch.py`, with a ladder plan from
  `fab/tests/ladder_plans.py` and records from `fab/tests/qa_records.py`,
  through `tick(...)` with a `FakeRunner`, as the existing tick tests do.
