# fab-machines status

2026-11-01. Contract: `docs/design/fab-machines.md`. Split from `docs/design/fab.status.md`.

## Present

- **Slots and disk:** `fab slot` (claims, release sweep, reclaim of idle
  slots) and `heavy` (flock lanes, capped disk wait with reclaim), on main;
  fab is installed on hetzner6 and hetzner8 (`~/src/fabrig/fab/install`,
  `fab` on PATH). hetzner6's slots 5 and 7 carry fab claims mirroring the
  paused ladder work's old claims.
- **Logins:** `fab logins` (3): the shelf, capture, lend, return, swap,
  retire, check and borrow; live on hel8 since 10-31 23:3xZ, holding every
  machine's logins, the user's new sign-ins and QA's six (moved 11-01).
  `fab after-landing --live` borrows them for `live-skein` (whose tests
  read logins' files since fabrig 978e17e); the after-landing unit on
  hetzner8 runs with it, on the cheapest models. `live-temper` is out
  (11-01): its owner-run live stories are ignored, and since fabrig
  eb6c40aaf its live binaries have no harness unit tests; nextest exits 4,
  faulting every run and holding the cursor. It awaits the user's decision
  on which ignored stories, if any, to run with `--run-ignored` (fab-after-landing.md 2, 3).
  Borrowing and its `chatgpt` / `claude-box` kinds remain tested with a
  test-only live table.
  `live-smith` was taken out 11-01 ~02:00Z (red on 831e86f27 and
  e4f852afa: `SMITH_LIVE` unset): it needs a smith live root signed in by
  `smith login`, a directory kind the shelf does not have yet.

## Gaps and departures

- **Live, but transient:** fab's heavy on hel8, hetzner6 and hetzner8; the
  tick (`fab-tick.timer`, every 2 minutes) on hel8, a transient user unit a
  reboot loses. It becomes a unit installed by `fab wake --install`.
- **The slot bound of 25 GB is one measurement** (10-30 20:18Z): a
  whole-workspace build from a swept slot. Repeated scoped builds within one
  task are not measured yet; heavy.jsonl and the sweep's freed bytes will
  show them.
