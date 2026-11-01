# df-followups: the cut's decisions

What the request left to the cut, each settled with its reason. The specs
bind them.

1. **Two direct parts, one task each,** as the request names them: item 1
   (`from-main`) by itself, items 2-4 (`small-fixes`) together. Neither has
   a contract another part reads.
2. **`small-fixes` needs `from-main`:** both change `fab/calls.py` and
   `fab/tests/test_calls.py` (`main`'s start; `answer_brief`), and two
   tasks on the same files are ordered. Item 1 goes first, since it must
   land before the next fabrig integration plan lands its trunk.
3. **One helper for the base,** so the request's expression is written
   once rather than at six sites: `fab.integration.call_base(plan: Plan,
   events: Sequence[dict]) -> str`, returning `"main"` when `plan.landing
   == "integration"` and `trunk_landed(plan, events)`, else `plan.trunk`,
   beside `trunk_landed`. It only adds, so the task's kind is `feature`.
4. **Every role, including triage.** The request names triage among the
   calls that fail and asks for "every role" in `calls.main`, which hands
   triage to `fab.triage.main`; its `calls.start(..., base=plan.trunk)`
   (`fab/triage.py` ~332) takes the helper too, at that call only.
5. **The foreman and refusal starts** are the three the request names:
   `_start` (`runs.start(..., trunk=...)`, ~1498), `_foreman`
   (`foreman.start(..., trunk=plan.trunk)`, ~1545) and `_examine`
   (`repairs.start(..., trunk=...)`, ~1623). A fix kind (`fix.FIX_KINDS`)
   keeps `"main"` as today; otherwise the helper. The settled answer's and
   the remedy's spec commits (`foreman.commit` ~1566, `repairs.commit`
   ~1656, `trunk=plan.trunk`) are not in the request and stay as they are.
6. **`_integration` returns** right after `events = _lift_catch_up(...)`
   when `integration.trunk_landed(plan, events)`, before the `try` and its
   git reads; `integration.next_step` already returns None then, so no
   step is lost.
7. **The probe** (`fab/run.py` ~327) keeps its argv in a name, and a code
   outside (0, 1) raises `Failed(argv, probe)`, as `dispatch._contains`
   does; 1 stays "absent".
8. **The status lines are this plan's,** because the request words them
   (item 4); the status of item 1 itself and of items 2-3 is the retire
   call's.
9. **No user questions.** The request settles what is built, its order
   and how it lands.

## Critical path

`from-main` (60) -> `small-fixes` (45): 105 implementer-minutes, under
2 hours: the longest task plus the one that shares its files.

| Task | Needs | Minutes | Ends near |
|---|---|---|---|
| from-main | | 60 | 60 |
| small-fixes | from-main | 45 | 105 |
