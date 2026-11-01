# fab status

2026-11-01. Contract: `docs/design/fab.md` (its sections 1-5; each
subsystem's design has its own status file, section 6). Plan:
`docs/plan/agents-rebuild/plan.toml` (`bin/fab status docs/plan/agents-rebuild`).

## Present

- **Package and tests:** `bin/fab`, the runner seam, the test runner with its
  30 s CPU budget, the test helpers; 2231 tests in 23.1 s of CPU and 22.6 s
  of wall on main 21b50d6 (11-01, load 0.8).
- **The suite's budget is CPU time** (4; plan `docs/plan/test-budget`,
  retired 11-01; 21b50d6): `fab/testrun.py` takes the delta of `os.times()`'s
  user, system and both children's fields from before discovery, so a child
  counts only once waited for, and fails past `BUDGET_SECONDS`, still 30.0.
  The summary reads `fab test: 2231 tests in 22.6 s wall, 23.1 s CPU (budget
  30 s CPU)`. `TimedResult`'s per-test wall times still name the slow tests,
  and a `-k` run stays exempt. No reader parses the line; `fab/cli.py`'s help
  says CPU. Tested with patched `os.times` and clocks (`test_testrun.py`),
  not on a loaded machine (slice 1 has no walk). Each checkout runs its own
  `bin/fab test`, so no machine action.
- **The event log** on hel8 (`~/src/fabrig/fab/log.jsonl`) holds every run,
  landing and note since 10-30 20:11Z; `fab status` folds it.

## Gaps and departures

- **Retire done by hand, not by the plan's `retire-kit` part** (it has no
  tasks). Step 1 (the user's OK, 10-30 23:17Z): the dead `claim`,
  `precheck`, `ready-check` and `codex-run` links removed; hel8 on fab's
  heavy, the old reconcile timer disabled; `pipeline-watch` and the
  `record-collect-*` timers stopped and disabled (`retire-step1.txt`).
  Step 2 (the user's go, 11-01 13:35Z): `fleet-sync`, `fleet-tend`,
  `status-page`, `issue-router` and `qa-watch` disabled wherever they were
  enabled, and the `~/.local/bin` links into the frozen `~/src/rust/agents`
  kit (`post`, `record`, `land`, `landings`, `land-set`, `repin`, `issue`,
  `fleet`, `after-landing`, `setup`) removed on hel8, hetzner6 and hetzner8
  (`retire-step2.txt`; both records in each host's `~/src/fabrig/fab/`);
  then `tools/`, `fleet/`, `pipeline/`, `prompts/` and their designs
  deleted from this repository. The checkouts and unit files stay (Later).
- **Parts done by hand have no task specs** (package, slot-probe), so the
  tick's design line lists them.
- **A wall limit remains around the suite:** `bin/fab land` still stops
  `bin/fab test` at 120 s of wall time (`docs/design/landing.status.md`,
  gaps), so the request's loaded machine is safe only up to about five
  times the suite's CPU time.
