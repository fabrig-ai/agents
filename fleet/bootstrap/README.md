# Rebuild a fleet member (Debian 13 amd64)

Elastic `pool-N` builders use [fleet-scale](../../tools/fleet-scale/fleet-scale.md)
and `fleet/pool.toml` instead of the fixed-host manual steps below. The scaler
stages the reviewed release, supplies only the fleet public key to root/free,
creates the member's git-only key, relays verified pinned peer artifacts, and
streams the declared kache credential. Pool repository origins are hel8's
mirrors; no GitHub key or interactive agent login is copied. Pool host and
repository resolution continues after fleet-sync promotes a release. Normal
readmission/build acceptance remains the operator's after the scaler reports
ready. The scaler's fake-service tests do not prove a real rebuild.

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
