# Rebuild a fleet member (Debian 13 amd64)

Target: hetzner2 / debian-16gb-hel1-2, drained gate2. See [inventory](inventory.md)
for the read-only 2026-10-29 survey and the state that a wipe would destroy.
The sequence is USER preparation, **one root script**, **one user script**,
then fleet-sync and heavy. Commands below are a future operator procedure;
the bootstrap task does not execute machine changes or the acceptance builds.

**Not wipe-ready until the six TODO-USER tool pins below are resolved.** A
successful fleet-sync exit with `warn: manual` is not acceptance. Legacy
post/fleet/QA/landing tools are also not ported here: preserving their frozen
checkout alone is insufficient to restore their SSH transport automatically.
If gate2's required role still uses them, ops must migrate/restore those
workflows separately before admitting it. No script depends on `old/`.

## USER preparation (in order)

1. **USER — retain state and resolve pins before wiping.** Confirm the drain
   with the coordinator, retain unpushed work/private notes and needed runtime
   evidence off-host, especially `~/src/fabrig/queue-worker` and
   `~/src/fabrig/ops/worker-smoke-20261029T0223`. Preserve heavy receipts/history,
   holds, gate and after-landing state, post messages, sessions and any local
   prover artifacts required by ops; inventory lists the observed directories.
   Back up credentials only through the user's private process, never into git.
   Approve and fill these fields in `fleet/versions.toml`, then land through
   `tools/land` after the gate passes (this task pushes a branch only):

   | Tool | Required approval / provenance missing from the machines |
   |---|---|
   | cargo-nextest 0.9.148 | release tarball URL and tarball SHA256; member cargo-nextest |
   | Claude 2.1.312 | install.sh URL/SHA256 and Linux x64 payload URL/SHA256 |
   | Codex 0.162.1 | full x86_64-unknown-linux-musl standalone package URL/SHA256 |
   | Chromium 147.0.7727.101 | extracted Debian bundle URL/SHA256, including bin/chromium launcher |
   | Forgejo 17.0.0 | linux-amd64 binary URL/SHA256 |
   | Forgejo runner 13.2.0 | linux-amd64 binary URL/SHA256 |

   Hash the approved **download**, not a different installed/extracted file.
   Tar installers accept regular files/directories only, without a containing
   directory; repackage a bundle with links if necessary, approve its URL/hash,
   and keep its license/resources. Codex must include code-mode-host,
   codex-resources, codex-path and codex-package.json as on h3, not just codex.
   Claude's approved installer must pin VERSION and verify its internal payload
   downloads before execution. Fleet additionally verifies its downloaded script,
   prefetches the approved payload, runs `install.sh VERSION` in a staging HOME,
   and checks the resulting versioned binary's SHA256 before promotion.

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

`--provision` holds the fleet lock, checks each pin and installs missing/different
versions, reporting provision:TOOL items. Rust components/targets are checked
even if rustc's version matches. It fetches exact kache source, applies the
vendored patches, verifies musl SHA256 and builds with the wrapper disabled;
its isolated build may take eight minutes. SHA256 failure leaves installed
artifacts untouched. The regular fleet run renders config/units and installs
fabrig via its installer. Only explicit provision starts/enables kache; a
running daemon is not restarted. The timer, --check and --preview never provision.

7. **USER — Claude login.** After its approved installer succeeds, open a new
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
its private, user-owned 0600 ~/.config/kache/store.env, convergence renders only
non-secret remote selectors/drop-in. On a drained machine, ops then restarts
kache explicitly. Bootstrap never opens that credential or clears the cache.

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

Existing hosts need a manual first invocation from an updated agents checkout
on a drained machine: older fleet-sync runners reject the new declaration asset
paths. Fetch/switch the dedicated agents clone to reviewed origin/main and run
`python3 -I -B ~/src/fabrig/agents/tools/fleet-sync --provision --host NAME` once;
subsequent timers use the promoted runner. Review config diffs/daemon restart
needs on each host. To revert, land the revert through tools/land and invoke
its runner manually; keep private logins and operational evidence intact.
