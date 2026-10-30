# Slot tools status

Copied with codex-run from fabrig 9a0594837 on 10-30. PATH and the `claim`
link remain on fabrig pending handover; central claims and existing local slot
maintenance paths are unchanged. No installed row or activation change is added.
The original claim, guard and trim suites already use agents' gate naming.
The full recovery suite is `test_recovery_periodic.py`; `test_recovery.py`
selects four fast authority/lifetime contracts from it. The recovery test for
completion ordering now runs the real lifetime helper across a Git checkout
and restoration; full queue/precheck integration remains with the queue move.
Owner `ops` uses the repaired gate's `[files."path"]` rows in
`tools/gate.toml`; selectors cover launcher/slot cross-dependencies, and
filename suffixes determine tiers. The old base still discovers periodic
files too; landing requires the coordinator-supplied repaired gate on main.

Automatic idle-target policy (`tools/slots/design.md`, 5.5–5.6): FIRSTDAYDRYRUN.
`--automatic-targets` defaults to observation; live refuses before claims or local
state while the source gate remains set. Observational candidates stay PROTECTED.
The gated consumer uses an exact persistent ops claim on hel8, strict owner
final.json records, completed lifetimes, repeated source/target/history/process/
borrower proofs and durable terminal evidence before exact release. It is
exercised only in isolated fixtures. Producer integration and fleet lifetime
coverage remain prerequisites for Ops-reviewed activation; no finality backfill,
deployment, timer or activation change is included. Existing manual acknowledgement
recovery and executable trimming remain separate. Uncertain automatic claims are
retained for operator reconciliation.

Safety repair: unsupported common-directory layouts refuse; source/target directory
identities protect cwd aliases; exact active maintenance fds require matching kernel
flock metadata. Eligibility is filtered before acquisition intent, and only exact
source-established ordinary refusals become retryable no-acquisition terminal
records. Ambiguous/transport failures and all post-acquisition uncertainties stay
retained. Fully inventoried internal hardlinks are supported; external/unaccounted
links refuse. Nonzero 40/64-hex final OIDs are supported; producer second-precision
timestamps are NOT accepted when earlier than ended nanoseconds. Producer precision
alignment and all rollout prerequisites still block activation.

Central SSH transport uses the shared fixed HEL8 endpoint free@204.168.210.29,
with normal host-key checking and login-shell quoting. No short-alias DNS,
environment override or local-authority fallback is required.
