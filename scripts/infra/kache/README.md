# Rebuilding the fleet's kache

`git-checkout-rev.patch` is commit `0f4075c69cd1998242b4747c3a125f89896a8b64`
on upstream v1.2.2, `96052b4842239bb216f6c4812054203c21550788`. It changes
four files in [kache](https://github.com/kunobi-ninja/kache).
`upload-bound.patch`, applied second, makes the version `1.2.2-gitrev.2`:
failed uploads release their GC pins after three attempted failures or 30
minutes from first intent, with durable budgets across restarts. It also
adds `remote_upload_max_bytes` (default 0, unlimited); the fleet sets
64 MiB so large test executables stay local. Neither this second patch nor
the version bump changes cache keys, schema, remote namespace/layout or
local store format. Source and licenses are fetched with the build. Their
behaviour and verification are
[build-cache.md, section 4](../../../docs/design/build-cache.md).

Run from an agents worktree, naming a new absolute scratch directory:

```sh
scripts/infra/kache/build "$HOME/src/rust/tmp/kache-rebuild"
```

The script fetches that exact base, checks and applies both patches in
order, checks the musl 1.2.5 source archive's SHA-256, and queues the
header generation and Cargo
build together through `heavy`. It uses Rust 1.95.0's musl target, clang
with musl headers, and Rust's bundled musl libc and `rust-lld`, producing
a static x86_64 Linux binary at `out/kache` in the scratch directory.
The machine must already have Rust 1.95.0 with the
`x86_64-unknown-linux-musl` target, clang, make, ar, readelf, curl and git;
the script installs no tools or system packages.

The scratch directory contains its own Cargo home and target; the build
runs with the rustc wrapper disabled. It neither installs the output nor
starts a daemon. Remove that scratch directory after keeping the output
and its `out/SHA256SUMS` if needed.

The script prints the digest and compares it with the fleet pin. A new
build is an artifact for the director to verify and place; the script
never installs it or runs setup.

Migration: the director places `kache-1.2.2-gitrev.2`, then runs
`heavy --gate -- kache-setup` on one drained machine at a time. Setup's
existing version-change policy clears that machine's local store once.
Old upload intents start their age at replay. Rollback: restore the prior
version/digest in setup and rerun it through the gate with that artifact
present; this also clears the local store. The old binary ignores the new
intent fields, but restores unbounded retries and unlimited pack uploads.

The earlier gitrev.1 recipe was verified on hetzner2, 2026-10-24: release
build 7m56s, static binary SHA-256
`d9ba88fb73359c05625ef19a6734082a7152b4c7198c7547a20dd9ba47f53309`.
It did not reproduce the then-deployed `93f8551e…` digest; byte-for-byte
reproducibility remains open.

Verified 2026-10-25: the gitrev.2 release build passed in 7m55s (queued
payload 478 s, queue wait 2 s). `out/kache` reported
`kache 1.2.2-gitrev.2`, was 28,592,984 bytes, and `readelf -l` showed no
dynamic interpreter. Its SHA-256, now pinned by `kache-setup` and this
recipe, is `91fb6aa7d7ddd427e3e2732aa346ce116fbf075df0c871e1148bf309aaadafaf`.
The director places and rolls out this artifact; it has not been installed.

## Local cap rollout

Setup writes `gc_evict_shared = true` and `auto_gc = true`: the budget
includes blobs retained by target files, whose links survive eviction.
`auto_recover_min_free_bytes` is `(PLAN_MIN_DISK_GB + KACHE_MAX_GB)` GiB
(with at least 1 GiB above the floor), so recovery begins before heavy
refuses work. `KACHE_MAX_GB` and `PLAN_MIN_DISK_GB` keep their defaults
and environment/file precedence. The cap counts registered blob bytes,
excluding the index, metadata and staging files.

After landing, run `heavy --gate -- /path/to/scripts/infra/kache-setup`
on one builder at a time, then `heavy --gate -- kache gc --json` and
`kache stats --json`. The pinned version stays the same, so setup keeps
the store. Shared bytes removed from the namespace may remain on disk
until their target files go. Upload intents and recently accessed entries
can temporarily prevent reaching the cap; inspect GC pin counts and wait
for the pinned upload retry budget and active-use grace before sweeping
again. This config does not retire upload intents.

Rollback: revert the cap-config commit, land it, and rerun setup through
the gate. This restores reclaimable-only budgeting and recovery at the
heavy floor; it cannot restore evicted cache hits. No cache keys, binary,
remote selectors or credentials change in this rollout.

During a remote outage, set `KACHE_LOCAL_ONLY=1` in each builder's
`tmp/machine.env` and rerun setup through the gate. The default is 0;
environment values 0/1/false/true override the file. Setup writes
`cache.local_only`, retaining the remote selectors and credential drop-in
for later recovery. Kache then retires replayed upload intents itself
without remote I/O and stops creating new ones, so upload pins cannot
hold the namespace above its cap. After Garage is intentionally restored,
set the machine key to 0 and rerun setup through the gate. Ordinary upload
pins can again temporarily exceed the size cap in remote-enabled mode.
The stopped Garage service and its settings are outside this rollout.
