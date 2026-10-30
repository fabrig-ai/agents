# Fleet status

2026-10-30. Owner: s/deploy. Baseline: `deploy/design` `373b246`.
Contract: `docs/design/fleet.md`, sections 1–6.

## Present

- Agents periodic units are gated by builder role and AGENTS_PERIODIC=1; only
  hetzner3 declares the flag (`tools/fleet-sync`, `tools/test_land.py`).
- Project-quota boot proposal: `fleet/bootstrap/pquota` and opt-in root bootstrap;
  all flags off, no live boot/quota changes. Follow-up replaces zero-claim/history
  fencing with pinned full central occupancy and bound retained-owner approvals.
  Pre-boot source/environment/writer proof, write-once backups, owner restart
  recording and bounded post-boot EDQUOT/inheritance verification have fixtures.
  Accepted ops review fixes now cover boot-time producer/trigger prevention,
  root UUID agreement, exact new-boot proof, literal GRUB input grammar and
  state-bound complete original manifests. Regression fixtures fail on 9e656e9.
  Re-review fixes add bounded dependency/target/socket activation proof, validated
  leading BOOT_IMAGE metadata, uncached root probes, saved-default refusal and
  shared bound bootstrap recovery transactions. Five fixtures fail on 36872fd;
  real-guard/fake-service recovery covers both drop-in and regeneration interruptions.
  Third-review fixtures fail on d7d418d: success/failure handlers now include
  reverse evidence and reject producer routes or unsupported job modes; systemctl
  operands follow --, with option-parsing fixtures covering the root -.slice.
  Only plan has run on a real host; boot/quota enforcement remains unproved.
  Deploy the compatibility parser fleet-wide before the asset/bootstrap stage.

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
  found active/Transient=yes on hetzner3/6/7 at 2026-10-30 11:21 UTC.
- **Legacy units remain.** Read-only `systemctl --user list-unit-files` and
  `list-units --all` for these names at 11:21 UTC confirmed the list below, compared
  with `fleet/units/roles.toml`. Heavy, ops and runtime units are excluded.

  | Host | Legacy units outside fleet declarations |
  |---|---|
  | hel8 | fleet-tend.service (static), fleet-tend.timer (enabled); fleet-watch.service (static), fleet-watch.timer (disabled); issue-router.service (enabled) |
  | hetzner3 | fleet-tend.service (static), fleet-tend.timer (enabled); agents-after-landing@.service (indirect), instances hearth, jig, skein, smith, temper.1of2, temper.2of2 present; kache-prune.service (static/failed), kache-prune.timer (disabled) |
  | hetzner6 | fleet-tend.service (static), fleet-tend.timer (enabled); agents-qa-watch.service (disabled) |
  | hetzner7 | fleet-tend.service (static), fleet-tend.timer (enabled) |
  | hetzner8 | fleet-tend.service (static), fleet-tend.timer (enabled) |

  Kache-prune's legacy provenance is recorded in `fleet/bootstrap/inventory.md:135`;
  current ops ownership is unproven. Read-only `systemctl --user status kache-prune.service` and
  `journalctl --user -u kache-prune.service -n 30` show failure since 2026-10-27 08:04:26 UTC: “code=killed, status=15/TERM”, then “Failed with result 'signal'.” No cause or safe removal is established.
- **Journald's cap is bootstrap-only** (`fleet/bootstrap/bootstrap.py:119`).
  Read-only `/etc/systemd/journald.conf.d/` checks on all five hosts at 11:21 UTC
  found hel8's 90-fabrig.conf/SystemMaxUse=200M; the directory was absent on h3/6/7/8.
- **The bypass decision remains pending.** `fleet/claude/settings.json:1` sets
  permissions.defaultMode=auto; the user's decision on bypass is pending.
- **Factory tooling remains in fabrig.** `tools/fleet-sync:1086` uses its
  installer; read-only `git -C ~/src/fabrig/main ls-tree HEAD agents tools`
  confirms both trees. Role text remains external
  (`tools/session/session_lib.py:257`).
- **The reaper is unlanded.** Fetched origin/main `5c9e665` and this baseline lack
  tools/reap and reap units; origin/deploy/reap-1 `f71889c` contains them (`git ls-tree`).

## Verification

Fresh read-only host checks: 2026-10-30 11:21 UTC; hel8 via existing strict trust on h3.
Tools/fleet are unchanged since the prior full gate (26 files, 0 failures); no rerun.
The smoke probe used disposable HOME/fake services. No machine action required.
