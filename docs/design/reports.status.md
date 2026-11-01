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
  fixture log tests cover it. Its units are `fab serve --install`'s and
  `fab logins check --install`'s (machines.md 4), on main and not yet
  deployed (below).
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
- **The daily reports' timer and the page's unit** (2, 4; plan
  `docs/plan/hel8-units`, retired 11-01; a33e9ee, 10be9c0): `fab report
  daily --install` writes `fab-report-daily.timer` (00:33 UTC,
  `Persistent=true`) and its service, which runs `fab report daily` with
  no plan dir over `fab.channel.plan_dirs()`, skipping a directory without
  `plan.toml` and a retired plan; `fab serve --install` writes
  `fab-status.service`, and the server returns 75 when its checkout's HEAD
  moves (machines.status.md).

## Gaps and departures

- **The units are not deployed** (4, Deployment; machines.md 4): until ops
  runs `fab serve --install` and `fab report daily --install` on hel8, the
  page is the transient unit started by hand from `FAB_HOME/serve-install`
  and no timer runs `fab report daily`.

