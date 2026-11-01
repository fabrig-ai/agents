+++
id = "finding-signal"
part = "signal"
kind = "feature"
needs = ["finding-repair"]
files = ["fab/channel.py", "fab/tests/test_channel.py"]
effort = "medium"
minutes = 35
+++
# The finding-<n> signal on the user's page

Read first: `docs/plan/findings-repair/notes/common.md`,
`docs/plan/findings-repair/notes/fix.md` ("Records the finding's path
writes").

The request: "the `finding-<n>` signal on the user's page for a finding
its foreman left". Design: `docs/design/fab-channel.md`, 2 (`## Open
signals`' `finding-<n>` block, and "A signal opens and clears from the
log"); `docs/design/fab-qa.md`, 2 ("left (the finding is a signal)").

## What to build

In `fab/channel.py`, `signals` (near line 101) adds `_finding_signals`:
- one `Signal` per finding in state `left` (`fab.findings.findings`),
  id the finding's id, since its `finding.settled` ts, what `QA finding
  left`, clearable;
- facts `- Rung: <rung> (<backend>)`, `- Why: not the code's: <the
  foreman's reason>`, `- Title: <title>`; read the walk's report
  (`FAB_HOME/walks/<walk>/report.md`) and the foreman's report (its
  `report` from `fab.fixes.foremen`), as the red block joins two paths;
- it closes at its rung's next `rung.passed` after the settlement (the
  rerun showed it was not the code's), and by hand: `fab page clear
  finding-<n> TEXT` logs `signal.cleared`, which the fold reads as
  dropped. `clear` refuses it once closed, as any signal.

## Acceptance

Tests in `fab/tests/test_channel.py`:
- a settled-left finding is an open signal with its facts and read
  paths, on the page under `## Open signals`;
- a later `rung.passed` of its rung closes it; one of another rung does
  not;
- `fab page clear finding-<n>` logs `signal.cleared`, the signal closes
  and the finding folds dropped with the clear's text as its reason;
- a finding settled fix or none raises no signal; red, queue and fault
  signals are unchanged.

## Pre-approved defaults

- `fab/channel.py` and its tests are shared with `findings-loop/
  ladder-page`; if it lands while you work, rebase and keep both.
- `fab.channel` may import `fab.findings` and `fab.fixes`.

## Report

The block's lines as the page prints them, and how it closes.
