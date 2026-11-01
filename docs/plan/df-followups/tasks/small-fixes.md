+++
id = "small-fixes"
part = "small-fixes"
kind = "feature"
needs = ["from-main"]
files = ["fab/run.py", "fab/tests/test_run.py", "fab/calls.py", "fab/tests/test_calls.py", "docs/design/integration.status.md", "docs/design/tick.status.md"]
effort = "medium"
minutes = 45
+++
# The branch probe, a stop's empty report, two status lines

Read first: `docs/plan/df-followups/notes/common.md`,
`docs/plan/df-followups/notes/decisions.md` (7, 8).

The request's items 2-4.

## What to build

- **Item 2, `fab/run.py`** (~327-329, in the run's start): the `git
  rev-parse -q --verify refs/remotes/origin/<branch>` probe over ssh reads
  any failure, an ssh 255 or a git 128 among them, as "absent", and the
  rerun starts from the base. Make `probe.code not in (0, 1)` raise
  `Failed(argv, probe)`, as `dispatch._contains` does (decision 7); 0 is
  present, 1 absent.
- **Item 3, `fab/calls.py` `answer_brief`** (~350-352): when a stop
  question's `stop` (its report) is `""`, render `- Report: (none: the
  findings are quoted below)` instead of an empty code span.
- **Item 4, `docs/design/integration.status.md`** (~72-78), the bullet
  "An integration trunk through the queue is untried live": drop "no plan
  has yet run with `ready = true`", and replace what follows "So are the
  stop's question and its lift" so the bullet ends:

  > ... the stops are tested against fakes and real git only. So are the
  > stop's question and its lift. The retire from main ran live once (the
  > probe phase-case, 11-01): its trunk landed through the queue at
  > 17:17:58Z, its retire started from main (17:27:16Z), went through
  > `ready/calls/retire-2c39…` and landed at fc1651448b, and the plan
  > checkout detached there; its landing was never imported (no
  > `branch.landed` or `call.finished`; tick.md 5, start-commands item 4).
  > No trunk has stopped since the stop's records were built.

- **Item 4, `docs/design/tick.status.md`** (~32-33): "The dispatcher: …
  run by hand, live since 20:27Z" becomes "The dispatcher: `fab tick
  PLAN_DIR` collects, lands, starts and parks; on hel8 started by
  `fab-events.path` and the 10-minute `fab-backstop.timer` (Events drive
  the tick, below)".

## Acceptance

- `test_run.py`, beside `test_an_implement_rerun_continues_from_its_pushed_branch`
  (~571): a probe answering 255 and one answering 128 raise `Failed`
  and start nothing (no switch, no `worktree add`, no codex launch); 1
  starts from the base as today; 0 from `origin/<branch>`.
- `test_calls.py`, beside `test_answer_stop_section_has_its_report_and_no_spec`
  (~528): a stop with report `""` shows `- Report: (none: the findings
  are quoted below)` and no empty backticks; a stop with a report path
  shows it as today.
- The two status lines read as above; nothing else in either file changes.
- `bin/fab test` green.

## Pre-approved defaults

- If the probe's ssh wrapper hides the result's code, keep the call's
  shape and read `.code` on the result `sh(...)` returns, as today's
  `.ok` does.

## Report

The functions changed, the tests added, and the two status lines as
written.
