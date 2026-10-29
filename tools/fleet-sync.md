# Fleet convergence

Run `tools/fleet-sync` from a checkout for the first deployment, then use
`~/.local/bin/fleet-sync`. Python 3.13 and git are prerequisites. Fresh-machine
provisioning is deferred. The designer lands reviewed branches; `tools/land`
checks a clean branch, fetches/rebases, checks again if HEAD moved, and pushes
main without force. Commits that need machine action say so.

`fleet/hosts.toml` declares hostnames, SSH addresses, roles and host values.
`--host NAME` overrides `FLEET_HOST`, which overrides hostname discovery.
`fleet/env` supports only literal values and `$HOME`; host env overrides global
env. `fleet/repositories.toml` declares fabrig's origin. Agents' origin comes
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
2. Compare fabrig HEAD with `ls-remote`, and its installed links. Run its own
   installer on drift; bootstrap a missing clone using that installer in a
   temporary origin/main checkout. Preserve its output in `run.log`. Failure
   here does not prevent the remaining independent steps.
3. Link this repository's `tools/installed` through `current`, refusing files
   that are not symlinks. Render shell/systemd environments, Claude settings,
   Cargo config, machine.env and post/machines. Prepend the bashrc source block,
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

`--check` writes nothing, including state/logs/locks, and never fetches,
installs, extracts, switches releases or calls systemctl. It uses an existing
lock if present, `ls-remote` for remote heads, files and enablement symlinks for
units; it does not assert a timer's runtime activity. User-bus availability is
checked from the advertised address or runtime bus socket. Last timer age comes
from saved state, never from the check itself. Version commands are read-only
probes. An absent agents clone reports drift and checks the invoking declarations.

`status [--json]` checks locally in-process and other hosts concurrently with
60-second SSH deadlines, batch mode, strict existing trust and no trust updates.
Outside the fleet it checks all hosts remotely. Unreachable hosts are reported
individually. `--json` emits the state object
(status emits a hosts array); otherwise only non-ok items and a summary print.
Exit 0 means converged, warnings only, held, or a skipped busy timer; 1 means
drift in check mode or a failed step/unreachable host; 2 means usage, unknown
host or invalid declarations. To deploy after landing, run fleet-sync once by
hand on each of the six hosts; it installs the minute/boot timer. Remove hold
or pin explicitly when automatic following of main should resume.
