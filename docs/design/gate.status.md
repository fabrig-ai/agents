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
these behaviors.

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
Existing companion `load_tests` hooks already exclude inherited cases. The
base fleet behaviors are partitioned for per-file accounting, with no aggregate
CPU saving claimed and no change to the 100 s tier budget.
No existing behavior was moved to periodic solely because it was slow.

## 4. Remaining boundaries and validation

Remote branch protection and trusted lock-marker verification remain deferred.
The 60 s green-merge target is **not met**: current full-suite costs exceed
the requested targets. Report-only measurements now retain the full selection;
any starved file still prevents landing. Enforcement remains false; the CPU
and merge-wall targets remain unchanged.
See the task report for real hetzner7 dry-run and full-gate measurements and
focused validation. This branch is pushed for review, not landed.
Machine action after landing: fleet-sync installs the new timer on hetzner3;
no manual enablement or machine changes were performed by this task.
