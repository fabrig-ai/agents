+++
id = "qa-figures"
part = "figures"
kind = "feature"
needs = []
files = ["fab/landing_report.py", "fab/tests/test_landing_report.py"]
effort = "medium"
minutes = 35
+++
# The landing report's QA figures

Read first: `docs/plan/findings-loop/notes/common.md`,
`docs/plan/findings-loop/notes/fold.md` (the records only).

The request: "the landing report's QA figures (section 10)". Design:
`docs/design/fab.md`, 10 ("From the log too, the landing draft's 'QA
passes ... and their findings' (13.15)").

## What to build

In `fab/landing_report.py`, beside `_red_figures` (near line 204) and in
`FIGURES`' order after the red figures: from the log's records whose ts
the window holds, walks ended by verdict (`walks_pass`, `walks_fail`,
`walks_void`), `findings_raised`, `findings_merged`, triaged by decision
(`triaged_<decision>` for each of path, backlog, user, brief, drop,
again), `finding_repairs_landed` (`branch.landed` whose task is
`<draft>/finding-<n>`), `rungs_passed`, and `walk_pass_hours`: the median
hours from a failed walk's `walk.ended` to its rung's next `rung.passed`,
over the passes in the window. Labels as the red figures' read. Count raw
records; no fold (`fab.findings` is not needed, so do not import it).

## Acceptance

Tests in `fab/tests/test_landing_report.py`: each figure from records in
and out of the window, the median over two passes, and a day with no QA
records showing zeros and `-` for the median; the existing report tests
unchanged but for the new rows.

## Pre-approved defaults

- A failed walk with no later pass: not in the median.

## Report

The figures added, in order.
