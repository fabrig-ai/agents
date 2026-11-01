# answer-findings: the plan

One direct part, one task (`answer-set`), as the request asks: the
request's three items are one concept, the answer call's task set, and
fit one task. Its spec is `tasks/answer-set.md`, the standing rules
`notes/common.md`, the decisions and the critical path
`notes/decisions.md`.

## Overlaps with the drafts beside this one

`dogfood-faults` has tasks still to land on `fab/dispatch.py` and
`fab/tests/test_dispatch.py` (`call-env`, `rebase-trunk`, `stop-lift`;
`reruns` on the test file). This task changes the same two files and
could not avoid them: the tick's task set is built there. It keeps the
overlap small: it changes only `_tick_loaded`'s task-set lines (~1228-1230)
and `main`'s dry run (~1756), and adds its tests beside
`FindingDispatchTest`, away from the functions those tasks change
(`_call`, `_finish`, the integration stop, the rerun start). No other
draft's file is touched.
