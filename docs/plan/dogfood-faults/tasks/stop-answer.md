+++
id = "stop-answer"
part = "stop-answer"
kind = "feature"
needs = []
files = ["fab/foreman.py", "fab/tests/test_foreman.py", "fab/calls.py", "fab/tests/test_calls.py", "fab/roles/answerer.md"]
effort = "high"
minutes = 45
+++
# The answerer takes a stop's question

Read first: `docs/plan/dogfood-faults/notes/common.md`,
`docs/plan/dogfood-faults/notes/decisions.md` (6, 8).

The request, item 3, its third and fourth bullets. Design:
`docs/design/integration.md`, 3, "The answerer judges a stop". The stop's
records are `stop-record`'s (that spec, "What to build"); this task reads
them from fixture logs and needs none of its code.

## What to build

- `fab/foreman.py`, `questions` (~54): also take a `question.asked` whose
  task is `<draft>/integration` for a draft of the given tasks (their
  `draft`), with no task for it: it is specless, so queued. Nothing is
  added to the tasks, so `fab.state.fold` and `next_step` never see it.
  Its answer and a later ask follow the existing open rule.
- `fab/calls.py`, the answer call (~727-733) and `answer_brief` (~336):
  the caller adds to a stop's question dict `stop`, the `report` of the
  last `plan.stopped` for that task before its `question.asked`; the brief
  shows it as a section `Question: <draft>/integration (stop)` with `-
  Task: <draft>/integration`, `- Report: <stop>` and the question's text,
  and no task spec. Every other question reads as today.
  `integration.with_repairs` is not where it comes from.
- `fab/roles/answerer.md`: add, verbatim, "A stop's question
  (`<draft>/integration`: the trunk stopped after three tries) is answered
  as a spec-less task's is; the answer lifts the stop and reaches the
  trunk's later repairs; change no file for it." beside the role's lines on
  spec-less tasks, wrapped as the file wraps.

## Acceptance

- foreman: a stop's `question.asked` (`park` true) for a draft of the
  tasks is one queued question; for another draft it is not taken; after
  its `question.answered` it is gone; a later stop's question is open.
- calls: the answer brief of an integration plan with a stop's question
  holds `Question: <draft>/integration (stop)`, the text and the report
  path, and no spec; a repair's question reads as before.
- Every caller of `foreman.questions` (`fab/dispatch.py` ~93, ~209, ~1482,
  `fab/calls.py` ~732) copes with a question whose task is not in the
  tasks: a stop's question is only ever queued, so the foreman and settle
  paths never take it. Say in the report how each copes.
- `bin/fab test` green.

## Pre-approved defaults

- `fab/channel.py`, `fab/forge.py` and `fab/serve.py` do not change.
- The decide test (an answer call starts at once for a stop's question)
  and the `_finish` test are `stop-lift`'s, which owns
  `fab/tests/test_dispatch.py` after this task lands.

## Report

The rule as built in `questions`, the brief section as it reads, the role
line, and how each caller copes.
