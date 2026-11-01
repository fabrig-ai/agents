# channel status

2026-11-01. Contract: `docs/design/channel.md`. Split from `docs/design/fab.status.md`.

## Present

- **The user's questions on the forge** (11-01, 3): `fab issues sync`
  opens one labelled issue per subject, reads user comments through medium
  reply calls, records decisions through `channel.answer`, and closes
  answered issues. The log holds the state; a nonblocking flock serializes
  passes. Fake forge, HTTP and Claude runners cover conversations, retries,
  paging, locking and secret-free diagnostics. The token file is by hand;
  the two-minute timer is `fab issues --install`'s (plan
  `docs/plan/hel8-units`, retired 11-01; a33e9ee; machines.status.md).
- **The page** (2): `fab/channel.py` folds the user's open questions and
  signals, renders the page and runs `fab page show|write|answer|clear`;
  the tick rewrites `FAB_HOME/user.md` each round.
- **QA findings on the page** (2, qa.md 2; plan findings-loop, retired
  11-01): `finding` asks from a triage `user`, `brief` or `path ...;
  user:` line, quoted with the finding's title, rung and reproduction, and
  answered with `fab page answer <draft>/triage/<finding>`; the
  `backlog:<draft>` signal from `fab.triage.backlog_held` at the current
  render, cleared as the render changes, a backlog branch lands, or by hand; `## The ladder` per plan
  with rungs, each rung's `fab.findings.line` and the backlog's count.
  Tested with fixture logs and ladder plans.
- **`finding-<n>`** (2, qa.md 2; plan findings-repair, retired 11-01):
  `fab.channel._finding_signals` opens a QA finding its foreman left at its
  `finding.settled` left (`- Rung`, `- Why`, `- Title`, `- Read:` the walk's
  report and the foreman's) and clears it at the rung's next `rung.passed`
  or by `fab page clear`, which drops the finding with the clear's text.
  Tested with fixture logs.

## Gaps and departures

- **The issue timer is not deployed** (3, Deployment; machines.md 4):
  until ops runs `fab issues --install` on hel8, `fab issues sync` runs
  from the transient timer started by hand in `FAB_HOME/issues-install`,
  whose reply calls start there.
- **Where else the user reads the page** is the user's (4): it is a file on
  hel8, and its questions are on the forge (3).
