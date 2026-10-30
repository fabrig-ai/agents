# fab: the pipelines' code

2026-10-30. Owner: the user's pipeline session. Code: `fab/`, `bin/fab`.
Code departures: `docs/design/fab.status.md`. Inputs: the drafts
`docs/design/draft/code-producing-pipeline.md` and `landing-pipeline.md`, and
the user's "Execution modes for the code-producing pipeline" (Claude Docs,
2026-10-30; Feature mode is the one built first).

## 1. In one page

- **One package, one log.** `fab/` holds the code of both pipelines. Its
  memory is files: plans and tasks authored in git, and one append-only event
  log that only the dispatcher writes. State, metrics and reports are computed
  from them, never kept by hand.
- **Interim by intent.** temper's own primitives replace fab in time. Until
  then fab must be cheap to run, easy to change and good enough to prove the
  execution model. It uses the model's words (draft, part, slice, task, run,
  call), so the move to temper is a translation, not a redesign.
- **Pure core, thin shell.** Every decision is a pure function of files and
  the log. The shell runs git, ssh, codex-run and cargo through one injected
  runner (`fab/sh.py`). Tests check the core directly and the shell against a
  fake runner.
- **The whole suite runs in under 30 s.** `bin/fab test` runs every test and
  fails past 30 s wall time (section 8).
- **Builders own their disk.** A sweep bounds each slot's footprint at the end
  of every task. A build short of disk waits while the builder reclaims idle
  slots. No implementer stops or asks because of disk (section 7).
- **Strangler, not big bang.** Each fab part replaces an existing tool once its
  slice's story passes. The old tool stays live until then, and is deleted
  after.
- **Minimal now, with room left.** The current tools' safety layers (receipts,
  custody proofs, acknowledgements, recovery journals) are left out. Section 9
  says where each would attach if numbers show it is needed.

## 2. Where things live

| Place | What |
|---|---|
| `fab/` in this repository | the package; `fab/tests/` its tests; `fab/roles/` the role texts briefs are compiled from; `fab/hosts.toml` the machines |
| `bin/fab` | the command; `bin/fab COMMAND ...`, Python 3.13 standard library only |
| `docs/plan/<draft>/plan.toml` in the draft's repository | the thin cut: parts, slices, modes (section 4) |
| `docs/plan/<draft>/tasks/<task>.md` in the same repository | task specs, landed with their part's skeleton |
| `~/src/fabrig/fab/` on every machine (`FAB_HOME`) | runtime data, never in git |
| `FAB_HOME/log.jsonl` on the dispatcher's machine (hel8) | the event log (section 3) |
| `FAB_HOME/runs/<run>/` on hel8 | each run's brief, its collected report and metadata |
| `FAB_HOME/reports/` on hel8 | the standing reports, one file per draft and day (section 10) |
| `FAB_HOME/digests/<run>.md` on hel8 | each gated branch's structure digest (section 12) |
| `FAB_HOME/user.md` on hel8 | the user's page: their open questions and the latest reports (13.6) |
| `FAB_HOME/repos/<repo>` on each machine | fab's own clones; `FAB_HOME/wt/<run>` worktrees for runs that build nothing |
| `~/src/fabrig/slots/<n>` on a builder | warm fabrig checkouts (unchanged); `slots/<n>.claim` the slot's claim (section 7) |
| `FAB_HOME/after-landing.jsonl` on the after-landing builder | its verdicts; `FAB_HOME/after-landing/` its state and each run's logs (section 11) |

- **hel8** runs the dispatcher, Claude calls and `fab land` for this
  repository. **Builders** (hetzner6 today) run Codex and builds. **hetzner8**
  runs fabrig's merge queue.

## 3. The event log

- **Format:** one JSON object per line: `{"ts": "<UTC, ms, Z>", "ev": "<type>", ...}`.
  Fields are flat strings, numbers or lists. A line is never changed or
  deleted.
- **One writer:** `fab.log.append` on hel8, under a flock beside the log. A
  torn last line (a crash mid-write) is ignored on read. Builders report by
  being asked (`fab run status` over ssh); they never write the log.
- **The events:**

| ev | fields | meaning |
|---|---|---|
| `task.added` | draft, task, repo, path, sha | a task spec exists on its repository's main |
| `run.started` | run, task, kind, host, dir, branch, base | a Codex run began; kind is implement, repair, rebase, review or foreman |
| `run.ended` | run, task, outcome, report, minutes, tokens | outcome is done, question, infra or failed (section 5); tokens is Codex's (13.5) |
| `branch.ready` | task, branch, tip | handed to the landing pipeline |
| `branch.landed` | task, branch, tip, main | on main |
| `branch.rejected` | task, branch, tip, step, log | the landing refused it; a repair or rebase follows |
| `question.asked` | task, run, text | the task parks until answered |
| `question.answered` | task, by, answer | the task may run again; it names a task, never a call's subject |
| `call.started` / `call.ended` | call, role, subject; outcome, tokens, cache_write, peak, turns, minutes | a Claude call; its usage (13.5) |
| `call.finished` | call, role, outcome | the dispatcher landed a call's branch, or failed to |
| `call.parked` | call, subject, reason, report | a call's branch waits for the user (13.1) |
| `call.answered` | subject, call, by, question, answer | the user answered a subject's question or parked chain (13.6) |
| `note` | text | anything a person wants on the record |

- **New kinds are additive.** The fold ignores types it does not know, so a
  new event never breaks an old reader.
- **Ids:** a task is `<draft>/<task>`; a run is `<task>-<n>`, n counting the
  task's runs from 1; a branch is `<draft>/<task>` and a rebase pushes
  `<draft>/<task>-r<n>`.

## 4. Plans and tasks

- **The plan** (`plan.toml`) is the thin cut: `draft`, `repo` (the tasks'
  default repository), `sources` (the drafts it serves), and `[buffer]` `low`
  and `high` (the ready-task band as multiples of implementer places). Each
  `[[part]]` has `id`, `title`, `mode` (feature, migration, fix or probe),
  `needs` (other parts), `design` (where its design is) and `contract` (a
  shared contract, designed by the designer's contract call, 13.3; default
  false). Each `[[slice]]` has `id`, `story`, `parts` and `walk` (whether QA
  walks it). Each `[[question]]` is one of the user's, from the cut: `id`,
  `text`, `parts` (designed only once it is answered) and `answer`, written
  into plan.toml when the user gives it. `retired = true` ends the plan. No
  part is called `cut`, `retire` or `review`: those name calls' subjects.
- **A task spec** is Markdown with a TOML header between `+++` lines: `id`,
  `part`, `kind` (feature, interface, migration, repair, rebase or docs),
  `repo`, `needs` (tasks that land first), `files` (globs it may change),
  `effort` (medium or high) and `minutes` (the expected implementer time,
  20-30 for a feature task). The body says what to fill, how it is accepted,
  and the pre-approved options with their defaults.
- **A task's status is computed:** `waiting` (a need has not landed),
  `runnable`, `running`, `parked` (a question is open, or the run failed and
  needs judgement), `done` (its run ended checked), `ready`, `landed`,
  `rejected` (waiting for its repair or rebase run). An `Infra:` outcome makes
  it runnable again. `fab.state.fold` derives it from the specs and the log.
- **A part is designed** once its skeleton and task specs have landed, and
  **done** once all its tasks have landed (`fab.state.part_statuses`).

## 5. Runs

- **A run is one Codex execution** on a builder, in a slot (fabrig) or a
  worktree (repositories that build nothing heavy). `fab run start` prepares
  the checkout at the task's base, writes the brief, and starts
  `codex-run task` there.
- **The brief is compiled, not gathered:** the role text
  (`fab/roles/implementer.md`), the task spec, and the paths it cites. Codex
  reads what the brief names in the checkout itself.
- **The report's first line is its outcome:** `Done: <summary>`,
  `Question: <question>` (then the options and a recommendation),
  `Infra: <cause>` (disk, a machine or a tool, not the task's fault) or
  `Failed: <why>`. `fab run status` reads it; the dispatcher requeues an
  `Infra:` run without asking anyone.
- **Done means checked:** the branch is pushed and its checks passed inside
  the run (this repository: `bin/fab test`; fabrig: precheck and the merged
  readers' tests, `agents/implementer.md` in fabrig).

## 6. Landing

- **This repository:** `bin/fab land BRANCH` on hel8, one at a time under a
  flock. It refuses a branch touching anything outside `fab/`, `bin/fab`,
  `docs/design/fab*` and `docs/plan/` (those still go through `tools/land`).
  It rebases onto main, runs `bin/fab test`, pushes main fast-forward only,
  deletes the branch and logs `branch.landed`. A conflict or a red logs
  `branch.rejected`.
- **fabrig:** its merge queue (`fab/queue.py` on hetzner8), ported from
  `tools/queue/mq`'s core: ready refs oldest first, a batch merged on main,
  the selected checks through `heavy --gate`, bisection of a red batch, a push
  that expects main's parent, ready and task branches deleted. Its record is
  `FAB_HOME/queue.jsonl` there (`batch`, `landed`, `rejected`), which the
  dispatcher reads; the tips it has tried are its only other state. The port
  drops train, worker and recovery, and the publication journal (section 9).
- **The selection and the steps are shared** (`fab/gate.py`): the queue runs
  them in the gate lane on the batch, precheck in the build lane on the tip
  merged with main, in the implementer's slot. Precheck writes its receipt to
  `FAB_HOME/precheck/<tip>.json` on the builder. The gate's lists
  (`always.txt`, `read-by-tests.txt`) move with the cutover from fabrig's
  `tools/queue/` to its `.config/gate/`.

## 7. Slots and disk

- **Measured (hetzner6, 10-30 20:00Z):** eight slots of 5-39 GB each; cargo's
  incremental data is 50-90% of every slot, stale test executables up to
  14 GB, everything else 2-4 GB.
- **The sweep ends every task:** when a slot's run ends, `fab slot sweep`
  removes its incremental data and the test executables the run did not
  write. The next task's base differs anyway, so little is lost: the edited
  crates compile once without incremental help. A swept slot holds about
  4 GB. The slot bound is 25 GB: a whole-workspace clippy and test build
  from a swept slot peaked at 25 GB, 19 GB of it test executables and 3 GB
  incremental data (hetzner6, 10-30 20:18Z, kache warm).
- **The builder's budget:** disk = kache cap + slots x slot bound + headroom
  (5-10 GB). hetzner6: 50 + 8 x 25 + 10 = 260 of 305 GB, the rest for QA
  boxes, archives and the system. `fab hosts check` computes it from
  `fab/hosts.toml`.
- **Claims are the builder's:** `slots/<n>.claim` is created exclusively and
  holds the run, task and time. `fab slot claim` and `fab slot release` run on
  the builder (over ssh from the dispatcher). A claim whose run unit is gone is
  stale, and the dispatcher releases it.
- **Admission waits, it does not refuse:** before a build, `heavy` needs the
  headroom plus a build allowance free. Short of it, it reclaims and waits
  (checking every 30 s, reclaiming again) up to 20 minutes, then exits 75. A
  run that exits 75 reports `Infra: disk`, and the dispatcher requeues it.
- **Reclaim takes from idle slots only:** unclaimed slots, least recently
  released first; first their incremental data and stale executables, then
  the whole target (kache refills it). A claimed slot is touched only by its
  own run's sweep.
- **Lanes are flocks:** the build lane is `builds` lock files, the gate lane
  one; a holder that dies frees its place, so heavy needs no ledger or
  reconciler. The command runs in a systemd user scope with its lane's CPU
  weight (gate 10000, build 1000). Each command appends its lane and disk
  waits to `FAB_HOME/heavy.jsonl` on its machine, the metrics' source.
- **One floor:** the headroom. The current tools' separate floors (45, 40 and
  80 GB) go when `heavy` moves here.

## 8. Tests

- **Under 30 s for everything,** measured by `bin/fab test`, which fails past
  it. A module's tests run in about a second.
- **The core is tested directly:** decisions (`decide`, `fold`, selection,
  bisection, sweep plans) are pure functions over plain data.
- **The shell is tested against a fake:** commands take a runner
  (`fab.sh.run` by default). Tests pass `fab.tests.support.FakeRunner`, which
  records each argv and returns scripted results. No ssh, systemd, codex or
  cargo runs in a test.
- **One git fixture per module:** `support.git_repo()` builds a template
  repository once per process, and each test copies it. Real git only where
  git's own behaviour is the point (merges, rebases, pushes).
- **Temporary HOME and FAB_HOME** for every test that touches files. Python
  runs with `-B`.

## 9. Left out for now

- **Receipts and evidence hashes** (precheck's `result.json` bound to tips and
  trees): the log's `run.ended` and `branch.*` events carry tips; a check
  binding them attaches at `fab land` and the queue's intake.
- **Publication journal and recovery:** the queue re-derives its state from
  git (main, ready refs) on start; a crash between push and cleanup leaves
  ready refs contained in main, which the next cycle deletes.
- **Acknowledgement protocols for reclaiming:** reclaim touches unclaimed
  slots only, so no acknowledgement is needed; a slot kept for inspection is
  claimed by a person.
- **Mail between agents:** the dispatcher asks; nobody waits on a mailbox. One
  notification path to the user, when a question is the user's, comes with the
  answer queue.
- **Leases:** one writer per crate becomes the dispatcher's choice of
  runnable tasks (their `files`), not a lock.

## 10. Reports

- **Two standing reports, from records alone:** the code report of a plan
  (the metrics of `docs/design/draft/code-producing-pipeline.md`, 3, that the
  log records) and the landing report (those of
  `docs/design/draft/landing-pipeline.md`, 3, that the queue's record holds).
  Nothing is counted by hand and nothing new is recorded for them.
- **`fab report` runs on hel8.** It reads the whole log there, the queue's
  record from the gate machine (`fab queue log --since`, as the tick does) and
  each builder's and the gate's `heavy.jsonl`, over ssh, seven days back. A
  source it cannot read is named in the report, never a failure.
- **A report covers one UTC day,** or today so far on demand, and every figure
  stands beside the previous day's: the trend the drafts ask for until the
  user sets targets.
- **The code report** (`fab/code_report.py`): runs started and their outcomes,
  branches ready, landed and rejected; runs in flight per hour against the
  builders' places; idle gaps (no run in flight while a task is not landed,
  10 minutes or more) with the tasks' statuses at their start; runs and Codex
  minutes per landed task; questions, their rate per report and time to
  answer; Infra minutes and heavy's lane and disk waits on the builders;
  Claude calls, minutes and tokens, Codex's tokens and the weights (13.5);
  the stops (questions, failed and Infra runs, rejections) ranked by time
  lost; the same per part.
- **The landing report** (`fab/landing_report.py`): batches, their outcomes
  and branches; the share of the day in gate steps; rejections by step (the
  red classes) and collateral ones (a rejected tip that later lands); ready to
  landed latency (from the log's `branch.ready`), branches waiting and the
  oldest wait; bisection runs and minutes; repair rounds; each step's
  durations, failures and timeouts; batches in error; heavy's waits on the
  gate.
- **Signals without targets:** a report raises only the drafts' signals that
  need no number of the user's: idle gaps, rising rejections, Infra runs,
  collateral rejections, queue errors, a ready branch waiting over an hour and
  longer than the day before, disk waits and unread sources, each with the
  draft's first action and owner. Thresholds come with targets.
- **Where they go:** `FAB_HOME/reports/<draft>/<day>.md` and
  `FAB_HOME/reports/landing/<day>.md` on hel8, written to a sibling and
  renamed. `fab report daily PLAN_DIR...` writes yesterday's that do not
  exist yet; the director reads them there.

## 11. After landing

- **fabrig's slow tiers run on each new main,** ported from the agents
  repository's `tools/after-landing` (`docs/design/after-landing.md`) and
  fabrig's `tools/tiers/run`. `fab after-landing run --slot N` loops on one
  builder in one slot claimed for it (`fab slot claim N after-landing
  after-landing`); it refuses any other slot. Every cargo command goes
  through `heavy` in the build lane, which waits for disk by itself.
- **A tier is a pair:** a nextest profile `<tier>-<tree>` of fabrig's
  `.config/nextest.toml`, its packages and the native binaries its tests run
  from the package map (`.config/tiers/packages.toml`, or
  `tools/tiers/packages.toml` until fabrig moves it). `fab tiers run TREE
  TIER` builds the pair's browser bundle and binaries, then runs its packages'
  tests; `fab tiers verify` checks the map against the workspace's listing.
- **The tier set** is a list in the code: `exhaustive-skein`, `qa-skein`,
  `qa-smith`, `qa-jig`, `process-jig`, `browser-skein`, `browser-jig`,
  `browser-temper`, `qa-temper`, in that order. Not the live pairs (real
  providers, the user's sign-ins) nor `process-temper` (its owner's).
- **One tip at a time, the newest:** each cycle fetches main. A tip that is
  not the cursor (the last tip run without a fault) gets one run of the tier
  set. Its **suspects** are the first-parent commits since the cursor; a queue
  merge `Merge <draft>/<task>` names its task's branch. Tips published
  meanwhile are covered by the next run: their commits are its suspects.
- **A red is confirmed first:** each failed test (profile, binary id, test
  name, read from nextest's JUnit) runs once more alone. Failing again is a
  confirmed red; passing is a **flake**. Against the test's own history, a
  confirmed red is **new** (it last passed), **standing** (it was last red)
  or **unattributed** (never executed before); a pass after a red is
  **recovered**. A new red names the branches merged since its last pass.
- **A pair that cannot run faults:** an exit other than pass or test failure
  (heavy's 75 for disk among them), a missing or inconsistent JUnit, a rerun
  that does not select exactly its test. A faulted pair says nothing about
  its tests. A run is **red** with any confirmed red, else **partial** with a
  fault, else **green**. The cursor moves only past a run without a fault; a
  partial tip is not run again, the next tip's run takes its suspects.
- **Records, not posts:** each run appends to
  `FAB_HOME/after-landing.jsonl` on its builder one `test` record per test
  that is not plainly passing, then one `run` record (tip, suspects'
  branches, verdict, counts, pairs, faults, logs). `fab after-landing log
  --since` serves them over ssh, as `fab queue log` does. The state (cursor,
  last run, each test's last executed result) is
  `FAB_HOME/after-landing/state.json`, saved after the records; a run cut
  short is redone whole.
- **The slot stays bounded:** a run ends by sweeping the slot's target as the
  queue sweeps its own (section 7).
- **Left out from the old tool:** posts to coordinators and its resolver,
  bisection to a culprit commit, hourly coverage posts, the records writer and
  its detail files, heavy cancellation and wall bounds beyond the steps'
  timeout, the guardian and replay of a half-run pair, and the tier runner's
  CPU accounting and budgets (still fabrig's `tools/tiers --cpu`). Each
  attaches to the records above when numbers show it is needed (section 14).

## 12. Gates and the structure review

From the user's execution model: quality is checked by code on every branch,
and Claude reads the code's structure in batches, never on the landing path.

- **The digest** of a branch (`fab/digest.py`) is what a reviewer needs
  without reading the code: the public items it adds, removes or changes
  (from `fab.calls.inventory` on its base and its tip), new modules, its
  changed paths split into production, tests and docs with their lines, the
  paths outside its task's `files`, new or changed functions longer than 60
  lines, and blocks of 8 lines repeated from elsewhere in the package. The
  base is the tip's merge base with main; both trees are `git archive`s of
  `fab/`. It is deterministic Markdown of at most 8,000 characters, written
  to `FAB_HOME/digests/<run>.md` when the tick gates the branch.
- **The gates** (`fab/gates.py`, not fabrig's `fab/gate.py`) are pure checks
  over the digest and the task. The tick runs them, in `fab land`'s clone and
  under its lock, before it lands a task's branch of this repository:
  - `files`: every changed path is within the task's globs;
  - `shape`: no signature the base has is changed or removed, unless the
    task's kind is `interface` or `migration`;
  - `size`: no function the branch adds, or makes longer, is over 60 lines
    (a ratchet: touching an old long function without growing it passes);
  - `names`: no new public name or module holds a word from the banned list
    in `fab/taste.md`;
  - `docs`: every new public function, class and method has a docstring;
  - `clones`: no block of 8 lines (blank lines, comments and imports left
    out) touched by the branch also stands elsewhere in the package.
  `size` and `clones` read production modules only. A failed gate logs
  `branch.rejected` with step `gate:<the first failed gate>`, log the
  digest's path, and `findings`, the findings as text; a tip whose Python
  does not parse is step `gate:parse`. The repair run's brief quotes the
  findings (section 6). A gating that cannot run (git fails) is a failed
  action and the branch waits; it never lands ungated. The first gates read
  Python (this repository); fabrig's, over Rust and its public API, come
  later.
- **The taste file,** `fab/taste.md`, holds the banned names and pairs of
  good and bad code from this repository, each with one line on why. It is
  added to every implementer's brief after the role text.
- **The structure review** is a Claude call, role `review`
  (`fab/roles/reviewer.md`, subject `<draft>/review`), when ten tasks have
  landed since the last review call started or four hours have passed since
  then with any landed. A failed review counts as the last one, so it waits
  for the next threshold. Its brief is the digests of the branches landed
  since the last review that ended done, the taste file, the inventory and
  the designs those branches cite; it reads full code only for what the
  digests flag and a sample. It writes consolidation task specs (merges,
  renames, splits; kind `interface` when a signature changes) into the plan
  and new pairs into the taste file, on its branch, which lands as a
  skeleton call's does. It never holds up a landing.
- **A question from a call parks its subject:** a skeleton, answer or
  review call that ends with a question starts no further call for that
  subject until `call.answered` names it (13.6), or a later call of the
  subject ends done. An answer call's subject is its draft.

## 13. Growing toward the full model

What the user's execution model asks that fab does not do yet, cut into parts
the loop designs and builds itself (`docs/plan/agents-rebuild/plan.toml`,
slice 6). Two rules hold throughout: whoever designs a thing never accepts
it, and the flow grows from a small start rather than to a fixed cap.

### 13.1 Design and acceptance are separate

- **A Claude call's output is reviewed before it lands.** A skeleton,
  answer, structure review or designer's call's branch (13.3) gets a
  read-only Codex review run (kind `review`, effort medium,
  `fab/roles/call-reviewer.md`). Its brief
  holds the call's brief and its diff from the merge base with main. It
  reports at most ten lines on contradictions with the design, layering
  breaches, gaps a task would hit, and duplicates of what the inventory
  already holds. Its report's first line is `Done: approve` or `Failed:
  <findings>`. Approved, the branch lands. Refused, the findings go back
  once, as an amend call (`fab/roles/amender.md`) on the same branch.
  Refused twice, the call's subject parks for the user.
- **A chain** (`fab/call_review.py`) is a call that ended done, the amend
  calls on its branch, and their review runs; the tick folds it from the log
  and takes its next step:
  - review runs are ordinary runs: `run.started` with task the root call's
    id (run `<call>-<n>`), kind `review`, `call` the call reviewed and its
    `tip`. The tick collects them as any run.
  - A review run takes the builder with most free places, even at none,
    since it builds nothing.
  - The amend call is `fab call amend ROOT`, its `call.started` carrying
    `amends`. A run ending `Infra:` is reviewed again, up to three times.
  - A second refusal, an amend call that does not end done, or a third
    `Infra:` logs `call.parked`.
  - A `call.answered` naming the subject (13.6) starts the chain's counts
    afresh: the branch's tip is reviewed again, and may be amended once
    more.
  - While a subject's chain is open, no call starts for that subject; no
    answer call starts while an answer chain is open, and no review call
    while a review chain is open.
- **Acceptance is the test-writer's, at the level of the design.** When a
  part's skeleton lands, one test-writer run (Codex, high, kind `tests`)
  writes the part's acceptance tests from its design section and its
  skeleton's test vocabulary alone, never from bodies: the behaviours the
  design promises, through the part's public items. It runs beside the
  part's implementers, not before each one. Its tests land at once, marked
  pending (skipped with the reason `pending: <draft>/<part>`), so main stays
  green. Implementers write their own unit tests, as today, and never edit a
  pending test; one they believe wrong is a question.
- **A part is accepted when its acceptance tests pass.** When all a part's
  tasks have landed, an accept run (Codex, medium, kind `accept`) removes
  the part's pending markers and runs the suite. Green, the part is done and
  the branch lands; red, its findings become repair tasks of the part, and
  the part is not done.
- **A slice's story test** is the test-writer's too: written when the last
  part of the slice is designed, pending on the slice (`pending: slice <n>`),
  un-pended by the accept run of its last part. A slice is complete when its
  story test passes on main (`slice.done` in the log).
- **Every branch gets a self-critique before ready.** After the gates pass,
  a read-only Codex run (kind `critique`, effort high, `fab/roles/critic.md`)
  reviews the branch against its skeleton, the taste file and the gates'
  output; the implementer's next run on the same branch fixes what it finds,
  once, before the branch lands or is readied. A critique with no findings
  lets it through at once.
- **The foreman writes the rebase and repair tasks,** as the user's model
  has it. When the landing refuses a branch, a foreman run reads the task,
  the refusal and the failing step's log, and writes the repair: an
  `## Repair` section appended to the task's spec, saying what failed, where
  to look and what to change, or that the red is not the branch's (a fault
  of the gate, a flake), in which case the tip is retried unchanged
  (`fab queue untry`) and no repair run starts. A conflict gets a rebase
  section the same way. The repair or rebase run then reads its spec, as
  every run does.
- **The foreman settles what the options settle.** A run ending with a
  question first goes to a foreman run (Codex, medium, kind `foreman`,
  `fab/roles/foreman.md`; it writes no code, code records what it decides) with the task spec and the report: when
  the spec's pre-approved options answer it, the foreman's answer is
  recorded in the spec's Answers section and the task runs again; otherwise
  the question queues for the answerer: at once when it holds up other work
  (a task waits on the parked one, or nothing is running while work remains),
  otherwise at 4 queued or after 30 minutes (the user, 10-30; the model said 2
  hours).
  - `fab/foreman.py` folds where each open question stands: at the
    foreman, deciding, settled or queued. Questions of implement, repair and
    rebase runs go to the foreman; the rest (a park at the run limit, one
    logged by hand) queue at once. The answerer's thresholds and brief count
    queued questions only, aged from when they queued.
  - A foreman run is an ordinary run whose task is `<task>/foreman` (run
    `<task>/foreman-<n>`), which no task has, so it is not one of the task's
    runs; `asked` names the run that asked. It reads a worktree of the
    task's repository detached at main, started as review runs are
    (`fab.run.launch_detached`).
  - Its report's first line is `Done: <the answer>` or `Failed: <why the
    options do not settle it>`. Done, the tick writes the answer into the
    spec on a branch `answers/<run>`, lands it with `fab land` and logs
    `question.answered` (by the foreman run); a landing that fails is tried
    again next tick. Any other outcome, infra too, queues the question: a
    foreman runs once per question.
- **The structure review stays its own call** (section 12), never the
  skeleton author's.

### 13.2 The flow grows

- **Places are indicative.** A builder's `places` in `fab/hosts.toml` is a
  hint, not a cap: the dispatcher's own target for runs in flight starts at 2
  when a plan starts, grows by one with each task landed on its first
  attempt, and drops by one with each rejection or infra outcome, never below
  1; it may pass `places` while the builder's load and heavy's waits stay low
  (heavy and the disk wait still bound what actually builds).
- **The target is a fold** (`fab.flow.target`) over the plan's events in the
  log, recomputed every tick and never stored. A landing grows it only when
  its run ended with the window full (the plan's runs in flight, that run
  among them, at least the target): an unused target says nothing about a
  larger one. The tick starts runs while the plan's runs in flight are below
  it, and prints it (`flow <draft> target <n>, <m> in flight`).
- **Calm** (`fab.flow.measure`, one ssh per builder each tick): the 5-minute
  load per CPU below 0.7, and over the last 30 minutes of the builder's
  `heavy.jsonl` lane and disk waits under 5 minutes in all and no disk
  refusal. A builder with no free place that is calm takes one more run per
  tick, never more runs than its slots; a builder that cannot be measured is
  not calm.
- **Longer runs are better than more round trips.** A task is one module or
  concept, about 400-500 production lines with its tests, 30-60
  implementer-minutes; the skeleton author splits finer only where parts
  must run at once.

### 13.3 The designer's calls

The designer of the user's model is four Claude calls (`fab/designer.py`),
each with its role text in `fab/roles/`. Like every call, each is reviewed
before it lands (13.1).

- **cut:** a draft and the repository's designs in, `docs/plan/<draft>/plan.toml`
  out: parts with modes and needs, shared contracts as early parts marked
  `contract`, slices with their story and whether QA walks them, and the
  user's questions as `[[question]]`s naming the parts that wait for them.
  No signatures and no task specs. Its brief holds the drafts, a one-line
  index of the designs (path, title, size, status file) and the existing
  plans as examples; the call reads the designs it needs itself.
  - It is started by hand when a draft lands: `fab call cut --plan
    PLAN_DIR --source PATH...`, PLAN_DIR being `docs/plan/<draft>` in a
    checkout (it need not exist). The call lists PLAN_DIR in
    `FAB_HOME/plans` (13.4) and runs; its subject is `<draft>/cut`.
  - Its chain is the tick's of PLAN_DIR: a plan directory with no
    plan.toml but a cut call in the log ticks as a plan with no parts, so
    only the cut's chain moves. Once its branch lands, the plan is there and
    the next tick runs it: that is how the cut starts the plan.
- **contract:** a part marked `contract` is designed by the designer, not
  the skeleton author (the user's model: "the designer writes it"). The call
  is a skeleton call with the role `contract` (`fab call contract PART`),
  its brief the skeleton author's with the contract's readers named. Its
  subject is the part's, `<draft>/<part>`, so a part is designed by one or
  the other. One contract call and one skeleton call may run at once.
- **The user's questions park parts, not the plan:** a part named by a
  question without an answer is not designed; its readers wait as for any
  need. A skeleton or contract brief shows the part's questions and their
  answers. The user's channel (13.6) lists the open ones.
- **decision:** a probe's report in, a design section out. `fab call
  decision PART --run RUN` for a probe part, its brief the probe's report
  (`FAB_HOME/runs/<run>/report.md`), its readers and their designs; its
  subject is `<draft>/<part>/decision`. It writes the section the readers
  cite and its status file, and changes the plan only where the measurement
  does. What starts it is the probe's (13.7).
- **retire:** when a plan's parts are all done, the tick starts one retire
  call (subject `<draft>/retire`). Its brief holds every design changed
  since the plan started, with its status file: those a commit since the
  one that added plan.toml changed, or whose status file it changed. It
  brings the status files current and sets `retired = true` in plan.toml.
  The Codex consistency pass is its chain's review run, with its own role
  text (`fab/roles/consistency.md`) and the list of changed designs; a
  refusal goes back once as an amend call. Once it lands, the tick skips the
  plan.
- **Where they land:** as every call, through `fab land` for this
  repository, so they may change only what it allows (section 6).

### 13.4 Several plans, calls in parallel

- **The tick takes every plan** listed in `FAB_HOME/plans` (one checkout path
  per line), each its own draft; places are shared across plans.
- **Skeleton calls run in parallel** for independent parts, up to two at a
  time to start, growing as 13.2's target does.

### 13.5 Accounting

- **run.ended carries Codex's tokens** (input, cached, output) from the run's
  result: `fab run status` reads the launcher's `result.json` in the ssh that
  reads the report, and `tokens` is `<input>/<cached>/<output>`, Codex's
  input holding its cached tokens. call.ended's `tokens` keeps its shape,
  `<input>/<cache read>/<output>`, Claude's input holding neither cache reads
  nor writes, and gains `cache_write`. Records from before have no
  `cache_write` or no `tokens`, and weigh as if they had none.
- **A call's usage comes from claude's stream** (`--output-format
  stream-json`), kept as `FAB_HOME/calls/<id>/stream.jsonl`: the totals and
  turns from its result event, and `peak`, the largest context (input, cache
  write and cache read) of one message of the main thread; subagents have
  their own context and are left out of it. A call cut short by its timeout
  has no result event, and is measured from the messages it streamed.
- **The code report weighs both** (`fab/accounting.py`): input 1, cache write
  1.25, cache read 0.1, output 5 for Claude and 8 for Codex, in millions. A
  draft's Claude calls are those whose subject is the draft or under it; its
  Codex runs are its tasks' and the review runs of its calls. Its figures show
  the Claude and Codex tokens, both weights, the Claude to Codex weight, the
  largest call context and the calls over 600k; a Calls table lists each call
  with its minutes, turns, peak context, weight and whether it is over.
- **A call is measured, not capped, for now** (the user, 10-30): no context
  cap and no turn limit (no `--max-turns`); a call is stopped only by its
  40-minute timeout. call.ended carries its peak context and turns, and the
  code report flags calls over the user's 600k target (10-30; the model's
  draft said 120k). Of the first eleven calls, seven peaked over 120k
  (130k-190k) and all ended well; the user sets a cap, if any, from the
  measurements. The code may hold an unset
  bound for later; nothing ends a call for its size now.

### 13.6 A channel to the user

- **Questions that are the user's** (budgets, machines, what is hard to
  reverse) park their task and are listed, with the reports' signals that
  are the user's, on one page the user reads; nothing else goes to the user.
- **Whoever asks decides it is the user's,** never the page. Three things
  are (`fab.channel.asks`, folded from the plans and the log):
  - a plan's `[[question]]` with no answer, the cut's (13.3);
  - a call that ended `Question:` (section 12);
  - a call's chain parked after its review refused twice (13.1).
  A task's questions are the foreman's and the answerer's and never reach
  the page; an answer call that cannot settle one ends `Question:` itself.
- **The page** is `FAB_HOME/user.md` on hel8 (`fab/channel.py`):
  - the open questions, the plans' first, then the log's in the order they
    were asked, each with what to read and how to answer it;
  - then, from each standing report's latest day (section 10), its path and
    only the Signals lines whose owner is the user (the drafts' signal
    tables: targets, capacity, a usage limit, a budget the three questions
    could not settle); the rest of each report is the director's.
  The tick rewrites it at its end; `fab page show|write [PLAN_DIR...]`
  makes it on demand. Its plans are those in `FAB_HOME/plans` (13.4) and
  those named. The drafts send the reports to the director, who passes the
  user what needs the user; the director reads the same page.
- **Answers come back on the same path.** `fab page answer SUBJECT TEXT` on
  hel8 logs `call.answered` and rewrites the page. The subject's calls may
  start again, and a parked chain's counts start afresh (13.1). Every later
  call of the subject, and every review run of its chain, carries the
  user's answers in its brief (`# The user's answers`). A plan's question
  is answered in its plan.toml, landed with `fab land`.
- **Subjects are named apart from tasks:** `question.answered` names a task
  and `call.answered` a subject. A part and a task of the same name never
  unpark each other.

### 13.7 Probes

- **A probe** is a read-only Codex run with a time box (the part's
  `minutes`, hard) and a success criterion from its design; its report is
  the measurement; a decision call (13.3) turns it into design.

### 13.8 The landing side

- **Precheck receipts are reused:** a batch of one branch whose precheck
  receipt names the same main and passed lands on the receipt's checks
  alone, after fmt; the queue's own full checks still run on every fifth
  batch and on every batch of more than one.
- **Reds are classed before anyone hears them:** a failing test that passed
  in the branch's precheck is retried once alone; passing, the red is
  collateral, recorded as such, and the branch is retried without counting
  against it; failing twice, it is the branch's.

### 13.9 Events drive the tick

At the user's word (10-30): the loop reacts to what happens, and polling is
only the backstop.

- **An event starts a tick.** Whatever ends work the dispatcher waits for
  starts `fab-tick.service` on hel8: a Codex run's unit when it stops (its
  ExecStopPost, over ssh from the builder), a Claude call when it ends, the
  queue when it records `landed` or `rejected`, `fab land` when it lands, a
  question answered by hand.
- **Events coalesce.** Starting the tick while one runs or waits to run adds
  nothing: systemd keeps at most one start pending, so a burst of events
  makes one tick after the running one, never a queue of them. A tick reads
  every new record anyway.
- **The timer is the backstop,** never the driver: it ticks at most every 30
  minutes, for a lost event or a host that could not reach hel8. Until the
  events are in place the timer stays at 2 minutes.
- **A tick that wants another starts one:** when a tick's own actions end
  work the next decision depends on (a landing that makes tasks runnable,
  a finished call), it starts the next tick at its end.

### 13.10 The timeline's flow

The user's example timeline (`execution-modes.md`, "Example") is the order of
things fab follows, whatever the clock says:

- **Intake:** a draft landing in a repository's `docs/design/draft/` starts
  its intake: the surveys, then the cut. Nobody starts a cut by hand.
- **Surveys:** read-only Codex runs (medium, kind `survey`), at intake (the
  readers of what the draft changes, the primitives in reach with their
  signatures, each area's test world) and before each skeleton call (the
  primitives in reach, refreshed); their reports go into the cut's and the
  skeleton call's briefs, beside the code-built inventory.
- **The buffer's order:** among runnable tasks, consolidation tasks from a
  structure review come first ("at the head of the buffer"), then repairs and
  rebases, then tasks of contract parts, then tasks by their part's slice, in
  plan order.
- **Then, as written:** contracts land alone and their readers are pulled;
  probes run beside and their decisions land before their readers' skeletons;
  answers come in batches, at once when they hold up work; slices complete
  on their story tests; QA walks the walkable slices (once QA is here); the
  last call retires the draft. Each is a part above or in section 14.

## 14. Later

- The self-critique: a read-only Codex run against the skeleton and the taste
  file before ready, its findings fixed by the implementer.
- fabrig's gates, over Rust and its public API against the skeleton.
- Gates on the calls' own branches (skeletons, reviews), which have no task
  `files` to check against.
- `fab report daily` on a timer on hel8, with the dispatcher's; reports
  posted to the director rather than read from FAB_HOME.
- Report metrics the records do not hold yet: lines changed per landed
  branch, questions by kind, continuity, CPU per step against its budget,
  after-landing verdicts; targets and their signals once the user sets them.
- after-landing live: its unit on a builder and its slot, the old tool
  stopped, fabrig's package map moved to `.config/tiers/`; then new reds
  reaching their tasks through the dispatcher, bisection when several
  branches are suspects, CPU accounting against the tiers' budgets, and the
  landing report's after-landing figures. QA walks as a run kind.
- Elastic builders from `fab hosts check`'s numbers.
- The flow's target and each builder's calm in the code report, beside runs
  in flight per hour; the target shared across plans (13.4).
- The foreman for plans whose specs live in another repository: its answers
  landing through that repository's landing, not `fab land`.
- Retiring the session launcher, watch's session rules, mail, leases and the
  event collector once nothing resident remains.
- The cut started by the tick when a draft lands that no plan serves, once
  a draft can say where its plan goes.
- The designer's calls for repositories other than this one, and changes to
  designs outside `docs/design/fab*`, once calls land through tools/land or
  fabrig's queue.
- The user's page published where the user reads it without hel8 (the
  status page, a doc), once the user says where; a notification when a
  question joins it.
- A plan's question answered by `fab page answer`, writing plan.toml and
  landing it as the foreman lands its answers.
- A cap on a call's context or turns, once the user sets one from the
  measurements (13.5); Claude and Codex usage against their plans' limits,
  once the limits are recorded somewhere fab can read.
