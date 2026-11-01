+++
id = "stop-record"
part = "stop-asks"
kind = "interface"
needs = ["retire-main"]
files = ["fab/integration.py", "fab/tests/test_integration.py", "fab/dispatch.py", "fab/tests/test_dispatch.py"]
effort = "high"
minutes = 50
+++
# A stop logs `plan.stopped` and its question

Read first: `docs/plan/dogfood-faults/notes/common.md`,
`docs/plan/dogfood-faults/notes/decisions.md` (5, 6, 7).

The request, item 3, its first two bullets and the last. Design:
`docs/design/integration.md`, 3, "A stop asks". Today
`fab.integration.next_step`'s `Step("stop", ...)` becomes a log note only
(`fab/dispatch.py` `_integration`, ~1966).

## What to build

- `fab/integration.py`: `Step` gains `why: str = ""`, set on the three stop
  steps: `red` (the third end red, `next_step`), `catch-up` (a stopping
  catch-up refusal, `next_step`), `queue` (the third queue rejection,
  `queue_step`). Kind `interface` for this field.
- `fab/integration.py`, pure: `lifted(plan, events) -> int`, the position
  of the last `question.answered` for task `<draft>/integration` (-1 when
  none); and `stopped(plan, events, step, gate) -> list[tuple[str, dict]]`,
  the records to log for a stop step: none when a `plan.stopped` for
  `<draft>/integration` comes after `lifted`; otherwise `plan.stopped` (task,
  `tip`, `why`, `text`, `report`) and `question.asked` (task, `run`, `text`,
  `park` true). `report`: for `red` the last red end check's
  `FAB_HOME/runs/<run>/report.md`; for `queue` `<gate>:<log>`, the last
  queue rejection's `log` on the gate host; "" for `catch-up`, whose `text`
  quotes the stopping refusal's findings, at most 20 lines. `run`: the
  last red end check's run for `red`, "" otherwise. The question's text is
  the record's.
- `fab/dispatch.py`, `_integration`: a `stop` step logs `stopped`'s records
  in that order (the gate being the first host by name with role gate, as
  `_import_queue` reads it; "" when none) and prints as today. The
  same-tip note it logs today goes for stops; other steps' notes stay.

## Acceptance

- integration: a third end red, a stopping catch-up refusal and a third
  queue rejection each give `stopped`'s two records with the fields above;
  a second call with the first `plan.stopped` in the log gives none (a
  merge while it holds logs nothing); after a `question.answered` for
  `<draft>/integration` a new stop gives them again.
- dispatch: a tick at the third end red logs `plan.stopped` then
  `question.asked` (`park` true, `run` the red check's run), once across
  two ticks.
- `plan.stopped` is in no list of `fab/wake.py` (unchanged); the
  `question.asked` is in `wake.AGAIN` already.
- `bin/fab test` green.

## Pre-approved defaults

- Counts do not start afresh after an answer yet: `stop-lift` does that.
  Until it lands, an answered stop asks again once; that is expected.
- A test that pins today's stop note changes to pin the two records.

## Report

`Step`'s field, the two functions' signatures, the records as logged, the
tests added or changed.
