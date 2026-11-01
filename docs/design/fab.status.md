# fab status

2026-11-01. Contract: `docs/design/fab.md` (its sections 1-5; each
subsystem's design has its own status file, section 6). Plan:
`docs/plan/agents-rebuild/plan.toml` (`bin/fab status docs/plan/agents-rebuild`).

## Present

- **Package and tests:** `bin/fab`, the runner seam, the test runner with its
  45 s CPU budget, the test helpers; 2240 tests in 23.4 s of CPU and 23.0 s
  of wall on main 032cb12 (11-01).
- **The suite's budget is CPU time** (4; plan `docs/plan/test-budget`,
  retired 11-01; 21b50d6): `fab/testrun.py` takes the delta of `os.times()`'s
  user, system and both children's fields from before discovery, so a child
  counts only once waited for, and fails past `BUDGET_SECONDS`, 30.0 as that
  plan left it and 45.0 since d6fc657 (4). The summary reads `fab test: 2240
  tests in 23.0 s wall, 23.4 s CPU (budget 45 s CPU)`. `TimedResult`'s per-test wall times still name the slow tests,
  and a `-k` run stays exempt. No reader parses the line; `fab/cli.py`'s help
  says CPU. Tested with patched `os.times` and clocks (`test_testrun.py`),
  not on a loaded machine (slice 1 has no walk). Each checkout runs its own
  `bin/fab test`, so no machine action.
- **Code cites the split designs** (6; plan `docs/plan/citation-sweep`,
  retired 11-01; 032cb12): 21 lines in `fab/` and `bin/` that named
  `fab-<name>.md` or the old document's numbers now name the design and
  section holding the text, by 6's second table, with three departures from
  it: `fab/dispatch.py`'s header and `fab/calls.py`'s cited old 13, whose row
  gives this document's list of designs, and now cite `tick.md` 1 and
  `calls.md` 1; `fab/forge.py`'s bare `(13.6)` holds old 13.16's text and
  cites `channel.md` 3. Comments and docstrings only. 6 keeps its tables:
  plans, commits and status files still use the old names.
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
- **Two citations the sweep left** (6; Later): `fab/atomic.py`'s `fab.md, 2`
  uses no old number, but section 2 never held the hidden-sibling rule and no
  design does (it is `AGENTS.md`'s), so a reader following it does not reach
  the cited text, short of the plan's story. `fab/tests/test_dispatch.py`'s
  `"see fab-gates.md, 2"` is a test's answer value; no assertion reads it,
  but the request limits the sweep to comments and docstrings.
- **A wall limit remains around the suite:** `bin/fab land` still stops
  `bin/fab test` at 120 s of wall time (`docs/design/landing.status.md`,
  gaps), so the request's loaded machine is safe only up to about five
  times the suite's CPU time.
