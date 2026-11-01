+++
id = "logins-report"
part = "dispatcher-units"
kind = "feature"
needs = ["status-issues"]
files = ["fab/units.py", "fab/logins.py", "fab/report.py", "fab/tests/test_units.py", "fab/tests/test_logins.py", "fab/tests/test_report.py"]
effort = "medium"
minutes = 45
+++
# `fab logins check --install`, `fab report daily --install` and daily with no plan dir

Read first: `docs/plan/hel8-units/notes/common.md`,
`docs/plan/hel8-units/notes/decisions.md` (2, 3, 6), then
`docs/design/machines.md` 4 whole.

The request's task 2. It builds on `status-issues`' `fab.units`
(`timer_service`, `timer`, `cli_install`); change only what it needs there.

## What to build

- **`fab/units.py`:** `logins_check_units()` (`fab logins check --all`,
  `*:5/30`, TimeoutStartSec 1800, `quiet=True`, `the logins' checks`, `at
  :05 and :35`) and `report_daily_units()` (`fab report daily`, `*-*-*
  00:33:00 UTC`, `persistent=True`, TimeoutStartSec 1800, `yesterday's
  reports`, `daily at 00:33 UTC`), with the signatures of decision 3.
- **`fab/logins.py`, `main`** (~576-620): `check --install`, with no ids
  and no `--all` (otherwise usage error, exit 2), calls
  `units.cli_install("logins check", units.logins_check_units(),
  primary="fab-logins-check.timer", restartable=False)` before `Shelf()`
  is opened; `check` without `--install` keeps its rule.
- **`fab/report.py`, `main`** (~201-282): `daily`'s `plan_dirs` becomes
  `nargs="*"` with `--install` (with plan dirs: usage error, exit 2;
  installs `fab-report-daily.timer`, `restartable=False`). With no plan
  dir, `fab.channel.plan_dirs()`, skipping (decision 6) a directory without
  `plan.toml` and a retired plan, each printing `<dir> skipped`; the
  docstring says so.

## Acceptance

- `fab-logins-check.timer`, `fab-logins-check.service` (its
  `StandardOutput=null` and `StandardError=journal`, `KillSignal=SIGINT`),
  `fab-report-daily.timer` (`Persistent=true`) and
  `fab-report-daily.service` pinned byte for byte in
  `fab/tests/test_units.py`.
- `fab/tests/test_logins.py`: `check --install` installs without opening
  the shelf (FakeRunner, no shelf dir); `check --install ID` and `check
  --install --all`: exit 2. Put the tests beside the existing check tests.
- `fab/tests/test_report.py`: `daily --install` installs; `daily --install
  PLAN_DIR`: exit 2; daily with no plan dir over a FAB_HOME/PLANS listing a
  plan, a directory without `plan.toml` and a retired plan writes the
  first's report and the landing report, prints `skipped` for the other
  two, exit 0; with plan dirs given, as today.
- `bin/fab test` green.

## Pre-approved defaults

- `smith-live/kind` may land first and change `fab.logins`' `Kind` and
  `KINDS`: rebase over it; your change is in `main` only.
- The test FAB_HOME/PLANS file is written in the test's temporary FAB_HOME.

## Report

The four texts' commands and schedules as built, the CLI checks, and the
tests added.
