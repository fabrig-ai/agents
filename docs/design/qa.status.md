# QA status

2026-10-30. Keeper: s/qa. Evidence scanner repair baseline: origin/main `35bae73`.
Contract: `docs/design/qa.md`, sections 2–8.

## Present

- **Custody is built.** `tools/qa/logins` implements exclusive holds, pooled
  fairness, immediate admission, run metadata and holder-checked returns.
  `tools/qa/test_logins.py` checks these with temporary HOME and fake logins.
- **Walks and their watcher are built.** `tools/qa/qa` implements exact-SHA
  slot preparation, disk admission, starts/resumes, deployment supervision,
  launch recovery, cleanup and notices. `fleet/units/qa-watch.service` declares
  the service; this task neither deploys nor inspects a running instance.
- **Starter mailbox routing is built.** `POST_NAME` accepts a validated full
  `NAME@MACHINE` address or a bare name qualified with the local machine.
  Queue admission and direct/queued resumes preserve the saved starter.
  In-process fake-service tests cover pass, pause and finding end recipients,
  local bare-name routing, queue/resume preservation and invalid-address
  refusal before any claim or login take. Contract: `docs/design/qa.md`,
  section 4, “Save the starter's mailbox”.
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
  Evidence scan repair 2 recognizes Authorization credential tokens and HTTP
  client user flags without refusing date's UTC flag or workflow placeholders.
  `qa keep NAME --omit PATH` binds a prior content refusal to its exact file
  SHA-256 and records the one reviewed omission in the immutable kept index.
  Changed bytes refuse before/after keep and before pruning; installed-copy
  and quarantine recovery retain the same checks. No unsafe-file/name/path
  bypass or automatic omission is added. No live watcher was inspected.
- **JSON contracts are built.** Both tools expose the metadata interfaces in
  design section 2. `tools/qa/fixtures/logins-list.json` and
  `tools/qa/fixtures/qa-queue.json` are checked against real CLI output in the
  respective test suites. This establishes producers, not deployed consumers.

- **Offline tests have fast and periodic files.** `tools/qa/test_qa.py` keeps
  193 cases (161 walk cases plus 32 evidence repair probes);
  `tools/qa/test_qa_periodic.py` keeps 49 unchanged integration cases, including
  two evidence publication matrices. All 74 custody cases remain in
  `tools/qa/test_logins.py`, with two added fixture-isolation regressions.
  Fresh state, cached production code, scoped injections, lazy metadata
  fixtures and bounded real crash/IPC children replace ordinary CLI startups.
  The framework rewrite left production code unchanged; the starter mailbox
  repair changes address resolution under design section 4. The evidence
  scanner repair adds nine in-process probes and changes preservation under
  design section 7. The current `tools/check.sh` selects gate or periodic
  files through `tools/gate.toml`.

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

The starter mailbox repair passes all 184 QA gate cases. Measured through
`tools/check.sh tools/qa/test_qa.py`, the file's CPU/wall seconds are
8.869/8.839 before and 8.465/8.445 after, within its 10-second CPU budget.
The full gate passes 35 files in 19.454 wall seconds (91.560 CPU seconds);
QA uses 6.901 CPU / 7.682 wall seconds there. The unrelated
`tools/test_land_reconcile.py` exceeds its report-only CPU budget; there are
no failed or unobserved files. Measurements use temporary HOME and fake
services. Details and the repair commit are in
`/home/free/src/fabrig/notes/q/qa-walk-notify-report.md`.

Evidence scan repair 2 before this rebase: nine new probes first reproduce the scanner false
positives and missing omit CLI. All 191 gate-file cases pass after the repair.
Measured through `tools/check.sh`, the file uses 12.168 CPU / 23.293 wall seconds
before and 12.776 CPU / 19.784 wall seconds in the final affected gate run. The 10-second CPU budget and
15-second wall budget are exceeded in both samples (report-only). All 269
QA, custody and smoke cases pass in that final run. The added
probes use fresh temporary HOME and fake services, with no live state or SSH.
The repair changes production code; applying it requires deploying this revision
and restarting qa-watch to reload the scanner. This branch performs neither.
The task report records the final affected gate result and commit SHA at
`/home/free/src/fabrig/notes/q/qa-evidence-scan-2-report.md`.

The earlier test-framework rewrite's verification follows for reference.

The framework rewrite preserves all 305 original case names: QA 231 becomes
182 gate + 49 periodic; custody keeps 74 and adds two context/crash regressions.
The starter mailbox repair adds two gate cases and extends existing invalid
input, queue and resume cases, bringing QA's gate file to 184 cases.
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
change in the framework rewrite. The starter mailbox repair requires updating
`tools/qa/qa` on the builder before new direct starts accept full addresses;
restart the QA watcher to use the repaired queue/resume routing in its process.
Existing saved walk starter addresses are preserved. The evidence scan repair
also changes production code: deploy its updated `tools/qa/qa` and
`tools/qa/evidence.py` and restart qa-watch to reload the scanner. Budget rows
remain unchanged; neither repair performed deployment or a watcher restart.
