# Patched kache

The bootstrap recipe is independent of `old/`. The two patches were copied
unchanged from its reference kit: upstream commit
`96052b4842239bb216f6c4812054203c21550788` (v1.2.2), then
`git-checkout-rev.patch` (upstream change 0f4075c69cd1998242b4747c3a125f89896a8b64),
then `upload-bound.patch` (durable failed-upload budgets and the 64 MiB cap).
All source/install pins live in ../versions.toml. Git verifies the source commit;
Cargo --locked verifies registry dependency checksums; fleet-sync verifies the
musl 1.2.5 download against its declared SHA256 before extracting it.

Only explicit `fleet-sync --provision` builds, on a fresh/drained host. It uses
Rust 1.95.0 with the musl target, native musl headers, clang and Rust's rust-lld.
The compiler wrapper is disabled and CARGO_HOME and target are private staging
directories. No heavy/reconciler installation is required to bootstrap itself.
The output is checked for the pinned version and absence of an ELF interpreter,
then installed by sibling rename. The old binary is never edited in place.
The historical binary digest is recorded for comparison, not required of a
source build: the legacy recipe documented non-reproducibility. A build may
take about eight minutes; its timeout is 30 minutes. No cache is cleared.

config.toml renders the declared per-host cap and (floor + max(cap, 1)) GiB
recovery threshold. Existing user-owned regular 0600 store.env is inspected
with stat only: when present the non-secret remote selectors and unit drop-in
are rendered. A fresh machine needs no shared credentials and runs local-only.
The optional shared credential is restored by the operator outside git.
An existing drop-in without that file needs operator removal before starting
the service. Fleet never opens, copies or removes store.env. Changes to an
already-running daemon require an operator restart on a drained host.
