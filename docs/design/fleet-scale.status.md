# Fleet scale status

2026-10-30. Implements `docs/design/fleet-scale.md` sections 2–5 in
`tools/fleet-scale/`, `fleet/pool.toml`, `fleet/pool.py`, bootstrap and
fleet-sync pool resolution, and session-role mirror units.

The implementation relays pinned peer artifacts through hel8, with verification
at both ends, because git-only member authorization cannot run seed exports.
Deletion precedes final deregistration so interrupted API deletion remains
tracked and cleanable. Authorization and known_hosts changes retain backups.
Mirrors are served through the exact-path mirror-serve forced command;
pre-receive hooks provide additional protection.

Validation uses disposable HOMEs, a loopback fake API, fake SSH/scp and local
key utilities. No real Hetzner call, key registration, hel8 SSH edit, or server
creation/deletion is part of this implementation task. No rebuild is proven.
Land the fleet-sync parser commit alone, wait for all fixed-host timers to
adopt it, then land the declarations/helpers commit. Older runners parse the
candidate fleet tree before exec and would reject pool.py in one landing.
Real acceptance follows both reviewed landings and mirror adoption.

Heavy's current upstream source (fabrig main 059851a6bd8c) has no status
subcommand. Drain reads its version-1 snapshot under the existing shared host
lock and requires every task released, without changing heavy state. A missing
or unsupported snapshot fails closed; --force requires an independent drain.
Open: real rebuild/teardown acceptance by the user. The login pool (section 6),
consumer adoption and automatic decisions remain Later.

Scale-1b separates the exact hel8 kache source from the member destination.
Missing/insecure sources fail before allocation/API; --local-only-kache skips
source access, records the choice and persists its machine_env override in the
member's non-secret 0600 settings. Shared templates omit KACHE_LOCAL_ONLY and
new-member bootstrap installs remote selectors/drop-in after credential
streaming, then restarts that fresh cache. Existing fixed-host policy is unchanged.
Tests use synthetic credentials only; no live source is read by this task.

Scale-1c closes all six independent-review findings: exact read-only mirror
commands, isolated 0600 host trust and exact-line removal, recorded-id-only
deletion, bounded uncertain-create reconciliation with a ten-minute visibility
grace, and build-network attachment plus private-address/TCP readiness checks.
Debian 13 cloud-image DHCP remains responsible for the private NIC; bootstrap
adds iproute2 and no network manager overrides. Kache has no documented
read-only remote status command, so the bounded TCP probe is the store check.
The fixture now covers all eight pin commands and all six peer artifacts,
including tree formats, plus a real Git fetch without sshd. No live rebuild,
DHCP or authenticated store acceptance has been performed.
