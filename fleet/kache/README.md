# Patched kache

The bootstrap recipe is independent of `old/`. The two patches were copied
unchanged from its reference kit: upstream commit
`96052b4842239bb216f6c4812054203c21550788` (v1.2.2), then
`git-checkout-rev.patch` (upstream change 0f4075c69cd1998242b4747c3a125f89896a8b64),
then `upload-bound.patch` (durable failed-upload budgets and the 64 MiB cap).
All source/install pins live in ../versions.toml. Git verifies the source commit;
Cargo --locked verifies registry dependency checksums; fleet-sync verifies the
musl 1.2.5 download against its declared SHA256 before extracting it.

Only explicit `fleet-sync --provision` builds, on a fresh/drained host whose
kache is absent. Any existing binary (including on PATH), config, service,
drop-in or cache footprint leaves the installation entirely to ops, even if
its version differs. A lost binary with retained state is not a fresh install. It uses
Rust 1.95.0 with the musl target, native musl headers, clang and Rust's rust-lld.
The compiler wrapper is disabled and CARGO_HOME and target are private staging
directories. No heavy/reconciler installation is required to bootstrap itself.
The output is checked for the pinned version and absence of an ELF interpreter,
then installed by sibling rename. The old binary is never edited in place.
The historical binary digest is recorded for comparison, not required of a
source build: the legacy recipe documented non-reproducibility. A build may
take about eight minutes; its timeout is 30 minutes. No cache is cleared.

config.toml renders the declared per-host cap and (floor + max(cap, 1)) GiB
recovery threshold. fleet/policy.toml makes this config and kache.service
check-only: normal runs compare and warn, without writes, ownership adoption,
enablement or restarts. The unit is excluded from candidate unit verification.
Only the same invocation that successfully installs an absent kache may write
these two files and enable/start the service. Subsequent runs leave it to ops.
A fresh machine runs local-only without shared credentials. Existing non-secret
remote selectors are compared only when its config already has [cache.remote].
Fleet never inspects store.env or drop-ins, and never changes existing cache or
store contents. Ops must agree host by host before any existing-install takeover;
shared-store setup and any drained-host restart remain operator procedures.
