# Bootstrap inventory — 2026-10-29

Read-only SSH survey of free@2.29.101.185 (hetzner2, gate2) and
free@2.29.124.199 (hetzner3, builder), using `ssh -T -o BatchMode=yes HOST
'bash -lc "..."'`. No remote writes, builds, tests, logins or service changes.
Credential contents, SSH keys/config contents, token files and tmp/logins were
not opened. Cargo/Claude/Codex commands were version/installation probes only.

## Packages and system

Both: Debian GNU/Linux 13 (trixie), image point release 13.7, amd64; free
uid/gid 1000, supplementary sudo (27); Linger=yes.
`/etc/sudoers.d/free`: `free ALL=(ALL) NOPASSWD: ALL` (0440);
90-cloud-init-users grants root NOPASSWD. No SSH daemon changes are needed.
unattended-upgrades, apt-daily.timer and apt-daily-upgrade.timer are enabled.
20auto-upgrades sets Update-Package-Lists and Unattended-Upgrade to 1.
50unattended-upgrades has Automatic-Reboot=false commented (default false);
no active Automatic-Reboot override appeared in apt-config dump. Bootstrap
makes false explicit. /proc/swaps and swapon --show are empty on both.
h2 fstab: XFS root with defaults,noatime, EFI vfat, optical device; no swap.
No custom /etc/sysctl.d/*.conf. Only limits file is Debian's
10-coredump-debian.conf: soft core 0, hard core infinity for * and root.
The bootstrap does not copy device UUIDs or alter storage/sshd.

**Fleet-required manual packages** (kept in packages.txt): git, jq, python3,
clang, mold, build-essential, binutils, cmake, pkg-config, libssl-dev,
libsqlite3-dev (h3 only today), patch, bubblewrap, chromium, curl,
ca-certificates, openssh-client, sudo, adduser, systemd, libpam-systemd,
dbus-user-session, unattended-upgrades, ripgrep, rsync, file, xz-utils,
zstd, unzip. Tar/make/ar/readelf come from the image or these packages.
Chromium's Debian package supplies system dependencies, while the fleet
browser launcher still requires its pinned bundle. Chromium 147 bundle
runtime dependencies were not reconstructed from a package lock.

**Deliberate bootstrap prerequisite:** Debian rustup package candidate
1.27.1-3+b1 is available (not installed today); use apt's authenticated
package rather than an unrecorded rustup-init download. Today's manually
installed rustup is 1.29.2 (d8c92c676 2026-10-21). The toolchain, rather
than the manager's version, is the fleet pin. Rustup checks distribution
SHA256s; its self-update is disabled by bootstrap.

apt-mark showmanual common entries (unmarked entries are image/optional
packages, not a requirement to reproduce all of the image):
```text
acl acpid adduser apt apt-utils aptitude at base-files base-passwd bash bash-completion bind9-dnsutils bind9-host bsdutils btrfs-progs bubblewrap build-essential busybox bzip2 ca-certificates chromium clang cloud-init cloud-initramfs-growroot cloud-utils cmake console-setup coreutils cpio cron cron-daemon-common cryptsetup cryptsetup-initramfs curl dash dbus debconf debconf-i18n debian-archive-keyring debianutils dhcpcd-base diffutils dmidecode dosfstools dpkg e2fsprogs eatmydata efibootmgr ethtool fdisk file findutils gcc-14-base gdisk gettext-base git gnupg grep groff-base grub-common grub-efi-amd64 grub-efi-amd64-bin grub-pc-bin gzip hc-utils hostname htop ifupdown inetutils-telnet init init-system-helpers initramfs-tools iproute2 iptables iputils-ping jq keyboard-configuration kmod less libacl1 libapparmor1 libapt-pkg7.0 libattr1 libaudit-common libaudit1 libblkid1 libbpf1 libbsd0 libbz2-1.0 libc-bin libc6 libcap-ng0 libcap2 libcap2-bin libcom-err2 libcrypt1 libdb5.3t64 libdebconfclient0 libedit2 libelf1t64 libext2fs2t64 libfdisk1 libgcc-s1 libgmp10 libgssapi-krb5-2 libhogweed6t64 libidn2-0 libjansson4 libk5crypto3 libkeyutils1 libkmod2 libkrb5-3 libkrb5support0 liblastlog2-2 liblocale-gettext-perl liblockfile-bin liblz4-1 liblzma5 libmd0 libmnl0 libmount1 libncursesw6 libnettle8t64 libnewt0.52 libnftables1 libnftnl11 libnss-systemd libpam-modules libpam-modules-bin libpam-runtime libpam-systemd libpam0g libpcre2-8-0 libpopt0 libproc2-0 libreadline8t64 libseccomp2 libselinux1 libsemanage-common libsemanage2 libsepol2 libslang2 libsmartcols1 libsqlite3-0 libss2 libssl-dev libssl3t64 libstdc++6 libsystemd-shared libsystemd0 libtext-charwidth-perl libtext-iconv-perl libtext-wrapi18n-perl libtinfo6 libtirpc-common libtirpc3t64 libudev1 libunistring5 libuuid1 libxtables12 libxxhash0 libzstd1 linux-image-cloud-amd64 linux-sysctl-defaults locales locales-all login login.defs logrotate logsave lsof lvm2 man-db manpages mawk mdadm media-types mold mount mtr-tiny nano ncurses-base ncurses-bin ncurses-term net-tools netbase netcat-traditional nftables openssh-client openssl openssl-provider-legacy os-prober passwd patch perl-base pkg-config procps python3 python3-apt qemu-guest-agent readline-common reportbug resolvconf ripgrep rsync sed sensible-utils shim-signed sqv ssh-import-id sudo systemd systemd-sysv systemd-timesyncd sysvinit-utils tar task-english task-ssh-server tasksel traceroute tzdata ucf udev unattended-upgrades unzip util-linux util-linux-extra vim vim-common vim-tiny wget whiptail wtmpdb xfsprogs xz-utils zlib1g zstd
```
h2-only manual entries: clang-19.
h3-only manual entries: dbus-user-session, libsqlite3-dev.

## Rust and cargo

Both default to 1.95.0-x86_64-unknown-linux-gnu (rustc 59807616e, 2026-04-14).
Also installed: nightly-2026-10-21-x86_64-unknown-linux-gnu.
Stable components: cargo, clippy, rust-docs, rust-std, rustc, rustfmt; targets
x86_64-unknown-linux-gnu, wasm32-unknown-unknown, aarch64-apple-darwin.
Nightly has the same standard components and the host target.
Bootstrap adds x86_64-unknown-linux-musl to rebuild kache; it is absent on
these hosts today. rust-analyzer/Miri proxy links do not establish installed
components (neither appears in the component lists).
cargo install --list is empty on both: cargo-nextest 0.9.148 was placed
directly in ~/.cargo/bin (36,377,136 bytes); it is not cargo-install tracked.
All other ~/.cargo/bin entries are rustup (21,139,856 bytes) and its proxies:
cargo, cargo-clippy, cargo-fmt, cargo-miri, clippy-driver, rls,
rust-analyzer, rust-gdb, rust-gdbgui, rust-lldb, rustc, rustdoc, rustfmt.
No nextest release URL/archive checksum is recorded there: TODO-USER.

## Native tools and provenance

Both Claude links point to ~/.local/share/claude/versions/2.1.312;
2.1.310 and 2.1.311 are also retained. Probe: 2.1.312 (Claude Code).
No installer/manifest provenance was present in that version directory:
TODO-USER installer URL/SHA256 and payload URL/SHA256.
Both Codex links point to ~/.codex/packages/standalone/current/bin/codex.
current -> releases/0.162.1-x86_64-unknown-linux-musl. Probe: codex-cli 0.162.1.
The complete standalone release includes bin/codex (294,415,048 bytes),
bin/codex-code-mode-host (74,036,112), codex-resources, codex-path,
a codex -> bin/codex link, and codex-package.json:
```json
{"layoutVersion":1,"version":"0.162.1","target":"x86_64-unknown-linux-musl","variant":"codex","entrypoint":"bin/codex","resourcesDir":"codex-resources","pathDir":"codex-path"}
```
The manager also has install.lock and selection-history (h2) /
selection-history (h3). History contents were not needed/read.
The installed metadata has no source URL or package SHA256: TODO-USER.
Install the whole standalone package, including the code-mode host/resources.

Both opt trees have chromium-147.0.7727.101, forgejo-17.0.0,
forgejo-runner-13.2.0. There are no README*, .version or SHA256SUMS files at
their top levels. Chromium has bin/chromium launcher (5,240 bytes), etc/,
usr/; ~/.local/bin/chromium points at usr/lib/chromium/chromium.
SKEIN_TEST_CHROMIUM in fleet/env deliberately uses the bin/chromium launcher.
Probe: Chromium 147.0.7727.101.
Forgejo: 17.0.0+gitea-1.22.0, GNU Make 4.4.1, go1.26.9,
bindata/timetzdata/sqlite/sqlite_unlock_notify, 122,053,192 bytes.
Runner: v13.2.0, 22,290,594 bytes.
h3 links forgejo and forgejo-runner into ~/.local/bin; h2 has opt files
but no such links. URLs/archive or binary SHA256s: TODO-USER for all three.
h3 additionally has ~/.local/bin/garage (71,272,496 bytes); Garage's service
is disabled. Shared S3 infrastructure is not bootstrap's responsibility.

## Kache

Both run kache 1.2.2-gitrev.2 from ~/.local/bin/kache (28,592,984 bytes).
The same pinned artifact is in ~/src/rust/tmp/kache/kache-1.2.2-gitrev.2.
Legacy kache-setup writes config and service; its preserved source kit pins
upstream 96052b4842239bb216f6c4812054203c21550788, git-checkout-rev.patch,
upload-bound.patch, musl 1.2.5 URL and SHA256. The historical output SHA256 is
91fb6aa7d7ddd427e3e2732aa346ce116fbf075df0c871e1148bf309aaadafaf.
The source recipe and patch bytes are now independent files under fleet/kache;
the legacy kit documented that rebuilds need not reproduce historical bytes.

~/.config/kache filenames:
h2 config.toml, config.toml.bak-1041, config.toml.before-1.2.2,
config.toml.before-1.2.2-gitrev.1, config.toml.before-1.2.2-gitrev.2, store.env.
h3 has the same except config.toml.bak-1041. store.env is 0600, 132 bytes,
user-owned on both; **contents were never read**.
Both configs: gc_evict_shared=true, auto_gc=true, local_only=true,
cache_executables=true, prefetch_enabled=false, remote_upload_max_bytes=67108864.
h2 cap 25GiB / recovery 69793218560 bytes (40+25 GiB);
h3 cap 40GiB / recovery 85899345920 (40+40 GiB).
Remote selectors (non-secret): s3, bucket kache, endpoint http://10.80.0.13:3900,
region garage, prefix artifacts. No local_store override.
The enabled daemon has Restart=always/5s, KACHE_LOG=kache=info and
ExecStart=/home/free/.local/bin/kache daemon run.
20-shared-store.conf loads %h/.config/kache/store.env.
Bootstrap renders these non-secret settings; shared-store selectors/drop-in
are conditional on credential metadata. A fresh host works local-only.

## Units and ownership

| Owner | h2 | h3 | Recreated by |
|---|---|---|---|
| fleet-sync | fleet-sync service/timer, timer enabled | same plus record-collect-builder service/timer enabled | fleet declarations |
| heavy | skein-heavy-a3f2289065cb-reconcile service/timer, timer enabled | same | heavy --install-reconciler |
| old kache-setup | kache.service enabled + shared-store drop-in | same | fleet renders; --provision starts |
| legacy cache GC | kache-gc service/timer enabled (30min) | kache-prune service/timer disabled, Garage and GC-budget drop-ins | not recreated; current daemon auto_gc=true |
| legacy fleet setup | fleet-tend service/timer enabled, every 5min, exec fleet tend | same | not recreated; old executable dependency |
| legacy QA/landing setup | agents-qa-watch.service disabled | agents-after-landing@.service indirect | not recreated |
| ops / slots guard | absent | transient fabrig-slot-guard service/timer, every 5min, tools/slots/guard --below 80 | ops; deliberately not persisted by bootstrap |
| distribution/session | dbus, gpg/dirmngr/keyboxd/ssh-agent sockets and targets | same | Debian packages |

Heavy's launcher defaults DEV_ROOT=$HOME/src/rust and DEV_TMP=$DEV_ROOT/tmp.
Its design section 4 and Python install() probe cgroup containment (including
setsid), write tmp/heavy/reconcile.env with workspace/PATH/bus variables,
record installation in the existing ledger, then write the service/timer,
daemon-reload and enable --now. ExecStart is the absolute adjacent
heavy-recovery.py --reconcile; UMask=0077, Type=oneshot,
StartLimitIntervalSec=0. Timer: OnBootSec=5s, OnUnitInactiveSec=5s,
AccuracySec=100ms. Reinstall keeps queue/history/holds. Fleet does not manage
its units or ledger. Fresh installation creates its private state/locks,
not old receipts/history. h3 unit paths point to ~/src/fabrig/main/tools/heavy/.

## SSH and Git

h2 known_hosts: 21 non-comment entries; h3: 16 (keys not printed).
~/.ssh/config exists on both; contents not read. post/machines uses
hetzner2 local on h2, hetzner3 local on h3, and other fleet SSH addresses
from hosts.toml (hel8's bare IP is equivalent to free@IP).
The legacy post implementation selects ~/.ssh/post_ed25519 explicitly with
IdentitiesOnly=yes, BatchMode=yes and no control master, issuing the remote
command `deliver NAME`. Its key and any restricted authorized_keys delivery
entries were not read or recreated. Their absence blocks legacy messaging.
post and fleet-sync use noninteractive SSH with existing known_hosts trust;
fleet-sync explicitly sets StrictHostKeyChecking=yes, UpdateHostKeys=no.
Public-key authorization AND host-key trust must be arranged by USER.
Routing is check-only under fleet/policy.toml; bootstrap documents a USER
initial machines file. No script edits trust or private keys.

Global git keys are only user.name/user.email and url.*.insteadOf, no credential
helper. Safe values on both:
```ini
user.name=Free Ekanayaka
user.email=freee@debian.org
url.git@github.com:fabrig-ai/.insteadof=https://git.ekanayaka.io/ai/
url.git@github.com:fabrig-ai/.insteadof=git@github.com:fabrig-dev/
url.git@github.com:fabrig-ai/.insteadof=git@github.com:fabrica-works/
url.https://github.com/fabrig-ai/.insteadof=https://github.com/fabrig-dev/
url.https://github.com/fabrig-ai/.insteadof=https://github.com/fabrica-works/
```
These identity/legacy rewrite preferences are USER-managed; the bootstrap
does not overwrite personal git configuration.

## Directory skeleton and wipe loss

Tools default to ~/src/rust/tmp; fleet releases/checkouts are under
~/src/fabrig/{agents,current,main,releases,.fleet-sync}. Bootstrap creates
the empty tmp/{post,kache,logs} and fabrig/{notes,ops,tasks} parents.
Heavy, codex-run and record collectors create their own working state;
slots/claims/leases/queue are created by their owning tools as needed.
Mailboxes under tmp/post use new/, cur/, tmp/, sent/ and a .lock;
only directory names were surveyed with ls -d, no message contents.

h2 additionally has ~/src/fabrig/queue-worker (independent git clone) and
ops/worker-smoke-20261029T0223. There are no .git/mq* / *worker* / *proof*
entries in that clone and no running queue/prover/gate2 user unit in this
survey. That establishes no visible unresolved marker, **not proof that all
second-gate state is disposable**. Worker design stores immutable attempt
artifacts externally and .git/mq-worker-unresolved.json while unresolved.
USER must retain the queue-worker clone and ops worker-smoke artifacts and
confirm coordinator quiescence before wiping. Bootstrap neither recreates
nor activates a second-gate prover, and does not invent its state.

Wiping also loses legacy ~/src/rust/agents and tools linked into it,
~/src/rust product checkouts/unpushed work, gate worktrees, after-landing
logs/state, tmp/director, tmp/owners, Codex sessions, post messages,
heavy ledger/events/logs/receipts/holds, slot state, kache caches/artifact
and shared-store credential, auth logins, SSH authorization/trust, global
git settings and local notes/ops/tasks. Recovery of private credentials
and retained operational evidence is USER work outside this repository.
Bootstrap never resets or synthesizes existing runtime state.
Legacy post/fleet/land/qa/setup workflows need their own migration;
they are not restored by a hidden dependency on old/. During this task main
ported logins to tools/qa/logins: the rebased bootstrap installs that executable
via fleet-sync, without inspecting/restoring any resting credential or custody
state. The link listings below remain the historical survey observation.

## Observed local links and directory names

The following are metadata from the read-only survey, retained to distinguish
existing directories and legacy links from the empty parents bootstrap makes.

### hetzner2

```text
/home/free/.cargo/bin:
total 56176
lrwxrwxrwx 1 free free        6 Oct 26 15:49 cargo -> rustup
lrwxrwxrwx 1 free free        6 Oct 26 15:49 cargo-clippy -> rustup
lrwxrwxrwx 1 free free        6 Oct 26 15:49 cargo-fmt -> rustup
lrwxrwxrwx 1 free free        6 Oct 26 15:49 cargo-miri -> rustup
-rwxr-xr-x 1 free free 36377136 Oct 26 01:45 cargo-nextest
lrwxrwxrwx 1 free free        6 Oct 26 15:49 clippy-driver -> rustup
lrwxrwxrwx 1 free free        6 Oct 26 15:49 rls -> rustup
lrwxrwxrwx 1 free free        6 Oct 26 15:49 rust-analyzer -> rustup
lrwxrwxrwx 1 free free        6 Oct 26 15:49 rust-gdb -> rustup
lrwxrwxrwx 1 free free        6 Oct 26 15:49 rust-gdbgui -> rustup
lrwxrwxrwx 1 free free        6 Oct 26 15:49 rust-lldb -> rustup
lrwxrwxrwx 1 free free        6 Oct 26 15:49 rustc -> rustup
lrwxrwxrwx 1 free free        6 Oct 26 15:49 rustdoc -> rustup
lrwxrwxrwx 1 free free        6 Oct 26 15:49 rustfmt -> rustup
-rwxr-xr-x 1 free free 21139856 Oct 26 15:49 rustup

/home/free/.local/bin:
total 27924
lrwxrwxrwx 1 free free       54 Oct 26 15:52 after-landing -> /home/free/src/rust/agents/scripts/devel/after-landing
lrwxrwxrwx 1 free free       71 Oct 26 17:53 chromium -> /home/free/.local/opt/chromium-147.0.7727.101/usr/lib/chromium/chromium
lrwxrwxrwx 1 free free       44 Oct 29 13:02 claim -> /home/free/src/fabrig/main/tools/slots/claim
lrwxrwxrwx 1 free free       47 Oct 27 20:49 claude -> /home/free/.local/share/claude/versions/2.1.312
lrwxrwxrwx 1 free free       55 Oct 26 15:50 codex -> /home/free/.codex/packages/standalone/current/bin/codex
lrwxrwxrwx 1 free free       52 Oct 29 13:02 codex-run -> /home/free/src/fabrig/main/tools/codex-run/codex-run
lrwxrwxrwx 1 free free       50 Oct 29 14:54 fabrig-record -> /home/free/src/fabrig/current/tools/records/record
lrwxrwxrwx 1 free free       46 Oct 27 03:30 fleet -> /home/free/src/rust/agents/scripts/devel/fleet
lrwxrwxrwx 1 free free       46 Oct 29 13:34 fleet-sync -> /home/free/src/fabrig/current/tools/fleet-sync
lrwxrwxrwx 1 free free       44 Oct 29 13:02 heavy -> /home/free/src/fabrig/main/tools/heavy/heavy
lrwxrwxrwx 1 free free       46 Oct 26 15:52 issue -> /home/free/src/rust/agents/scripts/devel/issue
-rwx------ 1 free free 28592984 Oct 28 17:47 kache
lrwxrwxrwx 1 free free       45 Oct 26 15:52 land -> /home/free/src/rust/agents/scripts/devel/land
lrwxrwxrwx 1 free free       49 Oct 26 15:52 land-set -> /home/free/src/rust/agents/scripts/devel/land-set
lrwxrwxrwx 1 free free       49 Oct 26 15:52 landings -> /home/free/src/rust/agents/scripts/devel/landings
lrwxrwxrwx 1 free free       41 Oct 29 13:34 lease -> /home/free/src/fabrig/current/tools/lease
lrwxrwxrwx 1 free free       47 Oct 26 20:48 logins -> /home/free/src/rust/agents/scripts/devel/logins
lrwxrwxrwx 1 free free       49 Oct 29 14:54 pipeline-watch -> /home/free/src/fabrig/current/tools/records/watch
lrwxrwxrwx 1 free free       45 Oct 26 15:52 post -> /home/free/src/rust/agents/scripts/devel/post
lrwxrwxrwx 1 free free       47 Oct 29 13:02 precheck -> /home/free/src/fabrig/main/tools/queue/precheck
lrwxrwxrwx 1 free free       43 Oct 26 15:52 qa -> /home/free/src/rust/agents/scripts/devel/qa
lrwxrwxrwx 1 free free       50 Oct 29 13:02 ready-check -> /home/free/src/fabrig/main/tools/queue/ready-check
lrwxrwxrwx 1 free free       47 Oct 26 15:52 record -> /home/free/src/rust/agents/scripts/devel/record
lrwxrwxrwx 1 free free       58 Oct 29 14:54 record-collect -> /home/free/src/fabrig/current/tools/records/record-collect
lrwxrwxrwx 1 free free       46 Oct 26 15:52 repin -> /home/free/src/rust/agents/scripts/devel/repin
lrwxrwxrwx 1 free free       56 Oct 29 13:02 session-context -> /home/free/src/fabrig/main/tools/session/session-context
lrwxrwxrwx 1 free free       49 Oct 29 14:54 session-start -> /home/free/src/fabrig/current/tools/session/start
lrwxrwxrwx 1 free free       46 Oct 26 15:52 setup -> /home/free/src/rust/agents/scripts/infra/setup
lrwxrwxrwx 1 free free       55 Oct 29 14:54 status-page -> /home/free/src/fabrig/current/tools/records/status-page
drwxr-xr-x 5 free free        39 Oct 16 10:42 /home/free/.local/opt/chromium-147.0.7727.101
drwxrwxr-x 2 free free        22 Oct 16 10:42 /home/free/.local/opt/chromium-147.0.7727.101/bin
-rwxrwxr-x 1 free free      5240 Oct 16 10:42 /home/free/.local/opt/chromium-147.0.7727.101/bin/chromium
drwxr-xr-x 4 free free        40 Apr 15  2026 /home/free/.local/opt/chromium-147.0.7727.101/etc
drwxr-xr-x 5 free free        41 Apr 15  2026 /home/free/.local/opt/chromium-147.0.7727.101/usr
drwxrwxr-x 2 free free        21 Oct 19 03:25 /home/free/.local/opt/forgejo-17.0.0
-rwxrwxr-x 1 free free 122053192 Oct 19 03:25 /home/free/.local/opt/forgejo-17.0.0/forgejo
drwxrwxr-x 2 free free        28 Oct 19 05:13 /home/free/.local/opt/forgejo-runner-13.2.0
-rwxrwxr-x 1 free free  22290594 Oct 19 05:13 /home/free/.local/opt/forgejo-runner-13.2.0/forgejo-runner
forgejo version 17.0.0+gitea-1.22.0 (release name 17.0.0) built with GNU Make 4.4.1, go1.26.9 : bindata, timetzdata, sqlite, sqlite_unlock_notify
forgejo-runner version v13.2.0
Chromium 147.0.7727.101
/home/free/src/fabrig/agents/
/home/free/src/fabrig/current/
/home/free/src/fabrig/main/
/home/free/src/fabrig/notes/
/home/free/src/fabrig/ops/
/home/free/src/fabrig/queue-worker/
/home/free/src/fabrig/releases/
/home/free/src/fabrig/slot-guard-check.guW2SX/
/home/free/src/fabrig/slots/
/home/free/src/fabrig/tasks/
/home/free/src/rust/tmp/after-landing/
/home/free/src/rust/tmp/codex-run/
/home/free/src/rust/tmp/director-tasks/
/home/free/src/rust/tmp/director/
/home/free/src/rust/tmp/fleet/
/home/free/src/rust/tmp/gates/
/home/free/src/rust/tmp/git-fabrig/
/home/free/src/rust/tmp/github-conformance/
/home/free/src/rust/tmp/heavy/
/home/free/src/rust/tmp/kache/
/home/free/src/rust/tmp/lab/
/home/free/src/rust/tmp/land-set/
/home/free/src/rust/tmp/landing-turn/
/home/free/src/rust/tmp/logs/
/home/free/src/rust/tmp/owners/
/home/free/src/rust/tmp/post/
/home/free/src/rust/tmp/post/codex-run/
/home/free/src/rust/tmp/post/d+build-efficiency/
/home/free/src/rust/tmp/post/d+landing-flow/
/home/free/src/rust/tmp/post/design+agent-docs/
/home/free/src/rust/tmp/post/design+configuring-draft/
/home/free/src/rust/tmp/post/design+dynamic-memory/
/home/free/src/rust/tmp/post/design+look-requests/
/home/free/src/rust/tmp/post/design+process-model/
/home/free/src/rust/tmp/post/design+qa-evidence/
/home/free/src/rust/tmp/post/landings/
/home/free/src/rust/tmp/post/o+box-terminal-m1/
/home/free/src/rust/tmp/post/o+box-terminal-m2/
/home/free/src/rust/tmp/post/o+box-terminal-m3/
/home/free/src/rust/tmp/post/o+box-terminal/
/home/free/src/rust/tmp/post/o+chatgpt-paste/
/home/free/src/rust/tmp/post/o+configuring-3/
/home/free/src/rust/tmp/post/o+configuring-docs/
/home/free/src/rust/tmp/post/o+configuring-revisions/
/home/free/src/rust/tmp/post/o+configuring-stock/
/home/free/src/rust/tmp/post/o+dm-engine-root/
/home/free/src/rust/tmp/post/o+dm-skein/
/home/free/src/rust/tmp/post/o+dm-temper-exact/
/home/free/src/rust/tmp/post/o+dm-window-skein/
/home/free/src/rust/tmp/post/o+docs-help/
/home/free/src/rust/tmp/post/o+docs-settings/
/home/free/src/rust/tmp/post/o+dynamic-memory-2/
/home/free/src/rust/tmp/post/o+dynamic-memory/
/home/free/src/rust/tmp/post/o+heavy-without-pueue/
/home/free/src/rust/tmp/post/o+holds/
/home/free/src/rust/tmp/post/o+look-landings/
/home/free/src/rust/tmp/post/o+playground-page/
/home/free/src/rust/tmp/post/o+qa-flow/
/home/free/src/rust/tmp/post/o+upgrades-4/
/home/free/src/rust/tmp/post/o+user-issues/
/home/free/src/rust/tmp/post/o+verdicts/
/home/free/src/rust/tmp/post/p+configuring-revisions-qa/
/home/free/src/rust/tmp/post/qa-watch/
/home/free/src/rust/tmp/qa/
/home/free/src/rust/tmp/tasks/
```

### hetzner3

```text
/home/free/.cargo/bin:
total 56176
lrwxrwxrwx 1 free free        6 Oct 26 16:32 cargo -> rustup
lrwxrwxrwx 1 free free        6 Oct 26 16:32 cargo-clippy -> rustup
lrwxrwxrwx 1 free free        6 Oct 26 16:32 cargo-fmt -> rustup
lrwxrwxrwx 1 free free        6 Oct 26 16:32 cargo-miri -> rustup
-rwxr-xr-x 1 free free 36377136 Oct 26 01:45 cargo-nextest
lrwxrwxrwx 1 free free        6 Oct 26 16:32 clippy-driver -> rustup
lrwxrwxrwx 1 free free        6 Oct 26 16:32 rls -> rustup
lrwxrwxrwx 1 free free        6 Oct 26 16:32 rust-analyzer -> rustup
lrwxrwxrwx 1 free free        6 Oct 26 16:32 rust-gdb -> rustup
lrwxrwxrwx 1 free free        6 Oct 26 16:32 rust-gdbgui -> rustup
lrwxrwxrwx 1 free free        6 Oct 26 16:32 rust-lldb -> rustup
lrwxrwxrwx 1 free free        6 Oct 26 16:32 rustc -> rustup
lrwxrwxrwx 1 free free        6 Oct 26 16:32 rustdoc -> rustup
lrwxrwxrwx 1 free free        6 Oct 26 16:32 rustfmt -> rustup
-rwxr-xr-x 1 free free 21139856 Oct 26 16:32 rustup

/home/free/.local/bin:
total 97528
lrwxrwxrwx 1 free free       54 Oct 26 16:35 after-landing -> /home/free/src/rust/agents/scripts/devel/after-landing
lrwxrwxrwx 1 free free       71 Oct 26 16:41 chromium -> /home/free/.local/opt/chromium-147.0.7727.101/usr/lib/chromium/chromium
lrwxrwxrwx 1 free free       44 Oct 29 13:02 claim -> /home/free/src/fabrig/main/tools/slots/claim
lrwxrwxrwx 1 free free       47 Oct 27 20:37 claude -> /home/free/.local/share/claude/versions/2.1.312
lrwxrwxrwx 1 free free       55 Oct 26 16:33 codex -> /home/free/.codex/packages/standalone/current/bin/codex
lrwxrwxrwx 1 free free       52 Oct 29 13:02 codex-run -> /home/free/src/fabrig/main/tools/codex-run/codex-run
lrwxrwxrwx 1 free free       50 Oct 29 14:59 fabrig-record -> /home/free/src/fabrig/current/tools/records/record
lrwxrwxrwx 1 free free       46 Oct 27 05:06 fleet -> /home/free/src/rust/agents/scripts/devel/fleet
lrwxrwxrwx 1 free free       46 Oct 29 14:59 fleet-sync -> /home/free/src/fabrig/current/tools/fleet-sync
lrwxrwxrwx 1 free free       44 Oct 26 16:34 forgejo -> /home/free/.local/opt/forgejo-17.0.0/forgejo
lrwxrwxrwx 1 free free       58 Oct 26 16:34 forgejo-runner -> /home/free/.local/opt/forgejo-runner-13.2.0/forgejo-runner
-rwxr-xr-x 1 free free 71272496 Oct 24 09:34 garage
lrwxrwxrwx 1 free free       44 Oct 29 13:02 heavy -> /home/free/src/fabrig/main/tools/heavy/heavy
lrwxrwxrwx 1 free free       46 Oct 26 16:35 issue -> /home/free/src/rust/agents/scripts/devel/issue
-rwx------ 7 free free 28592984 Oct 28 16:03 kache
lrwxrwxrwx 1 free free       45 Oct 26 16:35 land -> /home/free/src/rust/agents/scripts/devel/land
lrwxrwxrwx 1 free free       49 Oct 26 16:35 land-set -> /home/free/src/rust/agents/scripts/devel/land-set
lrwxrwxrwx 1 free free       49 Oct 26 16:35 landings -> /home/free/src/rust/agents/scripts/devel/landings
lrwxrwxrwx 1 free free       41 Oct 29 14:59 lease -> /home/free/src/fabrig/current/tools/lease
lrwxrwxrwx 1 free free       47 Oct 26 21:05 logins -> /home/free/src/rust/agents/scripts/devel/logins
lrwxrwxrwx 1 free free       49 Oct 29 14:59 pipeline-watch -> /home/free/src/fabrig/current/tools/records/watch
lrwxrwxrwx 1 free free       45 Oct 26 16:35 post -> /home/free/src/rust/agents/scripts/devel/post
lrwxrwxrwx 1 free free       47 Oct 29 13:02 precheck -> /home/free/src/fabrig/main/tools/queue/precheck
lrwxrwxrwx 1 free free       43 Oct 26 16:35 qa -> /home/free/src/rust/agents/scripts/devel/qa
lrwxrwxrwx 1 free free       50 Oct 29 13:02 ready-check -> /home/free/src/fabrig/main/tools/queue/ready-check
lrwxrwxrwx 1 free free       47 Oct 26 16:35 record -> /home/free/src/rust/agents/scripts/devel/record
lrwxrwxrwx 1 free free       58 Oct 29 14:59 record-collect -> /home/free/src/fabrig/current/tools/records/record-collect
lrwxrwxrwx 1 free free       46 Oct 26 16:35 repin -> /home/free/src/rust/agents/scripts/devel/repin
lrwxrwxrwx 1 free free       56 Oct 29 13:02 session-context -> /home/free/src/fabrig/main/tools/session/session-context
lrwxrwxrwx 1 free free       49 Oct 29 14:59 session-start -> /home/free/src/fabrig/current/tools/session/start
lrwxrwxrwx 1 free free       46 Oct 26 16:35 setup -> /home/free/src/rust/agents/scripts/infra/setup
lrwxrwxrwx 1 free free       55 Oct 29 14:59 status-page -> /home/free/src/fabrig/current/tools/records/status-page
drwxr-xr-x 5 free free        39 Oct 16 10:42 /home/free/.local/opt/chromium-147.0.7727.101
drwxrwxr-x 2 free free        22 Oct 16 10:42 /home/free/.local/opt/chromium-147.0.7727.101/bin
-rwxrwxr-x 1 free free      5240 Oct 16 10:42 /home/free/.local/opt/chromium-147.0.7727.101/bin/chromium
drwxr-xr-x 4 free free        40 Apr 15  2026 /home/free/.local/opt/chromium-147.0.7727.101/etc
drwxr-xr-x 5 free free        41 Apr 15  2026 /home/free/.local/opt/chromium-147.0.7727.101/usr
drwxrwxr-x 2 free free        21 Oct 19 03:25 /home/free/.local/opt/forgejo-17.0.0
-rwxrwxr-x 1 free free 122053192 Oct 19 03:25 /home/free/.local/opt/forgejo-17.0.0/forgejo
drwxrwxr-x 2 free free        28 Oct 19 05:13 /home/free/.local/opt/forgejo-runner-13.2.0
-rwxrwxr-x 1 free free  22290594 Oct 19 05:13 /home/free/.local/opt/forgejo-runner-13.2.0/forgejo-runner
forgejo version 17.0.0+gitea-1.22.0 (release name 17.0.0) built with GNU Make 4.4.1, go1.26.9 : bindata, timetzdata, sqlite, sqlite_unlock_notify
forgejo-runner version v13.2.0
Chromium 147.0.7727.101
/home/free/src/fabrig/agents/
/home/free/src/fabrig/current/
/home/free/src/fabrig/main/
/home/free/src/fabrig/notes/
/home/free/src/fabrig/ops/
/home/free/src/fabrig/records/
/home/free/src/fabrig/releases/
/home/free/src/fabrig/slot-maintenance/
/home/free/src/fabrig/slots/
/home/free/src/fabrig/tasks/
/home/free/src/rust/tmp/after-landing-aside-20261027/
/home/free/src/rust/tmp/after-landing/
/home/free/src/rust/tmp/codex-run/
/home/free/src/rust/tmp/director-tasks/
/home/free/src/rust/tmp/docs-gated-2/
/home/free/src/rust/tmp/fleet/
/home/free/src/rust/tmp/gates/
/home/free/src/rust/tmp/git-fabrig/
/home/free/src/rust/tmp/github-conformance/
/home/free/src/rust/tmp/heavy/
/home/free/src/rust/tmp/join-depth/
/home/free/src/rust/tmp/kache/
/home/free/src/rust/tmp/lab/
/home/free/src/rust/tmp/land-repo-name/
/home/free/src/rust/tmp/land-set/
/home/free/src/rust/tmp/landing-turn/
/home/free/src/rust/tmp/logs/
/home/free/src/rust/tmp/owners/
/home/free/src/rust/tmp/post/
/home/free/src/rust/tmp/post/after-landing/
/home/free/src/rust/tmp/post/codex-run/
/home/free/src/rust/tmp/post/design+browser-playground/
/home/free/src/rust/tmp/post/design+dynamic-memory/
/home/free/src/rust/tmp/post/design+look-recording/
/home/free/src/rust/tmp/post/design+look-requests/
/home/free/src/rust/tmp/post/design+process-model/
/home/free/src/rust/tmp/post/landings/
/home/free/src/rust/tmp/post/o+after-landing-runner/
/home/free/src/rust/tmp/post/o+dm-window-jig/
/home/free/src/rust/tmp/post/o+dm-window-smith/
/home/free/src/rust/tmp/post/o+dm-window-temper/
/home/free/src/rust/tmp/post/o+forge-domain-2/
/home/free/src/rust/tmp/post/o+forgejo-elsewhere-3/
/home/free/src/rust/tmp/post/o+github-land-2-m4/
/home/free/src/rust/tmp/post/o+github-land-2/
/home/free/src/rust/tmp/post/o+github-land-3-m1/
/home/free/src/rust/tmp/post/o+github-land-3/
/home/free/src/rust/tmp/post/o+journeys/
/home/free/src/rust/tmp/post/o+landing-flow-2/
/home/free/src/rust/tmp/post/o+landing-flow-cleanup/
/home/free/src/rust/tmp/post/o+landings/
/home/free/src/rust/tmp/post/o+look-landings-2/
/home/free/src/rust/tmp/post/o+playground-world/
/home/free/src/rust/tmp/post/o+qa-repo/
/home/free/src/rust/tmp/post/o+real-loop-cut-m2/
/home/free/src/rust/tmp/post/o+real-loop-cut/
/home/free/src/rust/tmp/post/o+tidy-evidence/
/home/free/src/rust/tmp/post/o+tier-flakes/
/home/free/src/rust/tmp/post/o+web-look-6/
/home/free/src/rust/tmp/post/ops/
/home/free/src/rust/tmp/post/tier-flakes/
/home/free/src/rust/tmp/prove-snapshot/
/home/free/src/rust/tmp/qa/
/home/free/src/rust/tmp/restored-git/
```
