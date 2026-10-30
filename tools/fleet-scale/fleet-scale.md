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
fleet-scale up --local-only-kache
fleet-scale list
fleet-scale list --json
fleet-scale hosts --json
fleet-scale ssh pool-1
fleet-scale ssh pool-1 'uname -a'
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
The registry records creating-unresolved/creating/bootstrapping/ready/draining/deleting and the
current step. A failed command leaves the entry visible in `list`. Clean up
with `down NAME`; investigate errors before another `up` (which reserves a new
name). Before POST it records the create-request time and creating-unresolved.
`down` and `list` retry both-label reconciliation for ten seconds. Exactly one
match resolves the id; multiple matches refuse. Empty results remain unresolved
until a fresh query at least ten minutes after the create request is still empty.
`list` flags that state; only `down` then retires it. Failed queries never prove
absence. A known id always selects only that server, regardless of label twins.

Member git access is a separate key generated on the member. Its exact marked
line on hel8 uses `restrict,command=".../current/tools/fleet-scale/mirror-serve"`.
The helper parses SSH_ORIGINAL_COMMAND without a shell and execs only
git-upload-pack for the two exact mirror directories. Other paths/commands,
symlinks, parent traversal, extra args and injection refuse with exit 1.
Pre-receive hooks remain an additional guard.
Members receive no GitHub identity or agent login. The central SSH alias uses
hel8's already trusted public host key imported read-only into the dedicated
trust file. Member aliases also use a dedicated trust file. All six peer-seeded tools are relayed
through hel8 with existing admin SSH access to the eligible seeds: the exact
allowlisted content is checked against fleet pins before transfer and again
before installation. No general SSH grant on a seed is needed by the member.
Rustup and pinned kache source provisioning retain the existing bootstrap rules.
The shared-store default reads only `kache_source` from pool.toml:
`~/.config/fleet-scale/kache-store.env` on hel8 (owned regular 0600 file).
The separate `kache_destination` is `~/.config/kache/store.env` on the member;
its parent is set to 0700 and file to 0600. Missing/unsafe sources refuse `up`
before name allocation or any API call, with no fallback search. The source is
streamed through its file descriptor and bounded SHA256 reads, never loaded
into a Python variable or command log; both SHA256s must match. Dry runs check
source metadata without reading credential contents.

The template keeps hetzner3's 40 GiB cache cap, 40 GiB disk floor and three
heavy build slots, but omits its `KACHE_LOCAL_ONLY=1`. After fresh provisioning
and credential delivery, bootstrap writes the declared remote selectors and
EnvironmentFile drop-in, reloads the manager and restarts this new member's
kache to enable shared storage. The recovery threshold is 80 GiB. Delivery
follows provisioning so its .config/kache footprint cannot block installation.
Fixed hosts and their existing caches retain the existing fleet-sync policy.

`up --local-only-kache` explicitly skips all credential access and delivery,
remote setup and that restart. It records the choice centrally and writes a
non-secret 0600 `~/src/fabrig/fleet/member.json` on the member before user
bootstrap. Pool declarations read that exact file for the matching member and
set `KACHE_LOCAL_ONLY=1`, including after release promotion and timer runs.

`down` marks draining, checks central claims and waits up to five minutes for
heavy's version-1 ledger (`~/src/rust/tmp/heavy/state.json`) to contain only
released tasks. The remote probe opens the existing host.lock read-only and
takes a shared lock; it creates or changes no heavy state. A busy lock waits;
missing, malformed, foreign-queue or unknown-version snapshots fail closed.
`--force` explicitly bypasses draining after an independent operator drain.
Partial bootstrap states do not receive work and can be removed without that
probe. Deletion is verified by GET returning 404; only then are the marked
key and only its exact recorded dedicated trust lines removed and the entry moved to `retired`.
A partial cleanup remains `deleting` and can be retried. Already retired names
are idempotent. Claims on members are not assigned by current consumers; their
adoption of the ready-only `hosts --json` feed is later work.

`list --json` emits `{members: {NAME: RECORD}, retired: [...], next: N}`;
`hosts --json` emits `{hosts: {NAME: {hostname, ssh, roles, ...}}}`, merging
fixed declarations and ready pool members. Dry runs read configuration and the
registry, plus shared-source metadata: no API, SSH, credential contents, locks or writes. `max_members` counts all
unretired entries, including incomplete ones. Other limits are reserved.

Configuration is `fleet/pool.toml`; tests inject a loopback API URL there.
HTTPS is required otherwise; redirects and proxy environment settings are
disabled. The token is read exclusively from its owned 0600 file for the
Authorization header. API bodies and subprocess output are never printed on
failure. Registry mutation holds a flock across each operation, serializing
allocation/deletion/cleanup, and uses fsynced sibling renames. Readers see the
last complete state while another operation holds the lock; `list` skips
reconciliation when that lock is busy. SSH file edits use
a separate lock and preserve a `.fleet-scale.bak` backup. No real infrastructure
is contacted by tests.

Verification runs `fleet-sync --check --json` (exit zero, no failed/drift or
busy/held results), each pinned version command, `heavy --installed` and
`systemctl --user is-active fleet-sync.timer`. Exit 0 means success; exit 1
means failure with a recoverable registry state; argparse errors exit 2.

Member trust lives exclusively in `~/.ssh/known_hosts.d/fleet-scale` (0600).
First contact uses accept-new there; every subsequent scaler SSH call uses
StrictHostKeyChecking=yes and that UserKnownHostsFile, disables global
known-hosts/DNS fallback and host-key updates. The normal `~/.ssh/known_hosts`
is read only for already approved fixed-peer public keys and never edited.
Cleanup matches exact recorded lines with counts, preserving unrelated hashed
and multi-alias entries; it never runs ssh-keygen -R. First-contact baselines
are journaled so interruption before recording additions is recoverable.

Use `fleet-scale ssh NAME [CMD]` for operator access, or:
```
ssh -o UserKnownHostsFile=~/.ssh/known_hosts.d/fleet-scale \
    -o GlobalKnownHostsFile=/dev/null -o StrictHostKeyChecking=yes \
    -o IdentitiesOnly=yes -i ~/.ssh/fleet-scale free@IP
```

`up` resolves `network = "build"` (currently 12769319) and attaches it in the
create request. Debian 13 cloud-image DHCP brings up the private NIC;
bootstrap installs iproute2 for verification, with no additional network
service changes. Shared readiness requires the API-recorded private 10.80.0.x
address and a successful `timeout 5 bash -c 'exec 3<>/dev/tcp/10.80.0.13/3900'`.
The kache recipe documents no read-only remote status command; this TCP probe
tests store reachability without writing the cache. Local-only mode still
attaches the configured network but skips both network probes.
