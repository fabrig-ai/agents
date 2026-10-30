# Agent login shelf

`agent-logins` is a Python 3.13 standard-library custody tool, run on hel8 as
shelf owner. Contract: `docs/design/logins.md`, sections 1–5. It is installed
through `tools/installed`, separately from QA's `logins` registry.

```
agent-logins capture HOST [--dry-run]
agent-logins prepare {claude,codex} ID
agent-logins register {claude,codex} ID
agent-logins list [--json]
agent-logins release HOST {claude,codex} [--dry-run]
agent-logins lend ID HOST [--dry-run]
agent-logins swap HOST {claude,codex} ID
```

The shelf is `~/src/fabrig/logins/pool/`, with owned 0700 provider and entry
directories. IDs match `[a-z0-9-]+`. Entries hold `.credentials.json` (Claude)
or `auth.json` (Codex), owned single-link nonempty regular files, mode 0600.
State and lock are also 0600. The tool sets umask 077 and refuses unsafe modes,
links and incorrect ownership rather than repairing them.

**Never use an entry in place.** Bound and lent entries are stale placeholders
for a machine's live credential. Free entries are copied to machines by lend.
Only prepare's one-time sign-in uses configuration variables into the shelf:

```
CODEX_HOME=DIR codex login --device-auth
CLAUDE_CONFIG_DIR=DIR claude auth login
```

Prepare prints one exact shell-quoted command and refuses an existing directory.
The user signs in once, stops using the shelf directory, then runs register.
Register checks the expected file by filesystem metadata, hashes externally,
and records `free`, `kind=own`, origin `signed-in`. Registering an unchanged free
own entry is idempotent. Changed credentials, snapshots and held entries refuse.
Unregistered prepared directories are not listed.

**Capture.** Hosts and SSH targets come from
`~/src/fabrig/current/fleet/hosts.toml`; the intentional current symlink is
supported, with no checkout fallback. Sources are `~/.claude/.credentials.json`
and `~/.codex/auth.json`. hel8 uses local subprocesses; others use SSH BatchMode
and existing host-key policy. A streamed private temporary must match the
source hash before rename into a new bound snapshot. A missing source reports
absent and skips that provider. Different hashes retain older placeholders;
repeating the same bound host/provider/hash leaves state unchanged. Capture
refuses a lent login (release first) and a hash already free on the shelf.
Capture never removes source files; each provider commits separately.

**Release.** `release HOST KIND` requires a bound or lent entry for that host
and provider. It prefers the lent entry; otherwise it uses the latest bound
capture in state order. Earlier bound versions stay unavailable placeholders.
Multiple lent matches refuse. The current host file streams back to a new
shelf temporary; local and source hashes must match. The old shelf copy is
backed up, the new copy is renamed into place and verified again. Only then
does a guarded host-side remover verify its hash/inode and unlink it. After
confirmed removal, state becomes free and a release move records the new hash.
A known mismatch before removal restores the stale shelf copy. The old backup
is deleted only after the free-state commit.

**Lend.** `lend ID HOST` requires an unambiguous ID across providers and a free
entry. HOST must not already have that provider's credential (even a symlink),
or the tool says release first. A recorded lent entry for HOST also refuses.
The source shelf hash must match state. The credential streams into a new host
temporary, with a 0700 parent created if absent, and both hashes are checked.
Installation rechecks the temporary hash and publishes without overwriting a
raced-in file. The installed hash must match before recording `lent:HOST`.
The shelf copy remains as a placeholder and may become stale. A final mismatch
removes the just-installed copy if its actual hash is still the expected one;
otherwise custody is blocked for recovery. Free state is not reused while a
transfer is uncertain.

**Swap.** `swap HOST KIND ID` releases then lends under one lock. KIND scopes
ID resolution. A lend failure after release reports `SWAP FAILED AFTER RELEASE`:
the old login is free on the shelf, and a known rollback leaves HOST with none.
A lost response or failed cleanup instead reports uncertain host custody and
blocks further commands. Swap never silently restores the old login to HOST.
Stop credential consumers before release/swap; the tool does not stop services.

Capture, release and lend dry-run validate roster/state and print plans without
reading sources, contacting hosts or changing custody. In particular lend's
dry-run does not prove destination absence. They may initialize shelf/lock.

`list` prints paths, statuses and hashes in provider/ID order. `list --json`
prints the state entries array with provider, id, status, origin, sha256, kind,
created_at, updated_at and moves. Kind and origin preserve capture/sign-in
provenance after release or lend. SHA256 is the latest verified shelf hash;
release/lend events add timestamp, event, destination status and hash. Old
initial state remains readable; older executables must not write transfer state.
No command except prepare emits shelf-based configuration variables.

All commands take one stable exclusive flock, including both swap operations.
State updates use private siblings, fsync and atomic rename. Before destructive
transfer steps, an optional state `pending` journal is saved. Unfinished journal
state blocks every command, including list, with an operator-recovery diagnostic.
A crash/lost SSH response can leave a verified copy, old shelf backup and pending
state; never clear pending without reconciling both ends and stopping consumers.
There is no automatic recovery command. Unused private temporaries may need
cleanup. Never register an orphaned snapshot as a new signed-in login.

Linux O_PATH descriptors pin checked credentials; Python never opens them for
reading. External cat and sha256sum perform reads through `/proc/self/fd/N`.
SSH runs the same standard-library helpers. Lend pipes cat stdout directly
into the destination helper's cat stdin: no Python read or byte buffer is used.
Helpers require Linux, Python 3 and coreutils. Child diagnostics are discarded;
only validated hash output enters Python. Subprocesses have 120-second bounds.
Shelf ancestors must be real directories; the logins parent must be private.
Provider/entry directories, known credentials and state are validated under lock.

Exit codes: 0 success, 2 argparse usage, 4 refused/unsafe/unavailable operations.
Errors contain safe paths and custody diagnostics, never subprocess output or
arbitrary metadata. Verification uses temporary HOME, fake SSH/current roster
and random dummy credentials only:

```
tools/check.sh tools/logins/test_agent_logins.py tools/test_fleet_sync_3c_manifest.py
```
