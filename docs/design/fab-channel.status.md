# fab-channel status

2026-11-01. Contract: `docs/design/fab-channel.md`. Split from `docs/design/fab.status.md`.

## Present

- **The user's questions on the forge** (11-01, 3): `fab issues sync`
  opens one labelled issue per subject, reads user comments through medium
  reply calls, records decisions through `channel.answer`, and closes
  answered issues. The log holds the state; a nonblocking flock serializes
  passes. Fake forge, HTTP and Claude runners cover conversations, retries,
  paging, locking and secret-free diagnostics. Deployment is by hand:
  provision the bot token file and a transient two-minute timer on hel8.
- **The page** (2): `fab/channel.py` folds the user's open questions and
  signals, renders the page and runs `fab page show|write|answer|clear`;
  the tick rewrites `FAB_HOME/user.md` each round.
- **QA findings on the page** (2, fab-qa.md 2; plan findings-loop, retired
  11-01): `finding` asks from a triage `user`, `brief` or `path ...;
  user:` line, quoted with the finding's title, rung and reproduction, and
  answered with `fab page answer <draft>/triage/<finding>`; the
  `backlog:<draft>` signal from `fab.triage.backlog_held` at the current
  render, cleared as the render changes, a backlog branch lands, or by hand; `## The ladder` per plan
  with rungs, each rung's `fab.findings.line` and the backlog's count.
  Tested with fixture logs and ladder plans.

## Gaps and departures

- **`finding-<n>` is not built** (2): the signal of a finding its foreman
  left waits for the repair path (fab-qa.md 2, plan
  `docs/plan/findings-repair`), as no finding is settled before it.
- **Where else the user reads the page** is the user's (4): it is a file on
  hel8, and its questions are on the forge (3).
