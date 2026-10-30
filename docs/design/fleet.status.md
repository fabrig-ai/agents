# Fleet status

2026-10-30. Owner: s/deploy. Baseline: `deploy/design` `dfc2798`.
Contract: `docs/design/fleet.md`, sections 1–6. Host observations: 2026-10-30,
11:08–11:16 UTC; these are observations, not rebuilt-host acceptance.

## Present

- **Declarations and rendering exist.** Host selection, roles, environment,
  Claude settings, declared Codex top-level keys, Cargo config, machine.env and
  shell blocks are implemented in `tools/fleet-sync:545`, `:696`, `:1206` and
  `:1312`. `tools/test_fleet_sync.py:353`, `:371`, `:381`, `:725` and `:801`
  cover rendering and preserved shell/Codex bytes. Claude and Cargo are owned
  as complete files, not merged by individual user keys (`:1325`, `:1330`).
- **Release validation and convergence exist.** `tools/fleet-sync:831` fetches
  main or a pin, archives a release, validates it, switches current atomically
  and executes the new runner. `:953`, `:1114`, `:1159`, `:1340`, `:1973` and
  `:2032` implement installer locking, links, atomic writes/backups, unit
  journals, state/history and timer backoff. `tools/test_review_fleet_sync.py:29`,
  `:38`, `:235` and `tools/test_fleet_sync_2.py:30` cover failure paths.
- **Services are not restarted by normal convergence.** Timers are enabled;
  marked services get initial enable/start and later activity warnings, with
  owners responsible for restarts (`tools/fleet-sync:1420`, `:1437`, `:1483`;
  `tools/test_fleet_sync_4.py:50`, `:76`, `:95`, `:183`).
- **Controls, inspection and recovery exist.** Hold suppresses writes, pins
  select a commit, defer-fabrig skips installation, and retry is consumed only
  by a timer under the lock (`tools/fleet-sync:840`, `:944`, `:2032`, `:2169`).
  Check, private preview and parallel SSH status exist (`:2061`, `:2232`);
  status prints a previous-runner recovery command. Reverting main and manually
  invoking that runner is covered by `tools/test_review_fleet_sync.py:75`.
- **Safe access and explicit provisioning exist.** Managed regular files use
  no-follow access; release/tool/enablement symlinks are explicit exceptions
  (`tools/fleet-sync:135`, `:733`, `:1114`, `:1474`). Children have separate
  process groups and timeout/signal cleanup (`:73`, `:109`). Version declarations
  restrict Claude/Codex to --version (`:630`); protected operational paths are
  covered by `tools/test_fleet_sync.py:970` and credential-free peer allowlists
  by `tools/test_peer_seed.py:272`, `:320`. Provisioning verifies pinned peer
  content or approved downloads before installation (`tools/fleet-sync:1510`,
  `:1674`, `:1709`, `:1769`); normal runs probe versions only (`:1920`).

## Gaps and departures

- **A minute is a polling interval, not a rollout bound.** The promises in
  `docs/design/fleet.md:10` and `:74` need hold/pin, busy-lock, backoff, network,
  validation and install-time qualifications. `fleet/units/fleet-sync.timer:6`
  schedules minutely with five-second accuracy; `tools/fleet-sync:840`, `:1942`,
  `:2011`, `:2169` and `:2190` can delay/prevent convergence. Version drift and
  check-only differences can remain warnings. Fix: describe healthy, unheld,
  unpinned polling without promising completion within a minute.
- **Declared units can be adopted.** The blanket non-adoption claim at
  `docs/design/fleet.md:20`, and “created” at `:70`, exceed the implementation.
  `tools/fleet-sync:1358` treats an unowned existing start-once unit as a first
  start, and `:1365` journals every writable wanted unit as owned. Established
  tests explicitly cover takeover (`tools/test_fleet_sync_4.py:64`,
  `tools/test_fleet_sync_2.py:182`). Fix: distinguish declaration-based unit
  adoption from existing kache, unrelated units and operational-state exclusions;
  removals follow journal ownership, including adopted units.
- **Collision protection has a fixed scope.** `docs/design/fleet.md:46` should
  say executable collisions in `/usr/bin` and `/bin`, the only directories
  checked by `tools/fleet-sync:37` and `:690`; other PATH directories are not
  inspected (`tools/test_fleet_sync_3b.py:61`, `:78`).
- **Fabrig installation also repairs links.** “Only when tools changed” at
  `docs/design/fleet.md:65` omits missing-clone bootstrap and incorrect links.
  See `tools/fleet-sync:1028`, `:1067`, `:1080` and
  `tools/test_fleet_sync.py:480`. Fix: include bootstrap and link repair triggers.
- **Promotion is validation, not proof of a clean check.** “A failing candidate
  never becomes current” (`docs/design/fleet.md:64`) needs qualification:
  `tools/fleet-sync:891` accepts smoke exit 0 or 1 and `:894` validates JSON
  structure, not the absence of drift/failed items. The unit verifier can also
  be unavailable (`:935`). Fix: promise refusal of failed self-check/available
  unit verification or invalid smoke output, not refusal of all reported drift.
  An isolated audit fixture confirmed promotion of valid smoke JSON with a
  failed item and exit 1; no live host was used for that probe.
- **Live Claude uptake is not established here.** `docs/design/fleet.md:75`
  claims live settings reads and next-start model/effort behavior, but
  `tools/fleet-sync:1325` only writes the settings file and the tests use fake
  Claude version commands (`tools/test_fleet_sync.py:138`). Fix: identify this
  as client-dependent behavior requiring a separate read-only observation.
- **Restart warnings cover particular services.** `docs/design/fleet.md:76`
  should specify long-running and start-once services: `tools/fleet-sync:1371`
  excludes ordinary oneshot services from restart-pending warnings.
- **Check/status have a write exception; preview writes its copy.** The
  “read-only modes” label (`docs/design/fleet.md:85`) needs these qualifications.
  `tools/fleet-sync:981` fetches an existing private fabrig mirror in --check;
  `tools/test_fleet_sync.py:516` verifies this exception. Status invokes check,
  while preview writes only inside its requested directory (`:2061`, `:2232`).
- **Routing and existing kache are check-only.** `fleet/policy.toml:3` marks
  post/machines, kache config and kache.service as check-only. Normal runs warn
  without adoption, verification or lifecycle operations (`tools/fleet-sync:1174`,
  `:1342`, `:935`). Only the invocation that successfully provisions absent
  kache may write its config/unit and enable/start it (`:1833`, `:1856`, `:1898`).
  Existing binary/config/drop-in/cache footprints prevent takeover (`:1862`;
  `tools/test_bootstrap_safety.py:21`, `:61`, `:73`, `:83`, `:109`).
- **The slot guard is undeclared.** `fleet/units/roles.toml:2` has no slot-guard
  entry. Read-only `systemctl --user list-timers --all --no-pager` showed
  fabrig-slot-guard.timer active on hetzner3, hetzner6 and hetzner7; `systemctl
  --user show fabrig-slot-guard.timer -p Transient,FragmentPath` reported
  Transient=yes and a transient fragment. It remains an ops-owned timer,
  consistent with `fleet/bootstrap/inventory.md:138`.
- **Legacy units remain; this is a list, not a removal plan.** Surveyed all five
  addresses in `fleet/hosts.toml` with read-only `systemctl --user
  list-unit-files` (all unit types), `list-units --all --type=service,timer`
  and `show -p Id,Description,FragmentPath,UnitFileState,Transient`. Compared
  against `fleet/units/roles.toml`. Unit descriptions identify old fleet-watch,
  QA, landing and issue-router contracts; `fleet/bootstrap/inventory.md:135`
  also classifies the old cache GC, fleet and QA/landing units. Presence does
  not establish safe removal or that an old executable still works.

  | Host | Legacy units outside fleet declarations |
  |---|---|
  | hel8 | fleet-tend.service (static), fleet-tend.timer (enabled); fleet-watch.service (static), fleet-watch.timer (disabled); issue-router.service (enabled) |
  | hetzner3 | fleet-tend.service (static), fleet-tend.timer (enabled); agents-after-landing@.service (indirect), enabled instances hearth, jig, skein, smith, temper.1of2 and temper.2of2; kache-prune.service (static/failed), kache-prune.timer (disabled), classified as legacy cache GC by inventory |
  | hetzner6 | fleet-tend.service (static), fleet-tend.timer (enabled); agents-qa-watch.service (disabled) |
  | hetzner7 | fleet-tend.service (static), fleet-tend.timer (enabled) |
  | hetzner8 | fleet-tend.service (static), fleet-tend.timer (enabled) |

  Heavy reconciler/task units, explicit fabrig-ops transients, the ops slot
  guard, vendor/generated units, Codex task/owner transients and the shared
  store's garage.service are excluded from this legacy-kit list. The hel8
  transient options-site.service is also present outside fleet declarations;
  its owner/legacy provenance was not established. Kache-prune's old-cache
  provenance is established, but present ops ownership was not established, so
  it is listed without recommending action. Hel8 was reached through hetzner3's
  existing strict SSH trust after direct trust was unavailable; no trust changed.
- **Bootstrap remains unproven and targets a retired host.**
  `docs/design/fleet.md:22` overstates reproducibility. The README begins with
  hetzner2 (`fleet/bootstrap/README.md:3`), absent from `fleet/hosts.toml`.
  `fleet/bootstrap/bootstrap.py:179` still defaults to hetzner2 and `:182`
  rejects it: `bash fleet/bootstrap/root.sh --dry-run` exits 2 with “unknown
  fleet host”. Tests use disposable HOME and fake services, not a rebuilt host
  (`tools/test_bootstrap.py:370`, `:421`). Fix: describe an unproven procedure,
  retarget it, and require real readmission evidence before claiming parity.
- **Peer seeding is only part of bootstrap.** `docs/design/fleet.md:114` should
  distinguish six peer-seeded tools (single-file hashes in versions.toml; tree
  manifests in seeds/) from Rustup's distribution checksums and kache's exact
  source revision, patches and checked musl download. `fleet/versions.toml:25`,
  `:33`, `:42` and `tools/fleet-sync:1576`, `:1591`, `:1769` establish the split;
  kache's recorded output digest is historical, not a reproducible-build pin.
- **Journald's cap is bootstrap-only.** Only
  `fleet/bootstrap/bootstrap.py:119` writes the 200M cap; normal convergence
  does not manage it. Read-only listing/reading of
  `/etc/systemd/journald.conf.d/` on all five hosts found hel8's
  `90-fabrig.conf` with `[Journal]` / `SystemMaxUse=200M`; the directory was
  absent on hetzner3, hetzner6, hetzner7 and hetzner8. This does not establish
  effective limits from other journald configuration sources.
- **Claude's permission default is auto.** `fleet/claude/settings.json:1`
  sets permissions.defaultMode to auto; the separate dangerous-mode prompt
  flag does not select bypass mode. The task leaves the user's bypass decision
  pending; no bypass rollout is established.
- **Factory migration is incomplete.** `tools/installed:1` contains the agents
  command links, but `tools/fleet-sync:1068` still uses fabrig's manifest and
  installer. Read-only `git -C /home/free/src/fabrig/main ls-tree HEAD agents
  tools` confirms both trees remain; its tools/installed lists codex-run,
  claim, precheck, ready-check and heavy. The launcher still references fabrig
  role text (`tools/session/session_lib.py:257`).
- **Hetzner3's old cache pruner is failed.** Read-only `systemctl --user status
  kache-prune.service --no-pager --lines=0` reported Result=signal since
  2026-10-27 08:04:26 UTC, main process killed by TERM; its timer is disabled.
  The last error lines from `journalctl --user -u kache-prune.service -n 30
  --no-pager` were:

  ```text
  Oct 27 08:04:26 debian-16gb-hel1-3 systemd[624801]: kache-prune.service: Main process exited, code=killed, status=15/TERM
  Oct 27 08:04:26 debian-16gb-hel1-3 systemd[624801]: kache-prune.service: Failed with result 'signal'.
  Oct 27 08:04:26 debian-16gb-hel1-3 systemd[624801]: Stopped kache-prune.service - Prune oldest complete kache S3 entries above 35 GiB to 25 GiB.
  ```

  The excerpt does not identify who sent TERM; no repair was attempted.
- **Landing enforcement and reaping remain deferred.** See
  `docs/design/gate.status.md` for the caller-trusted gate lock and unenforced
  landing convention. A read-only fetch found origin/main `5c9e665` without
  tools/reap or reap units; origin/deploy/reap-1 `f71889c` adds them
  (`git diff --stat origin/main...origin/deploy/reap-1`). Neither this baseline
  nor the observed main contains the reaper. The cited
  future `docs/design/reaper.md` reference at `docs/design/fleet.md:142` is
  absent here and on the fetched reaper branch, which has `tools/reap/reap.md`.

## Verification

The full `bash tools/check.sh` passed: 26 files, 0 failures, 467.791 seconds
with four workers. HOME, TMPDIR and AGENTS_GATE_LOCK were inside the audit
clone; tests used disposable fixtures and fake services. An additional disposable
fixture confirmed promotion despite a failed smoke-check item. Read-only host
checks are listed alongside their findings; no units, controls, credentials,
logins or operational state were changed. This change needs no machine action.
