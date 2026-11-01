+++
id = "answer-set"
part = "answer-set"
kind = "feature"
needs = []
files = ["fab/calls.py", "fab/tests/test_calls.py", "fab/dispatch.py", "fab/tests/test_dispatch.py"]
effort = "high"
minutes = 50
+++
# One task set for answers

Read first: `docs/plan/answer-findings/notes/common.md`,
`docs/plan/answer-findings/notes/decisions.md`.

The request, items 1-3. Design: `docs/design/calls.md`, 2, the answer
call; `docs/design/qa.md`, 2 (a finding's repair "gets two runs, then the
answerer"); `docs/design/integration.md`, 3 (a stop's question).

## What to build

- `fab/calls.py`: a public `answer_tasks(plan, tasks, events, *,
  folded=None) -> dict[str, Task]`, the tasks whose questions an answer
  call takes, as decision 3 has it: `integration.with_repairs`, the plan's
  `fix.FIX_KINDS` tasks dropped, then `tier_reds.tasks(plan, events,
  folded=folded)` and `fixes.tasks(plan, events)`. Its docstring says both
  the tick and the answer call use it, and that a stop's question comes
  through `fab.foreman.questions` over it.
- `fab/calls.py` `main`, the answer branch (~754-758): build `tasks` with
  `answer_tasks` instead of its own lines.
- `fab/dispatch.py` `_tick_loaded` (~1228-1230): the round's task set is
  `calls.answer_tasks(plan, <the checked tasks>, events, folded=folded)`,
  so `call_actions`' questions (~93) read the same set. `main`'s dry run
  (~1756) uses it too. `_integration_tasks` stays for its other callers
  (~1420, ~1931).
- The answer's path (request item 2): an answer call's report with
  `Answer <draft>/finding-<n>: <text>` and that id under `Answered:` is
  logged by `_finish` (~915, `_answered` ~1683) as that task's
  `question.answered` with the answer, and `fixes.tasks` folds it into the
  repair's body under `## Answers`. Test it; change `_finish` or
  `_answered` only if the test shows the path broken.

## Acceptance

- calls: `answer_tasks` of a plan with a finding repair (a `fixes.tasks`
  fixture, as `fab/tests/test_fixes.py` builds one) holds the repair; a
  red repair and, for an integration plan, a check repair too; a plan
  task of a fix kind is replaced by the folded one.
- calls: the answer brief (`main(["answer", "--plan", ..., "--brief-only"])`)
  of a ladder plan (`rungs` set, `repo = "fabrig"`) with a queued
  question on `<draft>/finding-1` lists that question and the repair's
  body as its spec, beside `test_answer_includes_red_task_questions_for_both_landing_modes`
  (~1147); an integration stop's question still reads as before.
- dispatch, beside `FindingDispatchTest` (~6275): a ladder plan's tick
  with a queued finding-repair question starts one answer call; with no
  queued question it starts none; and the brief that call would read
  lists the question (call `calls.main` with `--brief-only` on the same
  log, or assert both sides read `calls.answer_tasks`).
- dispatch: `_finish` on an answer chain whose report has `Answer
  <draft>/finding-1: <text>` and `Answered: <draft>/finding-1` logs
  `question.answered` for that task with the answer, and `fixes.tasks`
  then has the answer in the repair's body.
- `bin/fab test` green.

## Pre-approved defaults

- `fab/fix.py`, `fab/fixes.py`, `fab/foreman.py`, `fab/integration.py`
  and `fab/roles/answerer.md` do not change; if the answer's path needs
  one of them, that is a `Question:`.
- A test that pinned the answer call's narrower set (no `fixes.tasks`)
  changes to the shared set; say which in the report.
- The ladder plan's fixtures may reuse `LadderTickTest`'s and
  `FindingDispatchTest`'s helpers; do not move them.

## Report

The helper's set as built, each caller that now uses it, whether the
answer's path needed a change (and which), and the tests added.
