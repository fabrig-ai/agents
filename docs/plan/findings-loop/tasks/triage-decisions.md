+++
id = "triage-decisions"
part = "triage-rules"
kind = "feature"
needs = ["findings-fold", "ladder-plan"]
files = ["fab/triage.py", "fab/tests/test_triage.py"]
effort = "high"
minutes = 55
+++
# When triage is due, what its report decides, and the backlog's text

Read first: `docs/plan/findings-loop/notes/common.md`,
`docs/plan/findings-loop/notes/fold.md`,
`docs/plan/findings-loop/notes/triage.md`.

The request, item 3 (triage) and "the tick's triage steps: starting the
call when due, recording its decisions, rendering and readying the
backlog". Design: `docs/design/fab.md`, 13.15, "When", "Code records the
decisions", "Off the path is the tree's backlog" (its render and the two
rejections).

## What to build

New module `fab/triage.py`, pure, with the names `notes/triage.md` binds:
- `ROLE`, `AT`, `AFTER`, `subject(draft)`;
- `due(plan, events, now) -> bool`: 13.15 "When": a finding of the plan
  new; no triage call of the plan in flight; no triage `Question:` open
  (a `call.ended` outcome question for `<draft>/triage` with no later
  `call.answered` of that subject); and a new finding blocking or from a
  failed or void walk, or `AT` new, or the oldest new `AFTER` minutes old
  (since its walk's `walk.ended`, or since the answer or raise that made it
  new again). A call that ended failed is followed only after a new finding
  or `AFTER` minutes from its end.
- `decisions(plan, events, reports) -> list[tuple[str, dict]]`: per triage
  call of the plan ended done whose id no `finding.triaged`,
  `finding.merged` (by) or note (`call`) carries, its report's lines
  parsed as `notes/triage.md` binds them, giving `finding.triaged` (fields
  as `notes/fold.md`) or `finding.merged` (by the call); a merge into a
  finding not `fab.findings.mergeable` gives `finding.triaged` decision
  `again` (into the target); skip a line naming a finding that is not new
  (or backlog, for a re-decision), not the plan's, a merge into itself, an
  unknown finding or one it is already `again` of, and a second line for
  one finding; a call with no valid line gives one `note` (`call`, `text`
  `triage <call>: no decisions`).
- `backlog_text(plan, events) -> str`: a header (the ladder, that fab
  writes it from its log, not to edit by hand), then per finding in state
  backlog in raise order `## <finding>: <title>` with its rung, walk,
  backend, commit, area, severity, sightings, reproduction, expected, seen
  and the triager's reason; ending with a newline.
- `render_key(text) -> str`; `backlog_held(plan, events, render) -> dict |
  None`, as `notes/triage.md` binds them.

## Acceptance

Tests in `fab/tests/test_triage.py`:
- a failed walk's finding makes triage due at once; a passing walk's
  waits for four new or thirty minutes; an open triage question, or a call
  in flight, makes it not due; a failed call is followed only after a new
  finding or thirty minutes;
- each line form logs once with its fields (`path`, `path ...; user:`,
  `backlog`, `user`, `brief`, `merge`, `drop`), a merge into a landed one
  logs `again`, and a line for a finding not new is skipped; a second
  `decisions` over the logged records gives nothing; a report of prose only
  gives the note;
- the backlog renders its findings in raise order and drops one
  re-decided to the path or merged;
- `backlog_held`: none after one rejection, the record after two of one
  render, none after a clear, a landing, or for another render;
- `AT == fab.dispatch.ANSWER_AT` and `AFTER == fab.dispatch.ANSWER_AFTER`.

## Pre-approved defaults

- Lines may carry leading `- ` or `* ` (a list): accept and strip them.
- An unknown decision word: the line is skipped.

## Report

The rules built, and the parse's tolerance in one line.
