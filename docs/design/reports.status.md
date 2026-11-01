# reports status

2026-11-01. Contract: `docs/design/reports.md`. Split from `docs/design/fab.status.md`.

## Present

- **Subscriptions on the status page** (11-01, 3, machines.md 3–4): account
  checks return every Codex window and Claude's zero-turn local `/usage`
  limits, dropping Fable. `login.checked` stores three parallel scalar
  lists. `fab logins check --all` skips custody refusals and continues
  after account failures. The public snapshot includes recent nonretired
  logins, same-window rate and pace, with `5 h` only above 80%; the page
  has the Subscriptions panel, meters and weekly-use tile. Account and
  custody details stay private. Pure folds and parsers, fake commands and
  fixture log tests cover it. Deployment remains by hand: update the
  serving checkout and install a 30-minute check timer on hel8.
- **The standing reports** (2): `fab report` (`fab/report.py`) with the
  code report (`fab/code_report.py`) and the landing report
  (`fab/landing_report.py`), computed from records alone.
- **The landing report's QA figures** (2, qa.md 2; plan findings-loop,
  retired 11-01): walks by verdict, findings raised and merged, triaged by
  decision, finding repairs landed, rungs passed and the median hours from
  a failed walk to its rung's next pass, from the log. Tested with fixture
  logs; `finding_repairs_landed` counts nothing until the repair path lands
  (qa.status.md).
- **Accounting** (3): `fab/accounting.py`'s weights and the draft's calls
  and runs, under every subject of the draft; `fab.calls.Usage` read from
  claude's stream-json (tokens, peak, turns, cache writes on call.ended);
  `fab run status` reading the run's tokens for run.ended.

## Gaps and departures

- **No unit in this repository runs `fab report daily`;** a timer, if one
  runs, was installed by hand.

