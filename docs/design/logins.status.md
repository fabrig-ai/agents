# Agent login custody status

2026-10-30. Owner: s/deploy. Contract: `docs/design/logins.md`, sections 1–5.

## Present

- Capture, prepare, register, list, release, lend and swap exist in
  `tools/logins/agent-logins`; `tools/installed` supplies the command.
- Bound/lent entries are stale placeholders. Release verifies a fresh copy back,
  removes the machine file and records free. Lend requires an empty host path,
  verifies the copy out and records lent. Shelf copies are never used in place,
  except prepare's one-time sign-in. Swap holds one lock across both halves.
- The optional pending journal blocks all commands after uncertain destructive
  transfers. Known checksum failures restore the old shelf or remove the new
  host copy. Kind/origin remain provenance; hashes and move history track returns.
- Exact owned modes, no-follow paths, one-link credentials, write-only receive
  descriptors, private temporary files and atomic metadata are implemented.
- Offline tests cover inventory and transfers, refreshed credentials, mismatches,
  swap failure, host-path refusal, dry-run, locks, privacy and pending guards.

## Gaps and departures

- Remote operations use Linux O_PATH guards and standard-library helpers around
  cat/sha256sum. Installation uses same-directory link/unlink for no-overwrite
  publication. Linux, Python 3 and coreutils are required on remote hosts.
- Ambiguous SSH outcomes require operator reconciliation, not automatic retry.
  Historical bound snapshots remain unavailable; release selects a lent entry
  first, otherwise the latest bound capture. Account-level deduplication and
  recovery tooling remain in Later.
- No real capture, release, lend, swap or shelf sign-in was performed. First live
  use and stopping credential consumers belong to the user after review.

## Verification

Run `tools/check.sh tools/logins/test_agent_logins.py tools/test_fleet_sync_3c_manifest.py`
with offline fixtures: 35 custody tests and 1 manifest test passed (2 files,
0 failures, 41.245s). No full gate was requested for this follow-up.
