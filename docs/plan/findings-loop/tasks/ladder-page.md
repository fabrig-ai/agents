+++
id = "ladder-page"
part = "page"
kind = "feature"
needs = ["triage-decisions", "rungs-fold", "ladder-plan"]
files = ["fab/channel.py", "fab/tests/test_channel.py", "fab/forge.py", "fab/tests/test_forge.py", "fab/serve.py", "fab/tests/test_serve.py"]
effort = "high"
minutes = 50
+++
# The page: a finding's question, the backlog's signal and the ladder

Read first: `docs/plan/findings-loop/notes/common.md`,
`docs/plan/findings-loop/notes/fold.md`,
`docs/plan/findings-loop/notes/triage.md`.

The request: "the page's `finding` asks and `## The ladder`
(`fab/channel.py`)"; needs the user, "a question on the user's page".
Design: `docs/design/fab.md`, 13.6 (the fourth kind of ask, the page's
sections, `backlog:<draft>`) and 13.15 ("fab says a rerun is due").

## What to build

In `fab/channel.py`:
- `KINDS` gains `finding`. `_log_asks` (near line 542) opens one per
  `finding.triaged` with a question (decision `user` or `brief`, or `path`
  with a `; user:` action): subject `<draft>/triage/<finding>`, text the
  question, since its ts, call the triage call, report
  `FAB_HOME/walks/<walk>/report.md`; a `call.answered` of the subject
  closes it.
- `compose` gives a finding ask's body: the finding's title, rung and the
  first `QUESTION_LINES` lines of its reproduction, then the ask's text;
  `render` heads it `### <subject>, asked <since>` with `- Read:` and `-
  Answer: fab page answer <subject> TEXT`, as a call's.
- `answer` answers an open finding ask as it does a call's.
- `backlog:<draft>` among the open signals for each loaded ladder plan
  while `fab.triage.backlog_held(plan, events, render_key(backlog_text))`
  holds a record: `- Branch`, `- Step`, `- Read:` the record's log;
  clearable (`fab page clear backlog:<draft> TEXT` logs `signal.cleared`).
- `## The ladder` after `## After landing`, before `## Unread`: per loaded
  plan with rungs, `### <draft>`, one `- <line>` per rung
  (`fab.findings.rungs` at the plan's editions, `fab.walks.editions`),
  then `- Backlog: <n> findings in \`<backlog path>\``. An edition that
  cannot be read: the plan's line in `## Unread`.

`fab/forge.py` (13.16) and `fab/serve.py` (13.14) read asks: a finding ask
must open and close its issue as a call's does, and count under
`by_kind` `finding`. Change them only where they do not.

## Acceptance

Tests in `fab/tests/test_channel.py` (and the forge or serve tests if
either changed):
- a `user` decision is on the page with the finding's title, rung and
  reproduction, and its answer closes it; `brief` and `path ...; user:`
  likewise;
- `## The ladder` shows each rung's line and the backlog's count, after
  `## After landing`;
- `backlog:<draft>` shows after two rejections of one render and goes
  after a clear;
- pages without ladder plans are unchanged (the existing tests).

## Pre-approved defaults

- A ladder plan whose directory is not in a checkout: its editions
  unreadable, so its line in `## Unread`.

## Report

The page's new parts, and whether forge or serve needed a change.

## Repair (2026-11-01, step gate:size, foreman findings-loop/ladder-page/foreman-1)

Extract rendering helpers in fab/serve.py so render meets the 60-line cap.
The gate finding is `fab/serve.py:347`: `render` is 130 lines (cap 60).
This branch modifies `render` to display finding asks, so the finding requires repair.
Move the nested tile, card and subscriptions-table functions to module-level helpers.
Extract the tiles and Drafts panel construction into focused helpers as needed.
Keep `render` and each extracted helper within 60 lines.
Preserve HTML escaping, section order, empty states, issue links and the Finding questions row.
Keep the behavior required by `docs/design/fab.md`, section 13.14.
Limit the repair to `fab/serve.py`, with `fab/tests/test_serve.py` changes only if needed.
Run the serve tests with Python `-B`, then `bin/fab test` and the size gate.

## Repair (2026-11-01, step test, foreman findings-loop/ladder-page/foreman-2)

isolate the page’s edition reader from the dispatch edition-read spy
`LadderTickTest.test_decisions_then_passes_reach_decide_and_use_one_edition_read` expects one call but sees two.
The first is dispatch’s `_record_passes(..., sh=self.fake)` on origin/main.
The second comes from this branch’s `fab/channel.py:compose`, calling `walks.editions` without `sh`.
Both reference the same module attribute, so the dispatch test also intercepts the page’s independent read.
In `fab/channel.py`, import `editions` into a channel-local binding and use that binding in `compose`.
Update edition-reader patches in `fab/tests/test_channel.py` to patch that local binding and retain FakeRunner coverage.
Preserve current-edition rendering and unreadable-plan handling required by `docs/design/fab.md`, sections 13.6 and 13.15.
Keep changes within those two authorized files; do not weaken the dispatch assertion.
Run the channel tests and the failing dispatch test with Python `-B`, then `bin/fab test` and the size gate.
