# Fleet convergence

Run `python3 -I -B tools/fleet-sync` from a checkout for the first deployment,
then use `~/.local/bin/fleet-sync`. Python 3.13 and git are prerequisites.
The fresh-machine procedure is fleet/bootstrap/README.md. Explicit manual
`--provision` installs missing/different pins from fleet/versions.toml; it is
incompatible with timer/check/preview/status. Normal runs only probe versions.
The six native tools use `seed = "peer"`: exact file SHA256/modes or the
fleet/seeds tree manifests, including every file, symlink and directory mode.
Only seed=true hosts are eligible; h3 is preferred, never self. Check local
content before running anything; matching artifacts/links need no writes or
SSH. Missing links alone are repaired locally. Transfer only allowlisted paths
through strict SSH/no-follow opens, stream tar into private staging, verify all
members/hashes/modes/targets, then promote and link. Partial/mismatched trees
are refused before installation. Peer disagreements report warn: manual and
transfer nothing until reviewed. See fleet/seeds/README.md for observed drift.
Optional URL artifacts require HTTPS plus SHA256 before extraction/execution;
file URL SHA256 is the content pin; trees require archive SHA256 AND their
complete manifest. No credential/config/state is seeded. Rustup and
Cargo verify their distribution/locked registry checksums, and kache source is
fetched at the exact declared git revision with vendored patches. Source builds
have a 30-minute bound. The full Codex standalone layout is preserved.
Only a successful explicit provision of absent kache may create its local-only
config/unit and enable/start it. Existing binaries (also on PATH), config,
service, drop-in or cache footprints prevent takeover even under --provision.
Its config and unit are check-only in policy.toml: normal runs only compare and
warn, without ownership adoption, unit verification or lifecycle operations.
No store.env or drop-in is inspected; existing stores/caches are never changed.
Ops agrees any takeover host by host and manages shared-store setup/restarts.
Chromium uses h3's canonical tree with a hetzner3-only seed_hosts allowlist;
hel8's own copy gets a version-only warning, without normal reinstallation.
Bootstrap rollout has two separate landings. Stage A is code only and keeps
main's fleet declarations unchanged, including version-only kache (no config
rendering or preview copy without its kache-source install declaration).
Stage B adds the pins, seeds, kache assets/unit/policy and bootstrap procedure.
Land stage A through tools/land, then wait for all six hosts' timers to report
its release (or a later descendant) before landing stage B through tools/land.
Publishing both stages to main together would strand older parsers. No host
needs a manual runner invocation when this order is followed. Normal stage B
runs remain check-only for kache; provisioning is a separate operator action.
`tools/land` gates a clean branch, fetches/rebases, gates again if HEAD moved,
and pushes main without force. Machine-action commits say what must happen.

Declarations: hosts.toml defines names, hostnames, SSH addresses, roles and host
values. `--host` overrides FLEET_HOST, then hostname discovery. env supplies
literal KEY=VALUE with only $HOME expansion; host env overrides globals.
Expanded env values may contain no whitespace, quotes, backslashes or remaining $.
Every host's machine_env maps environment keys to nonnegative integers or nonempty
literal strings with no whitespace, quotes, backslashes or `$`, using the same
value validation as env. No key names are special. Strings are not expanded;
`=` and `,` are accepted, including compact QA_WALK_KINDS and QA_WALK_SLOTS values.
Invalid machine_env values name the host and key and are refused before writes.
Both types render as `KEY=value` in machine.env.
environment.d is plain KEY=VALUE. POSIX env.sh adds each local/cargo bin directory
only when absent; nested shells retain PATH. Other competing env assignments
warn; PATH assignments never conflict. repositories.toml declares both origins.
Agents uses release metadata first, then the invoking checkout's git origin.
Plain archives fall back to the declared agents origin with source SHA `unknown`.
units/roles.toml maps every unit to roles (`["*"]` means all roles).
The recovery service and timer must both have exactly `["*"]`, always render
for every host, and are never eligible for removal. This is enforced in code.
policy.toml maps managed paths to write (default) or check. post/machines is
check-only pending ops/coordinator agreement: differences warn, without backups
or writes. Check-only units are also excluded from ownership, verification,
enablement, removal and manager queries; the first successful absent-kache
provision is the sole exception for its config/unit. Routing compares name-to-target mappings, ignoring order, blank lines
and comments; a bare SSH target equals `$USER@target`. The `local` sentinel
never receives a username and differs from the SSH target `free@local`.
Equal mappings are ok; otherwise warnings list missing, extra or changed names. Conflicting duplicate
names and malformed entries also warn. Invalid declarations/unknown hosts exit 2
before changing anything.

A hold file suppresses all writes, even bookkeeping. Otherwise an exclusive
flock on ~/.local/state/fleet-sync/lock serializes runs; a busy timer exits
quietly. A check (including each host checked by status) reports only `busy`
with "a run is in progress; check again" and exits 0 while converge holds the
lock. Busy checks preserve state and backoff. Controls hold, pin and defer-fabrig
are never created or removed by us.
The sole removable control is retry: after acquiring the lock, a timer reads
and removes ~/.config/fleet-sync/retry, bypassing its current backoff once.
Hold and a busy lock leave retry untouched; checks and previews never consume it.

1. Validate the dedicated agents clone, fetch, and detach at origin/main or the
   full lowercase SHA in pin. Archive into a sibling, excluding old/, and rename.
   Before promotion, run the candidate's isolated self-check, enforce the fixed
   login-shell `current/tools/fleet-sync --timer` service launcher in code, and
   run `systemd-analyze --user verify` for all host units (warn if unavailable).
   Smoke-test the candidate with `--check --json --host NAME` on the same HOME:
   require exit 0/1 and state JSON. An inherited, inode-checked lock descriptor
   lets it inspect configuration while its parent holds the fleet lock. Smoke
   mode disables mirror fetch/diff too, so it writes nothing. Any failure keeps
   current unchanged. Mark validated promotions, atomically switch current, then
   exec the new runner with the lock/results; continuation skips deployment.
   Keep ten newest releases plus current and the newest previous promotion.
2. Before fabrig, check defer-fabrig; report deferred with its first line. Flock
   the persistent ~/.local/state/fabrig/install.lock non-blockingly: regular
   0600 in a 0700 directory, never replaced or unlinked. Busy means held; other
   steps continue. Recheck defer under the lock, before every link check and
   install, and release at step return. Ops uses the same inode:
   `flock ~/.local/state/fabrig/install.lock python3 -I ~/src/fabrig/main/tools/install`.
   Fetch a private bare partial mirror at src/fabrig/.fleet-sync/fabrig.git.
   Compare installed HEAD with origin/main under tools/ there; missing commits
   count as changed. Install only for changed tools or wrong links. Non-tool
   landings are ok, reporting both short SHAs. Only the installer writes main;
   fleet uses read-only rev-parse/remote get-url there. Bootstrap a missing main
   through its installer in a temporary origin/main checkout. Log output.
   Validate .local/bin and all its parents without following symlinks before
   inspecting links and immediately before either installer invocation; unsafe
   destinations fail the fabrig step. Fabrig's installer itself is unchanged.
3. Link tools/installed through current, refusing non-symlinks. Entries are NAME
   (tools/NAME) or NAME PATH (relative to tools/); names are unique lowercase
   letters/digits/hyphens starting with a letter. Paths cannot be absolute or
   contain ..; executable regular targets must resolve inside the candidate.
   Names matching executable files in /usr/bin or /bin are refused, so fleet
   tools cannot shadow system commands. Self-check validates before promotion.
   `fleet/retired-links.toml` retires five legacy commands: after-landing, land,
   land-set, repin and setup. Remove only symlinks whose lexical targets lie
   under `~/src/rust/agents/`, including dangling targets, and refuse any further
   symlink along the target path. Other links, files, directories and unrecorded
   absences warn; an absent journaled link is ok. Installed/retired overlap fails
   self-check (exit 2). Before unlinking, atomically journal the name, exact link
   text, time and release in private state `retired_links.json` beside links.json.
   Restore manually from that journal with `ln -s "$TEXT" ~/.local/bin/NAME`;
   there is no restore command. Hold suppresses retirement; check/status report
   drift and preview displays removals while changing only its private copy.
   The old kit checkout and other links are untouched.
   Journal created links in links.json;
   remove obsolete recorded links only while they still target current/releases.
   Older change history provides ownership evidence during migration; unrelated
   links and user replacements are retained. Roll out parser support with the
   one-field manifest first, and wait for hosts to adopt it before enabling nested
   entries: older runners also parse the candidate manifest before exec. Render env,
   Claude settings, Cargo config, machine.env and policy-controlled routing.
   Prepend bashrc's source block, append profile's, and edit only declared Codex
   top-level keys. Preserve all outside/project bytes, including CRLF/multiline
   TOML. Compare Claude JSON semantically. Write siblings, fsync, then rename;
   files are 0600, shell files 0644. Save one pre-fleet-sync backup of originals.
   Immediately before rename re-read without following links. On a competing
   edit, recompute once from new bytes; a second change warns "busy; retry next
   run". Claude retries replace the whole fleet-owned object. This detects
   observed races; unrelated clients do not share a filesystem compare-and-swap.
4. Journal unit ownership and reload intent in private state/units.json BEFORE
   writing/enabling units. It is authoritative on restart, including interrupted
   runs without final state.json. Disable/remove obsolete recorded units only;
   stop timers, never services. Disable uses --no-reload. Reload only for changed
   files, journaled intent, or owned units reporting NeedDaemonReload=yes via
   a read-only manager query on each apply. Combine these into one reload and
   clear intent after success. Read is-active, then
   enable --now --no-reload only if a timer is inactive or its enablement link
   is absent/wrong. Unchanged runs make no state-changing systemctl calls.
   A conflicting enablement symlink for a journal-owned timer is replaced by
   sibling rename before enable; unrelated links/files are never forced.
   Changed long-running services warn restart pending; never restart them.

   A service opts into one initial start when its first line is exactly
   `# fleet-sync: start-once` and it has an `[Install]` section (for example,
   `WantedBy=default.target`). The marker on a timer or a unit without [Install]
   is refused by self-check (exit 2). Older runners, including release 1148127,
   accept the comment and treat the unit as an ordinary service.
   After writing a previously absent or unowned service, fleet-sync runs
   `enable --now --no-reload` after daemon-reload. Journal-owned units whose
   first enablement never completed are retried when their enablement link is
   missing. The journal records completed initial enablement so later missing
   or wrong links are repaired with `enable --no-reload`, without starting it.
   It never stops or restarts a start-once service. Later content changes warn
   `restart pending`, including oneshot services. Inactive or failed services
   warn `start-once service not active; its owner restarts it` and stay inactive.
   Role removal disables without --now, removes the owned file, and reports
   `stopped by its owner`; a running service is left running.
   **The service owner must coordinate its first start:** fleet-sync starts it
   at the first run after landing on a host whose role selects it. Further
   starts, restarts and shutdowns belong to that owner. `--check` and `--preview`
   report first-start intent, enablement drift, content changes and activity
   without systemctl writes; existing start-once services get a read-only
   `is-active` probe.
5. Probe versions, save state.json/run.log atomically, and retain seven days of
   changed/failed JSONL records. State includes actual/desired SHAs, items and
   last timer completion, which manual checks preserve. Later steps continue
   after fabrig failure. A completed timer run with any failed item increments
   consecutive_failures and records last_failure. Its next timer waits 1, 2, 4,
   8, 16, 32, then 60 minutes (capped) from that failure. While waiting it exits 0
   without console output, appends one line to run.log, and leaves state and
   timer completion unchanged. Each waiting timer uses git ls-remote to check
   agents origin/main: a SHA different from the last deployed SHA bypasses the
   wait immediately, as does retry. A failed remote probe keeps the wait and is
   included in that log line. Completed runs without failed items reset the
   counter; manual runs never wait. Manual failures preserve the timer counter.
   Checks and status show `backoff until HH:MMZ (n failures)` while it is active.
   Child commands have private process groups; a timeout
   sends TERM, allows five seconds, KILLs survivors and waits before unlocking.
   KeyboardInterrupt and SIGINT/TERM/HUP use that same cleanup, including
   status's parallel children. Exit after unlocking: INT 130, TERM/HUP 143.
   Repeated termination signals during cleanup do not cut the grace period short.
   Installers get 300 seconds; version probes ten; SSH status sixty.

Every managed HOME path is walked with directory descriptors and O_NOFOLLOW.
Every file open, including state, controls and locks, is nonblocking and must
fstat as regular before reading/locking. Refuse symlink leaves/parents before
reads, backups or writes. Current/release links and installed tool links are
explicit exceptions; systemd enablement links are inspected without following.
State/journals/logs use the same safe file access. Normal installs repair lock
permissions in place; checks refuse insecure modes without changing them.

Never read credentials, ~/.claude.json, SSH keys/config/trust or personal
instructions; never modify/depend on old/. Claude/Codex run only --version.
Never touch src/fabrig/{claims,leases,queue,slots}, heavy state/units,
src/rust/tmp/{codex-run,owners}, or anything under post/ except machines.
Never touch ~/src/rust/tmp/logins/: held QA logins must be kept.

For step 0 on each host, run
`python3 -I -B tools/fleet-sync --preview DIR [--host NAME]` from the checkout.
DIR must be new or empty, owned by the caller, mode 0700, and a directory with
existing parents and no symlinked components; each component is checked with
lstat. A new DIR is created with mode 0700; other ownership/modes are refused.
DIR is the caller's private directory. Swapping it mid-run requires the user's
own process, which is outside fleet-sync's threat model.
Preview copies existing managed regular files and their existing backups to
DIR/home using no-follow reads, then converges that copy. It refuses unsafe
managed files; installed tool symlinks are inspected and reproduced as links.
Rendered paths and link targets name the real HOME, even inside the copy.
Preview uses the invoking checkout's declarations without fetching/deploying a
release, defers fabrig, and makes no systemctl writes or live lock, journal or
state writes. Existing start-once services may be probed with is-active.
Conflict checks use the real HOME and environment. Version probes are skipped:
`versions: not probed in preview; see --check`. `--check` still probes versions.
Preview prints unified diffs (including additions, removals and backups),
tool-link changes,
and a list of new files. Check-only files retain their original contents and
report differences as warnings. Hold suppresses preview too. All preview writes
stay inside DIR; preview accepts only --host alongside --preview.

`--check` and `--preview` continue checking other items after an agents failure;
normal deployment still stops on that failure.
`--check` creates no files/locks/state and makes no systemctl writes. Its only write
exception is fetching/comparing an EXISTING private fabrig mirror; an absent
mirror stays absent and falls back to HEAD equality. Unit checks inspect files,
enablement links and advertised bus availability; start-once services also get
a read-only activity probe. Timer runtime activity is not probed.
`status [--json]` checks locally in-process and others in parallel, using strict
existing SSH trust without updates; outside the fleet, all checks are remote.
Unreachable hosts are individual lines. Status names the newest marked previous
release and prints a recovery command. After reverting main, recover a bad
promotion with the previous immutable runner, even if current cannot execute:
`ssh HOST 'bash -lc "python3 -I ~/src/fabrig/releases/agents-<prev>/tools/fleet-sync"'`.
That runner fetches the revert and re-converges; hold/pin must permit it.

Exit 0: converged, warnings only, held/deferred or skipped busy timer. Exit 1:
drift/failed steps or unreachable hosts. JSON emits state (status: hosts array);
text prints non-ok items and summary. After landing, deploy once on each host;
the boot/minute timer follows main thereafter. Ops manages control-file lifetimes.
