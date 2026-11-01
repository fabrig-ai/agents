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

## Gaps and departures

- **The user's channel is a skeleton:** `fab/channel.py` holds 2's
  fold of the user's open questions, the page and `fab page
  show|write|answer`. The task `channel` fills the fold, the reports'
  listing and the page's text; `channel-tick` fills the command and the
  page's writing, and makes the tick rewrite the page. It also makes
  `call.answered` the only answer that unparks a subject or resets a
  chain, and carries the user's answers into every later brief of the
  subject, and makes an answer call's `Question:` park its draft. Until
  then nothing writes `FAB_HOME/user.md`, and an answer call that ends
  `Question:` starts again on the next tick. The open question
  of the log today is the retire skeleton call's; the accounting call's was
  answered in fab-reports.md 3 (measured, not capped). The page
  is a file on hel8: where else the user reads it is the user's (4).
