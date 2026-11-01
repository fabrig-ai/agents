+++
id = "stop-lift"
part = "stop-asks"
kind = "feature"
needs = ["stop-record", "stop-answer"]
files = ["fab/integration.py", "fab/tests/test_integration.py", "fab/dispatch.py", "fab/tests/test_dispatch.py"]
effort = "high"
minutes = 55
+++
# The answer lifts a stop

Read first: `docs/plan/dogfood-faults/notes/common.md`,
`docs/plan/dogfood-faults/notes/decisions.md` (5, 6, 9).

The request, item 3, its fifth and sixth bullets and the `_finish` part of
the fourth. Design: `docs/design/integration.md`, 3, "The answerer judges
a stop" ("After a lift the stop's counts start afresh ..."). Builds on
`stop-record`'s `integration.lifted`.

## What to build

- `fab/integration.py`, counts start afresh after the lift
  (`lifted(plan, events)`):
  - `next_step`: only end reds started after the lift count toward three;
  - `queue_step`: only queue rejections after the lift count toward
    `QUEUE_LIMIT`;
  - `_catch_up_refusals`: at the lift `refused` restarts at 0 and `merged`
    empties (a main sha's repair counts as merged only when it merged
    after the answer); repair ids keep counting (`catch-up-<n>` on from
    before);
  - `catch_up_waiting`: only a stopping refusal after both the last clean
    catch-up and the lift.
  `repair-<n>` keeps its numbering too.
- `fab/integration.py`, `repair_tasks`: a `question.answered` for
  `<draft>/integration` with an `answer` and no `by` `tick` is folded under
  Answers into every repair not merged into the trunk when it was logged
  (the stopping red's own repair among them) and every later one, in log
  order with the repair's own answers.
- `fab/dispatch.py`, `_integration`: while a `catch-up` stop is open (its
  `plan.stopped` after the lift, `why` `catch-up`), a clean catch-up logged
  after it (the records `integration._clean_catch_up` reads: the tick's,
  a checked repair's or by hand; expose a public pure helper in
  `fab/integration.py` for it)
  logs the stop's `question.answered` (task `<draft>/integration`, answer
  `lifted by a clean catch-up`, `by` `tick`), once.

## Acceptance

- integration: after an answer, a fourth end red is a first (no stop), a
  third red after the answer stops again; the same for queue rejections
  and catch-up refusals; the catch-up repair after the answer is numbered
  on; a repair merged before the answer does not count as merged for its
  sha after it.
- integration: the stop's answer is in the Answers of the unmerged repairs
  and of a repair made after it, not of one merged before it; the tick's
  lift is in none.
- dispatch: a clean catch-up after a catch-up stop logs the
  `question.answered` above, once across two ticks; after a red stop it
  logs none.
- dispatch: `decide` for an integration plan whose only queued question is
  a stop's starts the answer call at once; `_finish` of that call with a
  report holding `Answered: <draft>/integration` and `Answer
  <draft>/integration: <text>` logs `question.answered` with that answer
  (today's `_finish` should already; add the test).
- `bin/fab test` green.

## Pre-approved defaults

- A docstring that states the old counting rule is reworded as built.
- An answer logged by hand (no call) for `<draft>/integration` lifts as a
  call's does.

## Report

Each function's rule as built, the tests added, and whether `_finish`
needed a change.
