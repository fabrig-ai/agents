+++
id = "optimistic-start"
part = "wide-start"
kind = "feature"
needs = ["fabrig-calls-land", "rust-gates", "start-wide", "direct-mode"]
files = ["fab/dispatch.py", "fab/run.py", "fab/call_review.py", "fab/state.py", "fab/plan.py", "fab/gates.py", "fab/tests/test_dispatch.py", "fab/tests/test_run.py", "fab/tests/test_call_review.py", "fab/tests/test_state.py", "fab/tests/test_gates.py"]
effort = "high"
minutes = 60
+++
# Optimistic start: a part's tasks run from its skeleton's tip while the review runs

docs/design/fab.md 13.11 ("Optimistic start", and the gates' place in
"Rust gates, minimal").

## What to change

- Checks on a skeleton's tip: when a skeleton or contract call ends done,
  the tick runs the checks on its branch's tip: for this repository `bin/fab
  test` and the gates (`fab.gates`), in a detached worktree; for fabrig `fab
  precheck` in a slot of the builder and the Rust gates (`fab.rust_gates`).
  The outcome is logged (one event, say `call.checked`, with `tip` and
  `outcome`). The Codex review starts as now, beside the checks.
- Green checks make the part's tasks runnable before the skeleton lands:
  the specs are read from the call's tip (`git show`), they count as the
  part's tasks for status, needs and the buffer, and their runs start from
  the tip (`fab.run.start`'s base, today always `origin/main`, is the tip).
- Such a task holds landing (this repository) or readying (fabrig) until
  the skeleton has landed. When the call's branch landed with the same tip,
  it lands or readies as now. When the branch was amended before landing,
  its first step is a rebase run onto main (kind `rebase`, the amendment's
  diff in the brief), then it lands or readies as now. A parked chain holds
  its started tasks.
- Wire the Rust gates for fabrig task branches: before `_ready`, as
  `fab.gates.screen` runs before `fab land` for this repository.

## Acceptance

- Tests with the fake runner and hand-built events: green checks start a
  task from the tip before the review ends; red checks start nothing; the
  task waits for the landing; an amended skeleton sends it to a rebase run
  first; a parked chain holds it; a fabrig task branch failing the ratchet
  is rejected at `gate:ratchet` and not readied.
- `bin/fab test` passes within the 30 s budget.
