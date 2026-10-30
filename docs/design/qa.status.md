# QA status

2026-10-30. Keeper: s/qa. Baseline for walk preservation: origin/main `e98c22d`.
Contract: `docs/design/qa.md`, sections 2–7.

## Present

- **Custody is built.** `tools/qa/logins` implements exclusive holds, pooled
  fairness, immediate admission, run metadata and holder-checked returns.
  `tools/qa/test_logins.py` checks these with temporary HOME and fake logins.
- **Walks and their watcher are built.** `tools/qa/qa` implements exact-SHA
  slot preparation, disk admission, starts/resumes, deployment supervision,
  launch recovery, cleanup and notices. `fleet/units/qa-watch.service` declares
  the service; this task neither deploys nor inspects a running instance.
- **Queue, retries and orphan claims are built.** Starts/resumes retain
  dependencies and admission identity; end steps retry independently; idle
  orphan claims require grace and token-checked release. Ordered per-kind slot
  lists define caps and resume affinity. `tools/qa/test_qa.py` covers these
  through fake services, claims, disk observations and local Git origins.
- **Walk evidence and retention are built.** `qa keep NAME`, the final-end
  scanner, immutable local snapshots, opt-in private branch publication,
  retried refusal/status notices and guarded seven-day pruning share the walk
  service. Durable pin/unpin and scratch-byte reservation/measurement protect
  retained work and queue starts over budget. Remote publication defaults off.
  Temporary-HOME tests cover scans, publication recovery and deletion guards.
  Review repairs add componentwise path scans, bounded enumeration after all
  custody cleanup, saved device/inode identities with verified quarantine,
  concrete retention times, stable resume accounting and explicit two-setting
  publication activation. Older walks without saved identities are retained.
  Scratch sizing now streams metadata with a shared ten-second deadline per
  walk and no evidence entry/depth caps. Incomplete sizing charges the larger
  of saved reservation and counted bytes, with one retried notice. Per-walk
  exception handling keeps measurement, preservation and pruning retryable
  while other walks and later watcher passes continue.
  Repair 3 makes queue, claim/orphan release, launch and evidence-refusal notice
  identities stable by operation. Diagnostic changes refresh the same receipt
  without resending accepted messages; manual measurement shares that path.
  Added repair probes run in process with fresh HOME and fake services.
- **JSON contracts are built.** Both tools expose the metadata interfaces in
  design section 2. `tools/qa/fixtures/logins-list.json` and
  `tools/qa/fixtures/qa-queue.json` are checked against real CLI output in the
  respective test suites. This establishes producers, not deployed consumers.

## Plan differences and remaining gaps

- **Passes are not built or activated.** `tools/qa/passes.md` is provisional;
  its sections 12–13a specify producer prerequisites, implementation boundaries
  and rollout. The current tool admits no passes and manages no old pass state.
- **Pass evidence/results are not built.** The walk scanner and publisher are
  ready for reuse, but required pass reports/details, authority and publication
  lanes in `tools/qa/passes.md`, sections 7, 9, 10 and 13a, remain future work.
- **Live tiers between walks are not built here.** Director decisions
  0007/0001 are external context supplied by the coordinator, not decision files
  in this checkout. Concrete tier enrollment and scheduling remain to agree.
- **Records changes are paused by the user.** The first pass version must use
  section 13a's QA-owned publication path and existing read-only after-landing
  facts. Earlier proposals for QA records writers/events are deferred.
- **Reaper coordination is a boundary, not a new implementation claim.** This
  checkout's QA tests establish QA's custody/cleanup behavior, not acceptance
  of another owner's reaper or a live pipeline-watch integration.

## Verification

`bash tools/check.sh` runs `tools/qa/test_logins.py` and
`tools/qa/test_qa.py` along with the repository gate, with isolated temporary
HOME and fake services. This branch runs only
`python3 -I -B tools/qa/test_qa.py`, as assigned. The original feature run
passed 208 tests; the first repair run passed 220 and repair 2 passed 230.
Repair 3 passed 231 tests in 86.691 seconds (86.902 seconds shell wall time;
274.626 seconds CPU). One new in-process regression test covers 100 changing
queue failures plus claim/orphan release, evidence refusal, measurement and
overdue-launch notices. All 23 in-process probes passed separately in 1.220
seconds (1.395 seconds CPU), with no child interpreters.
The 208 existing child-isolated cases are unchanged in count. The full suite
still exceeds the ten-second per-file CPU budget; the suite framework rewrite
is separate work.
No full gate or live service tests were run. Deployment requires matching `qa` and
`evidence.py` plus a watcher restart. Remote publication requires explicit
configuration of both private repository and branch; no service is deployed here.
