# Agent login custody

2026-10-30. Owner: s/deploy. Code: `tools/logins/agent-logins`.
Reference: `tools/logins/agent-logins.md`. Decisions: director 0015 and 0017,
plus the user's copy-back custody flow. Code status: `docs/design/logins.status.md`.
Related design: `docs/design/fleet-scale.md`, section 6, on `origin/deploy/fleet-scale`.

## 1. In one page

- **One active holder.** A free login is available for copying to one machine.
  The shelf copy is never used in place, apart from prepare's one-time sign-in.
- **Bound and lent entries are placeholders.** They stand for a machine's
  current login. Their stored credentials may go stale and cannot be lent.
- **Release copies back before removing.** The machine's current credential
  replaces the placeholder only after verification. Its machine copy is then
  removed, and the entry becomes free.
- **Lend copies out.** A free entry goes to an empty machine credential path.
  After verification it becomes lent; the shelf retains a stale placeholder.
- **Swap is one locked operation.** Release, then lend. A failed lend leaves the
  released login free; a normal verified rollback leaves the machine empty.
- **Credential bytes bypass Python.** External cat and sha256sum read them.
  Python handles descriptors, paths, hashes, state and custody transitions.

## 2. Shelf and custody state

The runtime shelf on hel8 is `~/src/fabrig/logins/pool/`, mode 0700.
Entries are `PROVIDER/ID/`, both directory levels 0700. Providers are `claude`
and `codex`; IDs match `[a-z0-9-]+`. Each directory holds `.credentials.json`
(Claude) or `auth.json` (Codex), mode 0600. Nobody runs an agent using a shelf
entry. Prepare prints provider configuration variables solely for signing in;
register records the resulting login, after which it is used through lend.

`state.json`, mode 0600, retains version 1 and an entries array. Each row has
provider, id, status (`bound:HOST`, `free`, `lent:HOST`), origin, SHA256 of the
latest verified shelf copy, kind, created_at, updated_at and moves. Origin and
kind retain provenance: snapshots have source host/path and kind `snapshot`;
shelf sign-ins have origin `signed-in` and kind `own`. Releasing a snapshot can
make it free without changing its provenance. Register cannot free a held entry.

Moves begin with capture or register; subsequent release/lend moves record UTC
RFC 3339 time, event, destination status and SHA256. State history validates
release from bound/lent to free, and lend from free to lent. Old initial state
without transfer events remains readable; older executables must not mutate
this expanded state. Times and hashes update when a transfer commits.

An optional top-level `pending` record journals a destructive transfer before
it changes either active path. It records event, provider/id, host, verified
hash and recovery paths. Any pending transfer blocks every command, including
list, with an operator-recovery diagnostic. No free row can be used while
there is an unresolved journal. Successful transfers atomically commit their
move and clear pending. There is no automatic recovery command.

Every command holds one global exclusive flock, including subprocesses and
both halves of swap. Provider/entry directories, expected credentials and
state are validated under it. Metadata is written and fsynced to a private
sibling, renamed over state.json, then its directory is fsynced.

## 3. Capture and sign-in

Hosts and SSH targets come only from the current release's
`fleet/hosts.toml`. hel8 accesses local paths; other hosts use SSH. All tests
use a temporary HOME and fake roster/SSH. There is no live source-path override.

Capture streams each current machine credential to a private shelf temporary,
compares hashes at both ends, installs it by rename and records a bound snapshot.
Missing sources report absent and skip. A repeated bound host/provider/hash is
a no-op; changed hashes retain older bound placeholders. Capture refuses a
host's lent login (release it instead) and a hash already recorded free.

Multiple bound captures can exist from the initial inventory. Release prefers
an entry lent to that host, otherwise the last bound entry in capture order.
Older bound entries remain unavailable historical placeholders; they are never
freed merely because a newer capture was released. Multiple lent entries for
one host/provider are refused for operator review.

Prepare creates a new empty private directory and prints the exact sign-in
command. The user signs in once, then registers it. Register checks metadata
and hashes externally; it does not parse or validate account identity. Repeating
registration of an unchanged free own entry is a no-op. Changed entries,
snapshots and held entries are refused. Plain lend IDs must identify exactly
one provider; swap resolves its ID within the explicitly supplied provider.

## 4. Transfers, safety and recovery

**Release.** Stream the host's current file to a private temporary in the entry,
compare source and temporary SHA256, then journal the operation. Keep the old
shelf file as a private backup, rename in the new file, and verify the installed
hash. A mismatch restores the original shelf file and leaves the host untouched.
The host-side remover rechecks the expected hash and inode metadata before
unlinking. Only confirmed removal permits saving free state and the release
move. Delete the old shelf backup after that commit.

**Lend.** Refuse a non-free entry or an existing destination credential, including
a link (release first). Check the shelf hash against state, stream through an OS
pipe into a private host temporary, and verify both ends. Journal the operation,
then install without overwriting an existing credential: a same-directory
link/unlink publishes the checked temporary exclusively. Recheck the installed
hash, then save lent state. The shelf copy remains. Verification failure removes
only the just-installed, hash-matching copy before clearing the journal; a
changed or uncertain copy keeps custody blocked.

**Swap.** Release then lend under the same lock. If lend fails, report
`SWAP FAILED AFTER RELEASE` loudly: the previous login is free on the shelf,
and after a known rollback the host has none. An ambiguous transport or cleanup
failure instead reports uncertain host custody and retains the pending guard.
The tool cannot truthfully claim a remote unlink succeeded after a lost response.

The caller stops credential consumers before release/swap. The tool does not
stop services. Hash and inode checks detect observed refreshes; they cannot
coordinate an agent writing a new credential after removal.

The QA safety principles apply: owned exact modes, umask 077, no symlinks,
O_NOFOLLOW, one-link nonempty regular credentials and private directories.
Linux O_PATH pins a credential without opening it for reading in Python. Cat
and sha256sum read the pinned descriptor. Host mutation helpers traverse
parents without following links, create only 0700 parents and 0600 write-only
temporaries, and never read stdin in Python. SSH stderr is discarded; only
strictly formatted hashes are captured. No credential bytes enter state or logs.

This is not a distributed filesystem transaction. A lost response, interruption
or failed metadata commit can leave pending state and private backups/temporaries.
Keep both copies sealed, stop consumers and reconcile actual machine/shelf hashes
and state before clearing the journal. Never just delete pending to retry.
Unregistered/orphaned snapshots must not be registered as new signed-in logins.
Unused remote temporaries can remain after a failed cleanup; no program uses them.

## 5. Verification and rollout

Offline tests cover initial inventory, prepare/register/list, refreshed release
and lend round trips for both providers, local hel8, mismatches before and after
installation, guarded source removal, existing/unsafe destinations, missing
entries, successful and failed swaps, concurrent lends and swaps, dry-run,
ambiguous IDs, journal blocking, modes, links and unreadable Python descriptors.
Known random dummy bytes must never appear in stdout, stderr, SSH logs or state.

Run `tools/check.sh` for the custody and installed-manifest test files. No real
capture, release, lend, swap or sign-in is part of implementation verification.
Install after review; the user owns the first real custody operations on hel8.

## 6. Later

- Operator-assisted recovery and reconciliation of pending transfers, orphaned
  entries and abandoned local/remote temporary files.
- Retire older bound inventory versions once the operator resolves their identity;
  detect duplicate accounts across credentials without exposing credential bytes.
- Integrate fleet-scale up/down and weekly-limit swap requests.
