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
- the name prefix (`pool`), the Hetzner SSH key name, and the API base;
- `[limits]`, empty until the user sets them: `max_members`,
  `min_members`, `idle_minutes`, and a monthly cap. `up` refuses beyond
  `max_members` once it is set.

**Central registry** `~/src/fabrig/fleet/members.json` on hel8, locked like
claims. Each member records its name (`pool-N`), Hetzner id, IPv4, ssh target,
host key fingerprint, template revision, state (`creating`, `bootstrapping`,
`ready`, `draining`, `deleting`) and times. Only fleet-scale writes it.

**One reader** for consumers: `fleet-scale hosts --json` prints fixed hosts
plus ready members with roles and ssh targets. Post's machines, slots and
heavy's pool adopt it through their owners; until then a member is usable by
ssh but receives no work (section 5).

## 3. `up`

1. **Name and lock.** Take the registry lock, pick the next `pool-N`, record
   `creating`.
2. **Create.** POST the server with the template, the fleet SSH key, and
   labels `fleet=pool`, `member=pool-N`. Record the id and IPv4.
3. **First contact.** Wait for SSH, record the host key fingerprint on first
   connection into hel8's known_hosts (trust on first use, immediately after
   creation; the fingerprint is kept in the registry).
4. **Bootstrap.** Copy `fleet/bootstrap` at the deployed release, run
   `root.sh --host pool-N` as root and `user.sh --host pool-N` as the user.
   The member's declaration comes from the template; repository origins point
   at hel8's mirrors (`~/src/fabrig/mirror/{agents,fabrig}.git`) through a
   per-member git-only SSH key on hel8 (`restrict,command="git-shell -c ..."`).
   Peer-seeded tools are relayed by the controller using its existing trusted
   seed access; only allowlisted artifacts are transferred and verified against
   fleet pins both before transfer and on the member. Members need no general
   SSH authorization on a seed. Pool host/origin resolution is also used by
   fleet-sync after release promotion.
5. **Credentials.** Copy the kache store credential file from hel8's 0600 path
   to the member's 0600 path. Assign agent logins from the pool (section 6).
6. **Verify.** On the member: `fleet-sync --check` exits 0 (warnings only),
   the pinned tool versions answer, heavy reports installed, the fleet-sync
   timer is active. Record `ready`.

Any failure stops at the failing step with the member left in its state;
`down` removes a member in any state.

## 4. `down`

1. **Drain.** Record `draining`. No new claims (the slots tool skips draining
   members once adopted). Wait for its claims and heavy jobs to end, with a
   five-minute bound; `--force` is the user's or ops' explicit call. Heavy's
   version-1 atomic snapshot, under a shared read-only host lock, must show
   every task released. Missing/unknown snapshots fail closed; no heavy state
   is created or reconciled by the drain probe.
2. **Return logins** to the pool (section 6).
3. **Deregister.** Remove its git-only key from hel8, its known_hosts line, and
   its registry entry (kept in a `retired` list with times).
4. **Delete** the server by id and verify the API reports it gone.

## 5. Mirrors and access

**hel8 serves two bare mirrors,** refreshed every minute by `mirror.timer`
(session role): agents and fabrig from GitHub. Members fetch only; mirrors
reject receive-pack ref updates through a pre-receive hook, since git-shell alone also permits receive-pack. They have
no GitHub credential. A member's key on hel8 runs git-shell only.

**Pushing from members** is out of scope in this pass: members run builds,
gates and tier work that produce no branches. Implementer slots on members
need a push path; that is a later design with the login pool.

**hel8's fleet SSH key** (`~/.ssh/fleet-scale`, created by fleet-scale on
first use, 0600, registered in the Hetzner project by its public half) is
used only for root bootstrap of new members. No agent reads it.

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
