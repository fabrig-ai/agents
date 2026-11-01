# fab status

2026-10-30. Contract: `docs/design/fab.md` (its sections 1-5; each
subsystem's design has its own status file, section 6). Plan:
`docs/plan/agents-rebuild/plan.toml` (`bin/fab status docs/plan/agents-rebuild`).

## Present

- **Package and tests:** `bin/fab`, the runner seam, the test runner with its
  30 s budget, the test helpers; about 250 tests in about 3 s.
- **The event log** on hel8 (`~/src/fabrig/fab/log.jsonl`) holds every run,
  landing and note since 10-30 20:11Z; `fab status` folds it.

## Gaps and departures

- **Retire, step 1 done by hand** (the user's OK, 10-30 23:17Z): the dead
  `claim`, `precheck`, `ready-check` and `codex-run` links removed on all
  three hosts; hel8 on fab's heavy, the old reconcile timer disabled;
  `pipeline-watch` and the `record-collect-*` timers stopped and disabled.
  Each host's `~/src/fabrig/fab/retire-step1.txt` says what it was.
  `fleet-sync` is still enabled and stopped: run as it is, it would rebuild
  `~/.local/bin` from fabrig's deleted `tools/installed`; it must learn fab
  first. The rest of retire (post, the session launcher, lease, watch and
  the collector's code, the old role files) waits, parked, for gates and
  after-landing to be live.
- **Parts done by hand have no task specs** (package, slot-probe), so the
  tick's design line lists them.
