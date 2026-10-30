# QA status

2026-10-30. Keeper: s/qa. Baseline for this test rewrite: origin/main `580a456`.
Contract: `docs/design/qa.md`, sections 2–8.

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

- **Offline tests have fast and periodic files.** `tools/qa/test_qa.py` keeps
  182 cases (159 walk cases plus 23 evidence repair probes);
  `tools/qa/test_qa_periodic.py` keeps 49 unchanged integration cases, including
  two evidence publication matrices. All 74 custody cases remain in
  `tools/qa/test_logins.py`, with two added fixture-isolation regressions.
  Fresh state, cached production code, scoped injections, lazy metadata
  fixtures and bounded real crash/IPC children replace ordinary CLI startups.
  Production code is unchanged. The current `tools/check.sh` has no tier
  selection and still discovers periodic files by default; explicit file runs
  verify the split until the gate owner's runner rollout.

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

The framework rewrite preserves all 305 original case names: QA 231 becomes
182 gate + 49 periodic; custody keeps 74 and adds two context/crash regressions.
The periodic assertions are unchanged. Focused whole-file CPU/wall samples
are QA 8.538/8.494 and 8.712/8.663 seconds; custody 1.841/1.642 and
1.918/1.710 seconds. The periodic file passes twice at about 67.5 CPU / 12.8
wall seconds. The full gate passes 29 files in 84.539 seconds, so the overall
minute target remains unmet by other suites (fleet-sync, after-landing periodic
and records watch each exceed a minute). Both focused gate files and the
periodic file pass; all measurements use temporary HOME/TMPDIR, fake services
and local Git origins. See the assigned measurement report
`/home/free/src/fabrig/notes/q/qa-gate-budget-report.md` for two before/after
CPU and wall samples, the evidence-case classifications, full-gate result,
case-name accounting and commit IDs. Neither production code nor budget rows
change, and this branch requires no machine action or watcher restart.
