# answer-findings: the cut's decisions

What the request left to the cut, each settled with its reason. The spec
binds them.

1. **One direct part, one task,** as the request says. The helper, the
   end-to-end check of the answer's path and the test are one concept
   (the answer call's task set) and about 50 implementer-minutes.
2. **The helper is `fab.calls.answer_tasks(plan, tasks, events, *,
   folded=None) -> dict[str, Task]`.** `fab.calls` already builds the
   answer brief and `fab.dispatch` already imports it; `fab.calls` may
   import `fab.fix` and `fab.fixes` (neither imports `fab.calls`), so no
   cycle. It adds a public function and changes no signature: kind
   `feature`.
3. **The helper is the tick's set, moved:** `integration.with_repairs`
   (applied whatever the landing, as the tick's `_integration_tasks` does:
   it adds nothing to a plan with no integration records), the plan's
   tasks of a kind in `fix.FIX_KINDS` dropped, then `tier_reds.tasks(plan,
   events, folded=folded)` and `fixes.tasks(plan, events)`. The tick keeps
   its `specs.checked_tasks` before it; the answer call loads its tasks
   from the spec files, as now. The tick's set is the one that was right,
   so moving it changes nothing the tick decides.
4. **The stop's question comes through `fab.foreman.questions`,** which
   since `dogfood-faults` takes `<draft>/integration` for a draft of the
   given tasks (`docs/design/integration.md`, 3). The helper adds no task
   for it; a test pins that the helper's set brings it to both sides.
5. **The answer's path is checked, and changed only if broken.** The tick's
   `_finish` reads an answer call's `Answered:` and `Answer <task>:` lines
   (`fab.dispatch._answered`) and logs `question.answered` with the answer;
   `fab.fixes.tasks` folds `fab.fix.answers` into the repair's body. The
   task tests the path end to end and fixes only what the test shows
   broken.
6. **No user questions.** The request settles what is built, where and how
   it lands; nothing in it is a budget, a machine or hard to reverse.

## Critical path

`answer-set` (50 implementer-minutes): the one task, with no needs.
