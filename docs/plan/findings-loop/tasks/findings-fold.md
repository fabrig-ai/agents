+++
id = "findings-fold"
part = "findings"
kind = "feature"
needs = []
files = ["fab/findings.py", "fab/tests/test_findings.py", "fab/tests/qa_records.py"]
effort = "high"
minutes = 55
+++
# Where each finding stands

Read first: `docs/plan/findings-loop/notes/common.md`, then
`docs/plan/findings-loop/notes/fold.md` (the records and the bound names).

The request, item 2: "Findings as events (`finding.raised`) ... A finding
with the same reproduction merges with the earlier one." Design:
`docs/design/fab.md`, 13.15, "A finding is temper's record", "The same
finding is merged, never filed twice" and "Where each finding stands".

## What to build

New module `fab/findings.py` (pure; imports `fab.plan` only under
`TYPE_CHECKING`):

- the constants of `fold.md`: `BACKENDS`, `VERDICTS`, `SEVERITIES`,
  `DECISIONS`, `STATES`, `WALK_HOURS`;
- `Finding` as `fold.md` binds it, with `holds`;
- `findings(events) -> dict[str, Finding]`, keyed by id in raise order,
  holding only findings whose walk has a `walk.ended`. States, in log
  order, as 13.15 "Where each finding stands": new at its walk's end;
  merged at `finding.merged`; triaged `path` -> foreman (with `action` the
  `; user:` text while no `call.answered` of `<draft>/triage/<finding>`
  follows it), `user` or `brief` -> asked (its `question`), `backlog`,
  `drop` -> dropped, `again` -> stays new with `again` set; an answer to
  an asked finding -> new again (user) or dropped (brief, reason the
  answer's text), the answer kept in `answers`; the foreman's
  `run.started` -> deciding, its `run.ended` done -> decided, ended
  otherwise -> repairing (the fallback); `finding.settled` fix or none ->
  repairing, left -> left; the repair's `run.started` -> repairing; its
  `branch.landed` -> landed (`landed` its main); then fixed at a later
  `rung.passed` of its rung, unfixed when a later raise or triage line
  files one `again` of it; `signal.cleared` of `finding-<n>` -> dropped
  (reason the clear's text). A raise carrying `again` is new. A merged
  finding's target gains it in `sightings`.
- `target(found, identifier) -> str`: follow `into` through merged
  findings to the first that is not merged (a cycle or an unknown id gives
  the last id reached).
- `mergeable(finding) -> bool`: the merge rule's target side: new, asked,
  backlog, or foreman to repairing (a repair not landed) -> True; landed,
  fixed, unfixed, left or dropped -> False (filed again instead).

Test vocabulary `fab/tests/qa_records.py`: builders returning records as
`fab.log.record` makes them, with defaults for every field:
`walk_started(walk, rung, *, draft="ladder", ...)`, `walk_ended(walk,
verdict, findings=(), ...)`, `finding_raised(finding, walk, rung, *,
blocking=False, again="", ...)`, `finding_merged`, `finding_triaged`,
`rung_passed`; later tasks extend them.

## Acceptance

Tests in `fab/tests/test_findings.py`, each from built records:
- a walk's findings are absent until its `walk.ended`, then new;
- each triage decision gives its state; an answer makes a `user` finding
  new and a `brief` finding dropped, and releases a `path` finding's
  action;
- the repair-path records walk a finding foreman -> deciding -> decided ->
  repairing -> landed -> fixed at the next pass of its rung, and a raise
  `again` of a landed one makes it unfixed;
- `target` resolves a chain of merges; `mergeable` per state as above;
- `holds`: a blocking finding while new holds, a non-blocking one of a
  passing walk does not, one of a void walk does; a left one does not;
- a record missing a field is skipped.

## Pre-approved defaults

- `findings` folds every draft's findings; readers filter by `draft`.
- `evidence` not a list of strings in a record: `()`.

## Report

The functions and states built, and any state transition the design left
open that you had to choose (one line each).

## Repair (2026-11-01, step gate:size, foreman findings-loop/findings-fold/foreman-1)

Extract per-finding transitions from findings() into a private function in fab/findings.py.
The branch owns this gate finding: `fab/findings.py:113` findings is 97 lines (cap 60).
Move the `finding.triaged`, `finding.settled`, `signal.cleared`, and run/landing transition block into a documented private function.
Pass its finding, event, and fold state explicitly; preserve updates to `found`, `asks`, and `foremen`.
Keep `findings(events)` and every extracted function within the 60-line cap.
Preserve log order, walk-end visibility, and all transitions required by `docs/design/fab.md`, 13.15, “Where each finding stands”.
This refactor needs only `fab/findings.py`; use the existing `fab/tests/test_findings.py` coverage.
Verify with `python3 -B -m fab.testrun` and the landing size gate.
No files changed or builds run. The read-only environment prevents writing report.md; this response is the report.
