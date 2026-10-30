+++
id = "foreman-tick"
part = "foreman"
kind = "feature"
needs = ["foreman", "call-review-tick", "flow", "tick-split"]
files = ["fab/dispatch.py", "fab/calls.py", "fab/tests/test_dispatch.py", "fab/tests/test_calls.py"]
effort = "high"
minutes = 40
+++
# The tick sends each question to the foreman before the answerer

Today every open question waits for the answerer: an answer call starts at
four open questions or when the oldest is two hours old. From this change
on, a question asked by an implement, repair or rebase run first gets a
foreman run. When the foreman settles it from the spec's options, the tick
writes the answer into the spec, lands it and logs question.answered, and
the task runs again. Only questions the foreman did not settle, and those it
never sees (a park at MAX_RUNS), queue for the answerer, and the answerer's
thresholds count only those. The states are `fab.foreman.questions`
(filled by `foreman`); this task drives them from the tick. Update the
docstrings of every function you change to say what it now does. Design:
`docs/design/fab.md`, 13.1; the events in section 3.

## What to build

- **`fab.dispatch.foreman_actions(tasks, events) -> list[Action]`,** a new
  pure function: one action per `fab.foreman.questions(tasks, events)`, in
  its order:
  - foreman: `Action("foreman", task=<task>, run=<asking run>,
    detail=<asking run>)`;
  - settled: `Action("settle", task=<task>, run=<foreman run>,
    detail=<foreman run>)`;
  - deciding and queued: nothing.
- **`fab.dispatch.tick`:** after decide's actions and before call_actions',
  it takes `foreman_actions(tasks, log.read(log_path))`; call_actions then
  reads the log as it stands after them. Each action's body is a private
  module-level function, as `call-review-tick` left the others:
  - foreman: the builder is chosen as vet chooses it (most free places,
    even at none, ties by name; no builder at all is a failed action),
    through the same private function. The question is recomputed from the
    log: the one of the task and asking run in state foreman, else a
    ValueError. Start it with `fab.foreman.start(question, tasks[<task>],
    host, log.read(log_path), sh=sh, log_path=log_path)`; the printed
    detail is `<asking run> <host>`.
  - settle: the question is recomputed the same way, in state settled. The
    answer is `fab.foreman.answer` of FAB_HOME/runs/<foreman run>/report.md
    (fab.run.collect's copy). The branch is `fab.foreman.commit(question,
    task, answer, <the plan's checkout root>, run_id=<foreman run>,
    day=<today, UTC, YYYY-MM-DD>, sh=sh)`. A branch lands through
    `fab.land.main([branch])` by the private function `tick-split` adds for
    land and finish (`_land_branch`; refused: a RuntimeError with its
    output); None lands nothing. Then log
    question.answered (task, by: the foreman run, run: the asking run,
    answer: the answer's first line). Any failure logs no
    question.answered: the question stays settled and the next tick tries
    again. A plan_dir that is not a git checkout fails the action.
- **`fab.dispatch.call_actions`:** the answer call's thresholds read the
  queued questions, `fab.foreman.questions(tasks, events)` in state queued,
  in place of `fab.calls.open_questions`: ANSWER_AT of them, or the oldest
  `since` ANSWER_AFTER minutes before `now`.
- **`fab/calls.py`:**
  - `main`'s answer role gives `answer_brief` the queued questions only,
    each as `{"task", "run", "text", "foreman"}`, foreman being the
    question's `report` ("" when no foreman ran).
  - `answer_brief` adds the line `- Foreman: \`<path>\`` after a
    question's `- Report:` line when its `foreman` is not empty, so the
    answerer reads why the options did not settle it.

## Acceptance

- `fab/tests/test_dispatch.py`:
  - `foreman_actions` as a pure function: each state's action, their
    order, tasks of another plan left out.
  - `call_actions`: questions at the foreman or deciding do not count
    toward ANSWER_AT; a queued one ages from its foreman's run.ended, not
    from its question.asked; a park question counts at once.
  - `tick` with `support.FakeRunner` and patched `fab.foreman.start`,
    `fab.foreman.commit` and `fab.land.main` (record their calls):
    - a run collected with a question starts its foreman in the same tick,
      on the builder with most free places, even at none;
    - settle lands the branch and logs question.answered with by and run,
      and the next tick starts the task (decide sees it runnable);
    - commit returning None logs question.answered without a landing;
    - a refused landing logs a note and no question.answered, and the next
      tick settles again;
    - foreman actions come before the call actions.
- `fab/tests/test_calls.py`: `main answer --brief-only` lists only queued
  questions, with the Foreman line for one the foreman refused.
- `bin/fab test` passes; the touched test modules stay under a second each.

## Options, settled up front

- `foreman-tick` follows `call-review-tick` (vet's builder choice), `flow`
  (places as hints) and `tick-split` (`tick`'s actions as private
  functions, `_land_branch`), all in `fab/dispatch.py`. Reuse what they
  left; keep each new or changed function within 60 lines.
- `Action.kind`'s comment lists the new kinds foreman and settle.
- A foreman run is never retried: an infra foreman queues its question for
  the answerer (`fab.foreman.questions`).
