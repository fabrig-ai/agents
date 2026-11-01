# landing status

2026-11-01. Contract: `docs/design/landing.md`. Split from `docs/design/fab.status.md`.

## Present

- **Precheck receipts require every test observed for reuse** (3; plan
  `docs/plan/acceptance-fixes`, retired 11-01; e500bc3):
  `fab.precheck.precheck` records `unobserved`, the skipped cases summed
  across test profiles, inventory entries that never started among them
  (`fab.cpu.cases`), without naming them in the log. A conflict's receipt
  says 0. `fab.receipts.reusable` refuses green receipts
  with starved or unobserved tests; missing counts still mean 0 for older
  receipts. Parsing, delivery and `covers` stay as they are, so a red still
  reads such a receipt. After reading each profile's reports, precheck
  removes the collector's `records` directories (2), keeping JUnit and
  summary files, on green and red runs. Tested with fake nextest and
  collector records (`test_precheck.py`, `test_receipts.py`), not on a
  stopped run (neither slice has a walk). Builders follow main at their
  next run start (tick.md 3).
- **The queue's retire fix and `rejected`'s tests** (11-01, section 2):
  the retire push runs with `--porcelain` and is read per ref; a refused
  source delete is left alone (a `left` line in the detail log); a refused
  ready ref is read back with `git ls-remote`, an error only when still at
  the landed tip or when the read-back fails; `landed` is recorded for
  every branch. A test step's `rejected` carries `tests`. Tested against a
  fake runner; the lead deploys it after landing.
- **Queue CPU and starvation** (11-01): default/fuzzy reuse `fab/cpu.py`
  with the queue's package scope and gate lane, one wrapper per batch, and
  separate collector directories per step. Batch records and logs report
  package-mapped per-tree CPU, summed test wall, pass/fail/starved/unobserved
  counts, full versus partial selection, and the ten highest-CPU tests per
  tree. Optional `[gate.<tree>.<profile>]` limits start unset; excesses are
  report only, suite totals evaluated only for full selections. Starvation
  alone is green; real failures and other exit-code checks stand. Fake
  services/JUnit/records cover both. A real slot-5 scoped gate-lane run on
  fabrig `eb6c40aaf5` passed 265 default and 7 fuzzy tests, reporting smith
  and jig CPU separately. The lead lands and deploys this change; no live
  queue unit was changed. Turning budget excesses red remains in Later (2, 4).
- **Precheck judges starvation as the queue does** (2, "The selection and
  the steps are shared"; plan `docs/plan/precheck-starved`, retired 11-01;
  3c59a96): `fab precheck` runs its steps through `fab.queue_cpu.run_steps`
  with the wrapper in the build lane (`lane="build"`; the queue keeps
  `"gate"`). Its `default` and `fuzzy` steps go through the collector and
  its reconciliation, so a step red only by starvation is green and an
  assertion failure stays red. Its other steps keep `gate.run_steps`, inside
  `run_steps`. The receipt gains `starved`, the reconciled starved cases
  summed over both profiles (0 on a conflict). `outcome` is still `green`,
  `red` or `conflict`, so receipt parsing did not change. Reuse (3) now
  requires every test observed, as described in the Present bullet above.
  The precheck log names each starved case as `<profile>: starved <binary>
  <test>` after the collector's per-tree lines. A second check of the same
  tip replaces the collector directory along with the log. Tested with
  fake nextest and collector records (`test_precheck.py`,
  `test_queue_cpu.py`): a global-timeout cancellation with nothing asserting
  is green with starved 4, and an assertion beside it is red with starved
  2, and fuzzy never runs. Builders pick this up when their installs follow
  main at their next run start (tick.md 3). This call has not seen
  `v0.1.0-ladder/finding-5`'s precheck run again on it.
- **The queue takes ready refs of two segments or more** (2; plan
  `docs/plan/dogfood-faults`, retired 11-01; 6e72974):
  `fab.queue.candidates` keeps every `ready/<name>` whose name has at least
  two segments, and the full name carries through ordering, tried tips,
  the leased cleanup and the records. `_import_queue` already took full
  branch names (`answers/<run>` and `repairs/<run>` owned through the
  foreman runs, `ladder/` through `_backlog_branches`), so it was left as
  it was. Tested with fake commands and disposable git remotes
  (`test_queue.py`). It is live once `fab-queue.service` on the gate
  restarts on that code (services move only with `bin/install.sh`); then
  `ready/ladder/v0.1.0-ladder/backlog-1` (unlanded since 11-01 14:52Z)
  becomes a candidate.
- **The landing checks** (3): `fab/receipts.py` keeps a precheck receipt on
  the gate (`fab queue receipt`), reads it, and says whether it is reusable
  for a tip and main and whether it covers a test; the dispatcher carries
  each tip's receipt from its builder at ready (`fab.receipts.deliver`).
  `fab.queue.Queue.attempt` lands a batch of one on a reusable receipt's
  checks after fmt, and `fab/reds.py` reads the test steps' JUnit, retries a
  failed test alone and gives the verdict the queue classes the red by. The
  landing report counts `retried` and `reused`.
- **Landing this repository:** `bin/fab land`, live since 20:22Z; every
  change to `fab/` since then landed through it.
- **fabrig's landing:** `fab gate`, `fab queue`, `fab precheck` on main.
- **A ladder's backlog branch is fab's** (3, qa.md 2; plan
  findings-loop, retired 11-01): `ladder/` joins the branch forms kept out
  of `queue.*`, and `_import_queue` maps each readied
  `ladder/<draft>/backlog-<n>` to its draft, so its `landed` and `rejected`
  come home as `branch.landed` and `branch.rejected` with task the branch
  and advance the cursor. Tested with fixture queue records.

## Gaps and departures

- **The queue is fab's unit, not fleet's:** `fab-queue.service`, written by
  `fab queue install`, which the deploy runs on every machine (section 2).
  It ran as a transient unit on hetzner8 from 10-30 21:15Z (it landed the
  cutover) until 10-31 10:08Z, when hetzner8 also became a builder.
- **`bin/fab land` drops a branch's merge commits** (2, "It rebases onto
  main"; seen at dogfood-faults/reruns, 11-01): `git rebase` replays only a
  branch's ordinary commits, so a change that lives only in a merge commit
  never lands and is never tested. The rerun's merge of main into its
  branch (tick.md 3) held the task's fixture fix and later edits; three
  landings (`7751332`, `bb9b2e3`, `d74f981`) tested the first commit alone
  and refused, until the answerer had the run squash the change into one
  ordinary commit (53dfbf6). Code and design agree; the fault is the
  design's (4, Later).
- **`bin/fab land` gives the suite 120 s of wall time** (`fab/land.py`; 2
  does not name it): the budget is CPU time (`docs/design/fab.md` 4), but a
  machine that stretches the suite's 23 s of CPU past 120 s still refuses a
  good branch at `test` (plan `docs/plan/test-budget` did not change it; 4,
  Later).
- **The gate may still reuse a starved receipt:** `fab-queue.service` runs
  for days and moves only with `bin/install.sh`, so `fab.receipts.reusable`'s
  change is live once e500bc3's machine action, `bin/install.sh <gate host>`,
  has run. The retire did not check the gate; until the action is run, a
  batch of one on a starved receipt on the same main still lands on fmt alone.
- **`FAB_HOME/precheck/` is not pruned** (2; 4, Later): `_checks` stops new
  `records` only. Those of prechecks from before e500bc3 stay on the
  builders unless the same tip is checked again, and a precheck that raises
  before the end of `_checks` leaves its own. Receipts, logs and reports stay
  on every run.
- **The bounds of the landing checks are first guesses:** two collateral
  reds per tip (`fab.reds.LIMIT`) and five retried tests per red
  (`fab.reds.RETRIES`), to be set from the queue's records.
