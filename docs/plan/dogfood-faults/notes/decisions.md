# dogfood-faults: the cut's decisions

What the request left to the cut, each settled with its reason. The specs
bind them.

1. **Eight direct parts, ten tasks.** One part per request item, item 3
   in two (the tick's side, `stop-asks`, and the answerer's,
   `stop-answer`), item 7's worktree rerun with item 5 (`reruns`: the
   request has them share the "absent `origin/<branch>`" check) and its two
   other paper cuts in `paper-cuts`. Item 3's tick side is two tasks
   (`stop-record`, `stop-lift`): one would be past the size band.
2. **Retire starts from main; other calls only deliver through the
   queue.** The request moves the retire's start to `main` and every
   call's delivery after the landing to the queue; it does not move other
   calls' starts, so neither does the cut. The trunk's tip is on main once
   it landed, so an answer call started from it still readies cleanly.
3. **`_checkout` reads the draft from the plan directory's name** (it runs
   before the plan loads), with the same `branch.landed` + `queue_ts`
   test as `fab.integration.trunk_landed`.
4. **The queue's depth fix is `fab/queue.py` only.** `fab.dispatch`
   `_queue_record` already reads deep branches through `owners`
   (backlog, answers, repairs); `queue-depth` checks it and reports.
5. **Tasks sharing `fab/dispatch.py` are ordered, in the request's order:**
   `retire-main` (item 1) -> `stop-record` -> `stop-lift` (item 3) ->
   `rebase-trunk` (item 4) -> `call-env` (item 7). Each changes different
   functions and puts its tests beside the function's, so each rebase is
   clean; the order only keeps two branches off the file at once.
6. **The stop's records and the lift are `fab/integration.py`'s, pure:**
   `Step.why`, `lifted` and `stopped` (stop-record); the counts afresh and
   the folding (stop-lift). `Step` gains a defaulted field, so
   `stop-record` is kind `interface`, as `rebase-trunk` is for
   `task_rebase`'s new keyword.
7. **The queue stop's report is `<gate>:<log>`,** the gate the first host
   by name with role gate (as `_import_queue` reads it) and the log the
   last queue rejection's `log` field, per the design.
8. **The stop's report reaches the answer brief through the question
   dict** (`stop`), filled by the answer call from the last `plan.stopped`
   before the question: `answer_brief`'s signature is unchanged.
   `stop-answer` reads fixture logs, so it needs none of `stop-record`'s
   code and starts at once.
9. **The end-to-end tick tests are `stop-lift`'s** (decide starts the
   answer call; `_finish` logs the answer), since it owns
   `fab/tests/test_dispatch.py` after both stop tasks; it needs
   `stop-answer` for them.
10. **A repair rerun with nothing pushed starts from the base in both
    paths**; the worktree's implement continuation merges the base in and
    leaves a conflict to the run, as the slot path does.
11. **Status files:** only `status-current` edits status files (the two
    the request names). The faults' own status lines are the retire
    call's; the designs are already written and no task edits them.
12. **No user questions.** The request settles what is built, where and
    how it lands; nothing in it is a budget, a machine or hard to reverse.

## Critical path

`retire-main` (50) -> `stop-record` (50) -> `stop-lift` (55) ->
`rebase-trunk` (25) -> `call-env` (15): 195 implementer-minutes, about 3.3
hours. It is longer than the longest task (55) because five tasks change
`fab/dispatch.py` and are ordered (5). Every other task starts at once and
ends well inside it.

| Task | Needs | Minutes | Ends near |
|---|---|---|---|
| retire-main | | 50 | 50 |
| queue-depth | | 35 | 35 |
| stop-answer | | 45 | 45 |
| reruns | | 50 | 50 |
| status-current | | 45 | 45 |
| cut-direct-text | | 15 | 15 |
| stop-record | retire-main | 50 | 100 |
| stop-lift | stop-record, stop-answer | 55 | 155 |
| rebase-trunk | stop-lift | 25 | 180 |
| call-env | rebase-trunk | 15 | 195 |
