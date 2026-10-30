# Fleet

2026-10-30. Owner: s/deploy. Code: `fleet/`, `tools/fleet-sync`,
`tools/installed` and `fleet/bootstrap/`. Command references:
`tools/fleet-sync.md`, `fleet/bootstrap/README.md`, `fleet/seeds/README.md`,
`fleet/kache/README.md`. Code departures: `docs/design/fleet.status.md`.

## 1. In one page

- **Main is the fleet's desired state.** Every host's timer converges it to
  agents origin/main once a minute. A healthy host that is not held or pinned
  picks up a landing at its next run, usually within a minute, with nobody
  logging in.
- **Declarations, not scripts.** `fleet/` says what each host has: roles, tools,
  environment, settings, units and pinned versions. `tools/fleet-sync` makes the
  host match and reports what it could not.
- **Same settings everywhere.** Hosts differ only by role and by the few
  per-host values declared in `fleet/hosts.toml`. Sessions choose model and
  effort at launch; the shared defaults are a starting point only.
- **Converge, never take over.** fleet-sync owns what it created and what
  `fleet/` declares, and its journal records that ownership. It never restarts
  a running service. It never adopts check-only paths that an operator already
  runs. It leaves credentials, logins and run state alone.
- **A new host is reproducible.** One root script and one user script, whose
  `fleet-sync --provision` step brings a fresh Debian 13 machine to the same
  state from pinned artifacts, without copying any login. Not yet proven on a
  rebuild (status file).

## 2. Declarations

**`fleet/hosts.toml`** names each host, its SSH address, roles and per-host
values (`env`, `machine_env`, seed eligibility). Roles today: session (hel8),
builder, qa, after-landing and gate. A host is identified by `--host`, then
`FLEET_HOST`, then its hostname.

**Rendered files.** fleet-sync renders, from `fleet/`:

- the login environment (`env.sh`, `environment.d`) and PATH;
- the Claude user settings (`fleet/claude/settings.json`);
- the declared top-level Codex keys and the Cargo config;
- `machine.env`, the per-host values that tools read at run time;
- marked source blocks in `.profile` and `.bashrc`.

Bytes outside fleet-owned blocks or keys are preserved. `fleet/policy.toml`
marks paths that are compared and warned about but never written (mail routing,
an existing kache).

**Session placement and central state (0013).** Every host's `machine.env`
has `SESSION_SLOTS`, the number of sessions the launcher may place there (0 on
hel8 apart from the director, and 0 on the gate host). Every login environment
has `FABRIG_CENTRAL` (the ssh target of hel8) and `FABRIG_CENTRAL_HOST`. Tools
reach claims, leases, records and mailbox homes through that target.

**Tools.** `tools/installed` lists the agents commands linked into
`~/.local/bin` through the `current` release. A name that matches an executable in
`/usr/bin` or `/bin` is refused.

**Periodic gate.** Agents checks run every two hours on the sole builder with
`machine_env.AGENTS_PERIODIC = 1` (hetzner3). Both periodic units are omitted
on other hosts and the service checks the flag again; see `docs/design/gate.md`,
section 4.

**Units.** `fleet/units/` holds systemd user units; `fleet/units/roles.toml`
maps each to the roles that run it. fleet-sync enables timers. A service marked
start-once is started on its first install only. Its owner coordinates that
start and owns every later restart.

**Versions.** `fleet/versions.toml` pins the native tools: Claude, Codex, Rust,
nextest, kache, Chromium, Forgejo and its runner. Normal runs only probe
and warn; installing a pin is the explicit `--provision`.

## 3. Convergence

**One run, five steps,** under a per-host lock:

1. **Agents release.** Fetch main, build an immutable release directory, run
   its self-check and a smoke check, then switch the `current` symlink
   atomically and continue with the new runner. The smoke check proves the new
   runner executes on this host and emits valid state. It accepts drift and
   failed items (exit 1), which the new runner then reports. A candidate that
   cannot run never becomes current.
2. **Fabrig tools.** Run fabrig's own installer only when fabrig's `tools/`
   changed, when its links are wrong, or when its clone is missing. It runs under
   the install lock that ops also uses. Ops can defer this step.
3. **Links and rendered files.** Atomic writes, a one-time backup of
   pre-existing files, and a recheck against competing edits.
4. **Periodic gate.** Agents checks run every two hours on the sole builder with
`machine_env.AGENTS_PERIODIC = 1` (hetzner3). Both periodic units are omitted
on other hosts and the service checks the flag again; see `docs/design/gate.md`,
section 4.

**Units.** Write and enable declared units. Reload only when needed, and
   remove only units the ownership journal records.
5. **Record.** Write state, items and run log. Repeated failures back off
   (1 minute up to 60), but a new main commit skips the wait.

**Effect timing.** A rendered file is in place after the next successful
convergence. That convergence can be delayed by a hold, a pin, backoff, a busy
lock or a failed release. Claude
documents that it reloads its settings live, except model and effort, which
apply at the next start. That is Claude's behaviour, which fleet-sync's tests
do not establish. Changed long-running and start-once services report
`restart pending` for their owners.

**Operator controls** under `~/.config/fleet-sync/`:

- `hold` stops all writes;
- `pin` fixes the agents commit;
- `defer-fabrig` skips step 2;
- `retry` skips one backoff and is the only control fleet-sync removes.

**Read-only modes.**
- `--check` reports drift. Its only write is fetching an existing private
  fabrig mirror.
- `--preview DIR` converges a copy of the managed files inside DIR and prints
  diffs, for a first deployment.
- `status` runs the check locally in-process and on the other hosts over SSH,
  and prints a recovery command for a bad release.

## 4. Safety boundaries

- **No credentials.** fleet-sync never reads keys, tokens, `.credentials.json`,
  `~/.claude.json` or SSH configuration. It runs Claude and Codex only with `--version`.
- **Never touched:** claims, leases, queue and slots under `~/src/fabrig`;
  heavy's state and units; codex-run and owner state; the post spool except the
  routing check; QA logins. Those belong to their own tools and to ops.
- **No-follow file access** for every managed path. Child commands run in their
  own process groups and are killed cleanly on timeout or signal.
- **Recovery** is a revert on main. If `current` itself cannot run, the
  previous release's runner fetches the revert (`tools/fleet-sync.md`).

## 5. New hosts

**Bootstrap** (`fleet/bootstrap/README.md`; unproven, and its README still
names the retired hetzner2):

1. USER preparation.
2. `root.sh`: packages, the user, sudo, linger, unattended upgrades and the
   journald cap.
3. `user.sh`:
   1. installs the Rust toolchains;
   2. clones agents;
   3. runs `fleet-sync --provision` to install the pinned tools;
   4. runs a normal convergence, after which the timer takes over.

**Six native tools come from peers.** hetzner3 is preferred, and hel8 also
serves. Each is verified against its pin: single files by the SHA256 in
`fleet/versions.toml`, trees by the manifests in `fleet/seeds/`. Rust comes
from rustup, which checks its own distribution hashes. kache is built from
source at a pinned revision. Any download must be HTTPS with a pinned SHA256.

**Signing in is the user's.** Claude and Codex logins are never copied between
machines; the bootstrap ends at the login step.

**Readmission** follows the verification list in the bootstrap README.

## 6. Landing rules for fleet changes

- **Land through the gate** (`docs/design/gate.md`): rebase onto origin/main,
  then `tools/land`.
- **Parsers before inputs.** A change that a running runner or service must
  parse lands as code first. Its declarations land only after every host
  reports that code, or with or after the service's restart. Landing both in
  one step strands older parsers; this happened with qa-watch on 10-30.
- **Machine actions are named in the commit** when a landing needs one, for
  example an owner's first start.

## 7. Later

- Declare the slot guard timer in `fleet/units`, replacing the builders'
  transient timer.
- Retire the legacy old-kit units still present on some hosts.
- Move the remaining factory tooling from fabrig `agents/` and `tools/`.
- Prove the bootstrap on a rebuilt host and retarget its README.
- An enforced landing entrypoint (ops request).
- The automatic reaper: `docs/design/reaper.md`, once it lands.
