# fab status

2026-10-30. Contract: `docs/design/fab.md`. Plan:
`docs/plan/agents-rebuild/plan.toml` (`bin/fab status docs/plan/agents-rebuild`).

## Present

- **Package and tests:** `bin/fab`, the runner seam, the test runner with its
  30 s budget, the test helpers; about 250 tests in about 3 s.
- **The event log** on hel8 (`~/src/fabrig/fab/log.jsonl`) holds every run,
  landing and note since 10-30 20:11Z; `fab status` folds it.
- **Runs:** `fab run start|status|collect` with worktrees for this repository
  and slots for fabrig (claim, switch, release with the sweep at collect);
  `fab codex` launches Codex as user units (live on hetzner6 since 20:30Z;
  codex-run is no longer called). A failed start gives back what it took.
- **Landing this repository:** `bin/fab land`, live since 20:22Z; every
  change to `fab/` since then landed through it.
- **The dispatcher:** `fab tick PLAN_DIR` collects, lands, starts and parks;
  run by hand, live since 20:27Z.
- **Slots and disk:** `fab slot` (claims, release sweep, reclaim of idle
  slots) and `heavy` (flock lanes, capped disk wait with reclaim), on main;
  fab is installed on hetzner6 and hetzner8 (`~/src/fabrig/fab/install`,
  `fab` on PATH). hetzner6's slots 5 and 7 carry fab claims mirroring the
  paused ladder work's old claims.
- **fabrig's landing:** `fab gate`, `fab queue`, `fab precheck` on main.

## Gaps and departures

- **heavy is not switched over:** builders still run fabrig's old heavy;
  fab's replaces it at the cutover, which waits for the user's word.
- **fab queue does not run yet** on hetzner8; the old queue is stopped.
  `cutover-fabrig` is the first change meant to land through it.
- **The tick is run by hand,** not on a timer.
- **Claude calls** (`fab/calls.py`) are being filled; skeletons and task
  specs are still written by hand.
- **Parts done by hand have no task specs** (package, slot-probe), so the
  tick's design line lists them.
- **The slot bound of 25 GB is one measurement** (10-30 20:18Z): a
  whole-workspace build from a swept slot. Repeated scoped builds within one
  task are not measured yet; heavy.jsonl and the sweep's freed bytes will
  show them.
