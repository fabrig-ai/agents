# Fleet convergence

Run `tools/fleet-sync` from a checkout for the first deployment, then use
`~/.local/bin/fleet-sync`. Python 3.13 and git are prerequisites. Fresh-machine
provisioning is deferred. The designer lands reviewed branches; `tools/land`
checks a clean branch, fetches/rebases, checks again if HEAD moved, and pushes
main without force. Commits that need machine action say so.

`fleet/hosts.toml` declares hostnames, SSH addresses, roles and host values.
`--host NAME` overrides `FLEET_HOST`, which overrides hostname discovery.
`fleet/env` supports only literal values and `$HOME`; host env overrides global
env. Expanded env values must contain no whitespace, quotes, backslashes or
remaining `$`; invalid declarations exit 2. environment.d uses plain KEY=VALUE.
env.sh uses POSIX case tests to prepend each local/cargo bin directory only if
absent, preserving existing PATH entries across nested shells. PATH assignments
never produce conflict warnings; other owned env keys do.
`fleet/repositories.toml` declares fabrig's origin. Agents' origin comes
from the invoking git checkout, retained in `.fleet-release.json` in archives.
`fleet/units/roles.toml` maps every unit to roles (`["*"]` means all roles).
Versions are report-only commands with ten-second timeouts. No packages are
installed and no builds run.

A run validates all declarations and host selection before writing anything.
A hold file at `~/.config/fleet-sync/hold` suppresses **all** writes, including
state/lock updates, and reports its first line. Otherwise an exclusive `flock`
on `~/.local/state/fleet-sync/lock` serializes runs. A busy timer exits quietly.

1. Validate the dedicated agents clone (no symlink, dirt or foreign origin),
   fetch, detach at origin/main or the full SHA in `~/.config/fleet-sync/pin`.
   Archive into a temporary sibling, exclude `old/`, rename, self-check using
   isolated Python, atomically switch `~/src/fabrig/current`. Keep ten newest
   releases plus current. Exec the selected script, inheriting the lock and run
   results; the continuation skips release deployment to prevent an exec loop.
   A failed release/self-check stops before configuration or switching current.
2. If `~/.config/fleet-sync/defer-fabrig` exists, report `deferred` with its
   first line and skip fabrig. Otherwise non-blockingly flock the persistent
   `~/.local/state/fabrig/install.lock`: private regular 0600, directory 0700,
   O_NOFOLLOW, never replaced/renamed/unlinked. A busy lock reports `held:
   install lock busy` and the run continues. Recheck defer under the lock,
   immediately before link inspection and each install. Release the lock at
   step return. Ops uses the same inode with
   `flock ~/.local/state/fabrig/install.lock python3 -I ~/src/fabrig/main/tools/install`.
   Clone a private bare partial mirror at `~/src/fabrig/.fleet-sync/fabrig.git`
   (`--bare --filter=blob:none`) if absent, then fetch origin/main there each
   run. Diff installed HEAD against origin/main under tools/ in the mirror;
   a missing installed commit counts as changed. Run fabrig's installer only
   for changed tools or wrong links. Non-tool landings report `ok: main ahead,
   tools unchanged` and both short SHAs; main stays at its installed commit.
   Fleet only runs read-only rev-parse/remote get-url in fabrig/main; only the
   installer moves it or writes its git state. Bootstrap an absent clone by
   running the installer from a temporary origin/main checkout. Log installer
   output in run.log. Failure here does not prevent later independent steps.
3. Link this repository's `tools/installed` through `current`, refusing files
   that are not symlinks. Render shell/systemd environments, Claude settings,
   Cargo config and machine.env. `fleet/policy.toml` maps managed file paths to
   `write` (the default) or `check`. post/machines is check-only pending ops and
   coordinator agreement: a difference warns `differs; check-only`, without
   writing, backing up or taking ownership. Prepend the bashrc source block,
   append the profile block, preserve outside text. Change only declared Codex
   top-level keys, preserving project tables. Claude JSON compares semantically.
4. Write role units; reload only when unit files changed. Enable/start timers,
   never stop/restart services. Report changed long-running services as restart
   pending. Disable/remove obsolete units only when recorded as ours (stop
   obsolete timers with `disable --now`, disable services without stopping). A missing
   user bus is a failure. Report competing env assignments as warnings.
5. Check versions, then atomically save state.json and run.log. Keep seven days
   of changed/failed run records in runs.jsonl. State retains managed file/unit
   lists and the last timer completion independently of manual checks.

Managed regular files are sibling-renamed, 0600 (shell files 0644), only when
content differs. The first replacement of a file not recorded as ours creates
one `.pre-fleet-sync` backup; existing backups are never replaced. Symlinks also
switch by rename. State and logs are private. No credentials, `~/.claude.json`,
SSH keys/config/trust, personal instructions or legacy files are read or edited.
Claude and Codex run only with `--version`. Fabrig owns its own tool links.
Never touch `~/src/fabrig/{claims,leases,queue,slots}`, heavy's state or units,
`~/src/rust/tmp/{codex-run,owners}`, or post's spool directories (everything
under `~/src/rust/tmp/post/` except machines, which is currently check-only).

`--check` writes only inside an **existing** private fabrig mirror, where fetch
and tools comparisons may update refs/objects. It never creates a missing mirror;
without one it conservatively decides by installed HEAD == remote main. It
creates no locks, state, logs, backups or rendered files and never installs,
extracts, switches releases or calls systemctl. It flocks existing locks only,
refusing insecure install-lock modes without repairing them; normal runs repair
those modes without changing the lock inode. It uses files/enablement symlinks for
units; it does not assert a timer's runtime activity. User-bus availability is
checked from the advertised address or runtime bus socket. Last timer age comes
from saved state, never from the check itself. Version commands are read-only
probes. An absent agents clone reports drift and checks the invoking declarations.

`status [--json]` checks locally in-process and other hosts concurrently with
60-second SSH deadlines, batch mode, strict existing trust and no trust updates.
Outside the fleet it checks all hosts remotely. Unreachable hosts are reported
individually. `--json` emits the state object
(status emits a hosts array); otherwise only non-ok items and a summary print.
Exit 0 means converged, warnings only, held/deferred, or a skipped busy timer; 1 means
drift in check mode or a failed step/unreachable host; 2 means usage, unknown
host or invalid declarations. To deploy after landing, run fleet-sync once by
hand on each of the six hosts; it installs the minute/boot timer. Remove hold
or pin explicitly when automatic following of main should resume. Fleet never
creates or removes defer-fabrig, hold or pin; ops manages their lifecycle.
