# Reaper status

2026-10-30. Owner: s/deploy. Baseline: `origin/main` at `e98c22d`, plus
`deploy/reap-2`. Contract: `docs/design/reaper.md`, sections 2–6.

## 1. In one page

**Live mode is not enabled.** `fleet/reap.toml` says `mode = "dry-run"` and
`Reaper.execute`/the CLI refuse `--live` while that setting remains. No machine
action or legacy-cleanup retirement is part of this branch.

**The session-hook argument mismatch is resolved.** The reaper accepts the
landed hook unchanged, including its full session ID, short jobs path and
ownerless end. Producer deployment and Codex finality remain separate rollout
work; keep the fleet in dry-run through adoption and ops' first-day review.

## 2. Present and evidence

- **The eight accepted independent-review findings are addressed in reap-1e.**
  Repositories run only sanitized reachability plumbing and bundle operations;
  tests install touch-side-effect clean/process filters, fsmonitor and hooks in
  ordinary dry-run, read-only and live fixtures. Every worktree gets a verified
  tar; local-only refs/stash/detached HEAD get a verified bundle, with detached
  recovery tested. No status/diff/checkout or dirtiness detection remains.
- Final fingerprints follow slow observations. Ledger exclusion spans final
  checks/removal, writer waits are bounded at two seconds, and removal checks
  each inspected entry. Tests cover late edits, late starts, entry replacement,
  lock contention and successful retry after release.
- Traversal uses iterative run/candidate budgets, including archives and process
  metadata. Tests use 1,050 levels, wide trees, time/entry exhaustion and partial
  persistence/mail. Borrowed object stores protect descendants and ancestors.
- **Notes/tasks are disabled and fixed keeps.** The plan's builder-copy proposal
  has no authoritative finality evidence yet. Reintroducing it is deferred in
  `docs/design/reaper.md`, section 7; ended records cannot bypass the exclusion.
- Timer activation is bounded at 91 seconds with the exact requested values;
  boot scheduling is bounded at 151 seconds. `test_units_render_every_host`
  checks the sums. Reactivate an already-running timer on reviewed deployment
  to start its new activation interval; no host action was performed here.
- First timer mail includes the actual grouped list, paths and reasons; large
  homogeneous groups collapse without dropping entries from the saved JSON.
  Tests verify grouping, mtime bounds, daily transition and budget-report mail.
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

**Producer states are explicit.** Source compatibility does not prove runtime
adoption; this branch refreshes no existing project settings.

| Producer | Owner | State and evidence |
|---|---|---|
| SessionStart/SessionEnd | s/multi-coord | Landed `tools/session/reap-hook` is compatible. `tools/reap/test_reap.py` drives that real hook against reap through start, resume, end, duplicate end and the one-hour threshold. Existing settings still need producer-owner rollout verification. |
| Retired role paths | s/multi-coord | `tools/session/session_retire.py` supplies start owner and an ownerless end; both are accepted. `tools/test_session_start.py` covers retire, and reaper tests cover ownerless ends for every kind. Runtime use is not established by these source tests. |
| Ops scratch | ops | Record interface is available and tested; automatic producer adoption is not demonstrated here. |
| QA scratch | s/qa | Record interface is available; producer adoption remains with s/qa. Fixed QA never-paths still override records. |
| Codex run finality | ops | No codex-run producer is supplied by this repository. The consumer accepts atomic final JSON with fractional UTC time, but ops owns publication/adoption. Missing metadata keeps runs; never infer or backfill it. |

Ownerless ends inherit the start owner. Orphan ends cannot create eligibility;
explicit owner mismatches leave the ledger unchanged. Full Claude session IDs
protect the matching short jobs directory through both records and live inventory.
The fixed never-paths now also include the complete mailbox-home registry at
runtime `~/src/fabrig/homes`, with a live-mode temporary-HOME regression.

- **Borrower coverage is bounded.** Repository discovery covers six levels per
  named root and skips generated trees. A new deeper clone layout requires
  review. Cached borrower evidence cannot detect a borrower added during a run;
  stopping producers remains part of the lifetime contract.

## 4. Verification

`tools/reap/test_reap.py` uses temporary HOME, fake commands and synthetic proc
state. It covers the real timeout's deep build-tree shape, excluded generated
subtrees, working/bare/linked Git metadata, scan budgets and caching, remote
claims and failure paths, all fixed never-paths, UTC timestamp variants, resumed
records, real session-hook integration, owner inheritance/orphan ends and
preservation/removal guards. Run the focused and complete gates
through plain `tools/check.sh`; never set its lock environment variables.
Host evidence and test counts for this revision are in the external deployment
report `/home/free/src/fabrig/deploy/notes/reap-1e-report.md`.

## 5. Later

- Verify deployed session settings and producer adoption; ops supplies real Codex finality.
- Review one dry-run day before a separate reviewed live-mode commit.
- After live, retire the legacy tidy/pruning work with ops and update this file.
