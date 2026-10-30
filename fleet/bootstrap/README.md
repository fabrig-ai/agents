# Rebuild a fleet member (Debian 13 amd64)

Target: hetzner2 / debian-16gb-hel1-2, drained gate2. See [inventory](inventory.md)
for the read-only 2026-10-29 survey and the state that a wipe would destroy.
The sequence is USER preparation, **one root script**, **one user script**,
then fleet-sync and heavy. Commands below are a future operator procedure;
the bootstrap task does not execute machine changes or the acceptance builds.

The six native tool installers use pinned peer artifacts; no upstream URL is
needed. See [seed provenance](../seeds/README.md) for peer comparisons.
Chromium uses h3's canonical tree; hel8 is excluded as its seed and only gets
a version warning for its own differing copy. Main supplies the new QA/login
and landing tools; legacy post/fleet workflows still need their own migration
and acceptance before readmission.

## USER preparation (in order)

1. **USER — retain state before wiping.** Confirm the drain with the
   coordinator and complete the Wipe losses checklist below. Keep credentials
   in the user's private custody process, never git. Land reviewed changes
   through tools/land after the gate passes (this task pushes a branch only).
   Record any peer disagreement rather than choosing a reachable copy blindly.

2. **USER — rebuild the VM.** Reinstall Debian 13 amd64 using Hetzner's image,
   retaining the intended fleet IP/name and keeping it drained. Do not restore
   old queue/lease/slot files piecemeal. There is no second-prover activation in
   this procedure; ops decides how retained evidence is reconciled.

3. **USER — establish root SSH access.** Through the Hetzner console print
   `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`; approve the new host key
   on the admin machine before SSH (stage its existing known_hosts to a sibling,
   run `ssh-keygen -R 2.29.101.185 -f SIBLING`, append the console-approved
   public host key, then rename the sibling over known_hosts).
   The bootstrap does not relax host checking
   or change sshd settings. The Debian image must have Python 3.13 (if absent,
   install python3 using apt in the console before running root.sh).

4. **USER — supply the public authorized key for free.** Put the intended
   user's SSH **public** key in root's authorized_keys through the trusted
   admin/console path. root.sh copies it only when free's authorized_keys is
   absent; existing authorization is retained. Private keys never enter this
   checkout. From a trusted admin checkout at the reviewed/landed revision:

   ```sh
   git archive HEAD fleet | ssh root@2.29.101.185 'mkdir -p /root/bootstrap && tar -x -C /root/bootstrap'
   ssh root@2.29.101.185 'bash /root/bootstrap/fleet/bootstrap/root.sh --host hetzner2'
   ```

   root.sh installs packages, sets the declared hostname, creates free, grants
   the surveyed passwordless sudo, enables linger and unattended upgrades with
   automatic reboot explicitly false, and writes Debian's surveyed core limits.
   No swap/custom sysctl was found. It never edits a running script in place.
   Preview without root or machine reads/writes: `bash fleet/bootstrap/root.sh --dry-run`.

5. **USER — give the new host GitHub access.** As free create or privately
   restore an SSH identity; add its public key to GitHub with access to both
   fabrig-ai/agents and fabrig-ai/fabrig. Approve GitHub's host key using GitHub's
   published fingerprints through a trusted source. Verify access with
   `git ls-remote git@github.com:fabrig-ai/agents.git HEAD` and the fabrig origin.
   Set desired global git identity; today it is Free Ekanayaka / freee@debian.org.
   The legacy rewrite preferences are recorded in inventory, not imposed.

6. **USER — exchange host keys and authorize fleet SSH.** Approve the new
   host's public identity for normal free@peer SSH as needed by its role.
   Every fleet host's trust must include the replacement h2 key, and h2 must
   trust all peers. Use existing trusted admin SSH to print peer fingerprints:
   `ssh free@IP 'ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub'`.
   The IPs are hel8 204.168.210.29, h2 2.29.101.185, h3 2.29.124.199,
   h6 2.29.120.8, h7 62.238.103.124, h8 2.29.110.236.
   On the trusted admin machine, collect the replacement's public host key:

   ```sh
   ssh-keyscan -t ed25519 2.29.101.185 > /tmp/hetzner2.hostkey
   ssh-keygen -lf /tmp/hetzner2.hostkey
   # USER: compare with the console fingerprint above, approve before continuing.
   # Install the approved key on EACH peer (hel8, h3, h6, h7, h8):
   for peer in 204.168.210.29 2.29.124.199 2.29.120.8 62.238.103.124 2.29.110.236; do
     scp /tmp/hetzner2.hostkey "free@$peer:.ssh/.hetzner2.approved"
     ssh "free@$peer" 'set -eu; cd "$HOME/.ssh"; umask 077
       cp known_hosts .known_hosts.bootstrap
       ssh-keygen -R 2.29.101.185 -f .known_hosts.bootstrap
       cat .hetzner2.approved >> .known_hosts.bootstrap
       mv -f .known_hosts.bootstrap known_hosts
       rm -f .hetzner2.approved .known_hosts.bootstrap.old'
   done
   ```

   For h2's outgoing trust, scan each peer IP into a separate admin-side file,
   print its fingerprint and compare with the trusted peer command above, then
   combine the **approved** files and approved GitHub key as /tmp/h2.known_hosts.
   Install that approved file on h2:

   ```sh
   scp /tmp/h2.known_hosts free@2.29.101.185:.ssh/.known_hosts.bootstrap
   ssh free@2.29.101.185 'chmod 600 "$HOME/.ssh/.known_hosts.bootstrap"; mv -f "$HOME/.ssh/.known_hosts.bootstrap" "$HOME/.ssh/known_hosts"'
   ```

   On a rerun, preserve unrelated trusted entries when
   preparing that file. Never install unverified ssh-keyscan output.
   For normal SSH verify `ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes
   -o UpdateHostKeys=no free@IP true` in each needed direction.
   Legacy post uses a separate post_ed25519 identity and restricted `deliver`
   authorization; these are not recreated or read by bootstrap (see inventory).

   **USER — authorize temporary seed access before user.sh.** The new host's
   SSH public key must be in free's authorized_keys on at least one eligible
   seed host: h3 (2.29.124.199) or hel8 (204.168.210.29). h3 is needed for the
   pinned nextest, Codex and Chromium trees today; hel8 has nextest 0.9.137 and no
   pinned standalone Codex tree. Using existing trusted admin access, add the
   new public key as its own authorized_keys line, with a distinctive comment
   such as bootstrap-hetzner2. Preserve existing lines, use a sibling file,
   chmod 600 and rename it over authorized_keys. Never copy private keys.
   The new host must also trust that seed's console-verified host key. Verify
   from the new host:

   ```sh
   ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes -o UpdateHostKeys=no free@2.29.124.199 true
   ```

   If this grant is unwanted afterwards, **USER removes exactly that public-key
   line** through trusted admin access, again staging a sibling and renaming;
   retain unrelated authorization. Remove it after provisioning and real
   acceptance, or retain it intentionally for later explicit repair runs.
   Removing the grant does not change artifact pins; matching hosts need no
   peer connection, but future missing/different artifacts need renewed access.

## Run the user script and convergence

From the same reviewed admin checkout, transfer the declarations/helper to free
and run as free (never with sudo); root's archive is not accessible to free:

```sh
git archive HEAD fleet | ssh free@2.29.101.185 'mkdir -p "$HOME/bootstrap" && tar -x -C "$HOME/bootstrap"'
ssh -t free@2.29.101.185 'bash -lc "bash ~/bootstrap/fleet/bootstrap/user.sh --host hetzner2"'
```

user.sh installs Rust's declared 1.95.0 components and targets (including wasm,
Darwin and musl), and nightly-2026-10-21. Debian supplies rustup; Rustup checks
component SHA256s and does not self-update. It creates/validates the dedicated
agents clone, creates empty working parents, runs
`fleet-sync --provision --host hetzner2` from that clone, then `fleet-sync`.
It never resets state or changes a dirty/foreign clone. Rerun safely after a
partial failure. Preview: `bash fleet/bootstrap/user.sh --dry-run --host hetzner2`.

`--provision` holds the fleet lock and checks exact bytes/modes for seeded
items, repairing missing/different artifacts from seed=true hosts over strict
SSH into private staging. It verifies every pinned file and tree member,
including symlinks/modes, before promoting a sibling and recreating links.
It never runs an unverified copy. Matching artifacts and links do nothing;
missing links alone are repaired without transfer. An incomplete/corrupt peer
archive leaves the installed artifact intact. URL is still optional with a
verified SHA256; tree downloads must also match their full manifest.

Rust components/targets are checked even if rustc's version matches. Kache is
built from exact source with vendored patches and checked musl SHA256, wrapper
disabled; its isolated build may take eight minutes. Kache provisioning runs
only when no binary, config, service, drop-in or cache footprint exists.
Normal convergence compares its config/unit as check-only via policy.toml;
it neither writes them nor adopts or activates the unit. Only the invocation
that successfully installs absent kache creates its local-only config/unit and
enables/starts it. Existing installations stay ops-owned even under --provision;
ops agrees any takeover host by host. Fleet never inspects store.env or changes
existing store/cache contents. Timer/check/preview never seed or provision.
Other normal convergence and fabrig installation follow the existing policy.

7. **USER — Claude login.** After its pinned binary is seeded, open a new
   free login shell, run `claude` and complete interactive authentication.
8. **USER — Codex login.** In that shell run `codex login` and complete
   authentication. Neither login is copied by scripts or stored in git.
9. **USER — initialize routing.** post/machines is deliberately check-only.
   On fresh h2 install this non-secret file by sibling rename:

   ```sh
   mkdir -p "$HOME/src/rust/tmp/post"
   cat > "$HOME/src/rust/tmp/post/.machines.bootstrap" <<'ROUTES'
   hetzner2 local
   hel8 free@204.168.210.29
   hetzner3 free@2.29.124.199
   hetzner6 free@2.29.120.8
   hetzner7 free@62.238.103.124
   hetzner8 free@2.29.110.236
   ROUTES
   mv -f "$HOME/src/rust/tmp/post/.machines.bootstrap" "$HOME/src/rust/tmp/post/machines"
   ```

   On other hosts render their name as local and the other SSH targets from
   hosts.toml. Mailbox tools create new/cur/tmp/sent themselves; do not create
   fake messages, login holders or locks. A missing legacy post executable is
   a separate migration requirement, not repaired by a machines file.

In the free login shell, finish the explicit deployment and heavy installation:

```sh
fleet-sync --provision --host hetzner2
fleet-sync --host hetzner2
# Required for builder, gate and gate2 roles; heavy owns its units/state:
env -u DEV_ROOT -u DEV_TMP heavy --install-reconciler
heavy --check-recovery
```

No shared cache login is needed on h2 (KACHE_LOCAL_ONLY=1). If ops later restores
its private, user-owned 0600 ~/.config/kache/store.env, ops must also install the
non-secret remote selectors/drop-in and coordinate a drained-host restart.
Convergence only compares config/unit; it never inspects that credential or
changes an existing cache/store.

## Wipe losses — ops checklist

Tick each item only after preserving it off-host through a trusted private
backup process, or recording an explicit disposable decision. Verify backups
can be restored; do not reset live coordination state to make a wipe possible.

- [ ] **queue-worker clone** — preserve by an off-host archive including .git,
  unpushed objects and any unresolved worker marker; reconcile with ops.
- [ ] **ops/worker-smoke-* artifacts** — preserve by an off-host archive of the
  immutable attempts, logs and proof artifacts with the clone/generation.
- [ ] **heavy ledger and receipts** — preserve by a coherent, drained backup
  of tmp/heavy (ledger/events/receipts/logs/holds), then ops reconciliation.
- [ ] **post spool** — preserve by a drained archive of tmp/post, including
  new/cur/tmp/sent and routing, or disposable (ops decides after delivery review).
- [ ] **Codex sessions** — preserve by the user's private session/state backup,
  or disposable (ops decides); seed transfer never reads/copies this state.
- [ ] **slots and claims/leases** — preserve by a drained backup and ownership
  reconciliation with their tools, or disposable (ops decides after release).
- [ ] **private notes/ops/tasks and unpushed checkouts** — preserve by off-host
  archives or push non-secret work; disposable only by an explicit ops decision.
- [ ] **post_ed25519 delivery key and restricted authorization** — preserve by
  the user's encrypted key backup plus a private record of the matching
  restricted authorized_keys entries; restore/rotate together through ops.
- [ ] **kache store.env** — preserve by the user's private 0600 credential
  backup, or disposable (ops decides to remain local-only).
- [ ] **cache/build artifacts and other local runtime history** — disposable
  (ops decides); retain anything needed as proof before clearing storage.
- [ ] **interactive auth, SSH access/trust and global git preferences** —
  preserve by the user's private process or recreate via the USER steps above.

No unresolved worker marker/running prover was visible in bootstrap-1's survey;
that observation is not a quiescence proof. Bootstrap does not activate a second
prover or synthesize its evidence, credentials, messages, sessions or holds.

## Verification before readmission

10. **USER — accept and readmit only after the real checks succeed.** In a
    fresh free login shell:

    ```sh
    fleet-sync --check --host hetzner2
    systemctl --user is-active fleet-sync.timer kache.service
    systemctl --user list-timers '*reconcile*' --no-pager
    heavy --check-recovery
    # A real compiler/linker/wrapper build, from fabrig installed by fleet-sync:
    cd "$HOME/src/fabrig/main"
    heavy -- cargo build --locked --workspace
    # Real authenticated model execution, inside that trusted repository:
    codex exec 'Reply with BOOTSTRAP_OK. Do not modify files or run commands.'
    ```

    Require a green check with no drift/failed items, all pinned versions present,
    no outstanding manual/version warnings, active timers/cache/recovery, a
    successful real build and authenticated Codex response. Keep the host drained
    if any fail. An exit 0 with warnings, a fixture test or only --version is
    insufficient. For role work using post/codex-run/legacy gates, also validate
    its separately migrated messaging and retained prover state with ops before
    readmitting; this repository does not claim that proof from read-only survey.

Roll out in two separate landings through tools/land. Land the code-only
stage A first, leaving main's fleet declarations unchanged. Wait until timers
on all six hosts report stage A's release (or a later descendant). Only then
land stage B's bootstrap declarations/assets. Stage A's parser accepts stage B,
and each timer validates, promotes and executes it automatically; no manual
runner invocation is needed. Never publish both stages to main together.
Normal runs do not provision new tools or take over kache. Fresh-host
provisioning is a separate explicit operator action; existing kache takeover
requires host-by-host agreement. Reverts also go through tools/land; preserve
parser compatibility and keep private logins and operational evidence intact.

## XFS project quota proposal: full occupancy, ops review first

`pquota` is a Python 3.13 stdlib root tool. No host is opted in. This is an
operator procedure for review; this task authorizes **no live prepare, reboot,
rollback or quota operation**. It enables XFS accounting; project roots, limits,
write containment and admission budgets are separate work. Keep existing floors.

### Choose and drain a host

Ops chooses the **first fully drainable builder**, likely **h6 after QA's
producer and upgrade claims are released**, then the remaining builders. **H8
is last**, under a legitimate queue-rollout drain. Firm times come from ops after
reviewing the script, owner approvals, claims and heavy proof. Retain the >=2h
soak with quota, heavy and slot checks green before the next host; any failure
rolls back that host and stops the rollout. Never reboot hosts together.

Stop all claim and non-claim producers and drain their submitters/children,
including QA, codex-run, after-landing and queue paths. Keep heavy's reconciler
running until releases and scopes have drained. A stopped submitter or a
released claim alone does not prove its children have ended. The helper checks
heavy's installed atomic v1 ledger (every task released), no heavy payload or
wrapper user units, no heavy submitter/wrapper processes, and no active
`codex-run-*`, `after-landing*` or retained legacy `agents-after-landing*` units.
It never reconciles, stops services, or changes heavy's state. Reads run as free.
Inventory any non-default heavy queues separately: this tool reads the documented
`~/src/rust/tmp/heavy/state.json` queue and the canonical fabrig heavy entrypoint.

Start with the default **read-only** plan:

```sh
sudo python3 -I fleet/bootstrap/pquota plan --host hetzner6
```

It prints current boot/mount/quota state, safe source/environment summaries,
start-once service states, every host slot's occupancy/share and missing proof,
and the exact central inventory SHA256. It makes no local state/backup, GRUB,
service, quota or reboot changes. Strict SSH is retained; it uses hel8 at
`free@204.168.210.29` by default (`--central` selects another trusted route).

### Occupy every central slot; never force-release a claim

The installed central claim tool has claim/release/list, without JSON or a
host-disable API. The helper runs it via SSH as free, resolves its installed
path and reads its adjacent `tools/slots/hosts`, as documented in slots design
section 3. It reads declaration/list/declaration and refuses a changed read.
`--inventory-digest` is **SHA256 of that entire declaration's exact bytes**:
all host slot pools AND all shares are pinned, including slots added later.
The listing must cover precisely those configured pairs and shares. An empty or
unreadable whole inventory refuses. H8 currently has no eligible claim slots:
with the entire declaration pinned, the claim CLI rejects every h8 acquisition.
That closed admission domain is recorded explicitly; adding any slot changes
the digest and refuses. It does not replace h8's separate queue-rollout drain.

For every host slot, ops either places its exact maintenance claim or retains an
approved stopped-service claim. A free slot, foreign claim, wrong WHAT, changed
inventory or unreadable authority refuses. The tool **never claims or releases**.
Ops first agrees any lending with the share owner, then uses the authority:

```sh
ssh free@204.168.210.29 'claim claim hetzner6 1 ops "pquota maintenance REVIEW-REF" --lent-by s/qa'
# Repeat for EVERY configured slot; pool slots need no --lent-by.
```

The lending argument must match the actual inventory share, with its owner's
agreement. Use a unique maintenance WHAT for this maintenance lifetime. Claims
are central, have no expiry, and survive a builder reboot. Keep them all held
through post-boot verification and owner readmission. Pin the printed digest:

```sh
sudo python3 -I fleet/bootstrap/pquota plan --host hetzner6 \
  --inventory-digest SHA256 --maintenance-owner ops \
  --maintenance-what 'pquota maintenance REVIEW-REF'
```

### Retaining a long-lived claim requires a bound approval

H7:4's `ops` / `after-landing 20261029T1846Z` claim persists by design. Never
force-release it. Its claim owner and service approver may differ. Retain it
only with an actual approval from the named tool owner (s/dynamic-memory here):

```sh
--retained-claim 4:ops:s/dynamic-memory:APPROVAL_POST_ID \
--approval-file APPROVAL_POST_ID:/home/free/APPROVAL_POST_ID.md \
--retained-service 4:after-landing.service
```

All three options are repeatable for distinct slots/posts. Use an explicit
regular `.md` post file readable by free, copied through the trusted post
workflow if necessary. This fallback avoids consuming messages with `post read`;
the installed tooling has no documented non-consuming metadata read API.
Do not scan mailboxes or supply credentials. An arbitrary caller's reference is
insufficient. The original post must contain exactly one Id/From header and
these structured body lines (the service line binds the stopped service):

```text
Id: APPROVAL_POST_ID
From: s/dynamic-memory@hel8
To: ops@hel8

slot: hetzner7:4
what: after-landing 20261029T1846Z
service: after-landing.service
plan: preserve the owner's existing state and restart once after verified readmission
```

The From identity must match APPROVER, not merely the caller; the claim's owner
must match CLAIM_OWNER, and slot/WHAT must match the live central record. The
plan must describe preservation and restart. The declared service must be loaded
and **inactive**, after its owner has drained its children. Sender, post ID,
content hash, plan, service, owner, WHAT and claim creation time are bound into
state.json. File provenance is the operator's trusted-post responsibility;
From-line validation is not a cryptographic signature. Changing the claim's
incarnation or approval after prepare refuses even if the owner/WHAT look alike.

Alternatively, the claim owner deliberately releases its own exact claim under
the producer freeze, ops immediately occupies that slot with maintenance custody,
and the original owner deliberately reclaims only after successful verification
and ops' release. Coordinate any brief vacancy: no new producers are enabled.
Do not synthesize an owner release or discard the service's durable state.

### Prepare and choose the reboot moment

After producer freeze, full occupancy and drainage, ops creates a root-owned,
non-group/world-writable marker (the script never creates it):

```sh
sudo install -d -m 700 /var/lib/fabrig-pquota
printf '%s\n' 'hetzner6 ops: all producers stopped; heavy drained; approvals REVIEW-REF' |
  sudo tee /var/lib/fabrig-pquota/fence >/dev/null
sudo chmod 600 /var/lib/fabrig-pquota/fence
sudo python3 -I fleet/bootstrap/pquota prepare --yes --host hetzner6 \
  --inventory-digest SHA256 --maintenance-owner ops \
  --maintenance-what 'pquota maintenance REVIEW-REF'
# Include retained-claim/file/service arguments when applicable.
# Review state.json and original/ before choosing the moment:
sudo python3 -I fleet/bootstrap/pquota reboot --yes --host hetzner6
```

Prepare records sources (fabrig main HEAD, agents `current` release path and
start-once declaration hashes, all six installed heavy runtime-file digests),
boot ID, each start-once unit's actual pre-boot state and owner restart list,
and only allowlisted non-secret machine.env key/value pairs. Submitter inspection reads only bounded executable/action metadata; it never
reads payload arguments or process environments, and records no credentials. Reboot/verify require
sources and environment unchanged; arrange fleet pinning/deployment freezes
with ops rather than accepting a new release mid-maintenance. Owners retain the
plan's active-service list before drainage; retained stopped services remain in
the restart list even though they are inactive in the immediate pre-boot proof.

Unknown/conflicting boot input refuses: any existing rootflags in either kernel
command-line variable or another GRUB drop-in, dynamic command-line expansion,
unknown drop-in shell code, another fstab quota option, an unidentified default,
multiple fstab root rows or multiple `root=` arguments on the default Linux line.
Ordinary recovery/kernel menu entries remain valid when the numeric top-level
default is unambiguous. Saved/one-shot/submenu defaults refuse. Existing kernel
options must survive `update-grub` unchanged. The only added input is exactly:

```sh
GRUB_CMDLINE_LINUX="$GRUB_CMDLINE_LINUX rootflags=pquota"
```

at `/etc/default/grub.d/90-fabrig-pquota.cfg`. Before this change, a private,
atomic, **write-once** `/var/lib/fabrig-pquota/original/` stores the original
`/etc/default/grub`, all GRUB drop-ins, fstab, generated grub.cfg and binary
grubenv, with digests/modes/ownership in a manifest. Retries validate and never
replace this backup. A changed/corrupt original or incomplete transaction
refuses for investigation. Prepared retries preserve original evidence.

Prepare and reboot recheck the full fence immediately. The stored policy is
used by reboot/verify; supplied overrides must match it, as must the central
route. Reboot also proves the same boot/config and claim incarnations as prepare.
The marker is extra ops evidence: **full central occupancy**, rather than zero
claims plus a marker, prevents ordinary claim acquisition. Inventory must stay
pinned and every claim holder must honor the maintenance lifetime. Non-claim
writers still require the independent producer freeze and drainage proof.

### Verify, then owners restart once

```sh
sudo python3 -I fleet/bootstrap/pquota verify --host hetzner6
```

**Verify is no longer read-only.** It first checks new boot ID, cmdline pquota,
XFS prjquota, project accounting AND enforcement, unchanged installed sources
and environment, fleet-sync.timer, and the complete unchanged maintenance and
retained occupancy/drainage proof. Failure skips all quota mutation. Unlike the
old zero-claim proposal, no unsupported claim-history assertion blocks a valid
occupancy proof; release/recreate of a pinned claim is detected by creation time.

Only after every prerequisite passes, it creates a private scratch directory
under `/var/lib/fabrig-pquota/probe`, chooses an unused numeric project from the
kernel's project-quota report, sets it with `project -s -p DIR ID`, and applies
a **1 MiB hard cap**. A helper drops to free before creating a subdirectory and
attempting at most **2 MiB**. Linux FS_IOC_FSGETXATTR must show the same project
and project-inherit flag on both directories, and the write must fail with
**EDQUOT** (success, ENOSPC, or any other error fails). The tool clears the
project assignment and limit and removes the scratch tree in a finally path.
Freeze other quota administration during this bounded probe. Partial cleanup
fails verification and preserves the path for explicit ops reconciliation.
Verification checks and the probe receipt are recorded in state.json. No probe
runs under plan, prepare or reboot, and no service is started by the helper.

Before the reboot, owners stop and **disable** the relevant enabled services and
their triggers, preserving and recording prior enablement and application state.
Stopping an enabled WantedBy=default.target unit once does not prevent it from
autostarting at boot. Coordinate a fleet convergence hold so it cannot re-enable
those services; keep fleet-sync.timer itself active for the post-boot check.
The helper records UnitFileState but never changes enablement or convergence
controls. Owners retain the pre-drain plan's active-service list as well as the
immediate pre-boot state, then restore the agreed enablement and restart their
listed start-once services **once**, preserving their existing state, claims and
recovery evidence, after ops accepts the quota proof.
Fleet-sync does not restart an existing start-once service for its owner.
For **h8**, the current transient queue wrapper is **not durable across boot**:
ops owns the normal16 official queue restart, the **authority lock and checkout
lock**, and their preserved queue/claim/checkout identities. Do not replace that
with an ad-hoc wrapper, reset the queue, or synthesize lock evidence. These are
ops' steps under a legitimate queue-rollout drain, not actions of this helper.
Readmit and release maintenance claims only after verify and the owner/slot
checks pass. Retained claims remain with their existing owners.

### Rollback and console rescue

Keep the host drained and claims held:

```sh
sudo python3 -I fleet/bootstrap/pquota rollback --yes --host hetzner6
sudo python3 -I fleet/bootstrap/pquota reboot --yes --host hetzner6
```

Rollback validates the write-once backup, restores original files, removes only
the exact owned new drop-in, runs update-grub, then restores the exact original
generated bytes and verifies **every original digest** and selected default.
Unexpected new drop-ins or a foreign pquota file refuse. It does not reboot or
disable accounting on the running mount. The subsequent reboot retains the
same occupancy/source/writer fence. After boot, ops proves pquota absent, quota
accounting off, changed boot ID and intact services/claims before readmission.
A missing/corrupt backup requires console/operator investigation, not guessing.

Out-of-band rescue: Hetzner console, GRUB `e`, delete `rootflags=pquota` from
the Linux line, then Ctrl-X/F10 to boot. Keep producers stopped, then rollback
from the validated backup. Initial accounting may scan ~1.4 million inodes;
allow a maintenance window and console access. XFS cannot enable accounting
through remount.

### Bootstrap and landing order

Land the parser compatibility commit first and wait for it fleet-wide before
the asset/bootstrap changes; do not squash those stages. All host flags remain
off. A reviewed `pquota = true` host table entry opts a **fresh** XFS host into
root bootstrap. `root.sh` delegates to `bootstrap.py root`; it shares boot safety
and write-once backups with pquota and writes the same drop-in atomically.
False changes no quota boot input. A new host needs one drained reboot and
manual acceptance after root bootstrap; fleet-scale will add orchestration
later. Existing hosts use the full fenced prepare/reboot/verify procedure.
