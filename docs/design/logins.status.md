# Agent login custody status

2026-10-30. Owner: s/deploy. Contract: `docs/design/logins.md`, sections 1–5.

## Present

- Capture, prepare, register and list exist in `tools/logins/agent-logins`.
  The manifest installs the separate `agent-logins` command.
- Snapshots stay bound and changed hashes retain previous entries. Only
  signed-in shelf logins register as free. No lending commands exist.
- Exact modes, ownership, no-follow paths, one-link credentials, global locking,
  private temporary files and atomic state replacement are implemented.
- `tools/logins/test_agent_logins.py` supplies offline fixtures for the complete
  capture/sign-in/list flow, races through the lock, refusals and privacy.

## Gaps and departures

- Remote cat/sha256sum use a no-follow O_PATH helper instead of opening source
  pathnames directly. This preserves the streaming contract while pinning the
  checked inode. Remote Linux, Python 3 and coreutils are required.
- No live capture or shelf sign-in was run. Operational acceptance belongs to
  the user after review. No fleet or service action is performed by this branch.
- Lending/return/swap, recovery of interrupted commits and snapshot unbinding
  remain deferred as described in the design's Later section.

## Verification

`tools/check.sh tools/logins/test_agent_logins.py` passed all 17 offline tests.
The full `tools/check.sh` result is recorded in the task report.
