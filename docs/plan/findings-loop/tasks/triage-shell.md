+++
id = "triage-shell"
part = "triage-call"
kind = "feature"
needs = []
files = ["fab/calls.py", "fab/tests/test_calls.py", "fab/roles/triager.md"]
effort = "medium"
minutes = 40
+++
# A call that writes no branch, and the triager's role text

Read first: `docs/plan/findings-loop/notes/common.md`,
`docs/plan/findings-loop/notes/triage.md`.

The request, item 3: "Triage by a director-role call: on the path, a repair
task in a plan, with 'a test in the lowest world, red then green' as its
acceptance; off the path, the backlog; needs the user, a question on the
user's page." Design: `docs/design/fab.md`, 13.15, "Triage is a Claude call
in the director's role", "It writes no branch" and "It decides each new
finding".

## What to build

- `fab.calls.start(..., report_only: bool = False)` (near line 466): with
  report_only, the worktree is the repository detached at
  `origin/<base>` after a `git fetch origin` (`git worktree add --detach
  <wt> origin/<base>`); `call.started` carries no `branch`; nothing is
  pushed; the worktree is removed as now; the returned `branch` is "".
  Without it, nothing changes. A branch argument with report_only is a
  ValueError.
- `fab/roles/triager.md`: the triager's role text, from 13.15's triage
  bullets: who it is (the director triaging every finding of a ladder, as
  `temper/docs/design/draft/v0.1.0.md` 4 has it), what the happy path is
  (the brief's `# The happy path`), the six decision lines exactly as
  `notes/triage.md` binds them, when each applies (13.15's list, including
  "a blocking finding is on the path unless it is not the product's", the
  model going against what it is told, `; user:` for an action of the
  user's the rerun needs, a re-decision of a backlog finding), that a
  merge needs the same cause (the brief's `# Open findings`), that it
  writes nothing but its report, and the report's first line. Match the
  other role files' tone and length (`fab/roles/answerer.md`).

Do not register the role in `fab.calls.ROLES` (triage-brief does, with the
brief that uses it).

## Acceptance

Tests in `fab/tests/test_calls.py`, with a `FakeRunner`: a report-only
call adds a detached worktree, logs `call.started` without `branch`,
pushes nothing (even for a fabrig repository) and removes the worktree on
success and on failure; an existing call's argvs are unchanged.

## Pre-approved defaults

- A test may use an existing role (`answer`) for report_only.

## Report

The change to `start`, and the role text's sections in one line each.
