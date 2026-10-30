# Gate status

2026-10-30. Owner: s/deploy. Contract: `docs/design/gate.md`, sections 1–4.

## 1. Selection and budgets

Implemented in `tools/gate.py` and `tools/gate.toml`: tier/changed/explicit
selection, safe fallbacks, smoke, owners, wait4 CPU and wall tables, optional
JSON, report-only defaults and named enforcement. OS CPU caps apply when
enforcement is enabled; wall backstops always apply. Wall-starved files stay
unobserved and cannot authorize a landing.

## 2. Claimed landing

`tools/land` claims centrally, ships a full-history bundle, checks at low
priority, handles one upstream race and releases its exact claim in finally.
Dry-run exercises this flow without push. Local fallback is explicit.
Disposable SSH/claim/git fixtures cover shipping, release on red/interruption,
lost claim replies, race overlap, refusals and plain pushes (`tools/test_land.py`).

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
the requested budgets, and wall-starved files prevent landing. Enforcement
remains false; no budgets were raised to hide the measured costs.
See the task report for real hetzner7 dry-run and full-gate measurements and
focused validation. This branch is pushed for review, not landed.
Machine action after landing: fleet-sync installs the new timer on hetzner3;
no manual enablement or machine changes were performed by this task.
