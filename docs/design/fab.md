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
| `FAB_HOME/hosts.local.toml` on any machine | live overrides of `fab/hosts.toml` there, by hand (section 7) |
| `FAB_HOME/user.md` on hel8 | the user's page: their open questions and the latest reports (13.6) |
| `FAB_HOME/tick.want` on hel8 | the reasons the tick was woken since it last ran (13.9) |
| `FAB_HOME/repos/<repo>` on each machine | fab's own clones; `FAB_HOME/wt/<run>` worktrees for runs that build nothing |
| `~/src/fabrig/slots/<n>` on a builder | warm fabrig checkouts (unchanged); `slots/<n>.claim` the slot's claim (section 7) |
| `FAB_HOME/after-landing.jsonl` on the after-landing builder | its verdicts; `FAB_HOME/after-landing/` its state and each run's logs (section 11) |
| `FAB_HOME/reds/<red>.md` on hel8 | an after-landing red's evidence, written when it opens (section 11) |
| `FAB_HOME/walks/<walk>/` on hel8 | a QA walk's compiled brief, its walker's `report.md` and `result.toml` (13.15) |
| `~/src/fabrig/logins/shelf/` on hel8 | every login at rest or its placeholder while lent (13.13) |

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
| `run.started` | run, task, kind, host, dir, branch, base | a Codex run began; kind is implement, repair, rebase, review or foreman; check is an integration branch's full check (13.12); a foreman's carries `asked`, `refused`, `red` (13.1) or `finding` (13.15) |
| `run.ended` | run, task, outcome, report, minutes, tokens | outcome is done, question, infra or failed (section 5); tokens is Codex's (13.5) |
| `branch.ready` | task, branch, tip | handed to the landing pipeline; a ladder's backlog branch carries `render`, its file's sha256 (13.15) |
| `branch.landed` | task, branch, tip, main, into | on main; with into, merged into an integration plan's trunk, main being its new tip (13.12) |
| `branch.rejected` | task, branch, tip, step, log | the landing refused it; its foreman decides what follows (13.1) |
| `refusal.settled` | task, run, verdict, reason, branch, section | the tick acted on a refusal's foreman run: fix (its section landed in the spec), retry (the tip goes back unchanged) or none (13.1) |
| `question.asked` | task, run, text | the task parks until answered |
| `question.answered` | task, by, answer | the task may run again; it names a task, never a call's subject |
| `call.started` / `call.ended` | call, role, subject; outcome, tokens, cache_write, peak, turns, minutes | a Claude call; its usage (13.5) |
| `call.finished` | call, role, outcome | the dispatcher landed a call's branch, or failed to |
| `call.parked` | call, subject, reason, report | a call's branch waits for the user (13.1) |
| `call.answered` | subject, call, by, question, answer | the user answered a subject's question or parked chain (13.6) |
| `issue.opened` | subject, kind, number, url | an open user ask has a forge issue (13.16) |
| `issue.comment` | number, subject, comment | a user comment consumed before its reply call (13.16) |
| `issue.replied` | number, call; outcome | the loop posted a reply; outcome is failed only for an unreadable or failed call (13.16) |
| `issue.closed` | number, subject | the subject no longer has an open ask; its issue is closed (13.16) |
| `tiers.run` / `tiers.red` / `tiers.recovered` | tip, verdict, counts, branches, commits, faults, reds, log; tip, key, state, profile, binary, test, error, branches, log, rerun; tip, key, profile, binary, test | imported from the after-landing machine, `al_ts` its record's time, `host` the machine's name (section 11) |
| `red.opened` | red, tip, keys, suspects, tasks, draft, route, reason | an after-landing red's tests, grouped, sent to a foreman or to the page (section 11) |
| `red.settled` | red, run, verdict, reason, owner, section | the tick acted on a red's foreman: fix or none (a repair task follows) or left (the page) (13.1) |
| `red.closed` | red, reason, tip | every test of the red recovered or is no longer red in a run without faults, or its signal was cleared (section 11) |
| `queue.rejected` / `queue.landed` / `queue.collateral` | branch, tip, step, log, tests; branch, tip, main; branch, tip, step, tests, log | the queue's record of a branch no fab task owns, `queue_ts` its time, `gate` the gate host's name (13.8) |
| `signal.cleared` | signal, by, text | a signal taken off the user's page by hand (13.6) |
| `walk.started` / `walk.ended` | walk, draft, rung, backend, edition, commit, by; walk, verdict, reason, report, findings | a QA walk of a ladder plan's rung; verdict pass, fail or void (13.15) |
| `finding.raised` | finding, draft, walk, index, rung, backend, commit, edition, kind, title, severity, area, blocking, reproduction, expected, seen, evidence, again | a walk's finding, from its `result.toml` (13.15) |
| `finding.merged` | finding, into, by, reason | the same finding as `into`: named by the walker (by the walk) or judged by triage (by the call) |
| `finding.triaged` | finding, call, decision, owner, reason, question, into | a triage call's decision: path, backlog, user, brief, drop, or again (a merge into a fixed finding) |
| `finding.settled` | finding, run, verdict, reason, section | the tick acted on a finding's foreman: fix or none (a repair task follows) or left (the page) |
| `rung.passed` | draft, rung, walk, edition, commit | a rung's brief rerun unchanged and passing, its lower rungs passed (13.15) |
| `login.checked` | id, email, plan, used, resets, error, limit_names, limit_used, limit_resets | account check and limits (13.13); the three limit lists hold scalars of equal length in the same order, with null use or reset when unknown |
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
  part is called `cut`, `retire`, `review` or `triage`: those name calls'
  subjects. A ladder plan names `[ladder]` and its `[[rung]]`s instead of
  parts (13.15).
- **A task spec** is Markdown with a TOML header between `+++` lines: `id`,
  `part`, `kind` (feature, interface, migration, repair, rebase or docs),
  `repo`, `needs` (tasks that land first), `files` (globs it may change),
  `effort` (medium or high) and `minutes` (the expected implementer time,
  as 13.2 sizes them: one module or concept, about 400-500 production lines,
  30-60 minutes; in this repository, with its fast tests, tasks may come out
  smaller, which does not carry over to fabrig) and `consolidation` (true
  for a structure review's task, 13.10; default false). The body says what
  to fill, how it is accepted, and the pre-approved options with their
  defaults.
- **A task's status is computed:** `waiting` (a need has not landed),
  `runnable`, `running`, `parked` (a question is open, or the run failed and
  needs judgement), `done` (its run ended checked), `ready`, `landed`,
  `rejected` (waiting for its repair or rebase run). An `Infra:` outcome makes
  it runnable again. `fab.state.fold` derives it from the specs and the log.
- **A part is designed** once its skeleton and task specs have landed, and
  **done** once all its tasks have landed (`fab.state.part_statuses`).
- **A part's design waits for its needs to be designed, not done,** as the
  user's timeline has it: a contract's readers are pulled when its skeleton
  lands, not when its bodies are filled. A need that must be done first (a
  design that depends on measured behaviour) is listed in the part's
  `needs_landed` instead; a probe's readers wait for its decision. Tasks
  still wait for the tasks they need to land.
- **Design keeps just ahead of the flow:** the ready-task buffer is measured
  against the flow's current target for runs in flight (13.2), not against
  the builders' nominal places.

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
  `FAB_HOME/queue.jsonl` there (`batch`, `landed`, `rejected`,
  `collateral`), which the dispatcher reads; the tips it has tried and
  their collateral reds (13.8) are its only other state. A `rejected` at
  a test step carries `tests`: the failed tests of the step's derived
  `gate-junit.xml`, `<binary> <test>`, at most 20 ([] at any other step), so
  whoever hears it (a foreman, the user's page, 13.8) reads them without
  the log.
- **Queue CPU, report only:** `fab/queue_cpu.py` runs the queue's `default`
  and `fuzzy` steps through the shared `fab/cpu.py` collector (section 11),
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
  classification (13.8) reads a derived `gate-junit.xml` with those reconciled
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
  in the batch and detail log, without rejecting it. Receipt reuse (13.8)
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
  (5-10 GB), and one slot bound more on a gate for the queue's target, which
  each batch sweeps as a slot's is. hetzner6: 50 + 8 x 25 + 10 = 260 of 305
  GB, the rest for QA boxes, archives and the system. `fab hosts check`
  computes it from `fab/hosts.toml`.
- **Live overrides, by hand:** `FAB_HOME/hosts.local.toml`, never in git,
  holds tables named after hosts of `fab/hosts.toml` with the keys to change
  (`roles`, `places`, `builds`, `slots`, the disk figures; never `ssh` or
  `hostname`). Every reader of the machines applies the file of the machine
  it runs on: the dispatcher's on hel8 (`places`, `roles`: from the next
  tick), heavy's on a builder (`builds`, `headroom_gb`: from its next
  command), `fab queue install`'s at a deploy (`roles`). Scaling hetzner8's
  builds down for the queue is `[hetzner8]` with `places` on hel8 and
  `builds` on hetzner8; the running work drains. A bad file fails the tick
  and `fab hosts check` (which lists the overrides in force), and heavy
  reports it and builds on the file as it is. A lasting change goes into
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

- **Evidence hashes** (precheck's `result.json` bound to trees): the log's
  `run.ended` and `branch.*` events carry tips, and the queue reuses a
  receipt only for its tip and main (13.8); a check binding receipts to
  trees attaches at `fab land` and the queue's intake.
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
  red classes) and collateral ones (a rejected tip that later lands, and the
  branches the queue retried after a collateral red, 13.8); batches landed
  on a precheck receipt; ready to
  landed latency (from the log's `branch.ready`), branches waiting and the
  oldest wait; bisection runs and minutes; repair rounds; each step's
  durations, failures and timeouts; batches in error; heavy's waits on the
  gate. From the log, cheaply (section 11, 13.8): after-landing reds opened,
  sent to a foreman and sent to the page; settled fix, none and left (not
  the suspects'); red repairs landed; reds closed, by reason (recovered,
  absent, cleared), with the median hours from opened to recovered (the
  draft's "time to the confirmed fix"); hand-pushed rejections
  (`queue.rejected`). From the log too, the landing draft's "QA passes ...
  and their findings" (13.15): walks by verdict, findings raised and
  merged, triaged by decision, finding repairs landed, rungs passed, and
  the median hours from a failed walk to its rung's next pass. These are
  decisions the tick records anyway, not records kept for the report.
- **Signals without targets:** a report raises only the drafts' signals that
  need no number of the user's: idle gaps, rising rejections, Infra runs,
  collateral rejections, queue errors, a ready branch waiting over an hour and
  longer than the day before, disk waits and unread sources, an after-landing
  red or a hand-pushed rejection with no owner fab knows (13.6's open
  signals), each with the draft's first action and owner. Thresholds come with targets.
- **Where they go:** `FAB_HOME/reports/<draft>/<day>.md` and
  `FAB_HOME/reports/landing/<day>.md` on hel8, written to a sibling and
  renamed. `fab report daily PLAN_DIR...` writes yesterday's that do not
  exist yet; the director reads them there.

## 11. After landing

- **fabrig's slow tiers run on each new main,** ported from the agents
  repository's `tools/after-landing` (`docs/design/after-landing.md`) and
  fabrig's `tools/tiers/run`. `fab after-landing run --slot N` loops on one
  builder in one slot claimed for it (`fab slot claim N after-landing
  after-landing`); it refuses any other slot.
- **Its machine and slot are config:** the builder with the role
  `after-landing` in `fab/hosts.toml` names its `after_landing_slot`
  (hetzner8, slot 7). `fab after-landing install`, run by the deploy on
  every machine as `fab queue install` is (section 6, `fab/units.py`),
  claims that slot for good and writes `fab-after-landing.service`; a stop
  waits up to two hours for the run in progress, so a deploy never cuts one
  short. On a machine without the role it disables a unit it finds; the
  slot's claim is released by hand there. Every cargo command goes
  through `heavy` in the build lane, which waits for disk by itself.
- **A tier is a pair:** a nextest profile `<tier>-<tree>` of fabrig's
  `.config/nextest.toml`, its packages and the native binaries its tests run
  from the package map (`.config/tiers/packages.toml`, or
  `tools/tiers/packages.toml` until fabrig moves it). `fab tiers run TREE
  TIER` builds the pair's browser bundle and binaries, then runs its packages'
  tests; `fab tiers verify` checks the map against the workspace's listing.
- **The tier set** is a list in the code: `browser-jig`, `browser-temper`,
  `browser-skein`, `process-temper`, in that order (since 11-01: the qa,
  exhaustive and process-jig pairs ended, their tests re-tiered; process-temper
  joined within its 360 CPU-s). Not by default the live pairs (real
  providers, the user's sign-ins): `--live` adds `live-skein`, on logins
  borrowed from the shelf (13.13). `live-smith` awaits a signed-in live root.
  `live-temper` is out pending the user's decision on which ignored owner-run
  stories, if any, should run with `--run-ignored`: since fabrig eb6c40aaf its
  live binaries have no harness unit tests, so it selects no tests, nextest
  exits 4, the pair faults and the cursor cannot move.
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
  **recovered**. A new red names the branches merged since its last pass;
  an unattributed red names the run's suspects' branches (a test that
  never ran before and fails is most often new in one of them).
- **CPU measured on every pair:** `fab/cpu.py` loads the checkout's
  `tools/tiers/cpu.py` with `runpy`, as `tools/tiers/design.md`, 7.1 permits.
  It builds that tip's static `cpu-wrapper.c` once through heavy in the run
  directory, keeps fab's prerequisite steps, and calls `prepare`/`execute`
  for each nextest invocation, including exact-test reruns. Calling
  `tools/tiers/run --cpu` instead would reserve the config selection fab
  needs and apply its per-pair budgets as verdicts. An isolated Python
  worker runs the collector through fab's runner seam; `collect` accepts
  the caller's profile, command and package selection. The queue reuses it
  for default/fuzzy with report-only per-tree budgets (section 6).
  The collector verifies JUnit attempt coverage and descendant accounting
  (`tools/tiers/design.md`, 7.2–7.3); incomplete CPU on a stopped attempt
  remains a lower bound. A separate nextest listing inventories selected
  tests, so cancellation cannot turn unstarted tests into passes.
- **One optional budget for the set:** the checkout's
  `tools/tiers/budgets.toml` may have `[after-landing]` with any of
  `cpu_total_s`, `cpu_test_s`, `wall_hard_s`, each finite positive seconds.
  There are no defaults or initial figures: only the user sets them.
  CPU is user plus system time of tests and accounted descendants, summed
  across pairs and reruns; compilation, admission and wrapper overhead are
  excluded. Total wall is the sum of pairs' test execution spans, including
  reruns and settlement, excluding prerequisites and admission. With no
  limits, numbers are report only. Exceeded total or per-test CPU is red,
  naming the contributing tests. Per-pair budget tables are retained only
  as diagnostics in pair records, never as verdicts or enforced wall limits.
- **Wall expiry is starved:** nextest slow-timeout termination, global-timeout
  cancellation and collector-starved tests are passes reported as `starved`,
  counted separately and never confirmed with a rerun. The remaining total
  wall allowance caps each invocation's private `global-timeout`, keeping
  any shorter configured timeout. Nextest owns termination and JUnit;
  its cancellation line and terminated/pending records reconcile global
  cancellation, which JUnit otherwise calls an abort. Completed signal failures
  reported before cancellation stay red. This also works with
  fab's plain heavy, whose CLI has no token cancellation. Stop and descendant
  settlement can add cleanup time to the hard limit. Subsequent pairs are
  `unobserved`; selected tests never started are `unobserved`, never passed.
  An assertion or bad exit already observed remains red if wall expiry
  prevents confirmation or starves its rerun. Starved/unobserved results
  do not replace the last conclusive history or declare a red recovered.
  Starved tests using less than a tenth of their wall time in CPU are
  flagged as possible hangs, a diagnostic to investigate when repeated
  (`skein/docs/foundation/testing-strategy.md`, 2.10 and 8.1 in fabrig).
- **A retired pair is skipped:** a profile absent from the checkout's config
  is recorded as `retired`, without builds or login borrowing. The enrolled
  tier set stays explicit until the lead trims it.
- **A pair that cannot run faults:** an exit other than pass or test failure
  (heavy's 75 for disk among them), a missing or inconsistent JUnit, a rerun
  that does not select exactly its test. A faulted pair says nothing about
  its tests. A run is **red** with any confirmed red, else **partial** with a
  fault, else **green**. Exceeded CPU budgets also make it red; starvation
  alone stays green. The cursor moves only past a run without a fault; a
  partial tip is not run again, the next tip's run takes its suspects.
- **Records, not posts:** each run appends to
  `FAB_HOME/after-landing.jsonl` on its builder one `pair` record per pair
  (status, CPU, wall, diagnostic budgets), one `test` record per observed
  or inventoried test (state, CPU, wall, starvation and incomplete counts,
  possible-hang flag), then one `run` record (tip, suspects' branches,
  verdict, counts including starved and unobserved, total CPU and wall,
  optional budget, named budget excesses, possible hangs, pairs, faults,
  logs, and `reds`: the key of every confirmed red of the run, new, standing
  or unattributed, a test's key being `fab.nextest.Case.key`, the JSON
  string `["<profile>","<binary>","<test>"]`). Fields remain scalars or lists of scalars: budgets are `key=value`
  strings, `cpu_pairs` entries are `profile:cpu_s:wall_s` alongside the
  existing pair status summaries. `fab after-landing log --since` serves
  them over ssh, as `fab queue log` does. The state (cursor,
  last run, each test's last executed result) is
  `FAB_HOME/after-landing/state.json`, saved after the records; a run cut
  short is redone whole.
- **The verdict comes home:** each tick imports the after-landing
  machine's records into the log (`al_ts` the record's time, read from the
  newest imported, and beside it `host`, the machine's name, so the page
  can say where a log is: `<host>:<log>`, and `after-landing:<log>` for
  older records without it): a `run` as `tiers.run` (its `reds` and `commits` too:
  the evidence file counts the commits that are no branch's, which the
  tick cannot know otherwise), a `test` whose
  state is new or unattributed as `tiers.red` (tip, key, state, profile,
  binary, test, error, branches, log, rerun), and one whose state is
  recovered as `tiers.recovered` (tip, key, profile, binary, test). Standing
  reds are not imported one by one: the run's `reds` says which are still
  red. The user's page shows the newest run's verdict, counts, total CPU,
  test wall, starved count, possible hangs, any configured budget and
  excesses, faults, and its new and unattributed reds with their suspects'
  branches, each labelled by its state (`new red: ...`, `unattributed red:
  ...`), then
  one line per open red that is not a signal, `red-<n> (<draft>/red-<n>):
  <state>, <k> tests at \`<tip[:12]>\`, since <ts>` (below), under `##
  After landing`.
- **The slot stays bounded:** a run ends by sweeping the slot's target as the
  queue sweeps its own (section 7).
- **Left out from the old tool:** posts to coordinators and its resolver
  (the tick routes reds instead, below), bisection to a culprit commit,
  hourly coverage posts, the records writer and its detail files, heavy
  token cancellation, the guardian and replay of a half-run pair. Each
  attaches to the records above when numbers show it is needed (section 14).

**Reds reach their owners.** At the user's word (11-01, after the night of 10-31): fab found reds in two
places and acted on one. A red the queue found on a task's branch went to
its foreman and its repair; an after-landing red was classed and shown on
the page, and nobody acted. That night every such red was handled by a
session noticing it by chance: three runs red on live-smith's unset
`SMITH_LIVE`, live-temper faulting while every ChatGPT login was lent. The
landing draft's words are the rule: "a confirmed red goes to its owner with
its evidence; a fixed red is confirmed green by the same checks"
(`docs/design/draft/landing-pipeline.md`, 2). Built in `fab/tier_reds.py`,
which folds where each red stands, and the tick.

- **A red opens once, by tip and suspects.** After the import, the tick
  takes each `tiers.red` that no `red.opened` already holds (by tip and
  key), whose key the newest `tiers.run` lists in `reds` (still red; a red
  of an older run that has since passed opens nothing, and records from
  before `reds` existed open nothing), and whose key is in no open red. It
  groups them by tip and suspects (their `branches`, as a list), in log
  order, and opens one red per group: it writes the evidence file, then
  logs `red.opened`:
  - `red` is `red-<n>`, n counting `red.opened` in the whole log from 1;
    `keys` the group's keys; `suspects` its branches; `tasks` the fab tasks
    among them; `draft` the plan that holds it (the newest fab suspect's,
    the last in suspects order), "" when none; `route` foreman or signal;
    `reason` why a signal (`no suspects`, `no fab task among the suspects`).
  - **The unit is a tip's reds with one suspect set,** so a run that turns
    twelve tests red behind one merge starts one foreman, not twelve; the
    reds keep their own keys, so "one open repair per red" holds by key.
  - **The evidence** (`FAB_HOME/reds/<red>.md` on hel8, written to a
    sibling and renamed): the tip, the suspects (each branch, its task or
    `hand-pushed`, and the count of commits that are no branch's), then up
    to 20 reds, `- <profile> <binary> <test> (<state>): <error>` with
    `<machine>:<log>` and `<machine>:<rerun>`, then the last 40 lines of the
    first three reds' rerun logs, each in a `text` fence, read over ssh from
    the after-landing machine (`(log unreadable: <why>)` when it cannot be).
    A write that fails is a note and opens nothing; the next tick tries
    again. The foreman's brief and the repair's body quote it, since a
    builder cannot read the after-landing machine's files.
- **Which suspects are fab's:** a branch whose task (`fab.land.task_of`) is
  a task of a loaded plan, its red repairs included, or a loaded
  integration plan's trunk, `<draft>/integration` (its owner the plan,
  whose tasks the foreman reads). Any other named branch was readied by
  hand; a retired plan is not loaded, so its branches count as hand-pushed.
  This is a rule of its own, not 13.8's: the queue import keeps out of
  `queue.*` every branch the log knows, loaded or not, while a red's
  suspect must belong to a loaded plan that can hold its repair, so a
  retired plan's branch is hand-pushed as a red's suspect.
- **A red with a fab suspect goes to a foreman** (13.1, `fab/roles/
  foreman-red.md`): it reads the red, its evidence and the suspects' specs
  on main at the red's tip, and decides as a refusal's foreman does. The
  red is a suspect's: it writes what failed, where and what to change, and
  a repair task fixes it on a new branch from main. Not the suspects' (a
  flake that failed its rerun too, the tier or its environment, a
  hand-pushed suspect's change): no run starts, the decision is recorded,
  and the red goes to the page. A foreman that cannot say leaves the repair
  to start with the red alone, as a refusal's fallback does.
- **The repair is a task of its own, `<draft>/red-<n>`,** not the landed
  task reopened: the task's branch is gone, its dependents have started on
  its landing, and a landed status that went back would unsettle both. Its
  n is the red's, so ids never collide across drafts or with 13.12's
  `<draft>/repair-<n>`.
  - Folded from the log (`fab.tier_reds.tasks(plan, events)`, joined to the
    plan's tasks as 13.12's repairs are, `fab.integration.with_repairs`
    included), never a spec file: kind `red`, part `after-landing`, repo
    fabrig, no needs, files `**`, effort high, minutes 20. It exists from
    the red's `red.settled` with verdict fix or none, or its foreman's
    fallback; its draft is the red's `draft`. A red that closes before the
    task's first run.started drops the task.
  - Its body: `# Repair a red after landing (red-<n>)`, `- Tip: \`<tip>\``
    (main), the suspects and the owner when named, the evidence, the
    foreman's section when there is one, then `## Acceptance`: reproduce
    first, in the lowest tier that shows it (a unit test in the default
    profile when one can, failing on main before the change; else the red
    tests alone in their profile, through heavy), then fix; the
    reproduction and every red test pass with the change, then the task's
    own checks as any fabrig task (precheck `--onto origin/main`). A red of
    a live pair cannot be reproduced without logins: its section is the
    guide and the next after-landing run the check. Answers to its
    questions fold into the body under `## Answers`, as 13.12's.
  - It runs as an implement run from `origin/main`, in a slot, whatever
    the plan's landing: everything 13.12 reads as the trunk is main for it.
    Done, it is readied for the queue like any fabrig task (`ready/<draft>/
    red-<n>`, `branch.ready`, its precheck receipt) and lands as `Merge
    <draft>/red-<n>`; an integration plan never merges it into its trunk,
    and its end check, checks along the way and repairs leave kind `red`
    out. After-landing runs only fabrig, so no red task lands through `fab
    land`. The queue import's tasks include every loaded plan's red tasks,
    so its `landed` and `rejected` become `branch.landed` and
    `branch.rejected`; a queue refusal goes to its refusal foreman as any
    task's (13.1, specless).
  - **Two runs, then Claude:** its run limit is `RED_RUNS` (2), not
    `MAX_RUNS`: Fix mode wakes Claude after two failed tries
    (`execution-modes.md`). A park at the limit queues for the answerer as
    any park does, its thresholds applying; a question of its runs skips
    the foreman (no spec, no options) and queues, as a specless repair's
    does (13.12). Answer calls list red tasks and their questions in both
    landing modes (`fab/calls.py`), not only in integration plans.
- **One open repair per red, until it recovers.** A red is open from its
  `red.opened`; it closes when every one of its keys has closed, and the
  tick logs `red.closed` (reason `recovered`, `absent` or `cleared`, tip the
  run that closed the last key, "" for a clear). A key closes on a later
  `tiers.recovered` for it, in any run, or on a later `tiers.run` without
  faults, not wall-starved and with `starved` 0 and `unobserved` 0 that
  does not list it in `reds` (`absent`: it passed as a flake, or was
  removed, ignored or renamed). A starved test is not in `reds`, and one
  test past nextest's slow-timeout leaves `wall_starved` false, so without
  the counts starvation would close a red; there is no per-key tracking; a hand clear
  of the red's signal (13.6) closes them all. A red closes on its last
  key's reason, `recovered` when every key recovered. Its state (`fab.tier_reds.reds(events)`, from the log and in log
  order): foreman, deciding, decided, repairing (its task exists and has
  not landed), landed (waiting for a run that covers it), signal or
  closed.
  - Standing reds start nothing: a standing red is not a `tiers.red`, and a
    key already in an open red opens no other.
  - **A fixed red is confirmed green by the same checks:** once the red
    task lands, its keys' recoveries close it as any red's. The red
    records `covered`: the first `tiers.run` without faults one of whose
    `branches` is its repair by `fab.land.task_of` (so a rebased
    `<draft>/red-<n>-r<k>` counts). From that run on, any `tiers.run`
    without faults that lists one of its keys in `reds` makes it
    **unfixed**: the red becomes a signal, saying the repair landed and
    the test is still red. A key starved on the covering run neither
    closes nor unfixes the red there. A second repair round is left for
    later (14).
- **Reds no task owns are signals, on the user's page** (13.6): a red
  routed to the page at its opening, one its foreman left (verdict left),
  and an unfixed one. Each stays open until the red closes or its signal
  is cleared by hand. The page names the red, its tip, its tests (at most
  10, then the count), its suspects (the hand-pushed ones named), the
  reason (the foreman's line for a left red) and what to read (the
  evidence file and the foreman's report). Telling the session that pushed
  a hand-pushed suspect is left for later: a ready ref carries no pusher
  fab can read reliably (every session commits as the user), 14.
- **Faults are signals, not repairs:** a pair that cannot run says nothing
  about any task's code (live-temper's exit 4, a login every lender held).
  A pair the newest `tiers.run` lists in `faults` is an open signal,
  `fault:<profile>`, since the first of the unbroken run of `tiers.run`s
  that faulted it, with the fault's text, the count of runs and the run's
  log; it clears when the newest run does not fault that pair, never by
  hand.
- **Several suspects:** a red whose suspects span several fab tasks, of one
  plan or several, still opens one red and one foreman. The foreman names
  the owner among them (its report's `Owner:` line, 13.1), for the record
  and the report; one repair task, in the newest fab suspect's plan, fixes
  the group whoever the owner. Bisection to a culprit (the red tests run at
  each suspect's merge) stays left out: the foreman reads the suspects'
  diffs on main, and numbers will say whether it guesses wrong.
- **The after-landing machine wakes the tick** (13.9): at the end of a run
  that recorded a test new, unattributed or recovered, `fab after-landing
  run` wakes the dispatcher once, `after-landing <tip[:12]> new <n>
  unattributed <n> recovered <n>`, as the queue does at the end of a cycle;
  a wake that fails is printed and never fails the run.
- **The tick, each round** (`fab.dispatch._round`, after the imports and
  before the plans): it closes the reds whose keys have all closed
  (`red.closed`), then opens the new ones against every loaded plan's tasks
  (evidence, then `red.opened`). Then each plan, after its refusal actions,
  takes its reds' (`fab.dispatch.red_actions`, pure, the reds whose `draft`
  is the plan's): state foreman, `Action("examine-red", task=<draft>/red-<n>,
  detail=<red>)`, which starts the foreman; decided, `Action("remedy-red",
  run=<foreman run>)`, which settles it (13.1); renamed `examine-fix` and
  `remedy-fix` when `fab/fix.py` is factored out (13.15). A closed red takes no
  action: a foreman still deciding ends and is collected, and nothing
  settles it. A red task that exists is one of the plan's tasks, so
  `decide` starts, readies and parks it as any.
  - **A failed load defers openings:** in a round where any listed plan
    failed to load (a fetch failure among them), new reds are not opened
    until the next round (closing still runs), and, when there is a
    machine with the role `after-landing`, no fabrig plan's retire starts
    that round. Otherwise a red whose suspect is that plan's task would
    open as hand-pushed, and lose its owner for good.
  - **A replay never opens reds:** `fab tick --only` opens none and skips
    the retire wait below, since its plans never land on main.
  - With no loaded plan the round still closes and opens reds (13.4).
- **A fabrig plan retires after its verdict:** its retire call starts only
  once a `tiers.run` names its last branch to land on main among its
  `branches` (the trunk for an integration plan, its last task's for a
  queue plan) and none of its reds (`draft` the plan's) is in state
  foreman, deciding, decided, repairing or landed; a red that is a signal
  does not hold it. Otherwise an integration plan, retired as soon as its trunk
  lands (13.12), would be unloaded before its reds arrive and every one
  would read as hand-pushed. Without a machine with the role
  `after-landing`, the first condition does not apply.
- **Tests** (fake runner, records and log): `fab.after_landing.imported`
  makes a recovered test `tiers.recovered` and an unattributed one
  `tiers.red` with the run's branches, and the `run` record carries `reds`;
  a run with a new red wakes once, a run without new reds or recoveries
  not at all; a new red behind a queue merge
  of a loaded task opens one red with route foreman, and twelve such reds
  at one tip still open one; the next run's standing reds open none; a
  red behind a hand-pushed branch alone opens route signal and is on the
  page; a foreman's fix makes a `<draft>/red-<n>` task that starts as an
  implement run from main and is readied, its left puts the red on the page
  and starts nothing, its failure starts the task with the red alone; the
  red closes on `tiers.recovered`, or as absent on a fault-free run without
  it and with nothing starved or unobserved, but not on a run where it
  starved; a landed repair whose covering run still lists the key makes it
  unfixed; a faulted pair is a signal until a run does not fault it; a red
  task parks after two runs and its question skips the foreman.

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
  renames, splits; kind `interface` when a signature changes; each marked
  `consolidation = true`) into the plan and new pairs into the taste file, on its branch, which lands as a
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
  has it. When the landing refuses a branch, no repair or rebase run starts
  until a foreman run (`fab/roles/foreman-repair.md`) has read the task, the
  refusal and the failing step's log. Either the red is the branch's: it
  writes what failed, where to look and what to change, which code appends
  to the spec as a `## Repair` section (`## Rebase` for a conflict) and
  hands to the next run. Or the red is not the branch's (a fault of the
  gate, a flake): the tip is retried unchanged and no run starts.
  - `fab/repairs.py` folds where each open refusal stands: at the foreman,
    deciding, decided, settled or fallback. A refusal is open from a task's
    branch.rejected to its next run.started, branch.ready or branch.landed.
    A refusal's foreman is a foreman run (`<task>/foreman-<n>`, numbered with
    the question foremen) whose run.started carries `refused` (the tip) and
    `step` instead of `asked`. It reads a worktree detached at
    `origin/<branch>`, since `fab land`'s rebased tip is never pushed. Its
    brief quotes the gates' findings, `fab land`'s detail or the queue log's
    failing step (`fab.run.refusal_text`).
  - Its report's first line is `Done: fix: <line>`, `Done: retry: <line>`
    or `Failed: <why>`. On fix, the tick writes the section into the spec on
    a branch `repairs/<run>` and lands it with `fab land`, as answers land.
    On retry, the task folds as done again, so the next tick lands it again
    (this repository) or readies it with `fab queue untry` (fabrig). Either
    way it logs `refusal.settled`; a landing that fails is tried again next
    tick.
  - A retry is refused, and the repair run starts with the refusal alone
    (verdict none), for a gate or paths step, whose red is the branch's by
    construction, or when the branch already went back unchanged once since
    its last run. A report not in the foreman's form is verdict none too.
    A foreman ending in any other outcome, infra too, is a fallback: the
    repair or rebase run starts as without a foreman. A foreman runs once
    per refusal.
  - The repair or rebase run's brief carries the section before the
    refusal, since its checkout is the branch and not main. The run limit
    counts it as before.
  - **A specless task's refusal** (13.12's `<draft>/repair-<n>`, a red
    task, section 11): its foreman's brief quotes the task's body under
    `# The task` in place of `# The task spec` (no spec file is read), and
    a fix is written to no spec: `refusal.settled` carries the section with
    branch "", nothing lands, and the fold appends the section to the
    task's body, as its answers are, so the next run reads it.
- **The foreman reads a red after landing too** (the user, 11-01; section
  11): the model's foreman "writes rebase and mechanical repair tasks"
  (`execution-modes.md`), and a confirmed red with a fab suspect is the
  same decision as a refusal, made after the branch has landed. The same
  machinery, a role text of its own (`fab/roles/foreman-red.md`): the
  branch is gone, the checkout is main at the red's tip, the suspects are
  listed, and a fix is a new task rather than the next run of the old.
  - A red's foreman is a foreman run (Codex, medium, kind `foreman`, read
    only) whose task is `<draft>/red-<n>/foreman` (run
    `<draft>/red-<n>/foreman-1`, `fab.foreman.task_field` of the red task's
    id) and whose run.started carries `red` (the red's id) and `tip`
    instead of `asked` or `refused`, so neither questions nor refusals
    count it. It takes the builder with most free places, even at none,
    and reads a worktree of fabrig detached at the red's tip
    (`fab.run.launch_detached(host, run, "fabrig", <tip>)`, base the tip).
  - Its brief (`fab.tier_reds.brief`): the role text; `# The red`: `- Run`,
    `- Red: <red> at \`<tip>\` on main`, one line per suspect (`<branch>:
    task <id>, spec \`<path>\``, `<branch>: the trunk of plan <draft>`, or
    `<branch>: hand-pushed, no fab task`), `- Report: write it to
    \`<path>\``, and `Your checkout is fabrig at <tip>, read-only.`; `# The
    evidence`: the red's evidence file; `# The suspects' specs`: each fab
    suspect task's spec, newest first, at most five whole (the rest by id),
    and for a trunk the plan's tasks with their files. An evidence file it
    cannot read is quoted as `(evidence unreadable: <why>)`.
  - Its report keeps the refusal foreman's form: `Done: fix: <line>`, then
    optionally `Owner: <task id>` (one of the fab suspects, or a task of a
    suspect trunk's plan), then at most thirty lines: what failed, where
    on main and what to change; `Done: retry: <line>`, read here as **not
    the suspects'** (a flake that failed its rerun too, the tier, its
    environment or a login, a hand-pushed suspect's change, a commit that
    is no branch's), then at most ten lines of evidence; or `Failed: <why>`.
    When unsure, the red is the suspects': a repair that finds nothing to
    change says so.
  - The tick settles it (`fab.tier_reds.remedy`, pure, then
    `fab.dispatch._remedy_red`) with `red.settled`: verdict `fix` (reason
    the line, owner the `Owner:` task when it names a suspect's, else "",
    section `## Repair (<day>, after landing <red>, foreman <run>)` and the
    lines), `left` (from retry: reason the line; the red becomes a signal)
    or `none` (no verdict, reason as the refusal's). A foreman ending in any
    outcome but done is the fallback: the red task starts with the red
    alone, no `red.settled` needed. A foreman runs once per red.
  - **The section goes into the red task's body, not the owner's spec:**
    13.1 appends a refusal's section to the spec because the task's next
    run reads it there. A landed task has no next run; its repair is the
    red task, whose body carries the section. Appending to the owner's spec
    as well would cost a queue batch per red (fabrig's specs land through
    the queue) or a change to a trunk that has already landed (integration
    plans), for history the log (`red.settled`'s section) and the repair's
    commit already hold.
- **The foreman reads a QA finding too** (13.15): a finding the triage call
  puts on the path goes to a foreman of its own (`fab/roles/
  foreman-finding.md`) in the same form, its fix a new task
  `<draft>/finding-<n>` as a red's is.
- **The foreman settles what the options settle.** A run ending with a
  question first goes to a foreman run (Codex, medium, kind `foreman`,
  `fab/roles/foreman.md`; it writes no code, code records what it decides) with the task spec and the report: when
  the spec's pre-approved options answer it, the foreman's answer is
  recorded in the spec's Answers section and the task runs again (or, by
  `Accept:`, the pushed run is the task done: 13.12); otherwise
  the question queues for the answerer: at once when it holds up other work
  (a task waits on the parked one, or nothing is running while work remains),
  otherwise at 4 queued or after 30 minutes (the user, 10-30; the model said 2
  hours).
  - `fab/foreman.py` folds where each open question stands: at the
    foreman, deciding, settled or queued. Questions of implement, repair and
    rebase runs go to the foreman; the rest (a park at the run limit, one
    logged by hand) queue at once. A park's `question.asked` carries
    `park = true`, since it names the task's last run, which may itself have
    ended with a question; and an answer to a park grants the task a fresh
    run limit, counted from the answer. Without both, the playground replay
    (10-31) looped: the foreman settled each park and the task parked again
    within a minute. The answerer's thresholds and brief count
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
  hint, not a cap: the dispatcher's own target for runs in flight starts at
  the plan's places (13.11), grows by one with each task landed on its first
  attempt, and halves with each rejection or infra outcome as in 13.11, never below
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
  the other. Contract and skeleton calls share a plan's limit on design
  calls in flight (13.4).
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
  per line), then those named (`fab tick [PLAN_DIR...]`), each its own
  draft, in that order, under the tick's one lock (`fab/drafts.py`; the
  list is `fab.channel.plan_dirs`'). One fetch per checkout, one import of
  the queue's record over every plan's tasks, and one measure of the
  builders (13.2) serve them all. The import reads from the oldest of the
  plans' cursors, each the newest record it imported for its draft, so a
  plan that could not load, or is newly listed, gets the records it
  missed when it next loads. Then each plan decides on the log as the
  plans before it left it.
- **Places are shared across plans:** a run started by one plan fills a
  place the next plan sees. A calm builder's one extra place goes to one
  plan per tick: a builder a plan started on is not calm for the plans
  after it.
- **A plan owns its draft's work:** its tasks' runs and their foreman runs,
  its calls (subject the draft or under it), and the review runs of those
  calls; a ladder plan's walks and findings too (13.15). A plan collects only its own runs, and its call limits (one answer,
  review or amend call at a time) count only its own calls. Runs no ticked
  plan owns are collected after every plan has ticked.
- **A plan that cannot load** (its plan.toml, a fetch, a second plan of the
  same draft) is printed and skipped; the others tick. It logs nothing,
  and `fab tick` exits 1. A retired plan is skipped.
- **A tick with no loaded plan** (none listed or named, or none that
  loads) imports the queue's unowned records (13.8) and the after-landing
  records (section 11), closes reds, and, when no listed plan failed to
  load, opens new reds against an empty owner map, so each is a page
  signal; then it rewrites the page and starts nothing: no measurement of
  the builders, no decisions, no foremen and no strays collected. On 11-01
  hel8 had no plan listed and its log held no `tiers.run` at all: the night
  of 10-31's situation, every suspect hand-pushed, which only the page can
  hear. Failed loads are still printed and still make `fab tick` exit 1.
- **Design calls run in parallel** for independent parts. A plan's
  skeleton and contract calls in flight number at most its flow target
  (13.2): two at its start, growing as the target does. The eligible parts
  are independent, since a part waits for its needs' design. They are
  started in plan order, each in its own role. A call's user unit is named
  by its role and subject (`fab-call-<role>-<subject>`), so one subject
  never has two calls running, even before the log shows the first.

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
  60-minute timeout (40 until the user raised it, 10-31, after the
  playground replay's cut ran out with its four designers in flight). call.ended carries its peak context and turns, and the
  code report flags calls over the user's 600k target (10-30; the model's
  draft said 120k). Of the first eleven calls, seven peaked over 120k
  (130k-190k) and all ended well; the user sets a cap, if any, from the
  measurements. The code may hold an unset
  bound for later; nothing ends a call for its size now.

### 13.6 A channel to the user

- **Questions that are the user's** (budgets, machines, what is hard to
  reverse) park their task and are listed, with the reports' signals that
  are the user's, on one page the user reads; nothing else goes to the user.
- **Whoever asks decides it is the user's,** never the page. Four things
  are (`fab.channel.asks`, folded from the plans and the log):
  - a plan's `[[question]]` with no answer, the cut's (13.3);
  - a call that ended `Question:` (section 12);
  - a call's chain parked after its review refused twice (13.1);
  - a QA finding's question from its triage call (13.15: a `user` or
    `brief` decision, or a `path` line's `; user:`): Ask kind `finding`,
    subject `<draft>/triage/<finding>`, its text the question, what to read
    the walk's report; the page quotes the ask's text after the finding's
    title, rung and the first 12 lines of its reproduction. `fab page
    answer <subject> TEXT` logs `call.answered` as for any subject, which
    closes the ask (as it closes the call and parked kinds) and makes the
    finding new again or dropped (`brief`), its answer in the next triage
    call's brief; a `; user:` answer only releases the rung, and the next
    triage call's brief carries it.
  A task's questions are the foreman's and the answerer's and never reach
  the page; an answer call that cannot settle one ends `Question:` itself.
- **The page** is `FAB_HOME/user.md` on hel8 (`fab/channel.py`):
  - the open questions, the plans' first, then the log's in the order they
    were asked, each with what to read and how to answer it;
  - then `## Open signals` (`(none)` when there are none): each open
    signal folded from the log
    (`fab.channel.signals(events)`, pure), oldest first, as a block
    `### <id>, <what>, since <ts>`, its facts, `- Read: ...` and, but for a
    fault, `- Clear: \`fab page clear <id> TEXT\``. Three kinds:
    - `queue:<branch>`, a hand-pushed rejection (13.8): `- Tip`, `- Step`,
      `- Tests` (the record's, `(see the log)` when []), `- Read:
      \`<gate>:<log>\``;
    - `red-<n>`, an after-landing red no task owns (section 11): `- Tip`,
      `- Why` (`no fab task among the suspects`, `no suspects`, `not the
      suspects': <the foreman's line>` or `unfixed: <draft>/red-<n> landed,
      still red at <tip>`), `- Tests` (at most 10, then `and <k> more`),
      `- Suspects` (hand-pushed ones marked), `- Read:` the evidence file
      and the foreman's report when there is one;
    - `fault:<profile>`, a pair that cannot run: `- Fault` (its text),
      `- Runs` (how many in a row), `- Read: \`<host>:<run log>\`` (the
      run's `host`, section 11);
    - `finding-<n>`, a QA finding its foreman left (13.15): `- Rung`,
      `- Why` (`not the code's: <the foreman's line>`), `- Title`, `- Read:`
      the walk's report and the foreman's report;
    - `backlog:<draft>`, a ladder's backlog branch rejected twice at one
      render (13.15): `- Branch`, `- Step`, `- Read: \`<gate>:<log>\``;
  - then, from each standing report's latest day (section 10), its path and
    only the Signals lines whose owner is the user (the drafts' signal
    tables: targets, capacity, a usage limit, a budget the three questions
    could not settle); the rest of each report is the director's;
  - then `## After landing` (section 11), then `## The ladder` for each
    plan with rungs (13.15): `### <draft>`, one line per rung in plan
    order (its state: due, walking, waiting, holding or passed, with what
    it waits for), then `- Backlog: <n> findings in \`<backlog path>\``,
    then `## Unread`, as today. The ladder is not the user's: it is there
    so the session that walks by hand, and the director, read what is due
    where they read fab's other state, as `## After landing` is.
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
- **Signals with no other owner come to the page too** (the user, 11-01),
  a departure from "nothing else goes to the user" above: a red no fab task
  owns and a hand-pushed branch's rejection have no owner fab knows (no
  task, no plan, no session it can name), and the director, who passes the
  user what needs the user, reads the same page. The page's first line
  says so: `Only what is the user's (budgets, machines, what is hard to
  reverse) and what has no owner fab knows.`
- **A signal opens and clears from the log:** `queue:<branch>` opens at a
  `queue.rejected` and clears at a later `queue.landed` of the branch, at
  a later `queue.rejected` or `queue.collateral` of it at another tip (a
  newer tip was tried; a newer rejection opens its own), or by hand;
  `red-<n>` opens when the red becomes a signal and clears when the red
  closes (section 11) or by hand; `finding-<n>` opens at its
  `finding.settled` left and clears at its rung's next `rung.passed` (the
  rerun showed it was not the code's) or by hand, which drops the finding,
  the clear's text its reason; `backlog:<draft>` clears when the render
  changes, when a backlog branch of the draft lands, or by hand (the tick
  then readies it once more, and the count of two rejections restarts at
  the clear, so one further rejection raises it again); `fault:<profile>` clears only when a run
  does not fault the pair. `fab page clear ID TEXT` on hel8 logs
  `signal.cleared` (signal, by `user` or `--by`, text) and rewrites the
  page; it refuses an id that is not an open signal, and a fault. Clearing a
  red's signal closes the red (`red.closed`, reason `cleared`). A signal
  open again after its clear (a later raise) shows again.

### 13.7 Probes

- **A probe** is a read-only Codex run with a time box (the part's
  `minutes`, hard) and a success criterion from its design; its report is
  the measurement; a decision call (13.3) turns it into design.

### 13.8 The landing side

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
  - **The cursor:** the oldest of the loaded drafts' cursors (13.4), as
    before; with no loaded draft, the import resumes at the newest
    `queue_ts` of any kind in the log.
  - A `queue.rejected` opens the signal `queue:<branch>` on the user's page
    (13.6), since its `queue_ts`: branch, tip, step, failing tests and the log on the gate. It
    clears when the branch lands, when a newer tip of it is tried, or by
    hand. Telling the session that readied it is left for later (14): a
    ready ref carries no pusher fab can read reliably.
  - A `collateral` alone is no signal: the branch goes again by itself, and
    the report already signals collateral reds. A red that stands after
    its collateral bound ends as a `rejected`, which is heard.
  - The queue already wakes the tick on every `rejected` (13.9).
  - Tests: a fake queue log with a rejected hand-pushed branch gives one
    `queue.rejected` and the page's signal; a later `landed`, or a
    `rejected` at another tip, clears it (the latter opening its own);
    `fab page clear` clears it; a task's rejection still becomes
    `branch.rejected` and no signal.

### 13.9 Events drive the tick

At the user's word (10-30): the loop reacts to what happens, and polling is
only the backstop.

- **An event wakes the tick** (`fab/wake.py`). Whatever ends work the
  dispatcher waits for appends a reason to the want file,
  `FAB_HOME/tick.want` on hel8, beside the log: a Codex run's unit when it
  stops (its ExecStopPost runs `fab wake codex <id>`, over ssh from the
  builder), a Claude call when it logs `call.ended`, the queue at the end of
  a cycle that recorded `landed` or `rejected` (one wake per cycle), the
  after-landing machine at the end of a run that recorded a red new or
  unattributed or a recovery (one wake per run, section 11), `fab land`
  when it lands or refuses, the user's answer or clear (`fab page
  answer`, `fab page clear`), and a walk's result (`fab qa result`, 13.15).
  On hel8 a wake is one appended line; elsewhere it is one ssh to the host
  with the role dispatcher. A wake that fails is not retried: the backstop
  finds its work.
- **Events coalesce.** A path unit (`fab-events.path`, PathExists on the
  want) starts `fab-events.service`, `fab tick --trigger event`, whenever
  the want exists and the tick is not running. The tick takes the want
  (renames it away) first under its lock, so a burst of wakes makes one tick
  after the running one, never a queue of them, and a wake during a tick
  makes the next. An event tick waits for the lock; a hand or backstop tick
  that finds it held exits. A tick reads every new record anyway.
- **The timer is the backstop,** never the driver: `fab-backstop.timer`
  ticks every 10 minutes (the user, 10-30) as `fab tick --trigger backstop`,
  for a lost event or a host that could not reach hel8. In normal operation
  every change of state arrives as an event, so the backstop finds nothing
  to do. A backstop tick that took a want, collected an ended run or
  imported a queue record, a `tiers.red` or a `tiers.recovered` found a
  lost event, and logs a note saying so (the after-landing records count
  as one entry, `after-landing: <n> records`)
  (`lost event: ...`); its other work (an answer due after 30 minutes, a
  review after 4 hours, a builder become calm, a retried failure) is the
  timer's by nature and is not noted. `fab wake --install [PLAN_DIR...]`
  writes the four units into `~/.config/systemd/user`, enables the path and
  the timer and stops the transient 2-minute `fab-tick.timer`; until then
  that timer ticks.
- **A tick that wants another starts one:** when the log gained, during a
  tick, a record the next decision depends on (`run.ended`, `branch.landed`,
  `branch.rejected`, `question.asked`, `question.answered`,
  `refusal.settled`, `call.finished`, `call.parked`, `call.answered`,
  `red.settled`, which makes a red task, and `red.closed`, which may let a
  retire start; `red.opened` needs none, since the same round's plans take
  it; `finding.settled`, which makes a finding's repair task, 13.15;
  `finding.triaged` and `rung.passed` need none, being logged before the
  same round's decisions), the tick wakes itself at its end (`tick <n>: <kinds>`). Five such ticks in a
  row with no outside wake between them stop the chain with a note: a chain
  that long is a fault, and the next tick waits for an event or the
  backstop.

### 13.10 The timeline's flow

The user's example timeline (`execution-modes.md`, "Example") is the order of
things fab follows, whatever the clock says:

- **Intake:** the user starts a draft by hand (`fab draft start PATH`, at
  the user's word of 10-31): its surveys, then its cut. A draft landing in
  `docs/design/draft/` starts nothing by itself; the timeline's T+0:00 is
  the user's start.
- **Surveys:** read-only Codex runs (medium, kind `survey`), at intake (the
  readers of what the draft changes, the primitives in reach with their
  signatures, each area's test world) and before each skeleton call (the
  primitives in reach, refreshed); their reports go into the cut's and the
  skeleton call's briefs, beside the code-built inventory.
- **The buffer's order:** among runnable tasks, consolidation tasks from a
  structure review come first ("at the head of the buffer"), then repairs and
  rebases, then tasks of contract parts, then tasks by their part's slice, in
  plan order (`fab/buffer.py`, a pure sort the dispatcher applies before it
  starts runs):
  - a consolidation is a spec marked `consolidation = true` (section 4), a
    group of its own whatever else holds of it;
  - a repair or rebase is a task whose next run carries a refusal (a
    `branch.rejected` since its last run); a rerun after an `Infra:`
    outcome is not, and keeps its part's place;
  - a red task (`<draft>/red-<n>`, kind `red`, section 11) sorts into the
    repair group too, ahead of the plan's slice tasks, behind
    consolidations: a red reaches its owner at once;
  - within each group, tasks go by the first slice that holds their part,
    then their part's place in the plan, then their specs' order.
- **Then, as written:** contracts land alone and their readers are pulled;
  probes run beside and their decisions land before their readers' skeletons;
  answers come in batches, at once when they hold up work; slices complete
  on their story tests; QA walks the walkable slices (once QA is here); the
  last call retires the draft. Each is a part above or in section 14.

### 13.11 The entry path to fabrig

At the user's word (10-31): before the fabrig run (skein's component kit,
phase 1), fab runs a plan that lives in fabrig, gates its Rust branches
minimally, starts wide and early, and measures where the time and the
weight go. The api gate (rustdoc JSON) is out of scope.

- **A fabrig plan** is a plan directory inside a fabrig checkout, at any
  depth (`skein/docs/plan/<draft>`), with `repo = "fabrig"`, listed in
  `FAB_HOME/plans` (13.4). Its checkout on hel8 is the dispatcher's fabrig
  clone, `FAB_HOME/repos/fabrig`; the tick fetches it once, as any checkout.
  Its tasks build in slots and are readied to fabrig's queue (section 6).
- **Its calls land through fabrig's queue,** never `fab land`: a skeleton,
  contract, review, answer or retire call works in a worktree of the fabrig
  clone on hel8 and pushes `calls/<id>`; once its chain approves, the tick
  pushes `ready/calls/<id>` (as `_ready` does, with no receipt) and logs
  `branch.ready`. `call.finished` is logged when the queue's record says the
  branch landed (the import gives `branch.landed` for task `calls/<id>`). A
  queue rejection counts as a review refusal of the chain: its findings go
  to an amend call once, a second parks the subject. Answers (`answers/<run>`)
  and repair sections (`repairs/<run>`) to a fabrig plan's specs are readied
  the same way; `question.answered` and `refusal.settled` are logged when
  their branch lands, and the task waits for them as it waits now.
- **Its briefs speak Rust.** A call of a fabrig plan gets the role text's
  fabrig variant (`fab/roles/skeleton-fabrig.md` and so on where the
  wording differs: `todo!()` bodies, doc comments, the crate layout, `cargo
  check -p <crate>` under heavy to fix its own compile errors) and an
  inventory of the crates the part's design cites: their public items by
  grep (`fab/rust_digest.py`), not `fab.calls.inventory`.
- **Rust gates, minimal** (`fab/rust_gates.py`, beside `fab/gates.py`): on
  a fabrig task branch, before it is readied, and on a fabrig skeleton's tip:
  - `ratchet`: for each tree the branch touches that has
    `scripts/old_forms.py`, its counts on the tip are not above the
    base's (`python3 -I -B scripts/old_forms.py` from the tree's root;
    only falls);
  - `size` is a flag, not a gate: functions over 60 lines the branch adds
    or grows are listed in the digest.
  A failed gate logs `branch.rejected` with step `gate:<gate>` and
  `findings`, as section 12, and the foreman's repair path takes it.
- **The Rust digest** (`fab/rust_digest.py`, `FAB_HOME/digests/<run>.md`):
  public items added and removed (`pub fn|struct|enum|trait|type|const|mod`
  by grep over changed `.rs` files, base against tip), changed lines split
  into production, tests (`tests/`, `#[cfg(test)]` modules, `*_tests.rs`)
  and docs (`.md`), functions over 60 lines added or grown, paths outside
  the task's files and the ratchet's deltas per tree. Deterministic Markdown
  of at most 8,000 characters, as section 12's.
- **Optimistic start:** a part's tasks start once its skeleton call has
  ended done and its tip passes the checks (agents: `bin/fab test` and the
  gates; fabrig: `fab precheck` and the Rust gates), with the Codex review
  running alongside. The tasks are read from the call's branch tip, their
  branches start from it, and they hold landing (or readying) until the
  skeleton has landed. A refusal becomes an amend call as now; when the
  amended skeleton lands, each started task's branch is rebased onto main
  by a rebase run before it lands. A chain that parks parks its tasks.
- **Start wide:** the flow target (13.2) starts at the plan's places (the
  sum of its builders' `places`), not 2, and runs start up to the lesser of
  the target and the runnable tasks. A first-attempt landing with the window
  full grows it by one; a rejection or an `Infra:` outcome halves it
  (rounded down, never below 1). A rebase conflict halves nothing.
- **Direct mode** (`mode = "direct"`): a part of about 1-2 tasks with no
  shared contract skips the skeleton. The cut writes its short task spec
  itself, in the plan's `tasks/`, checked by the cut's review; the spec
  then runs as any task: one Codex run, the checks, the landing. A direct
  part is never marked `contract` and has no contract readers.
- **The hand session's weight:** the code report counts the Claude Code
  sessions listed in `FAB_HOME/hand-sessions` (`<session id> <draft>` per
  line): each transcript `~/.claude/projects/*/<id>.jsonl` and its
  `<id>/subagents/*.jsonl`, each assistant message's usage once (by request
  id), weighed as calls are. It is shown apart, a Hand line beside Claude
  and Codex, with the Claude to Codex weight both without and with it.
- **Time per part:** the code report's Parts table gains each part's time
  breakdown from the log: draft start (the plan's first call) to skeleton
  landed, spec landed to first run started, runs (started to ended,
  summed), run ended to checks (the gating or readying), checks to ready,
  ready to landed; a boundary with no event is shown as `-`.

### 13.12 The flow of a real run

At the user's word (10-31): fab's flow is modelled on real runs, so that a
real run replayed on fab differs from it only in who executes it. The
first model is the Codex manual run of skein's component kit
(`coord/codex-kit/`): a lead cutting the work into 24 direct tasks with
shared notes per family, Codex implementers in slots, every finished branch
merged into one integration branch, dependents started from its tip, one
full check at the end, a repair, never landed. That run's flow is fab's
default; the earlier mechanics (skeleton calls, call reviews, surveys,
landing each task through the queue) stay as options, off, and come back
only as tweaks once a replay matches its run.

- **The options** (`plan.toml`, read by `fab.plan.load_plan`); the
  defaults are the run's flow:
  - `landing`: `"integration"` (the default) or `"queue"` (each task
    landed or readied, as in section 6);
  - `ready` (default true): an integration plan readies its checked
    branch for the queue once; false leaves it unlanded (an experiment, as
    the replay of codex-kit);
  - `reviews` (default false): true sends every call's chain to a review
    run (13.1) and starts structure review calls (12). The code gates
    (files, ratchet) run either way;
  - `direct` (default true): every part must be `mode = "direct"`, a plan
    problem otherwise, so a cut that writes a skeleton part is caught
    before anything runs; false allows skeleton and contract parts.
  The agents repository's own plan (`docs/plan/agents-rebuild`) names
  `landing = "queue"`, `reviews = true` and `direct = false`, and keeps
  its flow.
- **The trunk.** A plan's trunk is `main`, or `<draft>/integration` for an
  integration plan. Everything that reads main for a plan reads its trunk
  instead: a run's base (`origin/<trunk>` at its start), the Rust gates'
  base (the tip's merge base with the trunk), a call's worktree, the
  foreman's and the refusal foreman's checkouts, the spec edits of answers
  and repair sections, and the implementer's precheck (`fab precheck SLOT
  TIP --onto origin/<trunk>`; the brief's facts name the trunk).
- **The plan lives on its trunk.** The operator makes the integration
  branch at the run's base and a worktree of hel8's fabrig clone on it,
  tracking it (`FAB_HOME/integration/<draft>`), and lists the plan
  directory inside that worktree. Its first commit holds the run's inputs
  that are not in the tree (below). The tick follows a
  plan checkout that tracks a branch: after its fetch it fast-forwards the
  checkout to its upstream, so it always reads the plan and specs at the
  trunk's tip.
- **Merging, not landing, and light** (the user, 10-31, after the first
  replay). For an integration plan, a task whose run ended done is merged
  by the tick, in the plan's checkout and under the tick's lock: reset to
  `origin/<trunk>`, `git merge --no-ff origin/<branch>`, push the trunk
  (the integration branch, never main) fast-forward only. No gates and no
  ratchet check run at the merge: what to check, and when, is the agents'
  (each implementer's own checks, the end check), as it was the lead's. It
  logs `branch.landed` with `main` the new trunk tip and `into` the trunk.
  A conflict confined to old-form baselines (`<tree>/scripts/old-forms.txt`,
  which tasks lower with `--write`) is resolved by recounting, as the lead
  did: the trunk's side of the file, then `python3 -I -B
  scripts/old_forms.py --write` in that tree (17 of codex-kit's 24 merges
  met there). Any other conflict, or a recount that exits non-zero, aborts
  the merge and logs `branch.rejected` with step `merge` and the conflict as
  `findings`, so a rebase run follows (13.1's refusal foreman first). Calls'
  branches (`calls/<id>`), answers (`answers/<run>`) and repair sections
  (`repairs/<run>`) are merged into the trunk the same way, never readied.
  Since a merged task counts as landed, its dependents become runnable and
  start from the trunk's tip: the manual run's "dependents start from the
  integration tip". The first replay's merges, gated, took 37-45 s each and
  queued behind each other; a light merge is a fetch, a merge and a push.
- **The cut releases its first specs early,** as the lead launched its first
  tasks while it wrote the rest. During a cut of an integration plan with
  reviews off, the cut first pushes the tasks that need no survey and no
  other task, in a plan.toml holding only their parts, then designs the
  rest while they run, pushing each batch that holds together (plan.toml
  grows), and wakes the tick each time (`fab wake cut <call>`). Replay 2
  (10-31) showed why first: its cut released at T+13.5 of a 21.5-minute
  call, after it had designed the whole plan; the lead's first task went
  out at T+4.8. No prompt names a timing figure (the user, 10-31). Nor
  does a family wait behind one story task (`cut-run.md`, the meeting
  point): replay 2 held every stage task behind echo-stage, codex-kit ran
  them beside it. The tick merges an
  in-flight cut's pushed branch into the trunk whenever its tip is not yet
  there, so those tasks start from the trunk as any; the cut's last push
  is merged when the call ends, as today. A spec the cut has released is
  never changed after. While the plan's cut is in flight the end check
  waits, and a direct part is never sent to a design call: the cut designs
  it.
- **A run may leave what is not its own** (the user, 10-31, after the
  playground replay: 48 of its 68 tasks waited at T+92 on two contract
  tasks rerun for scope and lint questions, where playground-kit's lead
  treated a pushed run with known reds as done and fixed them in its
  integration runs). Three changes:
  - The implementer's text (`fabrig-run.md`) allows without asking the
    arms, fields and literals the compiler requires because of a type the
    task changed, in any file of its tree, and a scoped
    `#[expect(clippy::<lint>, reason)]` on an item it wrote or changed; and
    when its acceptance holds and its work is pushed but something outside
    it stays red or open, it reports `Done:` with a `## Left` list, and
    fab merges it: the owning task or the end check takes the rest.
  - The foreman may answer `Accept: <what is left>`: the run's work is
    pushed, its acceptance met, and its question lies outside the task. In
    an integration plan, once the asking run's branch is on origin, the
    settle logs `question.answered` with `accept`, which folds the task
    done (its branch kept), so the tick merges it as any done task. Without
    the pushed branch, or in a queue plan, it is an ordinary answer.
  - The cut's text writes the shapes that cross parts in `notes/contracts.md`
    before the specs, as the lead's `binding.md`, gives each side of a
    boundary its own task built to it, and keeps a task many others need
    small: its surface first, its bodies and its readers' fallout later.
- **After the playground replay** (the user, 11-01): r4 merged all 64 tasks
  at T+6h51 (playground-kit: done at 4h24m) and stopped red three times.
  Four changes from what it showed:
  - The answerer prefers leaving what is not the task's (another task's
    files, fixtures, tests, crates) to its owner or the end check, widening a
    task only when its own acceptance cannot hold otherwise: r4 asked 61
    questions, nearly all answered by widening, each a longer rerun.
  - An implementer commits and pushes its work before it asks, and an
    implement rerun in a slot starts from the task's pushed branch when there
    is one, not from the trunk: r4's repair-2 stopped on a question with 46
    files uncommitted, which its rerun would have cleaned away.
  - The cut writes `plan.md` and its report's first lines with its first
    push and updates them with each later one: r4's cut ran out of its 60
    minutes and both were lost.
  - A start whose builder has no idle slot moves to the next builder with
    free places, since slots other work claimed are not fab's runs: r4
    retried a full hetzner6 every tick while other sessions held its slots.
- **Early starts** (the user, 11-01; `coord/fab-replay/design-early-starts.md`).
  r4's forge records were a chain of 11 tasks, each waiting for the last
  one's merge; playground-kit's lead started dependents from the
  integration branch and merged their needs as they landed. An integration
  plan with `early` (the default) lets a waiting task start when each need
  not merged is running or done and has pushed its branch, and has no
  unmerged needs of its own (one level). Its slot is set up from the trunk,
  then each such need's `origin/<branch>` is merged in, in needs order; a
  conflict aborts the start and logs `early.refused` (it then waits as any
  task). A task starts early once at most: after a question, an answered
  task whose needs are not all merged waits for them (r6: fe-playground-forge
  started early on fe-remove and asked four times for the same unfinished
  removal before it parked). A run that started early and ended `Failed:`
  (its needs' work unfinished) waits for them likewise and then runs again
  (r6: fe-world-remove), rather than parking with nobody to answer it. A
  rerun that continues from its pushed branch merges the trunk into it first
  (a conflict is left to the run), so it sees the needs merged since. Its brief gains `# Started early`, naming those branches and saying
  to merge them again before it pushes; `run.started` carries `early`. A
  done task of an integration plan merges only after every need has merged.
  The tick reads origin's branches of the draft from the plan checkout after
  its fetch (`fab.dispatch.early_starts`).
- **Checks along the way** (the same). r4's reds collected for the end: 101
  of 24,207 tests at its second end check. While tasks remain, after
  `MID_EVERY` (10) task merges since the last check, or `MID_AFTER` (45)
  minutes since it with one merge since, the tick checks the trunk's tip
  with the end check's steps less fuzzy (`fab check start --default`),
  when a slot is idle and no repair is open; `run.started` carries `mid`.
  A red makes a repair as at the end, whose body lists the tasks not merged
  then with their files, to leave what they own; mid reds never count
  toward the three that stop a plan, and the end check is never one of them.
- **The flow stays wide.** An integration plan keeps its target for runs
  in flight at its builders' places throughout: no halving on a refusal or
  an `Infra:` outcome and no growth (13.11's start-wide rule is the queue
  flow's), as the lead started every runnable task while slots were free.
  The simulation of codex-kit shows why: abort's ratchet refusal halved the
  target from 14 to 7 just as kit-lib's nine dependents became runnable,
  and staggered them by up to six minutes.
- **The end check.** When every task of the plan has landed on the trunk,
  the tick starts one check run of the trunk's tip: task
  `<draft>/integration`, kind `check`, in an idle slot of the builder with
  most free places. It runs `fab precheck` with the full selection
  (`--full`: every ratchet, fmt, workspace clippy, the build, default and
  fuzzy tests, as the queue's full checks) as a user unit with fab codex's
  contract (`<id> <state>`, `ended`, `result.json`, the report), so
  `fab run status` and `collect` read it as any run. Its report's first line
  is `Done: green <tip>` or `Failed: <first red step>`.
  - Green: with `ready`, the trunk is readied (`ready/<draft>/integration`,
    `branch.ready` for task `<draft>/integration`) and the queue lands it;
    without, the plan stops there, logging nothing more.
  - **Caught up with main first:** before each check of a plan with
    `ready`, the tick merges `origin/main` into the trunk when the trunk
    lacks it (an old-form baseline conflict recounted, as at a task's
    merge), pushes the trunk and logs `branch.landed` for task
    `<draft>/integration`, branch `main`; the check runs on the new tip. Any
    other conflict is aborted and logged as `branch.rejected`, step
    `catch-up`, with `main` the sha it could not merge; a catch-up repair
    follows (below).
  - **Caught up along the way** (the user, 11-01). Drafts run for hours
    beside each other, and main moves under a trunk each time another lands:
    on 10-31 every such merge was done by hand at the end (playground: 23
    conflicts, 4 repairs, 56 minutes; jigq/debt: a compile red from main's
    new `family::to_root` argument, hours after main had it). So while tasks
    remain, a plan with `ready` catches its trunk up whenever main has moved,
    as before a check: the tick reads after its fetch whether
    `origin/<trunk>` contains `origin/main`, and when it does not and
    `CATCH_AFTER` (30) minutes have passed since the plan's last catch-up
    (merged or refused; else since its first task merge), the next step is a
    catch-up, taken before a check along the way. It waits, as a check along
    the way does, while any repair is open and while the cut is in flight.
    Tasks started earlier merge into the caught-up trunk as any; those
    started later build on main's newer code. The tick's own catch-up merge
    is not a task merge: it does not count toward `MID_EVERY` (a catch-up
    repair's merge counts, as any repair's). Once every task has merged,
    catching up happens only before a check, as above, so a readied trunk is
    not moved under the queue. A plan without `ready` (a replay) never
    catches up: it stays on its base.
  - **A catch-up that conflicts is repaired, not stopped.** Each catch-up
    `branch.rejected` makes a repair task `<draft>/catch-up-<n>` (folded
    from the log like `repair-<n>`, numbered apart from them; kind
    `repair`, files `**`). Its body names the trunk's tip, the main sha and
    the conflict's findings, and asks the run to merge that sha into its
    branch (which starts at the trunk's tip), resolve each conflict keeping
    both sides' intent (main's side is other drafts' landed work, the
    trunk's this draft's), fix what main's changes break in this draft's
    code, and push. Its acceptance: the pushed branch contains the sha, has
    no conflict markers, and the crates the conflicts touched build and
    pass clippy and their tests; the trunk's next check runs the rest. It
    runs as an implement run from the trunk's tip and is merged like any
    task, which brings main in. Its questions, answers and the open-repair
    waits are a repair's; a catch-up repair is never one of the three reds
    that stop a plan. A refusal at a newer main is a new repair, but the
    plan stops for judgement when a catch-up refusal is at a main sha that
    already had a catch-up repair merged (that repair did not bring main
    in), or is the `CATCH_LIMIT`th (3) refusal since the plan's last clean
    catch-up (its `branch.landed` for task `<draft>/integration`, branch
    `main`), so repairs that never bring main in cannot follow a moving main
    for ever. The stop holds until a clean catch-up is logged after it: the
    person resolving it merges main into the trunk and pushes it, and the
    next tick, finding the trunk containing `origin/main` while the stop
    holds, logs that `branch.landed` (tip origin/main's sha, `main` the
    trunk's tip, `by` `hand`), which clears the stop.
  - **A queue rejection is checked again:** the trunk is caught up and
    checked once more, then readied again (the queue asked to forget its
    tried tip when the tip is unchanged). A red check goes to repairs as
    any red; the third rejection by the queue stops the plan for judgement.
  - Red: a repair task `<draft>/repair-<n>` (folded from the log, never a
    spec file; files `**`, its body the check's failing steps and report)
    runs as an implement run from the trunk's tip, is merged like any task,
    and the trunk is checked again. A third red parks the plan with a
    question.
  - A check run counts as the draft's run in flight and takes a place.
  - A repair has no spec file, so its question skips the foreman (no
    options to settle by) and queues, and an answer logged with `answer`
    is folded into the repair's body under Answers, which its next run
    reads (the playground replay, 11-01: a repair's question crashed the
    foreman on its empty spec path, every tick). The answer call's brief
    lists the repairs' questions too (`fab.integration.with_repairs`), and
    it records a repair's answer as a report line `Answer <task>: <text>`,
    which the tick logs as that question's `answer`.
- **The cut's inputs.** `fab call cut --set KEY=VALUE ...` passes plan options
  that differ from the defaults (`ready=false` for a replay) to the cut: its brief says to write them into plan.toml verbatim, and its
  `call.started` carries them (`options`), so the tick reads `landing` and
  `reviews` for the cut's own chain before plan.toml exists. For a replay
  the operator gives the cut the manual run's inputs as `--source`: the
  draft (`skein/docs/design/draft/component-kit.md`), fabrig's
  `AGENTS.md` and `agents/lead.md`, `implementer.md`, `operations.md` at
  the base, and, committed under the plan directory's `inputs/`, the
  kickoff, the review and the manual run's brief, with a README saying the
  brief's How, Machines and Measure are fab's in this run. With `direct =
  true` the cut writes every task spec itself and puts notes several tasks
  share in the plan's `notes/`, cited from each spec (the lead's
  `common.md`, `stage-common.md`, `lib-common.md`); implementers read them
  in their checkout.
- **The run's own texts** (the user, 10-31): the cut and the implementers
  are told what the manual run's lead and implementers were told, and fab
  adds only what its mechanics need.
  - The cut of a direct integration plan gets `fab/roles/cut-run.md` in
    place of `cut.md`, `cut-fabrig.md` and `cut-direct.md`: the run's brief
    (a source) is the lead's instructions; fab's text says only the plan
    and spec formats, that implementers read nothing but their spec, the
    notes it cites and the repository, and the early release above. It asks
    for no survey: the lead was not told to make one, and made it as it
    saw fit; when it surveys, the survey is a read-only Codex run at high it starts
    with `codex exec --sandbox read-only` on hel8 (the user, 10-31; `lead.md`
    said so too). Where the design is too wide for one writer, it may
    split it across Claude designer subagents, one per part or family, from
    contracts it fixes first, as playground-kit's lead did with two
    designers from shared binding calls; they write specs and notes only,
    and the cut checks and releases them batch by batch (the user, 10-31,
    after the playground replay's cut ran out of time with its four
    designers in flight; the call's timeout is now 60 minutes, 13.5). It is one call throughout: it never waits for, watches or
    reacts to a run, and hands its output over in pieces (the early release)
    only so fab can start them. It carries the plan and spec formats, and the brief leaves out
    the Designs, Plans and Inventory sections.
  - **fabrig's `agents/` files are not fed** (the user, 10-31): `lead.md`,
    `implementer.md`, `operations.md` and `ledger.md` describe the pipeline
    before fab (resident leads, `post`, `claim`, `precheck`, ready refs, the
    old machines). The cut's sources carry fabrig's `AGENTS.md` only;
    `cut-run.md` quotes, in `lead.md`'s own words and without naming it,
    every line of it that still holds (the code's
    shape, fanning out, one writer per crate, the task's contents,
    scope settled in the task after a reverse-dependency survey, readers'
    tests, effort, skimming; not its task size, which the cut decides, at
    the user's word). `fabrig-run.md` does the same for
    `implementer.md`, and the cut's brief quotes it (`What each implementer
    is told`), as the run's lead read `implementer.md`; the brief names its
    sources `Sources`. fab's texts assume a fabrig `AGENTS.md` written for
    fab's pipeline (the user, 10-31): a replay's base is fabrig's commit
    plus that `AGENTS.md` (the component kit's: `6de0cd271` +
    `AGENTS.md for fab's pipeline`). The run's lead was given nothing else: its prompt was
    its brief, and it read these files itself. Since fabrig `2c39875fd2`
    (the user, 10-31) fabrig's main has that `AGENTS.md` and no `agents/`
    (its files are this repository's `old/fabrig/`), and fab's texts name
    neither `agents/` nor its files.
  - An implementer of an integration fabrig plan gets the spec and its
    facts, with `fab/roles/fabrig-run.md` in place of `implementer.md`,
    the taste file and `fabrig.md`: its slot is claimed and set up, it
    commits and pushes its branch, fab merges it, and its report's first
    line is `Done:`, `Question:`, `Infra:` or `Failed:` (codex-start's
    report paragraph). The standing rules are the cut's notes, as the
    lead's `common.md` was. The spec's path is given relative to the
    repository.
  - The `files` gate is gone (sections 12 and 13.11): a spec's `files`
    say what a task owns, for the cut and the implementer, and nothing
    refuses a branch for a path outside them.
  - An integration plan answers a queued question at once (an answer call
    as soon as the foreman cannot settle it), as the lead did in two
    minutes, not at 4 queued or after 30 minutes.
- **Retire waits for main.** An integration plan's parts are done when
  their tasks have merged, but its retire call starts only once the trunk
  has landed on main (`branch.landed` for task `<draft>/integration` from
  the queue's record), and after its verdict after landing (section 11).
- **Departures from the user's drafts, at the user's word** (10-31;
  `execution-modes.md`): no surveys (not built), no skeletons or test
  vocabulary (every part direct), no Codex review of the cut, no structure
  review, and the code reaches main as one integration branch through one
  check instead of each task through the merge queue. The self-critique
  and test-writers are not built yet either. Each may come back as an
  option once a replay matches its run.

### 13.13 Logins

Replaces the agents repository's `tools/qa/logins` (QA's held logins) and
the unlanded `agents-logins` of `deploy/logins-pool-1b` (the machines'
sign-ins, director decisions 0015 and 0017). The user, 10-31: one custody
for both, recorded in the log; 4 Claude and 3 Codex subscriptions, every
login that still works reused across them before more are signed in.

- **One shelf, on hel8:** `~/src/fabrig/logins/shelf/<id>/` (0700), one
  entry per login, holding it under its kind's name. The kinds are `codex`
  (`~/.codex/auth.json`) and `claude` (`~/.claude/.credentials.json`), lent
  to a machine at that path, and QA's `chatgpt` (temper's ChatGPT record,
  a live run's `TEMPER_LIVE_ACCOUNT`), `claude-box` (a Claude Code
  directory, `TEMPER_LIVE_CLAUDE`) and `github` (temper's GitHub
  conformance fixtures, `TEMPER_LIVE_GITHUB_FIXTURES`: the probe App's
  `app.json` and `app.pem` and a `person-<owner>.token` per owner, none
  of which refreshes), lent to a run at a path of its own. An id is
  `<kind>-<n>`.
- **Custody is the log:** `login.added` (id, kind, origin, sha),
  `login.lent` (id, holder, host, at, sha), `login.returned` (id, sha),
  `login.checked` (id, email, plan, used, resets, error, limit_names,
  limit_used, limit_resets) and
  `login.retired` (id, reason). `fab.logins.fold` derives each login's
  holder; the dispatcher's machine is the only writer, under the shelf's
  flock.
- **Copied out, copied back:** both products refresh their tokens, so the
  copy last used is the true one. A lent login's shelf copy is a
  placeholder until `fab logins return` copies the lent copy back, checks
  its digest on both ends, and removes it where it was only if it has not
  changed meanwhile (its user must have stopped). Lending checks the shelf
  copy against the last returned digest, installs it only where nothing
  is, and checks it again there. tar, ssh and sha256sum move and hash the
  bytes; Python never holds them and nothing prints them.
- **A machine's logins:** `fab logins capture HOST KIND` takes a machine's
  current sign-in onto the shelf, still lent to it (decision 0017's
  "bound"); `--free --path P` takes one whose source is used no more (QA's
  custody holds it, its machine is gone). `fab logins swap HOST ID` gives
  back the machine's login of that kind and lends ID; `fab logins list`
  names each role's missing logins (a dispatcher or builder needs both
  kinds). Lending a `claude` login to a machine also drops the account
  Claude Code cached in `~/.claude.json`: it reports, and keeps, the
  previous login's until none is cached (11-01: three swapped builders
  said gmail until it was dropped).
- **A run's logins:** `fab logins borrow KIND HOST --path P --holder RUN`
  lends the free login of that kind with the lowest number and prints its
  id. Builders reach the shelf by ssh to hel8 (the user, 11-01: custody
  stays central). `fab after-landing run --live` adds the live pairs of
  `fab.after_landing.LIVE`: only `live-skein`. `live-temper` is out (11-01):
  all its live stories are ignored owner-run sittings, and since fabrig
  eb6c40aaf those binaries have no harness unit tests; nextest exits 4
  (no tests to run), faulting the pair and holding the cursor (11). It comes
  back only once the user decides which ignored stories, if any, should run
  with `--run-ignored`. Borrowing and the `chatgpt` record / `claude-box`
  directory kinds remain supported and tested. `live-smith` is
  out (11-01: all 17 of its tests red at once on hetzner8): besides
  `SMITH_LIVE_CLAUDE` its tests need `SMITH_LIVE`, a whole live root
  (`config/smith/config.toml`, `host-id`, `tokens/chatgpt`, a ChatGPT
  record of smith's own made by `smith login chatgpt`, and
  `programs/claude`), which no kind holds yet; it comes back as a
  directory kind once the user signs one in. Each pair borrows its logins, lent to the builder
  under its run directory for holder `after-landing/<tip>/<pair>`, runs
  with the variables naming them, and returns them when it ends; a pair
  short of a login faults, and a login that cannot be returned stays lent
  to its run with an `error` record. `live-skein` borrows a `codex` and a
  `claude` login (`SKEIN_TEST_LIVE_OPENAI_AUTH`,
  `SKEIN_TEST_LIVE_ANTHROPIC_CREDENTIALS`: its tests read a login's file
  instead of tokens in their environment, the user, 11-01, fabrig
  `logins/skein-live`). They read the access token and never refresh it,
  so fab refreshes each first where it was lent (`fab logins account KIND
  --home DIR --validate`); one that does not refresh faults the pair.
  The after-landing unit runs `--live` (the user, 11-01), on the cheapest
  models: temper's and smith's live tests pick `gpt-6-luna` and
  `claude-haiku-5-5` themselves, and `fab.after_landing.CHEAP` sets
  skein's `SKEIN_TEST_LIVE_*_MODEL` to the same.
- **Checks by the products themselves:** `fab logins check ID` asks Codex's
  app-server (`account/read`, `account/rateLimits/read`: the account, the
  plan and every limit) or `claude auth status` followed by local `/usage`. A lent
  machine login is checked in place, on its machine; a free one is lent to
  hel8 in a private directory and returned. Every check makes a real
  request (a Claude call of a few tokens; Codex refreshes its token), so an
  expired login says so and a swapped Claude login does not report the
  account its predecessor left cached (11-01: three swapped builders said
  gmail until their first call). The weekly percent is the signal for a swap.
  `account()` returns `limits`, dictionaries of `name`, `used` (percent) and
  `resets` (Unix seconds or null). Codex reads every bucket in
  `rateLimitsByLimitId`, sorted by key, or `rateLimits` alone, and each
  bucket's primary and secondary windows. Duration labels are `5 h` (300
  minutes), `week` (10080), otherwise whole days, whole hours or minutes;
  an unknown duration is `?`. A bucket whose `limitId` is not `codex`
  prefixes `other `, never its backend display name. The shelf's existing
  `used` and `resets` remain Codex's weekly window (the primary window for
  older responses without a labelled week).
  Claude runs `claude -p /usage --output-format json --no-session-persistence
  --strict-mcp-config --tools "" --model claude-haiku-5-5 --settings
  '{"disableAllHooks": true}'` with `TZ=UTC`. It accepts only a local
  `usage` command with zero turns and zero cost. `Current` lines yield each
  limit; `session` becomes `5 h`, `week (all models)` becomes `week`, other
  names stay as written, and Fable lines are dropped. English resets with
  an optional month/day and UTC suffix use the next matching date/time,
  allowing the previous hour as the old renderer did. A failed or
  model-answered `/usage` leaves limits empty and keeps the account.
  `Shelf.check` records limits as three parallel scalar lists:
  `limit_names`, `limit_used` and `limit_resets`, of equal length and order;
  unknown use or reset is null. It never puts dictionaries in log fields.
- **Check the shelf:** `fab logins check --all` checks each login whose kind
  has a check, sequentially. Custody refusals (including a run's login and
  retired logins) print `skipped`; account failures record `login.checked`
  with `error` and do not stop the remaining checks. Bulk checking exits 0;
  explicit ids retain their failure exit status. A 30-minute timer on hel8
  is deployed by hand, outside this change.
- **Left out:** the old tools' pending journals and backups, QA's waiting
  queue, reservations and admission caps (the dispatcher decides who gets a
  login, as it does places), and checks of `chatgpt` records, which only a
  temper box can read: their live runs show whether they work.

### 13.14 The status page

- **Public counts and subscriptions from the log.** `fab serve [--port 8370] [--bind 127.0.0.1]`
  serves one HTML page at `/`, its JSON snapshot at `/api/status` and `ok` at
  `/healthz`. GET only; other methods return 405, other paths 404, and query
  strings are ignored. It prints its bound address, including a port chosen
  by `--port 0`.
- **Pure core, read-only shell.** `fab.serve.snapshot(events, now, hosts)`
  computes counts and subscriptions; `render(snapshot)` returns escaped HTML. Each request
  reads `FAB_HOME/log.jsonl` through `fab.log.read` and host names through
  `fab.hosts.load`. No lock, writes, cache, ssh or plan files. An unreadable
  log still returns 200, with `log: "unreadable"` and no figures; failures
  show fixed classifications, never exception text.
- **Now and waiting.** The last event's age; runs started within 24 hours
  and calls within `fab.calls.TIMEOUT` seconds without a matching end, by
  host and role. Waiting uses `fab.channel.asks((), events)`: only the log's
  open user asks, without plans or the foreman's task questions. The
  `waiting_on_user` snapshot has `asks`, `by_kind` (`call`, `parked`, `finding`) and
  `oldest_age_s` from the asks' `since`, null when none. Waiting has no age
  cut; answers, completed designs and finished chains close asks as on the
  user's page (13.6).
- **Today is UTC.** `landed` counts `branch.landed` without `into` (on main);
  `merged` counts those with `into` (into a trunk). Each has `last_hour` and
  `today` counts; the page labels both under Today. Rejected branches and
  ended runs by done, question, infra, failed or other are today's.
  `fab.accounting.run_weight` and `call_weight` sum today's measured endings
  in millions, to one decimal; missing weights are skipped. Invalid timestamps
  and future events are skipped; today ends at the snapshot's time.
  The snapshot's `weight_today` keeps `codex_m` and `claude_m` and adds
  `ratio`: Codex divided by Claude using the unrounded totals, rounded
  to one decimal, or null when Claude's weight is zero. One tile replaces
  the separate Codex and Claude weight tiles: `Weight today · Codex/Claude`,
  value `4.9×` (one decimal) or `–` when the ratio is null, and sub
  `Codex 165.0M · Claude 33.2M` using the existing one-decimal figures.
  The Today card `Weight` stays unchanged.
- **Drafts come from run starts.** Only prefixes of `run.started` tasks in
  the log qualify. Those with a run in flight, a main landing or a trunk
  merge today show `runs_in_flight`, `landed_today` and `merged_today`.
  A main landing belongs to its task's prefix only when that prefix is a
  known draft from a run start; otherwise it belongs to `by-hand`. Missing,
  null, empty, `-` or slash-less tasks and unknown prefixes are `by-hand`.
  A trunk merge belongs to the prefix of `into` (`<draft>/integration`),
  only when that draft is known. Call branches do not create drafts.
- **Only public labels leave the fold.** Known host names, call roles from
  `fab.calls.ROLES` (others become `other`), and draft names matching
  `[a-z0-9][a-z0-9.-]{0,63}` (known drafts failing the pattern become
  `other`). A prefix ends at the first `/`; draft qualification uses this
  prefix before public classification. Subscription labels are
  masked emails. No task, run or call ids, branches, shas, paths, question
  or answer text, notes, reports, full emails or holders in HTML or JSON;
  subscriptions never expose hosts.
- **Subscriptions:** group nonretired Claude and Codex logins whose latest
  `login.checked` is within 24 hours and successful (no error), with a
  nonempty email, by `(kind, email)`. Each login's latest check decides its
  current account; a failed check or one without an email leaves that login
  out. Full email is only an internal grouping key; groups sharing a mask
  stay separate. The snapshot's `subscriptions` list has one entry per group,
  sorted by kind then label. Each has `subscription` (the masked email),
  `kind`, `plan` matching `[a-z0-9_]{1,40}` or empty, `logins` (the sign-in
  count), `checked_age_s` and `limits`. For `local@domain`, the mask keeps
  the local's first and last characters around `***`, followed by `@` and
  the lowercased domain. A local of one or two characters keeps only its
  first character before `***`. Local characters keep their case; the domain
  is otherwise unchanged. Without exactly one `@` and two nonempty parts,
  the label is `***`. For example, `free.ekanayaka@gmail.com` becomes
  `f***a@gmail.com`. The group's newest successful check supplies its plan,
  age and limits. The three scalar log lists are zipped back to `name`,
  `used`, `resets`; old checks without them have no limits. Fable is omitted;
  `5 h` appears only above 80% use. Each limit also has `rate_per_h`,
  `full_at` and `at_reset`, null without a usable earlier sample. Use the
  oldest successful sample across the group's logins for that account and
  limit with the same reset, at least 20 minutes before the latest check;
  decreasing use and expired or unknown resets give no pace. Checks made
  under another account do not contribute. Rate is percent per hour to one
  decimal; projections use the unrounded rate from the latest check time.
  `full_at` is Unix seconds if full before reset; otherwise `at_reset` is
  projected percent at reset to one decimal (zero rate lasts).
  The panel after Waiting on the user has Subscription (kind, plan, label,
  and `7 sign-ins` or `1 sign-in` on its first row), Limit, Used (meter and
  percent), Resets (countdown and a UTC `time` element/title), Rate
  (`3.6%/h`) and At this pace (`full in 1 d 13 h`, `lasts, 19% at reset`,
  or `–`). Meters warn at 80% and turn critical at 95%. A check with no
  limits shows `–`. With no eligible subscriptions:
  `No login checked in the last 24 hours.` A Subscriptions tile after the
  weight ratio shows the highest `week` percent (`–` when absent), with
  `<n> subscriptions` below.
- The page reuses the previous status page's stylesheet and layout (tiles, panels, cards, badges), 1280 px wide.
- **One plain document.** Title `fab status`, inline CSS, no JavaScript,
  refresh every 30 seconds, phone width and light and dark colours. Header,
  tiles, Waiting on the user, Subscriptions, Drafts, Today, In flight, then footer; ages in
  seconds, minutes or hours. Waiting is the first section below the tiles.
  Its tile, kind labels (Call questions and Parked chains) and "Open the
  questions" below the oldest age link to the forge's open `waiting-on-user`
  issues at `https://git.fabrig.ai/fabrig-ai/agents/issues?state=open&labels=1`.
  The repository is private; the public page links to it without showing
  issue contents.
- **Deployment is by hand at the user's OK:** a transient unit on hel8 and
  Caddy's `status.fabrig.ai` moved to `reverse_proxy 127.0.0.1:8370`.

### 13.15 QA findings

At the user's word (11-01, after qa-ladder): QA of temper v0.1.0 ran by hand.
A session wrote rung briefs, had a Claude subagent walk each, triaged the
findings itself, surveyed their causes, had Codex repair the on-path ones,
landed them as hand-pushed ready refs and reran each brief unchanged; the
off-path ones piled up in a file with no owner (`coord/qa-ladder/
findings.md`, 48 entries). fab runs that loop: a walk's findings enter the
log, a director's call triages them, on-path ones become Fix-mode repairs
through the foreman path reds use (section 11, 13.1), and fab says when a
rung's brief is due again, unchanged. `temper/docs/design/draft/v0.1.0.md`,
2-4, is the process; `execution-modes.md`'s Fix mode ("a finding, a red, a
bug"; one finding the unit of flow; the finding's own walk, rerun unchanged)
and "QA's findings enter Fix mode" are the model. In the first build a
session still walks by hand; walks run by fab are the section's last part.

- **The ladder is a plan,** a fabrig plan (13.11) with `landing = "queue"`,
  listed in `FAB_HOME/plans`, whose plan.toml names its rungs: v0.1.0's is
  `temper/docs/plan/v0.1.0-ladder/`. A plan owns its draft's work (13.4), so
  its walks, findings, triage calls and repairs are the plan's.
  - `[ladder]`: `happy_path` (a citation, as a part's `design`:
    `"temper/docs/design/draft/v0.1.0.md, 2 and 4"`) and `backlog` (a
    repository path: `"temper/docs/design/debt/v0.1.0-ladder.md"`).
  - Each `[[rung]]`: `id` (`[a-z0-9-]+`, unique), `backend` (one of
    `fab.findings.BACKENDS`: `chatgpt-forgejo`, `claude-forgejo`,
    `chatgpt-github`), `brief` (paths in the plan directory, read in order:
    the kit, then the rung's own, as qa-ladder's `briefs/kit.md` and
    `briefs/rung-b1.md`) and `after` (rung ids below it; default none). A
    story walked on two backends is two rungs (`b1`, `b1-claude`).
  - `fab.plan.load_plan` reads them into `Plan.rungs` (`fab.plan.Rung`) and
    `Plan.ladder`; `[[part]]` becomes optional, and a ladder plan has none,
    so it is never designed or retired. `fab.plan.problems` adds: a plan with
    neither parts nor rungs; a rung id used twice; `after` naming no rung, or
    a cycle; a brief file missing; rungs in a plan whose landing is not
    `queue` (the ladder walks main). `triage` joins `fab.plan.RESERVED`.
- **A rung's edition is its brief's bytes** (`fab.walks.edition`, pure): the
  first 12 hex of sha256 over each brief file's path and text, in order,
  read at `origin/main` of the plan's checkout (`git show`, by
  `fab.walks.editions` for the tick and `fab qa walk` alike). "Rerun
  unchanged" means a walk at the edition of an earlier walk of the rung. A
  kit or brief change makes a new edition (qa-ladder's B1 and B2 edition 2,
  11-01, after a careful model beat edition 1's gate by guessing its pull
  request's number): walks at an older edition count no more toward the
  pass, the new edition's first walk is a first walk, and its pass is that
  edition rerun unchanged (qa-ladder's advisor, 11-01 05:40Z). Findings
  raised under an older edition keep their state. A kit change reopens
  every rung that reads it, even one it does not touch (kit-github's
  edition 3 changed only CI reads): the price of "unchanged" being code's
  rather than a session's judgement.
- **A walk enters fab by a command on hel8** (`fab qa`, `fab/walks.py`; the
  session that walks runs it in the first build). Both of its writing verbs
  hold `FAB_HOME/qa.lock` (a flock) from counting ids to their last append,
  so two sessions never take one id; ids are global, `walk-<n>` and
  `finding-<n>`, n counting `walk.started` and `finding.raised` in the whole
  log, as `red-<n>` is, and a repair's id `<draft>/finding-<n>` stays short.
  - `fab qa walk PLAN_DIR RUNG --commit SHA [--by WHO]` fetches the plan's
    checkout, reads the rung's brief files at `origin/main`, refuses a commit
    that does not contain every landed repair of the rung's findings, a
    merged one's being its target's whatever rung raised it (`git
    merge-base --is-ancestor <its branch.landed main> SHA` in
    `FAB_HOME/repos/fabrig`, naming the first missing), and logs `walk.started` (walk, draft, rung, backend, edition,
    commit, by). It writes `FAB_HOME/walks/<walk>/brief.md` and prints its
    path and the walk's id: the brief files' text as read, then `# Reporting
    to fab` (the result's form, and where to write it: `report.md` and
    `result.toml` in that directory), then `# Open findings` (each open
    finding of the plan: id, state, rung, area, title), so the walker can
    name one it meets again. What fab adds is fab's mechanics, outside the
    edition. An early or speculative walk is not refused: qa-ladder walked
    rung A's first walk beside rung 0's.
  - **The result** is `result.toml` (TOML: multi-line strings are easy for a
    walker to write and tomllib reads them): `verdict` (`pass`, `fail` or
    `void`), `reason` (one line: where it broke; for void, why the story was
    not walked: a setup to redo, a gate the model beat, as qlc-b1-1), then
    per `[[finding]]`: `title`, `severity` (`low`, `medium`, `high`), `area`
    (the component it names: `temper ctl`, `jig tasks`, `smith`, `temper
    help`), `blocking` (it stopped the walk), `reproduction` (the commands
    from a fresh box, in order), `expected`, `seen`, `evidence` (paths on
    the walk's machine) and `same` (an open finding's id from the brief's
    list, when it is that one; else ""): qa-ladder's walkers' prose
    (`walks/*/report.md`) in fields. The prose report stays beside it.
  - `fab qa result WALK [DIR]` (DIR default `FAB_HOME/walks/<walk>/`) reads
    `result.toml` (`fab.walks.parse`, pure), copies it and `report.md` into
    the walk's directory, and logs one `finding.raised` per finding (its
    `index` the finding's place in the result), then the walker's merges,
    then **`walk.ended` last** (walk, verdict, reason, report, findings: the
    ids), and wakes the tick (`qa <walk>`). A finding counts in the fold only
    once its walk has ended, so an intake cut short is retried whole: the
    same command on a walk with no `walk.ended` skips the indices and merges
    already logged. It refuses, logging nothing and naming the field: a walk
    unknown or ended; a verdict not in the three; `pass` with a blocking
    finding; `fail` with no finding (where it broke is one); a severity not
    in the three; a `same` naming no finding of the plan; a title over 200
    characters or a reproduction, expected or seen over 4,000; more than 30
    findings.
  - `fab qa rungs [PLAN_DIR...]` prints each rung's line, as the page does.
  - A walk with no `walk.ended` for `WALK_HOURS` (4: the kit's wall cap of 3
    hours and an hour to report) is no longer walking; its result is still
    taken when it comes.
- **A finding is temper's record, kept in fab's log** (temper's
  `domain/findings.md`, 2 and 4; fab keeps no forge issue, 1's "interim by
  intent"). `finding.raised`: finding, draft, walk, index, rung, backend,
  commit, edition, kind (`qa`, temper's kind; reds keep their own path,
  section 11), title, severity, area, blocking, reproduction, expected,
  seen, evidence, `again` (below). Its state, as temper's: `new`, `routed`
  (on the path), `backlog`, `dropped`; and fab's: `asked` (needs the user),
  `merged`, and a routed finding's repair states.
  - **Departures from temper's record, each for a reason:** no signature: a
    QA finding has no failing test ids, and temper too files QA findings
    anew, matching only flakes by signature (its 4); `area` is the component
    the walker names, free text, since fab has no project's areas list;
    severity is the walker's, for the triager and the page (temper's open
    question 10, settled for fab by taking the finder's); a finding closes
    on its rung's rerun, not on `Fixes #n` once its landing clears (temper's
    7): there is no issue, and Fix mode's QA is the finding's own walk,
    rerun unchanged.
- **The same finding is merged, never filed twice,** by two hands and no
  key: a normalised reproduction would not match, since the same cause shows
  through different tasks, ids, SHAs, times and ports in each walk
  (qa-ladder 32 and 38: one reviewer's reads answered "busy", another's
  "declined", one capacity likely behind both). One rule for both hands,
  on the target (a merged one resolving to its own target):
  - new, asked, routed before its repair has landed, or backlog: merged,
    `finding.merged` (finding, into, by the walk or the call, reason). Its
    target's repair carries its reproduction too, and the target holds the
    rung for it when it would hold it itself;
  - repair landed, fixed or left: not merged but filed again, `again` set
    to the target, for triage: the fix did not hold. The walker's raise
    carries `again` itself; the triager's line logs `finding.triaged`
    decision `again` (into the target), and the finding stays new with
    `again` set, so a later merge line into that target is skipped;
  - dropped: `again` as above, the drop having been wrong.
  qa-ladder's walkers named theirs as "Known again: 2, 6, 9, ...".
- **Triage is a Claude call in the director's role** (v0.1.0.md 4: "the
  director triages every finding"; the user's request, 11-01): role
  `triage`, `fab/roles/triager.md`, effort medium as the answerer (a batch
  of small judgements, not a design), subject `<draft>/triage`, started by
  the tick, `fab call triage --plan PLAN_DIR` (`fab.triage.main`, reached
  from `fab.calls.main` as the designer's roles are).
  - **It writes no branch.** `fab.calls.start` gains `report_only`: its
    worktree is the plan's repository detached at `origin/<base>` (`git
    worktree add --detach`); nothing it writes there is kept (no branch is
    made or pushed, the worktree is removed) and `call.started` names no
    branch. `triage` is not in
    `fab.call_review.REVIEWED`, so it has no chain: nothing is reviewed,
    finished or landed. Its output is its report.
  - **When** (`fab.triage.due`, pure, in `fab.dispatch.call_actions`): a
    finding of the plan is new, no triage call of the plan is in flight, no
    triage `Question:` of the plan is open (an ask of kind call, section 12,
    until `fab page answer <draft>/triage`), and either a new finding is
    blocking or came from a failed or void walk (it holds its rung: at once, as a
    question that holds up work), or the answerer's thresholds hold:
    `ANSWER_AT` (4) new, or the oldest new one `ANSWER_AFTER` (30) minutes
    old. A finding the user answered, or filed again, is new again. A call
    that ends failed is followed only after a new finding or 30 minutes.
  - **Its brief** (`fab.triage.brief`, compiled by code): the role text;
    the call's facts; `# The happy path`, `happy_path`'s sections cut as a
    part's design is (`fab.calls._cited_design`); `# The rungs`: each rung's
    line and the brief of every rung with a new finding, whole; `# New
    findings`: each with every field, its walk's verdict, `again` when set,
    and the user's answers for it (`fab.channel.answers_text(<draft>/
    triage/<finding>)`); `# Open findings`, to merge against: every finding
    asked, routed, landed or backlog, one line each (id, state, rung, area,
    title, sightings: the merges into it).
  - **It decides each new finding,** one report line each, and may re-decide
    a backlog one (qa-ladder promoted `account list`'s raw dump to the path
    once every walk had met it):
    - `<id>: path <owner>: <why>`, on the happy path (4's: the ladder's
      stories and each part's bar, used as intended, on the four backends;
      a security hole, lost data and a gate's flake; the tool's friction
      where a walk stalled), owner the tree or crate it names; it may end
      `; user: <what the user must do>`, an action of the user's that the
      rerun needs besides the repair (qlg-0-2's reinstall of the GitHub App
      a connect had uninstalled), which holds the rung until answered while
      the repair goes on; it is not an input to the repair;
    - `<id>: backlog: <why>`, off the path;
    - `<id>: user: <the question>`, only what is the user's (a credential or
      sign-in, a machine, a budget, the product's direction: qa-ladder's
      GitHub rungs with no GitHub login on the shelf);
    - `<id>: brief <rung>: <what is wrong>`, the rung's brief at fault (its
      gate beatable, a step wrong): a question to the ladder's owner, the
      user, naming the brief's files; answered, the finding is dropped with
      the answer as its reason, and a new edition, if one comes, reopens
      the rung;
    - `<id>: merge <into>: <why>`, the same cause as another finding (the
      rule above);
    - `<id>: drop: <why>`: not reproducible from its report, the walk's
      setup or machine (qa-ladder's load-caused red, item 24), or not
      temper's or its trees'.
    A blocking finding is on the path unless it is not the product's:
    v0.1.0.md 4 puts a rung's own walk's findings on the path by
    definition, and the request triages them; the role text defaults to
    the path. The box's model going against what it is told is on the path
    only when it failed an acceptance (qa-ladder's ql-a-2: a chat reported
    an invented feature as the fix), its fix being what the model is told;
    otherwise backlog (findings 7, 16, 41).
  - **Code records the decisions** (`fab.triage.decisions`, pure; logged
    by the tick each round before `decide`, once per call): for a triage
    call ended done whose id no `finding.triaged`, `finding.merged` or note
    carries, it parses the report and logs per valid line `finding.triaged`
    (finding, call, decision `path`, `backlog`, `user`, `brief`, `drop` or
    `again`, owner, reason, question, into) or `finding.merged` (by the
    call). A line naming a finding that is not new (or backlog, for a
    re-decision), or merging into itself, an unknown finding or one it is
    already `again` of, is skipped; the finding stays as it was for the next
    call. A call with no valid line logs one note (`call`, `triage <call>:
    no decisions`).
- **Off the path is the tree's backlog,** `[ladder].backlog`, not the
  user's page: the page is for what is the user's (13.6) and 48 entries
  would bury it; the backlog outlives the plan, for the owner after v0.1.0
  (v0.1.0.md 4: it "waits until v0.1.0 is out"), as fabrig's
  `jig/docs/design/debt/` and `skein/docs/design/debt/` do.
  - **Code renders it from the log** (`fab.triage.backlog_text(plan,
    events)`, pure): a header, then per finding in state backlog, in raise
    order, `## <finding>: <title>` with its rung, walk, backend, commit,
    area, severity, sightings, reproduction, expected, seen and the
    triager's reason, as `findings.md`'s entries. A finding re-decided to
    the path, or merged, leaves it; the log keeps its history.
  - **Readied as a fab branch:** each round, after recording decisions, when
    the render differs from the file at `origin/main` and no backlog branch
    of the plan is ready and not yet landed or rejected, the tick commits it
    (`fab.spec_edit.commit_path`, `fab.spec_edit.commit` taking a repository
    path instead of a task) on `ladder/<draft>/backlog-<n>`, n counting the
    plan's earlier ones, and readies it as a call's branch is
    (`fab.dispatch._queue_branch`, no receipt; it gains a `**fields`
    passthrough to `branch.ready`, which carries `render`).
  - **Its landing comes home:** `fab.dispatch._import_queue`'s owners
    include each `ladder/<draft>/backlog-<n>` that has a `branch.ready`,
    mapped to its draft, so its queue records become `branch.landed` and
    `branch.rejected` with task the branch, and advance the draft's cursor,
    as a call's branch's do (13.11). `ladder/` joins the fab branch forms
    kept out of `queue.*` (13.8).
  - A rejected or failed commit is tried again, as a new n, on a later
    round; no triage waits for it. After two rejections of the same render
    (its sha256 recorded as `render` on `branch.ready`), the page raises
    `backlog:<draft>` (13.6: the branch, the step, the queue's log) and the
    tick readies no more until the render changes or the signal is cleared.
    The page shows the backlog's count and path only.
- **On the path is a Fix-mode repair through the reds' foreman path,** a
  new kind beside `red` sharing its machinery: a finding's lifecycle
  (walks, rungs, reruns, merges) shares nothing with a red's (tips, keys,
  suspects, tiers runs, coverage), while what follows the decision is the
  same.
  - **What moves out of `fab/tier_reds.py`** into `fab/fix.py`, Fix mode's
    shared steps, so both kinds call one copy (red-routing owns
    `tier_reds.py` and is wiring it now; this is one task after its wiring
    lands, behaviour unchanged, its tests kept):
    - `fab.fix.launch(task_id, host, tip, brief, events, **fields)`: the
      tail of `tier_reds.start` (`fab.run.next_run` over
      `fab.foreman.task_field(task_id)`, the report path under
      `fab.run.remote_home`, `fab.run.launch_detached(host, run, "fabrig",
      tip, ...)` with kind `foreman.KIND`, effort `foreman.EFFORT`, branch
      the task id, base the tip and the caller's run.started fields);
      `fab.fix.report_path(host, run)` gives the brief its report line;
    - `fab.fix.parse(report, *, skip=None)`: `tier_reds.remedy`'s parse of
      the first line (`Done: fix: <line>` or `Done: retry: <line>`) and the
      next `SECTION_LINES` lines, returning (verdict `fix`, `left` or
      `none`, reason, lines, skipped); red passes `skip`, its `Owner:` line
      taken out before the lines are kept and returned as `skipped`, whose
      value red's owner check reads;
    - `fab.fix.section(heading, reason, lines)`: the section, trailing blanks
      dropped, as `tier_reds.remedy` builds it;
    - `fab.fix.settle(ev, fields, *, log_path)`: `tier_reds.settle`'s stamp
      and append, `fields` a callable from the stamp's day to the record's
      fields (one `log.now` for both), so red's records and tests stay as
      they are;
    - `fab.fix.answers(events)` and `fab.fix.task(task_id, kind, part,
      body, answers)`: `tier_reds.repair_tasks`' scan of `question.answered`
      and its `Task` (repo fabrig, no needs, files `**`, effort high, 20
      minutes, no path, `## Answers` appended);
    - `FIX_KINDS = ("red", "finding")` and `RUNS = 2`
      (`tier_reds.RED_RUNS` kept as its name for it).
    `fab/fixes.py` then holds only the finding's: its foreman's brief, its
    repair's body, and their fold.
  - **One action pair for both kinds:** `Action("examine-fix", task=<repair id>,
    detail=<red or finding id>, run_kind=<kind>)` and `Action("remedy-fix",
    run=<foreman run>, run_kind=<kind>)`; `fab.dispatch.red_actions` and
    `finding_actions` (both pure) make them, and `_take` sends each to its
    kind's start or settle: section 11's `examine-red` and `remedy-red`,
    renamed with the move.
  - **Its foreman** (Codex, medium, read-only;
    `fab/roles/foreman-finding.md`): a finding routed starts one through
    `fab.fix.launch`, run `<draft>/finding-<n>/foreman-1`, its run.started
    carrying `finding` and `tip` (main's tip in the plan's checkout this
    tick), on the builder with most free places even at none. It is
    qa-ladder's cause survey. Its brief (`fab.fixes.brief`): the role text;
    `# The finding`: run, finding, rung, backend, walk, commit walked, area,
    the triager's owner and reason, the rung's brief paths (in its
    checkout), the report path, `Your checkout is fabrig at <tip>,
    read-only.`; `# The record`: title, reproduction, expected, seen, and
    each finding merged into it; `# The walk's report`: `FAB_HOME/walks/
    <walk>/report.md` whole (at most the kit's 15 KiB), since a builder
    cannot read hel8's files.
  - Its report keeps the form: `Done: fix: <line>`, then at most thirty
    lines: the cause, where on main, what to change, and the lowest world
    that reproduces it (a unit or world test on the fake backends; a fake
    model's script from the walk's transcript where the model's turn matters,
    v0.1.0.md 4); `Done: retry: <line>`, read as **not the code's** (the
    walk's setup or machine, a backend's outage), then at most ten lines; or
    `Failed: <why>`. When unsure, it is the code's. The tick settles it
    (`fab.fix.parse` and `section`, then `fab.fix.settle`) with `finding.settled`:
    finding, run, verdict `fix` (reason, section `## Repair (<day>, finding
    <n>, foreman <run>)`), `left` (the finding is a signal) or `none`. A
    foreman ending otherwise is the fallback: the repair starts with the
    finding alone. One foreman per finding.
  - **The repair is `<draft>/finding-<n>`,** folded from the log
    (`fab.fixes.tasks(plan, events)`, through `fab.fix.task`, joined to the
    plan's tasks as red tasks are), never a spec file: kind `finding`, part
    `qa` (no plan part, as a red's `after-landing`). It exists from
    `finding.settled` fix or none, or the fallback. Its body: `# Repair a QA
    finding (finding-<n>)`; the rung, backend, walk, commit and edition; the
    area, owner and the triager's reason; `## The finding` (the record, and each
    merged one's walk and reproduction); the foreman's section; then `##
    Acceptance`: reproduce first, in the lowest world that shows it, a test
    red on main before the change and green after, naming the world and why
    it is the lowest; then fix; design text the change makes untrue changes
    in the same branch (the tree's `docs/design/` and status file;
    `temper/docs/help/` with its help tests); then the task's own checks as
    any fabrig task (precheck `--onto origin/main`): qa-ladder's
    `tasks/TEMPLATE.md`, which every hand repair carried.
  - **Everything section 11 gives kind `red` holds for each of
    `fab.fix.FIX_KINDS`:** an implement run from `origin/main` in a slot;
    readied for the queue and landed as `Merge <draft>/finding-<n>`; in the
    queue import's tasks; `fab.fix.RUNS` (2), then the answerer (Fix mode:
    "Claude ... after two failed tries"); its questions skip the foreman;
    its queue refusal goes to the specless refusal foreman; the answer
    call's brief lists its questions; a landed one is a fab suspect after
    landing. Each repair is readied alone and the queue batches them:
    qa-ladder batched by hand, and two of its batches went stale on the
    first's landing (batch-2 and batch-3, ~40 minutes).
  - **One repair per finding:** a merge never makes a second; the merged
    reproduction reaches the repair's next run through the body.
- **Where each finding stands** (`fab.findings.findings(events)`, pure, log
  order, from its walk's `walk.ended` on): new; asked (triaged `user` or
  `brief`; new again, or dropped for `brief`, at a `call.answered` whose
  subject is `<draft>/triage/<finding>`); foreman, deciding, decided
  (triaged `path`, its foreman's run.started, its done end); repairing (its
  task exists, not landed); landed (its task's `branch.landed`); left
  (settled left); backlog; dropped (triaged `drop`, or its signal cleared:
  reason the clear's text); merged. After landed: **fixed** at its rung's
  next `rung.passed`, or **unfixed** when a later raise or triage line files
  one again of it. **Only a blocking finding, or one from a failed or void
  walk, holds its rung,** while new, asked, foreman, deciding, decided or
  repairing, or while a `; user:` action on it is unanswered; a merged
  one holds through its target. Others are triaged and repaired as any but
  hold nothing, and are fixed or unfixed at the rung's next pass. Left
  holds nothing: the foreman says it is not the code's, and the rerun shows
  whether it was.
- **Acceptance by itself** (v0.1.0.md 3: "the same brief, rerun unchanged,
  passing"). A rung's state (`fab.findings.rungs(plan, events, editions)`,
  pure, editions the current ones), the first that holds, in plan order:
  - **passed:** a `rung.passed` at its current edition and no failed walk of
    it since (a rung that fails after passing has a finding, never a retry,
    v0.1.0.md 3);
  - **walking:** a walk of it in flight;
  - **waiting:** a rung in `after` is not passed (it is holding, due,
    walking or waiting itself): "a rung's open findings hold the rungs above
    it" (qa.md 3), and "down before up";
  - **holding:** a finding holds it;
  - **due:** otherwise, a `first walk` when no walk at its current edition
    has ended pass or fail, else a `rerun`, at a main containing each
    landed repair of its findings (the newest such `branch.landed`'s main).
  The rerun does not wait for after-landing's verdict on that main: the
  walk is its own check on real backends, a red after landing reaches its
  owner by section 11, and the tiers would add an hour to each round.
- **A pass is recorded by the tick** (`fab.findings.passes`, pure, then
  `rung.passed`: draft, rung, walk, edition, commit; before `decide`; at
  most one per walk): a walk ended pass at the rung's current edition,
  after another walk of it at that edition ended pass or fail (a rerun),
  with no finding holding the rung at its end and no failed walk of the
  rung since, and each rung in `after` passed when it ended, or passed by a
  walk at the same commit (qa-ladder judged parallel walks in rung order:
  "counts once B0 passes"). A pass whose lower rung passed later, at
  another commit, counts no more: the rung is due again. A passing walk's
  non-blocking findings are triaged as any; the pass stands.
- **fab says a rerun is due** on the user's page and in `fab qa rungs`, one
  line per rung (13.6, `## The ladder`): `<rung> (<backend>), edition <e>:
  due: rerun at a main containing <sha12>`, `walking: <walk> since <ts>`,
  `waiting for <rungs>`, `holding: finding-3 repairing, finding-7 new`,
  `passed at <commit12> (<walk>)`. The first build's session reads it,
  starts the walk with `fab qa walk` and reports it with `fab qa result`.
- **The tick, each round** (`fab.dispatch._tick_plan`, a plan with rungs):
  first the decisions of ended triage calls, then `rung.passed`, then the
  backlog's branch, then the plan's tasks joined with its finding repairs,
  then `decide`; after the refusal settlements, `finding_actions` beside
  `red_actions`; `call_actions` starts the triage call when it is due.
- **Tests** (fake runner, records and log): `fab qa result` on a failed
  walk's `result.toml` logs two `finding.raised`, one `finding.merged` for
  a `same` naming an open finding and `walk.ended` last, and wakes once; an
  intake cut after the first `finding.raised` and run again logs the rest
  once and nothing twice, and the fold ignores the walk's findings until it
  ends; two intakes at once take distinct ids; a `same` naming a landed
  finding files it again with `again`, as a triage merge line into one
  does; a pass with a blocking finding, or a fail with none, logs nothing;
  the edition changes when a brief file does and earlier walks count no
  more; a failed walk's finding starts a triage call at once, a passing
  walk's waits for four or thirty minutes, and an open triage question
  starts none; the triage call makes no branch and no chain; its `path`,
  `path ...; user:`, `backlog`, `user`, `brief`, `merge` and `drop` lines
  log once, and a line for a finding not new is skipped; the backlog file
  renders from the log, is readied as `ladder/<draft>/backlog-1` when it
  differs from main, not again while that branch is pending; its queue
  `landed` imports as `branch.landed` for the branch, and a later decision
  readies `backlog-2`; a rejection readies the next n, and a second
  rejection of the same render raises `backlog:<draft>` and readies none; a path decision starts one foreman whose
  fix makes `<draft>/finding-<n>`, an implement run from main, readied, and
  whose retry leaves a signal and holds nothing; a user decision is on the
  page and its answer makes the finding new; a non-blocking finding of a
  passing walk holds nothing, and one of a void walk holds; the rung holds until the repair lands, then is
  due for a rerun, `fab qa walk` refuses an older commit, and the rung above
  waits meanwhile; the rerun's pass logs one `rung.passed` and the finding
  is fixed; a pass whose lower rung has not passed logs nothing until the
  lower passes at the same commit; a failed walk after a pass reopens the
  rung; red's tests pass unchanged after `fab/fix.py` is factored out.
- **Walks run by fab** (the last part; the cut leaves it for after the
  first build has walked a ladder by hand, or for later). A walk is a Claude
  call, role `walk` (`fab/roles/walker.md`, then the brief `fab qa walk`
  compiles, its id taken under `qa.lock`), started by the tick for a due
  rung, never two of one rung:
  - report-only on hel8 as the triage call is, its worktree fabrig detached
    at the walk's commit (qa-ladder's `read-<commit>` checkouts): nothing it
    writes there is kept (nothing is pushed, and the worktree is removed),
    since calls run without permission prompts; its box
    on the builder with the role `qa` in `fab/hosts.toml`, in `W =
    ~/src/fabrig/fab/walks/<walk>`, at most `boxes` (a new figure there) at
    once; its result taken at its end as `fab qa result` takes it;
  - its binary `W/bin/temper` copied from `walks/bin/temper-<commit>`,
    built once per commit by a run of kind `build` in a slot of that
    builder (`heavy cargo build -p temper`), which the walk waits for;
  - **logins are the resource:** the tick borrows, per the backend's kinds
    (`fab.findings.BACKENDS`: `chatgpt`, `claude-box`, `chatgpt` and
    `github`), the free login of each kind (`fab logins borrow KIND HOST
    --path W/<file> --holder <walk>`) before it starts the call, and starts
    none while one is missing, saying `due, waiting for a <kind> login` on
    the page: one live box per login (v0.1.0.md 2.2: "one holder per
    login"), the tick deciding who gets one as it does places (13.13). The
    walk returns them at its end (`fab logins return`) after its give-back
    has exported the account; one that cannot be returned stays lent with
    an `error` record, as a pair's (13.13);
  - its timeout is the kit's wall cap, 3 hours: `fab.calls.TIMEOUTS`, new,
    a timeout per role (`walk` 3 hours), `fab.calls.TIMEOUT` (60 minutes)
    for the rest.
- **Built in this order; what waits for red-routing** (section 11's code:
  `fab/tier_reds.py` and the page's red and fault signals are on main,
  21e391c; its wiring into the tick is being built, 11-01):
  - **Now, independent of red-routing's wiring:** the plan's `[[rung]]` and
    `[ladder]` (`fab/plan.py`); the findings' and rungs' fold
    (`fab/findings.py`); `fab qa`, `qa.lock` and the intake (`fab/walks.py`,
    `fab/cli.py`); the triage call, its role text, brief and decisions, and
    `report_only` (`fab/triage.py`, `fab/roles/triager.md`,
    `fab/calls.py`); the backlog's render and branch
    (`fab.triage.backlog_text`, `fab.spec_edit.commit_path`, the `ladder/`
    branch form and the import's owners); the tick's triage steps (the call
    started when due, its decisions recorded, the backlog readied,
    `rung.passed`) in `fab/dispatch.py`, rebased on red-routing's
    `_tick_plan` wiring if that lands first; the page's `finding` asks, `finding-<n>` signal and
    `## The ladder` (`fab/channel.py`); the landing report's QA figures
    (10). With these alone, findings enter, are triaged, the backlog lands,
    questions reach the page and rungs show their state; an on-path finding
    waits at its foreman, holding its rung.
  - **After red-routing's tick wiring lands** (`red_actions`, red tasks run
    from main and readied, `RED_RUNS`, the specless refusal foreman, the
    answer call seeing red tasks): `fab/fix.py` factored out of
    `fab/tier_reds.py`, then `fab/fixes.py` and
    `fab/roles/foreman-finding.md`, `finding_actions` and the
    `examine-fix`/`remedy-fix` pair in `fab/dispatch.py`: the repair path.
  - **Last, separable:** walks run by fab.

### 13.16 The user's questions on the forge

- **One issue per subject** (`fab/forge.py`): `fab issues sync` takes the
  log's open asks (`fab.channel.asks((), events)`, 13.6), calls and parked
  chains only. A plan's questions stay in plan.toml. One pass opens,
  converses, then closes, under `FAB_HOME/issues.lock`; a second pass while
  it runs exits 0 at once. The log is the only state. No webhook or router;
  one conversation call runs at a time.
- **The forge** is Forgejo on hel8: API
  `http://127.0.0.1:3000/api/v1`, links `https://git.fabrig.ai`, repository
  `fabrig-ai/agents`, label 1 (`waiting-on-user`). The bot's `write:issue`
  token is read from `~/.config/fab/forgejo.token` and sent as
  `Authorization: token ...`. Standard-library `urllib.request` only;
  requests have a 30-second timeout and refuse redirects. Neither token,
  response bodies nor exception text is printed or logged. A forge error
  stops the pass with exit 1 and one line naming the step, method and path;
  earlier records remain for the next pass.
- **Open:** an ask without `issue.opened` for its subject gets an issue;
  after `issue.closed`, only a later ask opens another. Log order, not
  timestamp precision, decides later. Both ask kinds for a subject share
  one issue, using the newest ask. Title: `<subject>: <first non-blank
  question line>`, cut to 200 characters. Body: the call report's
  `channel.excerpt`, or the parked reason and its report's excerpt, then
  `Read: <report path>` and the footer: "Answer in a comment. Ask for more
  context if you need it: the loop replies here. Your answer is recorded
  once the loop reads it as one." Apply label 1 and log `issue.opened`
  (subject, kind, number, url).
- **Converse:** read all comments of each issue opened and not closed,
  paginated, oldest id first. Only `free` is acted on, and only an id not
  already named by `issue.comment` for that issue. Log `issue.comment`
  (number, subject, comment id) before starting one `reply` call. Its brief
  holds the role text, Call facts, the ask's question, report excerpt and
  path, and the issue thread through this comment as
  `**<author>** (<time>): <body>` blocks. Later comments wait their turn;
  bot comments are context. An answer ends the conversation.
- **The reply** (`fab/roles/reply.md`, `fab.calls.ROLES`, effort medium)
  reads what the question and report point to: code, designs, FAB_HOME
  runs and calls. It changes no repository file and pushes nothing. It
  runs through `calls.start` in the agents clone, with subject
  `issues/<number>`, keeping the call's artifacts and usage (13.5).
  No plan owns that subject; the tick reserves no capacity for reply calls
  and neither reviews, collects nor lands them. Their `call.ended done`
  cannot close the asking subject (13.6).
- **The report's first line** is exactly `Done: reply` or `Done: answer`,
  then a blank line, then only the text to post or record. A request for
  context or a counter-question gets a short, plain reply, the options and
  a recommendation when helpful. A decision (an option, yes to the
  recommendation, the user's own choice) becomes a self-contained answer
  in one paragraph; wrapped lines become spaces.
  - Reply: post the text as a comment and log `issue.replied` (number,
    call).
  - Answer: `channel.answer(subject, text, events, by="user")` logs
    `call.answered` and wakes the tick exactly as `fab page answer` does;
    comment `Recorded as your answer: <text>`.
  - Anything else, or a failed call: comment "The loop could not read this
    comment; it will retry on your next comment." and log `issue.replied`
    with outcome `failed`. A consumed comment never runs again, including
    after a posting error; the user's next comment starts another call.
- **Close:** after conversations, reread the log. For each issue opened
  and not closed whose subject has no open ask, comment "Answered;
  closing.", PATCH its state to closed, then log `issue.closed` (number,
  subject). A `fab page answer` follows the same path. Completed mutations
  are logged before moving on; a crash between a forge mutation and its
  record can repeat that mutation on the next pass.
- Deployment (the token file, a transient timer on hel8 running
  `fab issues sync` every 2 minutes) is by hand.

## 14. Later

- (The self-critique is 13.1's, part `critique`, not later.)

- fabrig's api gate, the public API against the skeleton (rustdoc JSON);
  names, docs and clones over Rust (13.11 has the minimal gates).
- Gates on the calls' own branches (skeletons, reviews), which have no task
  `files` to check against.
- `fab report daily` on a timer on hel8, with the dispatcher's; reports
  posted to the director rather than read from FAB_HOME.
- Report metrics the records do not hold yet: lines changed per landed
  branch, questions by kind, continuity, CPU per step against its budget,
  after-landing verdicts by outcome, lag and coverage (its reds are counted,
  10); targets and their signals once the user sets them.
- The landing checks' next steps (13.8): a collateral red sent to the
  failing test's owner, not only signalled (fab knows a test's owner only
  as a red's suspects after landing, 11, which a collateral red at the gate
  does not have); receipts reused for batches of more than one, once
  numbers show how often a set's receipts all name its main; receipts on
  the gate pruned.
- after-landing live: its unit on a builder and its slot (done, 11-01), the
  old tool stopped, fabrig's package map moved to `.config/tiers/`. New
  reds reaching their tasks through the dispatcher are designed (11, 13.1),
  and the landing report's after-landing figures (10). Next, from their
  numbers: bisection when several branches are suspects (the red tests run
  at each suspect's merge in the lowest tier), if foremen name the wrong
  owner; a second repair round for an unfixed red instead of the page; the
  owner's spec gaining the red's section, if its history is wanted there;
  the session that readied a hand-pushed branch told of its rejection or
  red, once a ready records its pusher (`fab queue ready`, or a trailer);
  reds standing from before `reds` existed, which open nothing; Fix mode's
  gate waking Claude when a red's fix touches a public item (with the api
  gate, above). CPU accounting is present (11); the user sets the one total CPU budget
  from measurements after re-tiering lands. Default/fuzzy queue CPU now
  reuses the collector (6); making its report-only excesses red awaits the
  user's decision and budget figures.
- QA findings (13.15), next:
  - **Then it holds** (v0.1.0.md 3): a passed rung's story joins the live
    tier after-landing runs (`live-temper`'s stories, once the user says
    which run with `--run-ignored`, 11), and its fake twin goes into the
    worlds from the passing walk's transcripts (`qa-live.md`, 8): a task
    made from `rung.passed`, for Codex, kind feature, its body the walk's
    report and transcript paths. Waits for the first ladder fab runs.
  - Walks run by fab (13.15's last part), if the cut leaves it: the walk
    call, the `build` run, the `qa` host's `boxes`, logins borrowed per
    walk; and GitHub's managed rung, which needs a person's clicks in the
    manifest flow (the user, 11-01: a test account's web login on the shelf
    and a headless browser, deferred).
  - Findings of other finders, as temper's kinds: after-landing flakes
    (`flake`), reviews' follow-ups (`review`), QA after landing's passes
    (temper's `findings.md`, 8) once marks exist; and filed as forge issues
    once temper's findings are built and fab moves onto them.
  - A normalised key for merging, if the triage call's merges show walkers
    miss duplicates often; a second repair of an unfixed finding is today a
    new finding raised `again`, triaged as any.
  - A kit change that reopens only the rungs it touches (today every rung
    whose brief lists the kit gets a new edition).
  - Fix mode's gate waking Claude when a finding's fix touches a public
    item, with the api gate (as for reds, above).
  - The backlog taken up after v0.1.0 (v0.1.0.md 4): a cut of the backlog
    file into a plan of its own.
- Elastic builders from `fab hosts check`'s numbers.
- Logins (13.13), next: after-landing `--live` run on the
  queue's machine as well as builders (the user, 10-31); `tools/qa/logins`
  retired (QA's six logins are on the shelf since 11-01, held there by
  `fab/migrate`). Then a new builder lent its logins when it joins and
  returned when it goes, and swaps proposed from `login.checked`'s weekly
  percent.
- The tick's event and backstop units kept by fleet, as the queue's will be;
  lost-event notes counted in the code report; a wake retried before the
  backstop, if those notes show wakes are lost.
- The flow's target and each builder's calm in the code report, beside runs
  in flight per hour; the target shared across plans (13.4).
- The buffer's order across plans: each plan orders its own runnable tasks
  and plans start runs in their listed order (13.4), so one plan's
  consolidation can wait behind another plan's slice tasks.
- The foreman for plans whose specs live in another repository: its answers
  and repair sections landing through that repository's landing, not `fab land`.
- A repair run of this repository that starts without a foreman's section
  quoting `fab land`'s detail, as the foreman's brief does; it reads the
  detail as a queue log path today and quotes nothing.
- Retiring the session launcher, watch's session rules, mail, leases and the
  event collector once nothing resident remains.
- The cut started by the tick when a draft lands that no plan serves, once
  a draft can say where its plan goes.
- The designer's calls for repositories other than this one, and changes to
  designs outside `docs/design/fab*`, once calls land through tools/land or
  fabrig's queue.
- The user's page published where the user reads it without hel8 (the
  status page in 13.14, a doc), once the user says where; a notification when a
  question joins it.
- A plan's question answered by `fab page answer`, writing plan.toml and
  landing it as the foreman lands its answers.
- What the first live replay (codex-kit's run, 10-31: 76.1 min against
  54.75; `coord/fab-replay/report.md`) shows fab needs to match its run, the
  user to choose among:
  - a faster cut: start the ratchet and contract tasks while the cut writes
    the rest, or a smaller cut brief (the first implementer came at T+13.7,
    the lead's at T+4.8);
  - needs that do not funnel: the ratchet task in every task's needs held
    everything until T+22.6, and every stage task waited for one
    (codex-kit ran its first three side by side and eight stage tasks at
    T+11);
  - task files wide enough for mechanical fallout and the cut's
    pre-approved defaults for representation choices (three of seven
    questions were "outside my files");
  - merges off the tick's serial path (about 35 s each, the gates
    archiving two full trees), with collection never waiting behind them;
  - fabrig briefs without implementer.md's agents-repository test rules,
    and spec paths relative to the repository, not hel8's checkout;
  - the tick settling a refusal the gate caused by its own fault, which an
    operator did by hand in the replay.
- An integration plan's lighter checks (13.12): a workspace clippy of the
  trunk after each merge, the codex-kit run's lesson (two parallel branches
  meeting at clippy found only at the end check); once the replay matches
  the manual run.
- A plan `[[question]]` naming a direct part holds that part's tasks, not
  only its design: today a direct part's specs run while its question is
  open (the first dry cut of the component kit asked the user 6.1 and its
  task would have run anyway). cut-direct.md now tells the cut to decide
  what its sources settle and to make no task wait for a question.
- Claude implementer runs (`claude -p` in a slot, measured from its
  stream) for a replay of the Claude-only manual run (`coord/manual-kit/`).
- A cap on a call's context or turns, once the user sets one from the
  measurements (13.5); Claude and Codex usage against their plans' limits,
  once the limits are recorded somewhere fab can read.
