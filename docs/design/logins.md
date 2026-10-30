# Agent login custody

2026-10-30. Owner: s/deploy. Code: `tools/logins/agent-logins`.
Reference: `tools/logins/agent-logins.md`. Decisions: director 0015 and 0017.
Code departures: `docs/design/logins.status.md`. Related design:
`docs/design/fleet-scale.md`, section 6, on `origin/deploy/fleet-scale`.

## 1. In one page

- **One active holder.** A login rests on hel8's shelf or belongs to one
  machine. Future transfers must move and verify it, then remove the source.
- **Snapshots remain bound.** Decision 0017 permits copying each machine's
  current login to the shelf for safekeeping. A snapshot remains bound to its
  source machine and is never available to lend while that machine uses it.
- **The user signs in shelf-owned logins.** Prepare prints a sign-in command;
  register records the result as free. The tool never signs in for the user.
- **Credential bytes bypass Python.** External cat and sha256sum perform
  credential reads. Python manages descriptors, paths, hashes and custody.
- **This pass inventories the shelf.** It captures, prepares, registers and
  lists. Lending, returning and swapping have no command yet.

## 2. Shelf and custody state

The runtime shelf on hel8 is `~/src/fabrig/logins/pool/`, mode 0700.
Entries are `PROVIDER/ID/`, both directory levels 0700. Providers are `claude`
and `codex`; IDs match `[a-z0-9-]+`. Each Claude directory contains
`.credentials.json` and is usable as `CLAUDE_CONFIG_DIR`; each Codex directory
contains `auth.json` and is usable as `CODEX_HOME`.

`state.json`, mode 0600, contains version 1 and an entries array. Each entry
records provider, id, status, origin, SHA256 at capture/registration, kind,
created_at, updated_at, and a moves array. Times are UTC RFC 3339 to seconds.
Moves record time, event and destination status. A snapshot has origin host
and `~`-relative source path, kind `snapshot`, and status `bound:HOST`.
A shelf login has origin `signed-in`, kind `own`, and status `free`.
`lent:HOST` is reserved for future transfers and is not written or accepted by
this version. Snapshot entries never become free through register.

Every command holds a global exclusive flock on a stable private lock file.
Provider and entry directories, their expected credentials, all registered
entries and state are validated while holding it. Metadata
updates write and fsync a private sibling, atomically replace state.json, and
fsync the shelf directory. Unregistered prepared entries are absent from state.

## 3. Capture and sign-in

Capture uses only hosts in the current release's `fleet/hosts.toml`, selecting
its declared SSH target. hel8 reads local sources; other hosts use SSH. There
is no source-path override or real-host probing during tests.

For each provider, capture streams the source into a private temporary file,
hashes both ends, compares, renames into a new entry, and commits bound state.
Python never holds the streamed bytes. A repeated host/provider/hash is a no-op
even if an intervening capture found another hash; different hashes retain
separate snapshots. Missing files report absent and skip. Unsafe files, hash
mismatches and transport failures abort with temporary cleanup. The original
credentials are never changed or removed. Each provider commits independently.
Dry-run reports paths without source access; it can initialize the shelf lock.

Prepare creates a new empty private directory and prints the provider's exact
sign-in command. The user runs that command and then register. Register checks
the expected credential by filesystem metadata and hashes via an external
process. It neither parses nor validates account identity. Re-registration is
idempotent for the same hash and refuses changed or snapshot credentials.

## 4. Safety and recovery

The tool reuses QA custody's ownership/exact-mode checks, no-follow descriptors,
umask 077, stable locks, and sibling replacement principles. Credential files
must also have one hard link and be nonempty. Shelf paths and source directory
ancestors are traversed without following links. All operations refuse a
symlinked shelf, state, lock, registered entry or credential. The fleet's
intentional current release symlink applies only to roster lookup.

To prevent a link-swap between metadata validation and an external read, a
small Python helper pins credentials with Linux O_PATH, never a readable
Python descriptor. It then execs cat or sha256sum through the inherited
`/proc/self/fd` path. The helper runs over SSH for remote sources too. Cat's
stdout is always a private file descriptor; subprocess stderr is discarded.
Only validated hash output enters Python. State, logs and command output never
contain credentials. Metadata parse errors do not echo arbitrary file data.

There is no multi-file transaction. An interruption after credential rename
can leave an unregistered private entry; it is not free and must be reconciled
by the operator, never registered as a new signed-in login. Killed processes
can leave private temporary siblings. Automatic deletion or recovery of these
is deferred. Same-user writers must not edit the shelf during operations.

## 5. Verification and rollout

Tests run with temporary HOME, fake SSH, a fake deployed roster and random
dummy credentials. They cover capture and both providers, hash mismatch and
cleanup, idempotence and changed hashes, absence, local hel8, dry-run,
prepare/register/list, mode and link refusal, serialized concurrent captures,
snapshot binding, metadata privacy and unreadable Python source descriptors.
Known dummy bytes must not appear in stdout, stderr, SSH logs or state.

Install through `tools/installed` only after review. A real capture is a separate
operator action on hel8. This implementation task does not access any real
credential or perform sign-in, capture, fleet changes or service restarts.

## 6. Later

- `lend`, `return` and `swap`: verify/copy/remove transfers, exactly one active
  holder, restart coordination, crash recovery and explicit custody transitions.
- Release a snapshot's binding only after proving its original holder stopped
  using that login; bind duplicate credentials across captures by account.
- Integrate fleet-scale up/down and weekly-limit swap requests.
- Reconcile orphaned entries and abandoned temporary files safely.
