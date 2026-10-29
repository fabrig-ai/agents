# The build cache

Provisional, 2026-10-24. How builds reuse compiled crates across
worktrees, pins and machines: kache, our patch to it, and the fleet's
shared store, with the reasons for each choice and what they measured.
The landing flow built on it is [landing-flow.md](landing-flow.md);
`heavy` and `land` are
[build-infrastructure.md](build-infrastructure.md).

## 1. In one page

- **kache wraps rustc.** Cargo runs every compilation through kache.
  kache hashes everything that decides a unit's output into a key, and
  on a hit it restores the output instead of compiling (section 2).
- **Pins used to defeat it.** kache 1.2.2 kept a git dependency's
  checkout directory in its keys, and that directory names the pinned
  revision. A pin move therefore recompiled every crate of the moved
  repository and everything downstream of it, changed or not, with no
  hits at all (section 3).
- **Our patch drops the revision.** In `kache 1.2.2-gitrev.1`, an
  unchanged crate keeps its key across pins. A pin move recompiles only
  what changed upstream and the crates built on it, and the outputs are
  byte-identical to cold builds (section 4).
- **A shared store makes it fleet-wide.** A self-hosted S3 store on
  hetzner3, on a private network, sits behind every build machine's
  local store. Each machine reads it and publishes to it, so a unit is
  compiled once per fleet (section 5). A trial restored a whole jig
  build on a second machine with no Rust compile (section 6).
- **What a change still costs is its ripple:** the changed crates, plus
  every crate built on them, transitively, because a key includes the
  digests of its dependencies' outputs. Where a crate sits in the graph
  decides its cost.
- **What stays local:** build-script runs and a few C files, a few
  seconds per build, and units whose output names their own path.
- **The user's decisions (10-24):** we patch kache ourselves and may
  offer it upstream later; the store is self-hosted and central; every
  build machine publishes; plain HTTP on the private network; objects
  expire after 7 days (1 day since the bucket filled on 10-24, section
  5); the store has its own disk.

## 2. kache and its keys

[kache](https://github.com/kunobi-ninja/kache) is a rustc wrapper with
a daemon. `scripts/infra/kache-setup` points Cargo's `rustc-wrapper` at
it in `~/.cargo/config.toml` and runs the daemon as the user unit
`kache.service`. Build machines keep a 40 GiB local store
(`KACHE_MAX_GB=40` in their `tmp/machine.env`; the kit's default of 12
is for machines that don't build) with `cache_executables = true`, so
linked test binaries are cached too, and prefetch off (section 7).

- **The key** hashes what decides a unit's output: its source files,
  the compiler and its flags, the environment it reads, and the
  digests of the compiled outputs of its dependencies (its externs).
- **Paths are normalized.** The workspace root and `CARGO_HOME` become
  placeholders in the key and are remapped in the output. Two worktrees
  at different paths therefore share entries, which the spike
  confirmed (section 3).
- **A hit** restores the unit's outputs into the target directory, and
  nothing is compiled. Cargo still calls the wrapper for every unit it
  judges dirty, so a hit costs a lookup and a restore. Restoring takes a
  few milliseconds (a median of 6 ms in the trial), and a hit from the
  shared store took 182 ms including the download (section 6).
- **The ripple.** Because a key includes its externs' digests, any
  change to a crate's source changes the key of every crate built on
  it, even when its interface didn't change. rustc has no "interface
  unchanged, skip the users" cut-off. A change to `skein-lib` reaches
  nearly every crate in temper. A change to a temper view reaches only
  temper's binaries.

## 3. The defect: pins defeated the cache

Our repositories name their upstreams by git URL with no revision;
`Cargo.lock` pins a commit. Cargo checks each pinned revision out into
`$CARGO_HOME/git/checkouts/<repo>-<hash>/<short-rev>/`. kache 1.2.2
replaced only the `CARGO_HOME` prefix with its placeholder, so
`<short-rev>` stayed in the key of every crate of that repository.

- **The spike** (10-24) used three toy repositories wired like ours: 10
  crates, 16 units including tests and a binary, built through `heavy`
  with our kache.

  | Change | Units recompiled | kache hits |
  |---|---|---|
  | Pin moved, one leaf crate changed | all 16 | 0 |
  | Pin moved, a widely used crate changed | all 16 | 0 |
  | Path dependency, the same leaf change | 6: that crate and its users | not needed |
  | Path dependency, the widely used crate | 10: that crate and its users | not needed |

  Worktrees at different paths shared entries. Test binaries were
  cached and restored, and the restored ones ran correctly.
- **At our scale** every repin rebuilt all of skein's and jig's crates
  in every worktree that took it, about 14 temper repins on 10-23. That
  is likely a large part of the 46% of gate time spent building, in
  build-infra's history of 797 gate attempts.
- **It also ruled out the invariant** that main always pins the latest
  upstream mains (landing-flow.md). Every upstream landing would have
  meant a full downstream rebuild on every machine.
- **Upstream** had not fixed it, in 1.2.2 or on main (9531006,
  10-23), and no issue covered it. The user chose to patch it
  ourselves and keep skein and jig standalone repositories, since other
  projects will use them. A single workspace with path dependencies
  would have avoided the defect.

## 4. The patches: kache 1.2.2-gitrev.2

One commit (`0f4075c`) on v1.2.2 (`96052b4`), four files, +262/−5,
almost all of it in `src/path_normalizer.rs` and its tests.

- **What it does.** It recognizes
  `$CARGO_HOME/git/checkouts/<repo>/<rev>`, where `<rev>` is 7 to 40
  hex digits, as a checkout root. Keys name that root
  `<GIT_CHECKOUT:<repo>>`, and rustc remaps it to
  `/kache/git/checkouts/<repo>`, so outputs don't name the revision.
  kache already treats a second worktree of a project this way. The
  repository's identity, paths inside it, source bytes and dependency
  digests all stay in the key.
- **It errs towards a miss.** A wrong hit gives a wrong build; a miss
  only costs time. Some units still name the revision in their output,
  so they keep it in their key:
  - units that read `CARGO_MANIFEST_DIR` or another path from the
    environment when they compile;
  - build scripts, and units built with `OUT_DIR`.

  Unknown checkout layouts also keep the revision. Patched keys live in
  a new namespace, and registry crates are keyed as before.
- **Our code is fully covered.** skein and jig have no build scripts
  and no `CARGO_MANIFEST_DIR` in library code. smith's one build script,
  in `smith-agent-shell`, embedded smith's commit and is being removed
  (the user, 10-24). temper is never a git dependency of anything.
  Third-party crates come from the registry, where the path names the
  version, not a revision.
- **Verified** on the spike's scenarios, with isolated stores:

  | Scenario | 1.2.2 hits / misses | patched hits / misses | Wall, 1.2.2 → patched |
  |---|---|---|---|
  | Leaf pin move | 0 / 15 | 10 / 5 | 14.6 s → 5.2 s |
  | Shared-crate pin move | 0 / 15 | 6 / 9 | 13.8 s → 8.5 s |

  Ten rlibs restored across pins matched independent cold builds byte
  for byte. kache's own suite: 6,101 passed; the 5 failures also fail
  on v1.2.2.
- **Upload bounds** in `scripts/infra/kache/upload-bound.patch`, applied
  second, retire a retryable upload after three attempted failures or 30
  minutes from the intent's first write, whichever comes first. Attempts
  and first-write time survive daemon restart; old intents start at replay.
  An open write breaker consumes age but no attempt when it makes no
  network request. Retirement releases the GC pin and requests a size
  sweep; the entry stays local until GC. Under `[cache]`, the new
  `remote_upload_max_bytes` defaults to 0 (unlimited) and rejects larger
  compressed packs before PUT; the fleet chooses 64 MiB. Neither this
  patch nor the executable version bump changes keys, schema 32, remote
  namespace/layout, or the local store format.
- **Pinned** through `kache-setup` at `1.2.2-gitrev.2`; the patch README
  records the binary digest and build time. The director places the
  binary at `tmp/kache/kache-1.2.2-gitrev.2` on each machine, and setup
  runs through `heavy --gate`, so no build runs while it swaps the
  wrapper. A new version clears that machine's local store once.
- **Its source** is kept in `scripts/infra/kache/git-checkout-rev.patch`,
  based on v1.2.2 (`96052b4`). `scripts/infra/kache/build` fetches the exact
  base, checks and applies both patches in order, and builds the static
  musl binary through `heavy`, with Rust 1.95.0. Its README names the prerequisites and how
  to compare the printed digest with the deployed pin.

## 5. The shared store

Central, not peer to peer. There is one store, and each build machine's
daemon puts it behind that machine's local store:
- It looks a key up locally first, then in the store, and compiles only
  if both miss.
- It uploads what it compiled in the background, so a build never waits
  on an upload.
- Machines never fetch from each other.

| Part | What |
|---|---|
| Network | Hetzner Cloud network `build`, 10.80.0.0/24: hetzner .11, hetzner2 .12, hetzner3 .13, hetzner4 .14, hetzner5 .15 |
| Server | Garage v2.4.1 on hetzner3, user unit `garage.service`, config in `~/garage/` |
| Endpoint | `http://10.80.0.13:3900`, region `garage`; RPC and admin on loopback only |
| Disk | volume `kache-store`, 120 GB, ext4, at `/srv/kache-store`, delete-protected |
| Bucket | `kache`, under kache's default prefix `artifacts` (`v3/manifests`, `v3/packs`, `v3/predictions`) |
| Access | one read-write key, `kache-fleet` |
| Limits | 100 GiB quota; objects expire 1 day after upload; `kache-prune.timer` holds the bucket between 70 and 80 GiB |

Why each choice:
- **Self-hosted** (the user): no third party holds our builds. The disk
  costs about €7 a month.
- **Garage.** S3 is kache's best-supported remote. Garage is a single
  static binary with quotas and S3 lifecycle expiry, and it runs as one
  node. Of kache's other remotes, GCS is a third-party service, and a
  shared filesystem would need a network mount on every machine, with
  no quota or expiry. An OCI registry was not weighed.
- **Central, on hetzner3.** All build machines are in one location,
  hel1, so one node is enough. In the trial a second machine pulled a
  whole jig build, 4.4 GB, in about two minutes (section 6). If the
  store is down, builds compile locally: slower, never wrong.
- **Private network only.** The S3 port listens on 10.80.0.13 alone,
  and the public address refuses it. hel8 isn't on the network, since
  it builds nothing.
- **Plain HTTP** (the user, 10-24). Only our five machines are on the
  network, and every request is signed with the key. TLS would need an
  internal certificate authority, and how kache handles trust roots is
  unverified. Revisit when a machine outside the network joins: x1 and
  carbon are left out for now, and they would need a tunnel anyway.
  `kache doctor` flags plain HTTP to a non-loopback endpoint; that is
  expected.
- **Every build machine publishes** (the user), with one shared key.
  Any key holder can write any entry, which is acceptable while the
  same agents run on every machine. kache's `remote_readonly` makes a
  machine read-only.
- **Expiry and pruning.** kache never deletes remote objects; the
  bucket's lifecycle rule does. The user chose 7 days, since main moves
  many times a day and a week-old unit is mostly dead. On 10-24 the
  bucket filled its quota within about 7 hours, at about 48 GiB per
  active hour, so it was emptied and its expiry cut to 1 day (director
  1021, 1026). A user timer on hetzner3, `kache-prune.timer`, checks it
  every 5 minutes and deletes whole entries, oldest first, from above
  80 GiB down to 70 GiB. The age counts from upload, not from last use,
  so a unit still in use is compiled again, by the first machine that
  misses it, once it expires or is pruned. One full jig build is 4.4 GB.
- **Its own disk.** The store can't fill hetzner3's build disk, and
  hetzner3's builds can't starve the store. With the quota full,
  Garage refuses writes: uploads fail in the background, builds go on,
  and sharing stalls until expiry frees space. kache keeps each entry
  it failed to upload pinned in the local store, where no collection
  evicts it: on 10-24 a full bucket grew local stores past their caps
  (77 GB against 20 GiB on hetzner) until disks ran out (director 1020,
  1041). The pruner keeps the quota from filling; the second patch bounds
  those pins (section 4). A Hetzner volume grows
  without downtime but never shrinks. Garage refuses to start unless
  the volume is mounted, so a missing volume can't turn into an empty
  store on the root disk.
- **Secrets.** Garage's own secrets are in `~/garage/garage.toml` and
  the fleet key in `~/garage/kache-fleet.env`, both 0600 on hetzner3;
  each build machine gets a copy of the key at rollout. The network and
  the volume were made with the user's Hetzner Cloud token, which is
  never given to an owner or a Codex task.

## 6. What builds cost now

A trial on 10-24 (jig `779e9288` on skein `7b380c29`, `cargo test
--workspace --no-run`) used isolated patched kache instances on
hetzner2 and hetzner, with the shared store:

| Step | Machine | Rust units compiled / restored | From the store | Wall |
|---|---|---|---|---|
| Cold, publishing | hetzner2 | 695 / 0 | 0 | 247 s |
| Empty local store | hetzner | 0 / 695 | 709 | 120 s, at load 11 |
| Skein pin moved, publishing | hetzner2 | 21 / 71 | 0 | 21 s |
| The same pin move | hetzner | 8 / 93 | 21 | 17 s |

- **Correctness.** jig's tests, run from the restored binaries, passed
  the same on both machines: 6,224 in the default profile, 121 in the
  fuzzy one.
- **Per unit.** A median of 514 ms to compile, against 182 ms to fetch
  and restore. Restoring a whole build is download-bound, at 4.4 GB.
- **The pin move** changed the source of 5 units (`skein-io`,
  `skein-shell`, `skein-sim` and `skein-world`), and 17 more units built
  on them changed only through their dependencies' digests. Everything
  hetzner2 compiled restored on hetzner. hetzner's 8
  compiles were units hetzner2 never reached, because both builds
  stopped on an unrelated API break.
- **What stays local:** on each machine, 20 build-script runs (kache
  never publishes those) and 16 C files of `ring`, the cryptography
  under rustls, which kache can't key safely. They take a few seconds.
- **Under owners' traffic** (`kache stats`, the 24 h to 10-25 05:10Z):
  52% of crates served from cache on hetzner3 to 87% on hetzner4, 11
  to 25% of those hits from the shared store.
- **Executables.** `cache_executables = false`, set on four builders
  as disk relief on 10-24 (director 999, 1021, 1041), passed 15,400 of
  hetzner's rustc runs in those 24 h through uncached, nearly all of
  them test binaries: about 5 h of its 5.7 h of compiling, against
  40 minutes of misses. The user had them cached again on 10-25, once
  disks had room: one temper test binary came back in 1.1 s from an
  empty target, against 9.0 s compiled.

## 7. Operating it

`scripts/infra/kache-setup` pins the patched binary and writes the local
store settings. When `~/.config/kache/store.env` exists, setup checks that
it is a regular file owned by the current user with mode 0600, before
stopping the daemon or changing anything. It never reads the key.

- The config at `~/.config/kache/config.toml` gets `[cache.remote]` with
  `type = "s3"`, `bucket = "kache"`, `endpoint = "http://10.80.0.13:3900"`,
  `region = "garage"` and `prefix = "artifacts"`.
- The user unit's `kache.service.d/20-shared-store.conf` loads
  `EnvironmentFile=%h/.config/kache/store.env`. The file supplies
  `KACHE_S3_ACCESS_KEY` and `KACHE_S3_SECRET_KEY` to the daemon.
- The daemon ignores S3 selection variables in its environment, so the
  remote belongs in the config; the key belongs in its environment.
- `[cache]` gets `cache_executables = true` and `prefetch_enabled =
  false`. Prefetch plans what a build might want and downloads it ahead
  of demand. In the 24 h to 10-25 05:10Z it downloaded 13,388 entries,
  76 GiB, on the five builders, and 657 of them were used, all on
  hetzner3: 1.6% of the builders' 40,875 hits, from the same Garage
  whose uploads were timing out. Remote-enabled machines also get
  `remote_upload_max_bytes = 67108864`: compressed packs above 64 MiB
  stay local without a PUT. With prefetch off, the daemon still checks
  the remote for each exact key it misses and uploads eligible entries
  (kache's `src/config.rs`, `prefetch_enabled`).
- Without the key file, setup removes the remote section and that
  drop-in: x1, carbon, hel8 and a machine awaiting its key stay local.
- Rerunning setup preserves the local store at the same kache version.
  Run it through `heavy --gate -- ~/src/rust/agents/scripts/infra/kache-setup`
  so the daemon restarts between builds. Plain HTTP is expected to be
  flagged by `kache doctor` (section 5).

The director rolls out one machine at a time: hetzner2, hetzner4,
hetzner5, hetzner, then the store's host hetzner3. Check the daemon and
`kache doctor` on each; an empty-target build on hetzner2 publishes and
the same commit on hetzner4 must show remote hits. Stop on setup,
store or subsequent cache-related gate failures. Measure remote hits
over the following day.

Day to day:
- **The store's limit,** kept by each machine's tend too: every 5
  minutes it runs `kache gc` when the store is past its limit
  ([fleet-watch.md](fleet-watch.md) 4), since the daemon's own
  collection fell behind twice on 10-27.
- **Health.** On hetzner3, `garage -c ~/garage/garage.toml status` and
  `garage -c ~/garage/garage.toml bucket info kache` give size, object
  count and quota (the config isn't at Garage's default
  `/etc/garage.toml`), and `kache-prune.service`'s journal the pruner's
  last run. On a build machine, `kache stats` (`--full` for the
  remote's transfers and their failures), `kache explain` for misses,
  and `kache doctor`. The doctor's Remote access check fails from a
  shell, since only the daemon's unit loads the key: the transfers in
  `kache stats --full` say whether the remote works.
- **When things fail:**

  | Failure | Effect |
  |---|---|
  | Store or network down | Misses compile locally |
  | An upload times out (30 s; large packs while hetzner3 is busy) | Another machine compiles the unit again; the pin is released after 3 failed attempts or 30 minutes from first intent, whichever comes first |
  | Quota full | No new uploads; pins retire after 3 failed attempts or 30 minutes from first intent, whichever comes first; breaker suppression without network uses age only |
  | kache version change | That machine's local store is cleared once. Remote entries under an old key namespace are dead until they expire |

- **Adding a machine:**
  1. Attach it to network `build`.
  2. Copy the key.
  3. Run `kache-setup` through `heavy --gate`.

## 8. Open

- **Upstreaming the patch.** Its patch and build recipe live in
  `scripts/infra/kache/`; offer the patch upstream later.
- **An alert** when the store nears its quota or stops answering.
- **Done: the pins of failed uploads.** `upload-bound.patch` in
  `1.2.2-gitrev.2` releases pins after 3 failed attempts or 30 minutes,
  including across restarts. The fleet's 64 MiB compressed upload limit
  keeps executables of about 100 MiB local: per-worktree test binaries,
  among the uploads that time out (director 1026).
- **Upload timeouts.** Packs of 13 to 37 MB time out at 30 s while
  hetzner3, which also builds, is busy: in the 24 h to 10-25 05:10Z
  hetzner5 failed 3,549 of its 7,276 uploads, most of them from 15 to
  22Z.
  Garage on a host of its own is the user's call, on measured need
  (director 1026).
- **One key per machine,** so a key can be revoked, if the fleet ever
  grows beyond our own machines.
- **x1 and carbon:** left out for now (the user). They would need a
  tunnel into the network.
- **Git-dependency units with build scripts or `OUT_DIR`** stay keyed by
  revision. None of ours will have one once smith's is removed.
