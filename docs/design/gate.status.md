# Gate status

2026-10-30. Owner: s/deploy. Contract: `docs/design/gate.md`, sections 1–4.

## 1. Selection and budgets

Implemented in `tools/gate.py` and `tools/gate.toml`: tier/changed/explicit
selection, safe fallbacks, smoke, owners, wait4 CPU and wall tables, optional
JSON, report-only defaults and named enforcement. OS CPU caps apply when
enforcement is enabled. Report-only runs complete past budget targets, with
`OVER (report-only)` labels and a separate 900 s safety cap. Enforced runs
retain file and merge-wall hard limits. Killed/starved files always fail and
stay unobserved. Slow-completion, enforced-kill and hang-guard fixtures cover
these behaviors. Workers reap adopted zombies during execution as well as
at teardown, preserving process-group exit observations and CPU accounting.

## 2. Claimed landing

`tools/land` and `tools/land_remote.py` require a received exit, empty process
group, removed directory and clear read-only heavy observation before normal
release. Unknown ends/restoration retain the claim and durable private record;
`--reconcile [CLAIM]` inspects first, and requires `--kill` to terminate a live
run. SSH-drop, unseen-interrupt, live/ended reconciliation, restoration-drop
and heavy-submission fixtures use only private HOME, fake services and remotes.

Successful main pushes clean up only matching remote branch tips and, unless
`--keep-branch`, the local branch. The pre-push guard also covers movement
between the first observation and deletion's handshake; it chains existing
hooks without forcing updates. Both budget modes and report-only wall overruns
are printed and tested. Coverage: `tools/test_land{,_races,_reconcile,_branches}.py`,
`tools/test_check.py`. Disk admission reads HOME availability over SSH before auto claims, skips
low/unknown readings and prefers most free space; fixtures cover both the
85 GiB and higher plan floors. Restoration explicitly verifies and prints
removal of the gate's private temporary directory.

## 3. Periodic and cost

The two-hour builder units render only for flagged hetzner3; the service checks
the flag too. `tools/periodic` runs both tiers and mails file owners or ops.
Existing companion `load_tests` hooks exclude inherited cases. The combined
candidate adopts s/deploy's component fixtures and periodic compatibility
split; all 55 original fleet test method names remain represented, and the
six obsolete gate batches are removed. The cut's legacy lander fixtures are
superseded by the new gate's dedicated landing/race/reconciliation coverage. Historical rollout comparisons stay
pinned. Every discovered gate/periodic file has an owner row; QA limits are
10/15 s for test_qa and 3/8 s for test_logins (CPU/wall). Enforcement stays false.
Main's QA split is integrated: `tools/qa/test_qa_periodic.py` is periodic,
owned by s/qa, and included in the QA selector. The gate-land-2 report records
full-selection and periodic measurements after rebasing onto the QA cut,
including actual targets, ownership totals and claimed builder restoration.

## 4. Remaining boundaries and validation

Remote branch protection and trusted lock-marker verification remain deferred.
The preceding gate-land-1 measurement exceeded the 60 s merge target.
The gate-land-2 report supplies updated measurements after the QA split.
Acceptance depends on observed file, tier and merge budgets; report-only
labels or starved files cannot establish a passing candidate. Enforcement remains false; the CPU
and merge-wall targets remain unchanged.
See the task report for real hetzner7 dry-run and full-gate measurements and
focused validation. This branch is pushed for review, not landed.
Machine action after landing: fleet-sync installs the new timer on hetzner3;
no manual enablement or machine changes were performed by this task.


## 5. Review fixes, 2026-10-30 (gate-fix-1)

Added regressions before each fix: advancing local HEAD during a paused remote
gate previously pushed an unchecked descendant; dropped/interrupted uploads
previously released their claims; archive periodic runs lacked history; wall-only
notices omitted their owners alone and alongside another file's notice.

Landing now holds a checkout flock continuously, including local host-lock
waiting without re-exec, pins the bundle/checkout/receipt/push SHA,
refuses unexpected HEAD movement and records exact no-overlap rebase SHAs.
Upload intent is durable before SSH; a remote barrier publishes writer/group
and wrapper identities before copying. Unknown uploads retain the claim and
receipt until reconciliation proves both ended. Private release-pinned Git
snapshots supply periodic history; notices include wall-only budget overruns.
Coverage adds `tools/test_periodic.py` and extends the landing/race/reconcile
fixtures. The unit fixture follows the declared flag and exercises re-enablement.

Enforcement and budgets remain unchanged. Periodic remains paused at ed5c048;
the coordinator will re-enable AGENTS_PERIODIC on h3 after landing. This branch
requires no machine action before review and is pushed without landing.
Validation and actual auto-host dry-run timing are in the gate-fix-1 task report.


## 6. Follow-up repair, gate-fix-1b

Unit rendering coverage derives the enabled host set from the current
AGENTS_PERIODIC declarations and exercises a separately flagged fixture host;
main's entirely paused host list passes. The fleet selector now includes all
landing fixture files, disk admission and periodic coverage; a smoke regression
checks fleet host/unit selection against declaration readers in both tiers.

Local bundle scratch has a durable identity and exact local_dir in the claim
record before remote dispatch. Known failures/successes remove it; unknown ends
retain it until reconciliation proves restoration. Failed-gate, interrupted and
dropped-upload/wait fixtures assert local removal or retention as appropriate.
Builder allocation recovery distinguishes local scratch when fake SSH shares a
filesystem. Two prepare-only allocations from failed fixture development were
verified to lack any launch/upload artifacts, recorded and removed on hel8.
No periodic flag or budget change is included; this remains an append-only
review branch. The gate-fix-1b report records final checks and auto-host timing.
