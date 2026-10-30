# fab status

2026-10-30. Contract: `docs/design/fab.md`. Plan:
`docs/plan/agents-rebuild/plan.toml`.

## Present

- **Package:** `bin/fab`, `fab/cli.py`, the runner seam (`fab/sh.py`), the
  test runner with its 30 s budget (`fab/testrun.py`), the test helpers
  (`fab/tests/support.py`).
- **The event log** (`fab/log.py`) and the machines (`fab/hosts.py`,
  `fab/hosts.toml`, `fab hosts check`).
- **Skeletons, bodies to fill:** `fab/plan.py`, `fab/state.py` (task
  `files`), `fab/land.py` (task `land`), `fab/run.py` (task `run`).

## Gaps and departures

- **Nothing is live yet.** Runs start by hand, and this repository's main
  moves by hand (the user's 10-30 word) until `bin/fab land` lands.
- **Sections 5-7 are designed, not built:** slots, the sweep, reclaim and
  heavy are slice 2; the dispatcher is slice 3.
- **The slot bound of 20 GB is an estimate** from 10-30 measurements of idle
  slots; the `slot-probe` part sets it from a broad build's peak.
