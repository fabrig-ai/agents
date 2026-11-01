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
