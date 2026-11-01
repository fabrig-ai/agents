+++
id = "precheck-receipt"
part = "precheck-receipt"
kind = "feature"
needs = []
files = ["fab/precheck.py", "fab/receipts.py", "fab/tests/test_precheck.py", "fab/tests/test_receipts.py", "docs/design/landing.status.md"]
effort = "medium"
minutes = 30
+++
# A starved receipt never stands in for the gate; records leave the builders

Read first: `docs/plan/acceptance-fixes/notes/common.md`,
`docs/plan/acceptance-fixes/notes/decisions.md` (3-6), then
`docs/design/landing.md` 3, "Precheck receipts are reused".

The request's items 1 and 2. Since `precheck-starved`, `fab.receipts.reusable`
returns True for `outcome: green, starved: 7`, so a batch of one on the same
main runs only fmt, and 7 killed and 938 never-run tests land with no gate
run. And a full precheck leaves 127 MB and about 24,500 files under
`FAB_HOME/precheck/<tip>/` that nothing reads.

## What to build

- **`fab/precheck.py`:**
  - `precheck` (~45): `"unobserved": 0` in the receipt, beside `starved`; its
    docstring (~26) names the key.
  - `_checks` (~86): count `case.result == "skipped"` into
    `receipt["unobserved"]` in the loop beside `starved`, with no log line
    (decision 4).
  - At the end of `_checks`, after that loop, for each profile in `reports`:
    `shutil.rmtree(directory / profile / "records", ignore_errors=True)`.
    `directory` is already `_checks`' local. Its docstring says both.
- **`fab/receipts.py` `reusable`** (~83): add `not receipt.get("starved") and
  not receipt.get("unobserved")`. The docstring says a missing key counts as
  0, so older receipts stay reusable; the module docstring (~5) says a
  reusable receipt also has nothing starved or unobserved.
- `covers` stays as it is, and so does `deliver`: a green receipt with
  starved tests still reaches the gate for `covers`.
- **`docs/design/landing.status.md`:** a new bullet under Present saying what
  this built (3; plan `docs/plan/acceptance-fixes`). In the
  precheck-starved bullet (~35), "so receipt parsing and reuse (3) did not
  change" is no longer true: say parsing did not change and point at the
  new bullet. Say there that the collector's records are removed, and that
  the reuse change is live once the gate's `fab-queue.service` restarts on
  it.

## Acceptance

- `test_precheck.py`, `assert_receipt` (~91): `unobserved` in the key set,
  and its type `int`.
- `test_precheck.py`, a new test: with `FakeNextest` cases `("b", "ok",
  "pass")` and `("b", "never", "skipped")`, the receipt is green with
  `unobserved` 2 (one per profile) and `starved` 0, and the log has no line
  naming `never`.
- `test_precheck.py`, a new test: a `collect` wrapped as in
  `_global_timeout_checks` also writes `records/x` under its directory. After
  the check, `<tip>/default/records` and `<tip>/fuzzy/records` are gone and
  `junit.xml`, `gate-junit.xml` and `summary.json` are still there; on a red
  default step, `default/records` is gone too.
- `test_receipts.py`, beside `test_reusable_requires_green_and_both_commits`:
  False for `starved` 1 and for `unobserved` 1; True for 0 and for a missing
  key, each of the two.
- `bin/fab test` green.

## Pre-approved defaults

- `FakeNextest` writes no `records`; the test writes them. Do not change
  `fab/tests/landing_checks.py`; if you must, it is a `Question:`.
- `_global_timeout_checks` may gain a parameter if that is the short way to
  write `records/x`.
- A test elsewhere that pins a starved receipt as reusable is a `Question:`
  (the cut found none).

## Report

The functions changed, the tests added, and the machine action.

Your commit message says: machine action, `bin/install.sh <gate host>` once
landed, so `fab-queue.service` restarts on the new `reusable` (decision 3);
builders follow main at their next run start.

## Answers

- 2026-11-01, the answerer (run precheck-receipt-2): every test passes but
  `bin/fab test` exceeds 30 s of CPU on the builder; what now? Not this
  task's, and no change to make: commit 5fab700 stands. The overrun is
  hetzner6's: unchanged main took 34.8 s of CPU there, and the runs just
  before and after this one 24.7 and 25.5 s, while on hel8, where `fab land` runs
  (`docs/design/fab.md`, 2), the branch took 23.5 s and the branch merged
  with main 23.2 s. For this task "`bin/fab test` green" is every test
  passing; the budget line alone, past 30 s with no test failing, goes under
  `## Left` with `fab/testrun.py` as the file and the figures you saw. Do not
  touch tests or the budget, do not investigate further: verify, report
  `Done:`.
