# fleet-scale

Roll out in two landings: first the fleet-sync parser commit alone, then wait
for every fixed host timer to report it; only then land the pool declarations,
helper and mirror units. Older runners parse candidate declarations in-process,
so a single combined landing would reject the new pool helper asset.

Python 3.13, standard library only. Implements `docs/design/fleet-scale.md`
sections 2–5. Run on hel8 as free, from the reviewed, deployed release. Before
real `up`, land the parser/bootstrap changes and confirm mirror.timer has
created both mirrors containing that release on main. This branch is not landed
by its tests. The first real rebuild remains operator acceptance evidence.

```
fleet-scale key
fleet-scale up --dry-run
fleet-scale up
fleet-scale list
fleet-scale list --json
fleet-scale hosts --json
fleet-scale down pool-1 --dry-run
fleet-scale down pool-1
fleet-scale down pool-1 --force
```

`key` creates `~/.ssh/fleet-scale` (0600, ed25519), repairs its public half,
and registers the public half under the pool's SSH key name if absent. An
existing API key with different public bytes is refused. Output:
`fleet-scale key ready`. It never prints private material. Run it explicitly
before `up`; the user's existing Hetzner key is not used for new servers.

`up` reserves a monotonic `pool-N`, creates cpx42/debian-13/hel1 with
`fleet=pool,member=pool-N`, waits for its action and root SSH, records a TOFU
fingerprint, bootstraps, and verifies before printing
`pool-N ready free@IP`. It uses only the declared fleet key for member SSH.
The registry records creating/bootstrapping/ready/draining/deleting and the
current step. A failed command leaves the entry visible in `list`. Clean up
with `down NAME`; investigate errors before another `up` (which reserves a new
name). A lost create response is recovered by labels during deletion.

Member git access is a separate key generated on the member. Its exact marked
line on hel8 uses `restrict,command="git-shell -c \"$SSH_ORIGINAL_COMMAND\""`.
Mirrors reject receive-pack updates with a pre-receive hook; members fetch only.
Members receive no GitHub identity or agent login. The central SSH alias uses
hel8's already trusted known_hosts entry. All six peer-seeded tools are relayed
through hel8 with existing admin SSH access to the eligible seeds: the exact
allowlisted content is checked against fleet pins before transfer and again
before installation. No general SSH grant on a seed is needed by the member.
Rustup and pinned kache source provisioning retain the existing bootstrap rules.
The kache store.env is streamed from/to its declared 0600 path and its two SHA256s
must match; its contents are never stored in a Python variable or command log.
Transfer follows user bootstrap: creating .config/kache before provisioning
would correctly trigger fleet-sync's existing-installation protection.
The template retains hetzner3's local-only selector; copying the store credential
does not activate a shared store or restart an existing cache.

`down` marks draining, checks central claims and waits up to five minutes for
heavy's version-1 ledger (`~/src/rust/tmp/heavy/state.json`) to contain only
released tasks. The remote probe opens the existing host.lock read-only and
takes a shared lock; it creates or changes no heavy state. A busy lock waits;
missing, malformed, foreign-queue or unknown-version snapshots fail closed.
`--force` explicitly bypasses draining after an independent operator drain.
Partial bootstrap states do not receive work and can be removed without that
probe. Deletion is verified by GET returning 404; only then are the marked
key and that IP's known_hosts lines removed and the entry moved to `retired`.
A partial cleanup remains `deleting` and can be retried. Already retired names
are idempotent. Claims on members are not assigned by current consumers; their
adoption of the ready-only `hosts --json` feed is later work.

`list --json` emits `{members: {NAME: RECORD}, retired: [...], next: N}`;
`hosts --json` emits `{hosts: {NAME: {hostname, ssh, roles, ...}}}`, merging
fixed declarations and ready pool members. Dry runs read configuration and the
registry only: no API, SSH, secrets, locks or writes. `max_members` counts all
unretired entries, including incomplete ones. Other limits are reserved.

Configuration is `fleet/pool.toml`; tests inject a loopback API URL there.
HTTPS is required otherwise; redirects and proxy environment settings are
disabled. The token is read exclusively from its owned 0600 file for the
Authorization header. API bodies and subprocess output are never printed on
failure. Registry mutation holds a flock across each operation, serializing
allocation/deletion/cleanup, and uses fsynced sibling renames. Readers see the
last complete state while another operation holds the lock. SSH file edits use
a separate lock and preserve a `.fleet-scale.bak` backup. No real infrastructure
is contacted by tests.

Verification runs `fleet-sync --check --json` (exit zero, no failed/drift or
busy/held results), each pinned version command, `heavy --installed` and
`systemctl --user is-active fleet-sync.timer`. Exit 0 means success; exit 1
means failure with a recoverable registry state; argparse errors exit 2.
