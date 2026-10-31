# Backlog: the pipeline, its tools and its next ideas

Provisional, 2026-10-29. Kept by the coordinator and the operator: what is decided and not yet done, and the ideas to try, each with what would show it is worth it. Incidents and their remedies are in `agents/ledger.md`; this file is what comes next.

## 1. In one page
- **Throughput is the goal:** (1) a pipeline that widens, (2) short builds on warm caches, (3) no spurious blocking. An item names which it serves.
- **Data before structure:** an idea that changes the code's shape (crates, tiers) waits for the numbers that justify it; collecting them is an item of its own.
- **Done items leave this file;** what they taught goes into the ledger or a role file.

## 2. Queue and gate
- **Final-candidate reader evidence (3):** recurring ledger57/75/86/106/121/126 requires executable readiness enforcement, not another lead rule. Green/QA define graph-derived and declared semantic/profile readers; Ops binds complete nonzero execution receipts to the exact candidate, merged tree/main and configuration, invalidates them after edits, and refuses missing/stale evidence at ready publication and queue intake. Precheck currently compiles Rust tests without running their assertions; exact-tip compile success is insufficient. Source design precedes implementation after the active publication-producer branch.
- **Merge train (1), paused:** the user retired hetzner2 for this phase on 2026-10-29: capacity is subscription-bound and the builders and queue are lightly used. Release its second-prover reservation; pause the two-gate train and transport work that requires it until measured queue busy time is again most of the available time. Keep the existing controller/prover disabled and retain the unlanded transport work and evidence. Revisit a second gate only after that bottleneck returns and a machine is explicitly assigned; h8 continues ordinary batch16.
- **Cheap precheck invariants (3):** compile-only prechecks missed Jig vocabulary held by jig-boundary (ledger57). Jig now runs it manually. Inventory the other trees’ equivalent cheap invariant suites, measure their cost, then add an explicit touched-tree mapping to precheck beside clippy and test compilation, ordinary heavy and existing budgets/admission/restoration. Do not silently run whole suites or weaken the gate; this follows the pending corrected-precheck deployment.
- **Process tiers after phase D (3):** Green owns the process-tier definitions, pinned baselines and CPU/running-set measurements. Ops operates the after-landing runner and reports its coverage/faults; it starts no competing nightly or baseline job. The next Green measurement starts around13:30UTC on2026-10-30, under decisions0010/0012, and records cold profile pairs and complete configured-set peaks.
- **Partitioned full runs (2):** nextest `--partition` across two gate machines for the periodic full run.
- **Binaries a test runs (3):** a test that runs another package's binary passes only when something built it. Either each such test gets its own package's target (as smith's program check did), or the queue's selection adds the providing package (`tools/queue/binaries.txt`). 88 such launches, mostly browser tiers (hetzner2 `~/src/fabrig/notes/smith-hermetic-report-2.md`).
- **Starved counts (3):** count `skein-world: starved:` lines in passing tests' output per (binary, test), reported apart from passes and failures (testing-strategy 2.10).
- **CPU seconds per test and suite (3):** decision0010 assigns Green the single tiers wrapper, attempt record and completeness/budget summary; Ops consumes its reviewed schema in the queue after QA publication-producer review. CPU-budget excess is red; wall-limit starvation is a warning. The user supplies budget values; no competing wrapper, budget raise or test move to escape a red.
- **Checks the old gates ran:** wasm32 clippy (the browser client) first, then darwin clippy, skein's fail_stop.py, taste.sh, check-contracts, recovery-shape: the ones still worth it.

## 3. Machines and tools
- **Bounded warm slots (1, 3):** director decision0012 supersedes resize plans. Measure complete default/fuzzy, bundle and after-landing profile-set running/peak demand; budget approximately1.3–1.5times it; sweep proven-unused generated artifacts after task/lifetime closure; reserve and contain per-slot growth. Fit heterogeneous slots plus kache cap, role overhead and5–10GB operation reserve within each filesystem and CPU/RAM. Green owns baseline measurements, Ops heavy/slots/gate integration, QA H6 boxes/login budgets, deploy platform/provisioning. Keep current transition floors until all controls pass; a free-byte floor or polling size alone is not a hard slot bound. No resize or unapproved provisioning.
- **Every tool in fabrig (2, 3):** `codex-run` first, then `heavy`, `post`, `kache`'s setup, the rest, each moved, fixed and installed by `tools/install` from `~/src/fabrig/main`.
- **Elasticity (1, 2):** capacity follows the bottleneck of the moment: gate machines when the queue is the wait, builders when tasks wait for slots, leads when slots idle for want of tasks. Needs the hourly numbers (the operator's) first.

## 4. Code shape (data first)
- **Crate granularity (2):** per crate: build time (cargo `--timings` of a full build), how often it changes (git log per crate path), rebuild fan-out (its reverse dependencies and their build cost). A crate that changes often and drags a large fan-out is a split candidate; one that never changes alone may merge.
- **Wave 2.5 effect (2):** measure the queue’s build step and targets’ size before and after the completed one-binary-per-package consolidation.
- **Tiers we dropped for the spike (3):** browser, process, live, qa: their scripts assume per-tree targets and profiles the root `.config` lacks. First, a periodic run outside the gate (nightly, or after each wave) of the test targets no gate selects, temper's `qa_` binaries and the process tier, reporting failures to the tree's lead: retained `qa_` stories failed unchanged on main with nobody told (ledger 52; `qa_github_land`'s checked-head story from 10-28 until its fixture was fixed on 10-29). Restore the rest once the spike's numbers are in.

## 5. More than one designer
- **Operator effort (1, 3):** measure the Codex operator’s response times and missed incidents at high before deciding whether to try medium.
- **Crate leases (1):** one writer per crate across designers: a registry like the slots' claims, per wave.
- **Interfaces by expand, move, contract (1):** additive upstream changes let designers work at once; a skein lead shared by the designers orders the removals.
- **Mailboxes per designer;** the queue posts the branch's lead; the operator gets the rest; the ledger and operations are shared.

## 6. The ladder's findings off the happy path (qa)

Kept by coordinator q (s/qa). v0.1.0's happy path is the ladder's stories used as intended on the
four backends (temper `docs/design/draft/v0.1.0.md`, 4); a walk's finding off it waits here, by
the user's rule (10-29 13:35Z), until v0.1.0 is out or a walk shows it is on the path. Each line:
what, whose code, the evidence.

### 6.1 jig

- **A refusal names no tool family.** `Finding::Tool` carries no family or source, so a chat's
  refused `decide_escalation` reads "Authority refused: tool family; tool family; tool family;"
  (one per authority level checked: task, project, deployment). Rung A walk 12 attempt 2,
  hetzner6 `~/src/rust/tmp/qa-focused/rung-a-12/evidence/a2-empty-chat-held.txt`; temper renders
  it at `temper-engine-smith` `answers.rs:436`.

### 6.2 temper

- **A custom charter's shell writes for a run that cannot deliver.** The rail "modify only with
  deliver" (agent.md 4.3) does not cover `shell`; no stock charter grants `shell` (charter 2's is
  false; only test fixtures set it). lead/q/temper, g-modify, 10-29.
- **A custom Open change assignment checks and delivers with no deliver grant.** A requester-ended
  (Open) assignment keeps `outcome.change` without `deliver`, and smith still runs its check and
  delivery path at finish (`charter.rs`, `run.rs` `Declared::Change`, `land.rs`). Not a stock path.
  lead/q/temper, g-modify, 10-29.
- **An old store fails to open with no cause named.** After a pre-release schema change in place
  (store version unchanged), a kept box's `serve` exits six times with "temper serve: commit 0
  failed" and names no record or field; a store that cannot open should say why (protocol/store.md
  4). For upgrades. Rung A walk 12 attempt 3, finding 3 (`a3-kept-serve-masked.txt`).
- **ctl reads time out at 30 s while changes work.** Ordinary chat/task/change reads exited 1
  ("did not answer within 30 s") while two changes worked, then recovered; seen on a debug build.
  Rung A walk 12 attempt 3, finding 4; on the path if it recurs on main (github-pilot t33 is its
  likely cause: two watches filling Small's streams).
- **ctl names a not-yet-made task "unknown".** `task show N` before task N exists exits 2
  `{"error":"unknown"}`, not "no task N yet" (jig `documents/small.rs:24` Missing::Unknown to
  ctl's `jig/render.rs:272`). green's fixture investigation, 10-29.
- **Walk 12's tooling list:** `task show` cuts a result to 128 bytes even in `--json`; a whole
  activity takes one cursor call per page; a budget refusal "Authority missing" names no limiting
  setting; `task show --until replied` returns while delegates run. Rung A walk 12 reports.
- **The playground's starter CI only echoes:** rung A's "passed by CI" is a workflow that
  compiles and tests nothing (walk 12 attempt 2, `a2-csv-job3.log`).
