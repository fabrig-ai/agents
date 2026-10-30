# Reaper status

2026-10-30. Owner: s/deploy. Baseline: `origin/main` at `37c0fd9`, plus
`deploy/reap-1`. Contract: `docs/design/reaper.md`, sections 2–6.

## 1. In one page

**Live mode is not enabled.** `fleet/reap.toml` says `mode = "dry-run"` and
`Reaper.execute`/the CLI refuse `--live` while that setting remains. No machine
action or legacy-cleanup retirement is part of this branch.

**Effective producer wiring is incomplete.** Session hooks are s/multi-coord's
and Codex finality is ops'. Keep the fleet in dry-run through their adoption and
ops' first-day review; see sections 2–3 for current evidence and surprises.

## 2. Present and evidence

- `tools/reap/reap`, `tools/reap/test_reap.py` and `tools/reap/reap.md` implement
  class discovery, lifetime records, fixed keeps, verified archives and reports.
  `fleet/units/reap.service`, `reap.timer` and `roles.toml` declare all-role units.
- Targeted Git scans use depth six and a single cached 20-second budget. Scan
  completion, reason and elapsed time are carried into `runs.jsonl` by
  `Reaper.scan_alternates`, `execute` and `save`. A timeout keeps all candidates.
  The reap-1c external layout audits compare depth six with twelve on hel8 and
  hetzner3: neither deeper audit found additional alternates files. Hel8 has
  deeper fixture repositories without alternates; h3 has archived Git pointers
  into deleted temporary directories, counted as absent object stores.
- **Claims on builders have a supported route.** Fabrig's external
  `/home/free/src/fabrig/main/tools/slots/design.md`, section 3, requires builders
  to use SSH to hel8. `Reaper.claim_slots` now uses `fleet/hosts.toml` to identify
  the host and hel8 SSH target, reads installed `claim list` through a login
  shell, and filters builder rows. Failure, unknown identity, malformed output
  or missing host rows still protects every slot. No new claim protocol exists.
- **Fleet-tend stays until live.** `fleet/bootstrap/inventory.md` records the
  legacy fleet-tend timer on both hosts and disabled h3 kache-prune. Read-only
  `systemctl --user is-active fleet-tend.timer` probes on 2026-10-30 returned
  active on hel8 and hetzner3 (`reap-1c-legacy.json` beside the external report).
  This branch does not retire or modify those units; the replacement decision follows live
  review (`docs/design/reaper.md`, section 5).

## 3. Gaps and departures

- **Session hooks have landed since the task was written.** `tools/session/start`
  has retire; `tools/session/session_lib.py` publishes hooks when
  `session-reap-hook` is on PATH. That code is evidence of hook support, not
  evidence that existing runtime settings have been refreshed.
- **Those hooks do not yet match this record interface.**
  `tools/session/reap-hook` sends a full session ID with its eight-character job
  path on start; `Reaper.record` requires the path to match the ID. On end the
  hook omits owner, while the reap parser requires owner. Recording is best
  effort and therefore cannot prove adoption by exit status. The hook owner
  must reconcile both arguments and refresh existing settings. This branch
  preserves the reaper interface and does not change another owner's hooks.
- **Codex finality is not supplied by this branch.** There is no codex-run
  producer here. Ops must publish the specified atomic `final.json` after real
  finality; missing metadata keeps runs. Never infer or backfill it.
- **Borrower coverage is bounded.** Repository discovery covers six levels per
  named root and skips generated trees. A new deeper clone layout requires
  review. Cached borrower evidence cannot detect a borrower added during a run;
  stopping producers remains part of the lifetime contract.

## 4. Verification

`tools/reap/test_reap.py` uses temporary HOME, fake commands and synthetic proc
state. It covers the real timeout's deep build-tree shape, excluded generated
subtrees, working/bare/linked Git metadata, scan budgets and caching, remote
claims and failure paths, all fixed never-paths, UTC timestamp variants, resumed
records and preservation/removal guards. Run the focused and complete gates
through plain `tools/check.sh`; never set its lock environment variables.
Host evidence and test counts for this revision are in the external deployment
report `/home/free/src/fabrig/deploy/notes/reap-1c-report.md`.

## 5. Later

- Reconcile and deploy session hooks; ops supplies real Codex finality.
- Review one dry-run day before a separate reviewed live-mode commit.
- After live, retire the legacy tidy/pruning work with ops and update this file.
