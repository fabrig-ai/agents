# machines status

2026-11-01. Contract: `docs/design/machines.md`. Split from `docs/design/fab.status.md`.

## Present

- **Slots and disk:** `fab slot` (claims, release sweep, reclaim of idle
  slots) and `heavy` (flock lanes, capped disk wait with reclaim), on main;
  fab is installed on hetzner6 and hetzner8 (`~/src/fabrig/fab/install`,
  `fab` on PATH). hetzner6's slots 5 and 7 carry fab claims mirroring the
  paused ladder work's old claims.
- **Builder installs follow the dispatcher** (2, 11-01; 7b9fbb0, f703675):
  `fab.run`'s start moves a builder's `FAB_HOME/install` forward to the
  running dispatcher's commit under `install.lock`, skips a pinned install
  (`install.pinned`) and dispatcher hosts, and only notes stderr on
  failure (docs/design/tick.status.md). Tested with fake runners; the
  queue and after-landing services still move only with `bin/install.sh`.
- **Logins:** `fab logins` (3): the shelf, capture, lend, return, swap,
  retire, check and borrow; live on hel8 since 10-31 23:3xZ, holding every
  machine's logins, the user's new sign-ins and QA's six (moved 11-01).
  `fab after-landing --live` borrows them for `live-skein` (whose tests
  read logins' files since fabrig 978e17e); the after-landing unit on
  hetzner8 runs with it, on the cheapest models. `live-temper` is out
  (11-01): its owner-run live stories are ignored, and since fabrig
  eb6c40aaf its live binaries have no harness unit tests; nextest exits 4,
  faulting every run and holding the cursor. It awaits the user's decision
  on which ignored stories, if any, to run with `--run-ignored` (after-landing.md 2, 3).
  Borrowing and its `chatgpt` / `claude-box` kinds remain tested with a
  test-only live table.
  `live-smith` was taken out 11-01 ~02:00Z (red on 831e86f27 and
  e4f852afa: `SMITH_LIVE` unset): it needs a smith live root signed in by
  `smith login`.
- **The `smith-live` kind** (3; plan `smith-live`, 38de1b9): a directory
  kind with a fixed path, `.local/state/smith-live` (`Kind.fixed`).
  `lend` and `borrow` default to it and accept it as relative, `~/` or the
  host's absolute path; any other path is refused before anything is
  copied. `borrow` without `--path` is refused for a kind without one. A
  lent directory is made mode 700. `check` refuses it as it does
  `chatgpt` and `github`. Tested with fake hosts and a dummy root.
- **The dispatcher's own units** (4; plan `docs/plan/hel8-units`, retired
  11-01; a33e9ee, 10be9c0): `fab/units.py` holds `install_units` and
  `cli_install` beside the unchanged `Service`, `text` and `install`, and a
  pure text function per unit (`status_service`, `timer_service`, `timer`,
  and `status_units`, `issues_units`, `logins_check_units`,
  `report_daily_units`). `fab serve --install`, `fab issues --install`,
  `fab logins check --install` and `fab report daily --install` call them.
  An install asks `show --property=Transient,ActiveState` of every unit
  first, refuses (exit 1, nothing stopped or written) when a transient
  timer's service is not `inactive` or `failed`, stops and resets transient
  units timer first, keeps a pause, writes through `fab.atomic.write`,
  reloads, enables the primary, restarts it only when its own text changed
  and it is `fab-status.service` or a timer, and warns when linger is not
  `yes`. `fab serve` reads its checkout's HEAD before serving and every 60
  seconds in a daemon thread (`fab.serve.serve`, `head_of`); a change shuts
  the server down and `main` returns 75; an unreadable HEAD is never a
  change (the first readable one becomes the baseline). `fab report daily`
  with no plan dir walks `fab.channel.plan_dirs()`, printing `<dir>
  skipped` for a directory without `plan.toml` and a retired plan. Each
  text is pinned byte for byte; the installer's argv order, refusal,
  reruns, pause, linger, the watch and every `--install`'s usage errors are
  tested with `FakeRunner` and a temporary HOME and FAB_HOME
  (`test_units.py`, `test_serve.py`, `test_forge.py`, `test_logins.py`,
  `test_report.py`).

## Gaps and departures

- **No smith live root on the shelf yet:** the root on hetzner9
  (`~/.local/state/smith-live`) awaits the user's `smith login chatgpt`,
  then `fab logins capture hetzner9 smith-live --free --path
  .local/state/smith-live`. Until then `live-smith` stays out of
  `fab.after_landing.LIVE` (machines.md 5).
- **A pair's borrow ignores a fixed path:** machines.md 3 lends a pair's
  login "at the kind's fixed path or under its run directory", but
  `fab.after_landing`'s `borrow` always passes `--path
  <run>/logins/<variable>`, which the shelf refuses for `smith-live`. It
  must pass no `--path` for a fixed kind (and set the variable to
  `$HOME/.local/state/smith-live`) when live-smith returns. The comment
  above `LIVE` still says no shelf kind holds the root.
- **The dispatcher's own units are not deployed** (4, Deployment): on main
  since 11-01, not yet run on hel8, which is ops' after landing (the
  request). Until ops runs the four `--install` commands there,
  `fab-status`, `fab-issues` and `fab-logins-check` stay transient units
  started by hand (`FAB_HOME/bin/start-*.sh`, from the hand-made clones
  `FAB_HOME/serve-install` and `FAB_HOME/issues-install`), and `fab report
  daily` has no timer. Adding the commands to `bin/install.sh` after `fab
  after-landing install` is ops' too (that script is not in this
  repository).

- **Live, but transient:** fab's heavy on hel8, hetzner6 and hetzner8. The
  tick's units (`fab-events.path`, `fab-backstop.timer`) are persistent,
  installed by `fab wake --install` (since 11-01 09:37).
- **The slot bound of 25 GB is one measurement** (10-30 20:18Z): a
  whole-workspace build from a swept slot. Repeated scoped builds within one
  task are not measured yet; heavy.jsonl and the sweep's freed bytes will
  show them.
