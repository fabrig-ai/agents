# fab-landing status

2026-11-01. Contract: `docs/design/fab-landing.md`. Split from `docs/design/fab.status.md`.

## Present

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
  queue unit was changed. Turning budget excesses red remains in Later (2, 14).
- **Landing this repository:** `bin/fab land`, live since 20:22Z; every
  change to `fab/` since then landed through it.
- **fabrig's landing:** `fab gate`, `fab queue`, `fab precheck` on main.
- **A ladder's backlog branch is fab's** (3, fab-qa.md 2; plan
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
- **The landing checks are a skeleton:** `fab/receipts.py` (a receipt
  kept on the gate, read, reusable for a tip and main, covering a test, and
  carried from the builder at ready) and `fab/reds.py` (the test steps'
  JUnit, the retry of a failed test alone, the verdict) hold 3's
  contracts; `fab.queue.Queue.attempt`, `cycle` and `main` say how the queue
  uses them. The task `receipts` fills the first and the queue's reuse and
  `fab queue receipt`; `red-classes` the second, the queue's classing and
  the landing report's figures; `receipts-ready` makes the dispatcher carry
  each tip's receipt when it readies it, after the tick's other tasks on
  `fab/dispatch.py`. Until then every batch runs its full checks and every
  red rejects or bisects. The bound of two collateral reds per tip and five
  retried tests per red are first guesses, to be set from the queue's
  records.
