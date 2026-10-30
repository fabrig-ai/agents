# Agent login shelf

`agent-logins` is a Python 3.13 standard-library tool. Run it on hel8 as the
shelf owner. Contract: `docs/design/logins.md`, sections 1–5. Installation uses
`tools/installed`; it is separate from QA's `logins` command and registry.

```
agent-logins capture HOST [--dry-run]
agent-logins prepare {claude,codex} ID
agent-logins register {claude,codex} ID
agent-logins list [--json]
```

IDs match `[a-z0-9-]+`. The shelf is `~/src/fabrig/logins/pool/`, mode 0700,
with private provider and entry directories. A Claude entry holds
`.credentials.json` and can be used as `CLAUDE_CONFIG_DIR`; a Codex entry holds
`auth.json` and can be used as `CODEX_HOME`. Credentials, metadata and the lock
are owned, single-link regular files of mode exactly 0600. Source credential
directories must be owned and exactly 0700 too. Empty credentials are refused.
The tool sets umask 077. It refuses unsafe modes rather than repairing them.

`prepare` creates a new empty entry directory and prints one exact sign-in
command, with the absolute directory safely shell-quoted:

```
CODEX_HOME=DIR codex login --device-auth
CLAUDE_CONFIG_DIR=DIR claude auth login
```

The user runs the command, then `register PROVIDER ID`. Register checks the
expected credential using filesystem metadata, delegates hashing to
`sha256sum`, and records a free, shelf-owned login with origin `signed-in`.
Registering the same hash again is a no-op. A changed registered credential
is refused for operator review; a snapshot cannot be registered as free.
Prepare refuses an existing directory, even an empty one. Unregistered sign-in
directories are absent from list output.

`capture HOST` reads the host's SSH target from
`~/src/fabrig/current/fleet/hosts.toml`, with no checkout fallback. The
intentional `current` release symlink is supported. Host names must be in that
roster. The sources are `~/.claude/.credentials.json` and `~/.codex/auth.json`.
For `hel8`, local subprocesses use this HOME; other hosts use SSH with
BatchMode and existing host-key policy. No source is modified or removed.

To retain no-follow safety through the external read, SSH runs a small
standard-library Python helper that pins the source with `O_PATH|O_NOFOLLOW`,
then execs `cat -- /proc/self/fd/N` or `sha256sum -- /proc/self/fd/N`.
This is the guarded form of `ssh HOST cat FILE` / `ssh HOST sha256sum FILE`;
the remote needs Linux, Python 3 and coreutils. Python never opens a credential
for reading. Cat's stdout streams directly into a new private shelf temporary
file; all child stderr is discarded. Only strictly formatted SHA256 output is
captured in Python. Each subprocess has a 120-second timeout.

The local temporary file's SHA256 must equal the source's SHA256 before rename
into the new entry. Each provider commits separately. A missing source reports
`absent` and skips that provider. An unsafe source, SSH failure, or hash mismatch
aborts the command, removes its temporary file, and leaves earlier committed
entries intact. A snapshot records `bound:HOST`, `kind=snapshot`, its source
host/path, hash and capture time. It stays bound while the source machine uses
that login. The tool implements no release or lending operation.

Repeated host/provider/hash captures leave state unchanged. A changed hash adds
another snapshot, retaining every older one. Snapshot IDs start with HOST and
the full hash, with a numeric suffix if an existing directory occupies that ID.
`--dry-run` validates the roster and state and prints planned source and shelf
paths. It never invokes SSH or inspects sources, and may create the private
shelf directories and lock. It does not create entries or state.json.

`list` prints entry paths, custody statuses and hashes in provider/ID order.
`list --json` prints an array of state entry objects in that order, or `[]`.
It includes provider, id, status, origin, sha256, kind, created_at, updated_at
and moves. There are no credential contents or additional log files. Capture
and register print paths/hashes; errors print safe diagnostics on stderr.
Malformed metadata and subprocess diagnostics are never echoed. Exit status
is 0 for success, 2 for argparse usage, and 4 for refused operations or errors.

All commands hold one exclusive flock on the shelf's stable `lock` inode,
including list and capture subprocesses. State replacements use a private
sibling, fsync and atomic rename; credential installation also uses rename.
All ancestors of the shelf must be real directories, and its `logins` parent
must be private. Provider and entry directories, expected credentials (including
unregistered ones), and state are checked before any operation; a missing
registered credential is an error. The tool never repairs
unsafe paths. Do not edit the shelf or credentials during an operation.

A crash after installing a credential but before saving metadata can leave an
unregistered private snapshot directory. A killed process can leave a private
`.capture-*` or `.state-*` file. These are not listed or made available.
The operator must reconcile such artifacts before reusing them; do not register
an orphaned snapshot as a signed-in login. Atomic rename is per file, not a
transaction over the shelf. Credentials are never automatically removed.

Verification: `tools/check.sh tools/logins/test_agent_logins.py`, then the full
`tools/check.sh`. Tests use only temporary HOME, a fake current roster, fake SSH
and randomly generated dummy credentials. No live login or host is accessed.
