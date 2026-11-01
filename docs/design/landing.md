# fab: landing

2026-11-01, split from `docs/design/fab.md` (its section 6 maps the old
section numbers). Status: `docs/design/landing.status.md`. Shared: the
overview, the event log and the tests are `docs/design/fab.md`'s.

## 1. In one page

- **This repository lands through `bin/fab land`,** one branch at a time; fabrig through its merge queue (`fab queue`) on the gate machine.
- **The queue batches ready refs,** checks them in the gate lane, bisects a red batch and records every outcome for the dispatcher.
- **The landing side** reuses precheck receipts, classifies reds and keeps collateral rejections apart from real ones.

## 2. Landing

- **This repository:** `bin/fab land BRANCH` on hel8, one at a time under a
  flock. It refuses a branch touching `old/` (the legacy kit, reference only)
  or `docs/design/draft/` (the user's input); everything else in this
  repository lands this way.
  It rebases onto main, runs `bin/fab test`, pushes main fast-forward only,
  deletes the branch and logs `branch.landed`. A conflict or a red logs
  `branch.rejected`.
- **fabrig:** its merge queue (`fab/queue.py` on hetzner8), ported from
  `tools/queue/mq`'s core: ready refs oldest first (every `ready/<name>`
  whose name has two segments or more: `<draft>/<task>`, `calls/<id>`,
  `answers/<run>` and `repairs/<run>`, whose run ids hold slashes, and
  `ladder/<draft>/backlog-<n>`; fixed 11-01, found by dogfood/design: only
  two-segment names were taken, so those branches never landed), a batch
  merged on main, the selected checks through `heavy --gate`, bisection of
  a red batch, a push that expects main's parent, ready and task branches deleted. Its record is
  `FAB_HOME/queue.jsonl` there (`batch`, `landed`, `rejected`,
  `collateral`), which the dispatcher reads; the tips it has tried and
  their collateral reds (3) are its only other state. A `rejected` at
  a test step carries `tests`: the failed tests of the step's derived
  `gate-junit.xml`, `<binary> <test>`, at most 20 ([] at any other step), so
  whoever hears it (a foreman, the user's page, 3) reads them without
  the log.
- **Queue CPU, report only:** `fab/queue_cpu.py` runs the queue's `default`
  and `fuzzy` steps through the shared `fab/cpu.py` collector (after-landing.md 2),
  keeping `check_steps`' package selection and `heavy --gate` lane. A static
  wrapper is built once per batch through heavy in that lane, only when a
  test step is reached. Each attempt has a nanosecond-stamped batch directory
  `FAB_HOME/queue/<batch>/`, with `default/` and `fuzzy/` holding the collector's
  records, inventory, private config and JUnit; its detail log is the sibling
  `<batch>.log`. Other steps retain `gate.run_steps`' exit checks.
  Inventory package names assign tests to the root nextest config's tree
  clauses: `skein-*`, `forgejo-conformance`, `github-conformance`; `smith`
  and `smith-*`; `jig` and `jig-*`; `temper`, `temper-*`, `git-transcripts`;
  and `fabrig-boundary`. Binary ids are not package names, and there is no
  enumerated workspace package list.
- **The batch's CPU figures:** `queue.jsonl`'s `batch` gains `cpu_trees`, a
  list of JSON strings (the event log's fields remain scalars or lists of
  scalars). Each string names `profile`, `tree`, `full` (only a `full`
  selection), `cpu_s` (test user plus system CPU, descendants included),
  `test_wall_s` (sum of tests' wall, excluding compilation and admission),
  `tests`, `passed`, `failed`, `starved`, `unobserved`, `incomplete`,
  `budget`, `over`, `verdict`, and `top_cpu` (at most ten tests, descending
  CPU). Each step logs those totals and counts. Unstarted inventory entries
  are unobserved, never passes; incomplete accounting is a lower bound.
  Raw per-test records stay in the batch directory, without a per-test event.
- **Starvation stays green in the gate:** nextest slow-timeout terminations,
  global-timeout cancellation and collector-starved tests count separately
  from passes and failures. Starvation alone can clear nextest's test-failed
  exit; assertions and independently observed bad exits remain red. Other
  nextest exit codes keep their checks, even alongside starvation. Red
  classification (3) reads a derived `gate-junit.xml` with those reconciled
  cases, so a cancelled test is not retried as a failure beside a real red;
  the collector's original JUnit stays intact. The checkout's existing wall headroom is unchanged (`120s` default, `480s`
  fuzzy today). This implements fabrig's
  `skein/docs/foundation/testing-strategy.md`, 2.10 and 8–8.1, with CPU
  enforcement deferred below.
- **Optional gate budgets, no figures supplied:** the checkout's
  `tools/tiers/budgets.toml` may have `[gate.<tree>.default]` and
  `[gate.<tree>.fuzzy]` tables with `cpu_suite_s` and/or `cpu_test_s`, finite
  positive seconds. Only the user sets them. An unset budget has no verdict;
  only a full selection evaluates a tree's suite total, while a per-test
  limit can be reported on partial selections too. Excesses appear as `over`
  in the batch and detail log, without rejecting it. Receipt reuse (3)
  still runs only its existing fmt checks, without new CPU measurements.
- **Retiring a landed branch:** `ready/<name>` is deleted with a lease on
  its tip, and `<name>` only when its fetched tracking ref is that tip; a
  branch readied by hand (its ready ref alone, or a task ref that moved on)
  lands cleanly.
  - **A refused source delete is left alone, not an error** (11-01: on
    hetzner8 batches of hand-pushed branches landed and were recorded
    `outcome: error`, `cleanup: ... - [deleted] ready/ops/component-kit-draft
    ! [rejected] (delete) -> ops/component-kit-draft (stale info)`). The
    deletes go in one non-atomic push; the source `<name>` had moved on the
    remote after the cycle's fetch while its tracking ref still named the
    tip, so its lease failed. The ready ref was deleted and `landed` logged,
    but the push's exit made the batch an error.
  - The push runs with `--porcelain` and is read per ref (`-` deleted, `!`
    refused with its reason). A source `<name>` refused for any reason is
    left alone: one line `left <name>: <reason>` in the batch's detail log.
    A refused `ready/<name>`, or one the output does not name, is read back
    with `git ls-remote origin refs/heads/ready/<name>`: gone, or at another
    tip (readied again meanwhile, a candidate next cycle), it is left alone
    too; still at the landed tip, it is the batch's error, `cleanup:
    ready/<name> <reason>` per such ref, joined by `; `.
  - `landed` is recorded for every branch of the batch either way (main
    holds it), and each is marked tried unless its ready ref is in the
    error. Tests (fake runner): a push exiting 1 with the ready ref deleted
    and the source refused `(stale info)` gives outcome green, `landed`, the
    tip tried and the `left` line; a refused ready ref that ls-remote still
    shows at the tip gives outcome error naming it.
- **Short of disk is the gate's fault:** a check step that exits 75 (heavy
  waited out its disk cap) is an error, not a red: nothing is rejected or
  marked tried, and the batch goes again.
- **Dropped from the old queue** (the user, 10-31), not deferred: the train
  and its worker, the publication journal and recovery (the queue re-derives
  its state from git: a crash between push and cleanup leaves ready refs
  contained in main, which the next cycle deletes), the authority locks and
  the hot-swapped runtimes with their drain restart (the unit's stop drains
  instead), the lead and coordinator mail routes (the dispatcher imports the
  queue's record), repair priorities and holds, the launcher's CPU and wall
  budgets, the tools-suite policy, and the hourly and idle full runs with
  the selection-gap alert (every fifth batch is full).
- **The queue's unit is fab's** (`fab queue install`, `fab-queue.service`):
  the deploy runs it on every machine after moving fab's install to main.
  On a gate (role `gate` in `fab/hosts.toml`) it writes the unit and
  restarts the queue on the new code; a unit disabled by hand (a pause:
  `systemctl --user disable --now fab-queue`) stays disabled. On a machine
  without the role it disables a unit it finds, so moving the role moves the
  queue. A stop drains: the unit creates `FAB_HOME/queue.stop` and waits up
  to an hour for the cycle in progress, then interrupts it so the attempt's
  cleanup still runs; a start removes a stale stop file.
- **The selection and the steps are shared** (`fab/gate.py`): the queue runs
  them in the gate lane on the batch, precheck in the build lane on the tip
  merged with main, in the implementer's slot. Precheck writes its receipt to
  `FAB_HOME/precheck/<tip>.json` on the builder. The gate's lists
  (`always.txt`, `read-by-tests.txt`) move with the cutover from fabrig's
  `tools/queue/` to its `.config/gate/`.

## 3. The landing side

- **Precheck receipts are reused:** a batch of one branch whose precheck
  receipt names the same main and passed lands on the receipt's checks
  alone, after fmt; the queue's own full checks still run on every fifth
  batch and on every batch of more than one.
  - **The receipt travels with the ready:** when the dispatcher readies a
    fabrig tip, it reads `FAB_HOME/precheck/<tip>.json` on the builder of
    the task's last implement, repair or rebase run and hands it to the
    gate (`fab queue receipt TIP`, kept as `FAB_HOME/receipts/<tip>.json`
    there; `fab/receipts.py`). A receipt that is missing, red or does not
    parse is no receipt: the queue checks the tip in full.
  - **Reusable** means green, the same tip and the same main as the batch's
    parent. The ratchet steps still run with `--write` (they shape the
    candidate), then `fmt` for the queue's selection; the batch record
    carries `receipt`, and the batch counts toward the fifth.
- **Reds are classed before anyone hears them:** a failing test that passed
  in the branch's precheck is retried once alone; passing, the red is
  collateral, recorded as such, and the branch is retried without counting
  against it; failing twice, it is the branch's.
  - **Which reds** (`fab/reds.py`): the gate's test steps (`default`,
    `fuzzy`) write nextest's JUnit through an overlay config, as after
    landing does. A red test step with at most five failed tests, each
    passing in every merged branch's precheck (its receipt green, the step
    run, the test's package in its selection), is classed before any
    bisection; any other red stands as before.
  - **The retry** runs each failed test alone, in order, with the step's
    own scope and profile in the gate lane. All passing: the batch's
    outcome is `collateral`, each merged branch gets a `collateral` record
    (branch, tip, step, tests, log), nothing is rejected or marked tried,
    and the batch goes again next cycle. One failing alone, or a retry that
    cannot be read, and the red stands: bisection or rejection as before,
    the record carrying `stands`, the reason.
  - **Bounded:** a tip classed collateral twice has its next red stand, so
    a test that fails under load every time cannot hold the queue. A
    collateral attempt within a bisection ends that group's split.
  - The landing report counts the branches retried and the batches landed
    on a receipt, and raises a signal for each collateral red: a flake goes
    to its owner.
- **A rejection no task owns is heard** (the user, 11-01: a hand-pushed
  qa-ladder batch was rejected on a port flake and nobody was told; its
  `rejected` sat in `queue.jsonl`). The tick's queue import
  (`fab.dispatch._import_queue`) keeps, besides its tasks' records, the
  records of a branch that is not fab's: `rejected` as `queue.rejected`
  (branch, tip, step, log, tests), `landed` as `queue.landed` (branch,
  tip, main) and `collateral` as `queue.collateral` (branch, tip, step,
  tests, log), each with `queue_ts` and `gate` (the gate host's name, for
  the page's `<gate>:<log>`), deduplicated by the same key as its tasks'
  records. Imported `tests` keep their string entries only.
  - **A branch is fab's,** and never imported as `queue.*`, when a loaded
    task or fab branch owns it, or when the log knows it, loaded or not: a
    `branch.ready` or `run.started` naming the branch, a `run.started`
    whose task is `fab.land.task_of(branch)`, or a fab branch's form
    (`calls/`, `answers/`, `repairs/`, `ladder/`, `<draft>/integration`). A record of
    an unloaded plan's task is deferred, not relabelled: it imports as
    `branch.*` once its plan loads, from the plans' cursors as before.
  - **The cursor:** the oldest of the loaded drafts' cursors (tick.md 5), as
    before; with no loaded draft, the import resumes at the newest
    `queue_ts` of any kind in the log.
  - A `queue.rejected` opens the signal `queue:<branch>` on the user's page
    (channel.md 2), since its `queue_ts`: branch, tip, step, failing tests and the log on the gate. It
    clears when the branch lands, when a newer tip of it is tried, or by
    hand. Telling the session that readied it is left for later (4): a
    ready ref carries no pusher fab can read reliably.
  - A `collateral` alone is no signal: the branch goes again by itself, and
    the report already signals collateral reds. A red that stands after
    its collateral bound ends as a `rejected`, which is heard.
  - The queue already wakes the tick on every `rejected` (tick.md 6).
  - Tests: a fake queue log with a rejected hand-pushed branch gives one
    `queue.rejected` and the page's signal; a later `landed`, or a
    `rejected` at another tip, clears it (the latter opening its own);
    `fab page clear` clears it; a task's rejection still becomes
    `branch.rejected` and no signal.

## 4. Later

- The landing checks' next steps (3): a collateral red sent to the
  failing test's owner, not only signalled (fab knows a test's owner only
  as a red's suspects after landing, 11, which a collateral red at the gate
  does not have); receipts reused for batches of more than one, once
  numbers show how often a set's receipts all name its main; receipts on
  the gate pruned.
