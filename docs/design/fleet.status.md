# Fleet status

2026-10-30. Owner: s/deploy. Baseline: `deploy/design` `373b246`.
Contract: `docs/design/fleet.md`, sections 1–6.

## Present

- **Scale-down 0037 is prepared only.** The roster is hel8 (session), hetzner6
  (builder/qa, preferred seed) and hetzner8 (gate). Chromium, Forgejo and its
  runner seed only from hetzner6; hel8 remains ineligible for Chromium.
- Agents periodic units require builder role and AGENTS_PERIODIC=1; no
  remaining host declares the flag. The pipeline remains paused (0036).
- **After-landing renders nowhere.** Its service still names retired hetzner7,
  but no remaining host has its role. Its new host is ops and green's decision
  after the pause; no activation or host changes are authorized here.

- Release promotion, rendering, links, installer locking, unit journals, controls,
  backoff, inspection and recovery exist (`tools/fleet-sync:831`, `:953`, `:1114`, `:1312`, `:1340`, `:1972`, `:2032`, `:2060`, `:2232`).
- Safe access, provisioning and owner-controlled restarts have fixture coverage in
  `tools/test_review_fleet_sync.py`, `tools/test_peer_seed.py`, `tools/test_bootstrap_safety.py`, `tools/test_fleet_sync_4.py`.

## Gaps and departures

- **Bootstrap is unproven and targets retired hetzner2** (`fleet/bootstrap/README.md:3`).
  Its default is rejected by the roster (`fleet/bootstrap/bootstrap.py:179`); fixture tests are not rebuilt-host acceptance.
- **Routing and existing kache remain check-only.** `fleet/policy.toml:3` covers
  post/machines, kache config and kache.service. Only successful first provisioning
  of absent kache may write/start it (`tools/fleet-sync:1833`, `:1862`, `:1898`).
- **Slot guards remain transient.** No declaration in `fleet/units/roles.toml`;
  read-only `systemctl --user show fabrig-slot-guard.timer -p LoadState,ActiveState,Transient`
  found active/Transient=yes on hetzner6 (also the now-retired hetzner3/7) at 2026-10-30 11:21 UTC.
- **Legacy units remain.** Read-only `systemctl --user list-unit-files` and
  `list-units --all` for these names at 11:21 UTC confirmed the list below, compared
  with `fleet/units/roles.toml`. Heavy, ops and runtime units are excluded.

  | Host | Legacy units outside fleet declarations |
  |---|---|
  | hel8 | fleet-tend.service (static), fleet-tend.timer (enabled); fleet-watch.service (static), fleet-watch.timer (disabled); issue-router.service (enabled) |
  | hetzner6 | fleet-tend.service (static), fleet-tend.timer (enabled); agents-qa-watch.service (disabled) |
  | hetzner8 | fleet-tend.service (static), fleet-tend.timer (enabled) |

- **Journald's cap is bootstrap-only** (`fleet/bootstrap/bootstrap.py:119`).
  Read-only `/etc/systemd/journald.conf.d/` checks at 11:21 UTC found
  hel8's 90-fabrig.conf/SystemMaxUse=200M; the directory was absent on hetzner6/8.
- **The bypass decision remains pending.** `fleet/claude/settings.json:1` sets
  permissions.defaultMode=auto; the user's decision on bypass is pending.
- **Factory tooling remains in fabrig.** `tools/fleet-sync:1086` uses its
  installer; read-only `git -C ~/src/fabrig/main ls-tree HEAD agents tools`
  confirms both trees. Role text remains external
  (`tools/session/session_lib.py:257`).
- **The reaper is unlanded.** Fetched origin/main `5c9e665` and this baseline lack
  tools/reap and reap units; origin/deploy/reap-1 `f71889c` contains them (`git ls-tree`).

## Verification

Earlier read-only host checks: 2026-10-30 11:21 UTC; hel8 via existing strict trust on h3.
Scale-down validation is recorded in the scaledown-0037 task report. Historical
bootstrap fixtures retain their landing's roster; transfer and routing fixtures
are independent of retired hosts. No landing or machine action in this task.

## Later

Ops and green choose after-landing's new host after the pause.
