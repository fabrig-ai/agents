# fab-reports status

2026-11-01. Contract: `docs/design/fab-reports.md`. Split from `docs/design/fab.status.md`.

## Present

- **Subscriptions on the status page** (11-01, 3, fab-machines.md 3–4): account
  checks return every Codex window and Claude's zero-turn local `/usage`
  limits, dropping Fable. `login.checked` stores three parallel scalar
  lists. `fab logins check --all` skips custody refusals and continues
  after account failures. The public snapshot includes recent nonretired
  logins, same-window rate and pace, with `5 h` only above 80%; the page
  has the Subscriptions panel, meters and weekly-use tile. Account and
  custody details stay private. Pure folds and parsers, fake commands and
  fixture log tests cover it. Deployment remains by hand: update the
  serving checkout and install a 30-minute check timer on hel8.

## Gaps and departures

- **Reports are a skeleton:** `fab/report.py`, `fab/code_report.py` and
  `fab/landing_report.py` hold section 2's signatures and contracts, filled
  by the tasks `report-base`, `report-code`, `report-landing` and
  `report-command`; `fab report` is not a command until the last lands. No
  timer runs `fab report daily` yet.
- **Accounting is a skeleton:** `fab/accounting.py` holds 3's weights,
  the draft's calls and runs and the code report's Claude and Codex
  figures; `fab.calls.Usage` and `claude_usage` the reading of claude's
  stream, and `fab.codex.tokens_field` the run's tokens. The task
  `accounting` fills them, switches calls to claude's stream-json output,
  makes `fab run status` read the run's result and adds the figures and the
  Calls table to the code report. Until it lands, run.ended carries no
  tokens, call.ended no peak, turns or cache writes, and no weight is shown.
  A call's subject draws its calls into the report only when it is the draft
  or one of its parts; the task widens that to every subject under the
  draft (review, cut, retire, decision).
