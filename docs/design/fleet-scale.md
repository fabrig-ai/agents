# Fleet scale

2026-10-30. Owner: s/deploy. Code: `tools/fleet-scale/`,
`fleet/pool.toml`, `fleet/units/mirror.*`. Decisions: director 0012 (elastic
builders), 0015 (agent login pool). Code departures:
`docs/design/fleet-scale.status.md`.

## 1. In one page

- **Builders come and go through one tool.** `fleet-scale up` creates a
  Hetzner server from the pool template, bootstraps it with the fleet's own
  bootstrap, and registers it. `fleet-scale down` drains it, deregisters it,
  deletes the server and verifies the deletion.
- **A pool member is declared by its template, not by a commit.** The fixed
  hosts stay in `fleet/hosts.toml`. Pool members live in a central runtime
  registry on hel8, and each member converges as its template says.
- **Nothing is copied that the user did not allow.** The Hetzner token is
  read only to send the API header. The kache store credential is copied from
  hel8 at bootstrap (user, 10-30). Agent logins come from the login pool
  (section 6). New hosts fetch code from hel8's read-only mirrors, not from
  GitHub.
- **The first `up` and `down` are the rebuild proof.** They prove that
  `fleet/bootstrap` turns a fresh Debian 13 server into a converged fleet
  member, and that removing one leaves nothing behind.
- **Limits and automatic decisions come later.** This pass gives the
  capability. The user sets caps once the design exists; a `decide` timer
  follows (section 7).

## 2. Declarations

Roll out parser support first, without pool declarations/helper assets. Wait
until every fixed host reports that release before landing those inputs and
the mirror units: the previous runner parses candidate fleet assets before exec.

**`fleet/pool.toml`** holds:
- the template: server type (cpx42), image (debian-13), location (hel1), roles
  (builder), machine_env and env, exactly like a hosts.toml entry;
- the name prefix (`pool`), the Hetzner SSH key name, the API base,
  and `network = "build"` (currently id 12769319, 10.80.0.0/16,
  subnet 10.80.0.0/24);
- separate `kache_source = "~/.config/fleet-scale/kache-store.env"` on hel8
  and `kache_destination = "~/.config/kache/store.env"` on the member;
- `[limits]`, empty until the user sets them: `max_members`,
  `min_members`, `idle_minutes`, and a monthly cap. `up` refuses beyond
  `max_members` once it is set.

**Central registry** `~/src/fabrig/fleet/members.json` on hel8, locked like
claims. Each member records its name (`pool-N`), Hetzner id, IPv4, ssh target,
host key fingerprint, exact added trust lines, template revision, state
(`creating-unresolved`, `creating`, `bootstrapping`,
`ready`, `draining`, `deleting`) and times. Only fleet-scale writes it.

**One reader** for consumers: `fleet-scale hosts --json` prints fixed hosts
plus ready members with roles and ssh targets. Post's machines, slots and
heavy's pool adopt it through their owners; until then a member is usable by
ssh but receives no work (section 5).

## 3. `up`

1. **Name and lock.** Unless `--local-only-kache` is explicit, require the
   exact declared owned 0600 source before creating anything; never search for
   or derive another source. Take the registry lock, pick the next `pool-N`, record
   `creating`. Before allocating a name, scan all pool-labelled servers and
   refuse if orphans exist unless `--ignore-orphans` is explicit. Dry runs
   perform no API calls and cannot prove orphan absence.
2. **Create.** Resolve the configured network name to exactly one id and POST
   the server with `networks: [id]`, the template, the fleet SSH key, and
   labels `fleet=pool`, `member=pool-N`. Before POST, durably record the request
   time and `creating-unresolved`. A confirmed id moves it to `creating`;
   record public IPv4 and the attached network's private IPv4.
3. **First contact.** Wait for SSH using accept-new against only hel8's dedicated
   0600 `~/.ssh/known_hosts.d/fleet-scale`. Keep its fingerprint and exact
   added lines in the registry. All later member and seed SSH uses that file
   with strict checking, no global known-hosts fallback or DNS host-key trust.
   Fixed-peer public trust is imported read-only from normal known_hosts;
   that file is never modified.
4. **Bootstrap.** Copy `fleet/bootstrap` at the deployed release, run
   `root.sh --host pool-N` as root and `user.sh --host pool-N` as the user.
   The member's declaration comes from the template; repository origins point
   at hel8's mirrors (`~/src/fabrig/mirror/{agents,fabrig}.git`) through a
   per-member git-only SSH key on hel8 (`restrict,command=".../mirror-serve"`).
   Peer-seeded tools are relayed by the controller using its existing trusted
   seed access; only allowlisted artifacts are transferred and verified against
   fleet pins both before transfer and on the member. Members need no general
   SSH authorization on a seed. Pool host/origin resolution is also used by
   fleet-sync after release promotion.
5. **Credentials.** Stream the kache source to the separate member destination
   (parent 0700, file 0600), after provisioning, and compare both SHA256s without
   loading the source into memory. The shared-store template omits hetzner3's
   `KACHE_LOCAL_ONLY=1`; retain its 40 GiB cap, 40 GiB floor and three build slots.
   Initialize remote selectors and the EnvironmentFile drop-in, then restart
   only this newly provisioned member's cache. `--local-only-kache` skips this
   delivery/setup and sets `KACHE_LOCAL_ONLY=1` through a non-secret per-member
   `~/src/fabrig/fleet/member.json`, read by pool declaration resolution after
   promotion. Agent logins remain section 6, outside the scaling implementation.
6. **Verify.** On the member: `fleet-sync --check` exits 0 (warnings only),
   the pinned tool versions answer, heavy reports installed, the fleet-sync
   timer is active. Shared-cache members must also have the API-recorded
   10.80.0.x address on a non-loopback interface and pass a five-second bash
   `/dev/tcp/10.80.0.13/3900` connect. The pinned kache recipe documents no
   read-only remote status command; TCP is the reachability check.
   `--local-only-kache` skips these network probes. Record `ready`.

Any failure stops at the failing step with the member left in its state;
`down` cleans up a member in any state, subject to uncertain-create
reconciliation below. Debian 13 cloud-image DHCP configures the attached NIC;
bootstrap adds iproute2 for verification and needs no extra network service
configuration. A missing address or route prevents shared readiness.

## 4. `down` and reconciliation

1. **Resolve uncertain creates.** Without an id, `down` and `list` query
   both labels, retrying for ten seconds. Exactly one match records its id;
   multiple matches refuse. Empty results never establish permanent absence:
   the member stays `creating-unresolved`, regardless of elapsed time.
   Normal down cannot retire it until a matching server is found and deleted.
   `list` flags unresolved entries and records reconciliation errors; if the
   registry is busy it shows the last complete snapshot without waiting for
   that lock, while still performing the orphan scan below.
2. **Explicit forget.** `down NAME --forget` may retire an unresolved create
   without a recorded id. It prints a warning that deletion is unconfirmed and
   a server may still appear or incur charges. It removes the member's marked
   authorization and exact trust lines and records `forgotten: true` in the
   retired entry; it does not contact or delete a server. It cannot be combined
   with `--force` and is refused for confirmed ids.
3. **Drain.** Record `draining`. No new claims (the slots tool skips draining
   members once adopted). Wait for its claims and heavy jobs to end, with a
   five-minute bound; `--force` explicitly bypasses only this drain.
   Heavy's version-1 atomic snapshot, under a shared read-only host lock,
   must show every task released. Missing/unknown snapshots fail closed.
   Partial builders without ready_at have no work and skip this probe.
4. **Return logins** to the pool (section 6, later).
5. **Delete.** With a recorded id, GET only that id, require both exact pool
   labels and DELETE only it. Never expand this set through label search.
   A mismatching label refuses even under --force. Confirm absence by GET.
6. **Deregister.** After confirmed deletion, remove its marked git key and
   exact recorded lines from the dedicated trust file, preserving unrelated,
   hashed and multi-alias entries. Keep the member in `retired` with times.
   Interrupted deletion stays tracked; retries of retired names are idempotent.

**Orphan reconciliation.** `fleet-scale reconcile` scans every server labelled
`fleet=pool`. A server whose `member` label is not an active registry entry
is an orphan, including unknown, retired and explicitly forgotten members.
This scan also recovers late servers whose entries were retired by older code.
Active unresolved entries that become visible remain tracked, resolve through
`list` or `down`, and are deleted by normal down.

The command reports orphan ids/member labels without changing registry or
servers. `reconcile --delete-orphans` holds the registry operation lock,
GETs each reported id again and requires `fleet=pool` and the exact scanned
member label before DELETE, then confirms absence. Missing member labels are
reported but refuse deletion. Servers without `fleet=pool` are never reported
or deleted. Failed queries and failed deletion remain errors, never proof of
absence; the next full scan finds surviving or late servers again.

`list` always performs this read-only full scan and prints `ORPHAN` records
prominently, including when member-state reconciliation skips a busy lock.
`list --json` adds an `orphans: [{id, member}]` array without persisting it.
Real `up` scans under the operation lock before allocating and refuses while
orphans exist, unless `--ignore-orphans` is explicit. The override reports the
orphans and still fails on API errors. Dry-run up retains its no-API contract.

## 5. Mirrors and access

**hel8 serves two bare mirrors,** refreshed every minute by `mirror.timer`
(session role): agents and fabrig from GitHub. Members fetch only; mirrors
use a forced `mirror-serve` command with `restrict`. It parses
SSH_ORIGINAL_COMMAND with shlex, without a shell, and execs only
`git-upload-pack` for exactly `~/src/fabrig/mirror/{agents,fabrig}.git`.
Other commands, extra arguments, parent traversal and symlink paths refuse
with exit 1. Pre-receive hooks remain additional protection. Members have no
GitHub credential. The forced helper is in the deployed current release.

**Pushing from members** is out of scope in this pass: members run builds,
gates and tier work that produce no branches. Implementer slots on members
need a push path; that is a later design with the login pool.

**hel8's fleet SSH key** (`~/.ssh/fleet-scale`, created by fleet-scale on
first use, 0600, registered in the Hetzner project by its public half) is
used for member bootstrap and subsequent controller/operator access.
`fleet-scale ssh NAME [CMD]` resolves the recorded address and applies strict
dedicated trust and identity options. Direct operator access uses
`ssh -o StrictHostKeyChecking=yes -o UserKnownHostsFile=~/.ssh/known_hosts.d/fleet-scale
-o GlobalKnownHostsFile=/dev/null -o IdentitiesOnly=yes -i ~/.ssh/fleet-scale free@IP`.
No agent reads the private key.

## 6. Agent login pool (decisions 0015, 0017)

**Custody, not use.** Claude and Codex credentials rest on a shelf on hel8
(`~/src/fabrig/logins/pool/`), one entry per login. A machine uses its own
credential file; nothing ever uses a shelf entry in place. The custody tool
(`agent-logins`, `docs/design/logins.md`) moves files by streaming and sha256
checks, never reading or printing them. Signing in is the user's.

**Copy back on release** (the user, 10-30). Each machine's existing logins are
captured as entries bound to it; while bound or lent, an entry is only a
placeholder and may go stale. When a machine is done with a login (release,
swap, retire, `down`), the tool copies the machine's current credential back
over the entry, verifies it, removes it from the machine and marks the entry
free. Only free entries are lent; lending copies the entry to the machine.

**Operations:** `capture HOST`, `release HOST KIND`, `lend ID HOST`, `swap`
(when a weekly limit approaches, on the director's request), and supply at
`up` / copy back at `down`. About ten logins per subscription, signed in by the
user on the shelf (`prepare`, then `register`).

## 7. Later

- `fleet-scale decide`: scale signals (all slots held, heavy wait, starved
  runs, idle), user limits, dry-run proposals to ops for a day, then live.
- Consumers adopt `fleet-scale hosts`: post machines, slots, heavy's pool.
- A push path for implementer slots on members.
- Per-slot disk containment (XFS project quotas) is in the template's root
  bootstrap once ops adopts it.
