+++
id = "part-measures"
part = "accounting"
kind = "feature"
needs = ["accounting"]
files = ["fab/code_report.py", "fab/accounting.py", "fab/tests/test_code_report.py", "fab/tests/test_accounting.py", "fab/sh.py"]
effort = "high"
minutes = 40
+++
# Measure the ratio per finished part, and the skeleton's share

A running total early in a draft is all design and little implementation.
Per part, once all its tasks have landed, the code report shows:

- the part's skeleton call weight (its skeleton, amend and review calls)
  against its tasks' Codex weight (implement, repair, rebase runs), and their
  ratio;
- its **skeleton share**: production lines the part's skeleton commit added
  (the call's branch) over the part's production lines on main once its tasks
  have landed (`git diff --numstat` over the part's `files`), with a soft
  target of 10-20% and a signal above 25%;
- weight per landed production line, Claude and Codex apart.

## Acceptance

- Tests with hand-built events and a fake git numstat: a finished part's
  three figures; an unfinished part listed as unfinished, not counted; the
  skeleton-share signal above 25%.
- `bin/fab test` passes; the touched test modules stay within budget.

## Answers

- 2026-10-31, the designer: this task defines the per-part measures itself
  (no skeleton call came first). Add to fab/code_report.py a pure
  `part_rows(plan, tasks, events, numstat)` returning one row per finished
  part (skeleton weight, Codex weight, ratio, skeleton share, weight per
  landed production line), rendered as a `## Parts` table; read git numstat
  through the runner seam in one shell function beside it, injected in tests.
  Contracts short, private helpers yours.
