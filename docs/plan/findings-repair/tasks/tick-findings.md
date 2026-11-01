+++
id = "tick-findings"
part = "tick"
kind = "feature"
needs = ["finding-repair", "fix-pair"]
files = ["fab/dispatch.py", "fab/tests/test_dispatch.py", "fab/wake.py", "fab/tests/test_wake.py"]
effort = "high"
minutes = 50
+++
# The tick's finding steps: foremen started and settled, repairs joined

Read first: `docs/plan/findings-repair/notes/common.md`,
`docs/plan/findings-repair/notes/fix.md`.

The request: "the tick's steps: one examine/remedy action pair for reds
and findings ..., the finding repairs joined to the plan's tasks,
`FIX_KINDS` wherever the red wiring reads kind `red`". Design:
`docs/design/qa.md`, 2, "One action pair for both kinds", "Its
foreman", "Everything after-landing.md 2 gives kind `red` holds" and
"The tick, each round".

## What to build

In `fab/dispatch.py`, on `fix-pair`'s pair and `_fix_steps`:
- `finding_actions(plan, events) -> list[Action]`, pure, in raise order:
  for each finding of the plan's draft (`fab.findings.findings`) in state
  foreman, `Action("examine-fix", task=fixes.repair_id(f), detail=f.id,
  run_kind="finding")`; decided, `Action("remedy-fix", ..., run=<its
  foreman run from fab.fixes.foremen>, run_kind="finding")`.
- `_fix_steps` sends kind `finding`: examine to `fab.fixes.start` on
  `_builder(hosts, events)` (most free places, even at none) with `tip`
  main's tip in the plan's checkout (`git rev-parse origin/main` there,
  read once per round) and the plan directory's repository path; remedy
  to `fab.fixes.settle` with the report read from the foreman's `report`
  (unreadable: settle with "", which the fallback reads as none).
- `_tick_loaded` (near line 1053): the plan's tasks joined with
  `fab.fixes.tasks(plan, events)` beside `tier_reds.tasks`;
  `finding_actions` run after the refusal settlements, beside
  `red_actions`.
- `_reconcile_reds` (near line 925) and `_round` (near line 971): the
  queue import's tasks and the after-landing owners include each plan's
  finding repairs, so a landed `<draft>/finding-<n>` imports as
  `branch.landed` and is a fab suspect after landing.
- `fab/wake.py`: `finding.settled` joins `AGAIN` (after `red.settled`),
  so the repair starts on the next round as a red's does.

## Acceptance

Tests in `fab/tests/test_dispatch.py`, through `tick(...)` with a ladder
plan from `fab/tests/ladder_plans.py` and records from
`fab/tests/qa_records.py`, as qa.md 2's "Tests" words them:
- a path decision starts one foreman, and no second on the next tick;
- its `Done: fix:` report, collected, settles `finding.settled` fix once
  and makes `<draft>/finding-<n>`, which starts an implement run from
  `origin/main` and, done, is readied; its queue landing imports as
  `branch.landed`, after which `fab.findings.rungs` shows the rung due for
  a rerun at that main;
- its `Done: retry:` settles left: no repair starts and the rung is not
  held; a foreman ending failed starts the repair with the finding alone;
- a red's examine-fix and remedy-fix run as before beside a finding's in
  one round;
- `fab/tests/test_wake.py`: `finding.settled` wants another round.

## Pre-approved defaults

- A failed `git rev-parse` for the tip: one `note`, no foreman this round.
- `fab/dispatch.py` and its tests are shared with `findings-loop/
  backlog-branch`; if it lands while you work, rebase and keep both.

## Report

The steps added and where in `_tick_loaded`, `_reconcile_reds` and
`_round`; the end-to-end test's path.
