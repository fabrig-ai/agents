# Request: answer calls see a ladder plan's finding repairs

From fabrig/qa via agents/loop, 2026-11-01 ~17:15Z: a live fault on fabrig plan
`v0.1.0-ladder`. Since 15:26:24Z the tick has started an answer call for it about once a
minute, more than 80 so far. Each ends done in about 15 s with "Done: 0. The brief's
Inventory was empty". Meanwhile the questions of `v0.1.0-ladder/finding-4` (15:00:42Z) and
`v0.1.0-ladder/finding-5` (16:47:03Z) sit unanswered, and finding-5 blocks rung rb1-github.

Cause, confirmed in the code on main:
- The tick decides on an answer call over the plan's tasks plus `fab.tier_reds.tasks` and
  `fab.fixes.tasks`, the specless finding repairs (`fab/dispatch.py`, the round's task set,
  ~1230 and ~1756).
- The answer call builds its own set in `fab/calls.py` `main` (~757): the plan's tasks,
  `integration.with_repairs` for an integration plan, and `tier_reds.tasks`, but not
  `fixes.tasks`.
- So `_answer_questions` finds none, and the brief lists no question. The call answers
  nothing and ends done, and the next tick starts another.
- The design says such a question goes to the answerer (`docs/design/qa.md` 2: a finding's
  repair "gets two runs, then the answerer"; `docs/design/calls.md` 2's answer call).

Build:

1. **One task set for answers.** A single helper gives the tasks whose questions an answer
   call takes:
   - the plan's tasks;
   - an integration plan's repairs (`with_repairs`);
   - `tier_reds.tasks`;
   - `fixes.tasks`;
   - an integration plan's stop question, as `docs/design/integration.md` 3 has it since
     `dogfood-faults`.

   Both the tick's answer decision (`fab/dispatch.py`, `call_actions`'s questions) and the
   answer call's brief (`fab/calls.py` `main`) use it, so they cannot disagree again.
2. **An answer call's `Answer <task>:` lines** for a finding repair are logged as that task's
   `question.answered` and folded into its body (`fab.fix`, `fab.fixes.tasks`'s "user
   answers"), as for any specless repair. Check that the path exists end to end and test it.
3. **A test:** a ladder plan with a queued finding-repair question. The tick starts one answer
   call, whose brief lists that question; with no queued question, it starts none.

The user's rule: dogfood. Built by fab's loop (landed through `bin/fab land`); the plan's
landing is `queue` (the cut is started with `--set 'landing="queue"'`). One direct part, one
task.
