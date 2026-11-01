+++
id = "triage-brief"
part = "triage-call"
kind = "feature"
needs = ["triage-decisions", "triage-shell", "rungs-fold"]
files = ["fab/triage.py", "fab/calls.py", "fab/tests/test_triage.py", "fab/tests/test_calls.py"]
effort = "high"
minutes = 45
+++
# The triage call's brief and its command

Read first: `docs/plan/findings-loop/notes/common.md`,
`docs/plan/findings-loop/notes/fold.md`,
`docs/plan/findings-loop/notes/triage.md`.

Design: `docs/design/fab.md`, 13.15, "Triage is a Claude call in the
director's role" (role, effort, subject, `fab call triage --plan`) and "Its
brief".

## What to build

In `fab/triage.py`:
- `brief(plan, events, root, plan_dir, editions, *, call_id, branch,
  report, now) -> str`, through `fab.calls._brief` and `fab.calls._facts`
  as the other briefs are: `Role` (`fab/roles/triager.md`), `Call facts`,
  `The happy path` (`fab.calls._cited_design(root, plan.ladder.happy_path)`),
  `The rungs` (each rung's `fab.findings.line`, then the brief files of
  every rung with a new finding, whole, read from plan_dir), `New
  findings` (each with every field, its walk's verdict, `again` when set,
  and `fab.channel.answers_text(<draft>/triage/<finding>, events)`), `Open
  findings` (every finding asked, foreman to repairing, landed or backlog:
  id, state, rung, area, title, sightings; one line each).
- `main(argv)`: `fab call triage --plan PLAN_DIR [--brief-only]`: load the
  plan, compile the brief (editions through `fab.walks.editions`), and
  `fab.calls.start(ROLE, subject(draft), repo, text, base=plan.trunk,
  report_only=True)`, repo as `fab.calls.main` picks it
  (`FAB_HOME/repos/fabrig` for a fabrig plan); print the outcome; exit 0
  for done, 1 otherwise or on a refusal (a plan without rungs).

In `fab/calls.py`: `ROLES["triage"]` (`fab/roles/triager.md`),
`EFFORTS["triage"] = "medium"`, and `main` handing `triage` to
`fab.triage.main(argv[1:])` before its parser, as it hands the designer's
roles over, the role kept out of its subparser loop.

## Acceptance

Tests in `fab/tests/test_triage.py` and `fab/tests/test_calls.py`:
- the brief holds its sections in order, a rung's brief only when it has a
  new finding, each new finding's fields and the user's answer to it, and
  the open findings' lines;
- `fab call triage --plan` starts a report-only call with subject
  `<draft>/triage` and effort medium (a `FakeRunner`, as the answer call's
  test does); `--brief-only` prints the brief and starts nothing;
- `fab call answer` and the other roles are unchanged.

## Pre-approved defaults

- The brief over `fab.calls.BRIEF_LIMIT`: the ValueError `_brief` raises
  (no trimming).

## Report

The brief's sections and the command, and the brief's size on the tests'
ladder.
