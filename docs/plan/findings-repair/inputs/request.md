# The request: QA findings repaired through fab's red path

From the operator of the findings-loop run (2026-11-01), passing on the user's request. The
design is `docs/design/fab.md`, 13.15 (QA findings); the user's request in full, and the first
plan's part of it, are `docs/plan/findings-loop/inputs/request.md`. This plan,
`findings-repair`, builds the rest of the first build: the repair path, now that red-routing's
tick wiring is on main (`fab/tier_reds.py`, section 11, 13.1's red foreman).

## What this plan builds

What 13.15's "Built in this order" lists after red-routing's wiring, on top of the first plan's
code (`fab/findings.py`, `fab/triage.py` and the tick's triage steps, landed by
`findings-loop`):

- `fab/fix.py`, factored out of `fab/tier_reds.py` (the foreman's launch, `parse`, `section`,
  `settle`, the repair task's construction, `FIX_KINDS`, `RUNS`), red's behaviour and tests
  unchanged;
- `fab/fixes.py` and `fab/roles/foreman-finding.md`: a routed finding's foreman, its brief,
  its settlement (`finding.settled`) and the `<draft>/finding-<n>` repair task folded from the
  log, with the Fix-mode acceptance (a test in the lowest world, red before and green after);
- the tick's steps: one examine/remedy action pair for reds and findings (`examine-fix`,
  `remedy-fix`, the rename section 11 names), the finding repairs joined to the plan's tasks,
  `FIX_KINDS` wherever the red wiring reads kind `red`;
- the `finding-<n>` signal on the user's page for a finding its foreman left.

**Not in this plan:** walks run by fab (13.15's last part) and "Then it holds" (14). Walks
run by fab come after a ladder has been walked by hand through the first two plans.

Every task lands through `bin/fab land` (this repository), with `bin/fab test` green.
