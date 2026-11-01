# fab: plans, runs and the tick

2026-11-01, split from `docs/design/fab.md` (its section 6 maps the old
section numbers). Status: `docs/design/tick.status.md`. Shared: the
overview, the event log and the tests are `docs/design/fab.md`'s.

## 1. In one page

- **Plans and tasks are files in git;** the tick (`fab tick`) reads them and the event log and decides every action: collect, land, start, park.
- **Runs are Codex units on builders** (`fab run`), started from a plan's trunk and collected by the tick.
- **The flow grows** from a small target with each first-attempt landing and halves on rejections; several plans share the builders' places.
- **Events wake the tick;** a backstop timer covers lost wakes. The user's example timeline sets the order of things.

## 2. Plans and tasks

- **The plan** (`plan.toml`) is the thin cut: `draft`, `repo` (the tasks'
  default repository), `sources` (the drafts it serves), and `[buffer]` `low`
  and `high` (the ready-task band as multiples of implementer places). Each
  `[[part]]` has `id`, `title`, `mode` (feature, migration, fix or probe),
  `needs` (other parts), `design` (where its design is) and `contract` (a
  shared contract, designed by the designer's contract call, calls.md 3; default
  false). Each `[[slice]]` has `id`, `story`, `parts` and `walk` (whether QA
  walks it). Each `[[question]]` is one of the user's, from the cut: `id`,
  `text`, `parts` (designed only once it is answered) and `answer`, written
  into plan.toml when the user gives it. `retired = true` ends the plan. No
  part is called `cut`, `retire`, `review` or `triage`: those name calls'
  subjects. A ladder plan names `[ladder]` and its `[[rung]]`s instead of
  parts (qa.md 2).
- **A task spec** is Markdown with a TOML header between `+++` lines: `id`,
  `part`, `kind` (feature, interface, migration, repair, rebase or docs),
  `repo`, `needs` (tasks that land first), `files` (globs it may change),
  `effort` (medium or high) and `minutes` (the expected implementer time,
  as 4 sizes them: one module or concept, about 400-500 production lines,
  30-60 minutes; in this repository, with its fast tests, tasks may come out
  smaller, which does not carry over to fabrig) and `consolidation` (true
  for a structure review's task, 7; default false). The body says what
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
  against the flow's current target for runs in flight (4), not against
  the builders' nominal places.

## 3. Runs

- **A run is one Codex execution** on a builder, in a slot (fabrig) or a
  worktree (repositories that build nothing heavy). `fab run start` prepares
  the checkout at the task's base, writes the brief, and starts
  `codex-run task` there. A rerun continues from the work its earlier run
  pushed: an implement rerun starts from `origin/<branch>` when it exists,
  in a slot or a worktree, and merges the base in (a conflict is left for
  the run). Fixed 11-01, found by the findings loop: a worktree rerun
  started from the base and dropped it.
- **Builders follow the dispatcher:** before any builder command, `fab run
  start` reads the running fab package's checkout `HEAD` and, over one ssh
  under `flock -w 60 FAB_HOME/install.lock`, checks for
  `FAB_HOME/install.pinned` before fetching origin in `FAB_HOME/install`.
  If the pin exists, sync does nothing and notes `install pinned` on stderr;
  a person or replay setup owns creating and removing the pin. Otherwise,
  an install already at that commit stays; an ancestor moves to it with
  `git checkout -q --detach`; an ahead or diverged install
  stays. This moves only forward, so a dispatcher pinned for a replay never
  downgrades a builder. Any sync failure is a one-line note on stderr and
  never fails the start. A host with the `dispatcher` role is skipped: its
  tick already moves its install. Run worktrees, slots, PATH links and
  units are untouched; long-running services still need `bin/install.sh`
  to move and restart them (docs/design/machines.md, 2).
- **The brief is compiled, not gathered:** the role text
  (`fab/roles/implementer.md`), the task spec, and the paths it cites. Codex
  reads what the brief names in the checkout itself.
- **The report's first line is its outcome:** `Done: <summary>`,
  `Question: <question>` (then the options and a recommendation),
  `Infra: <cause>` (disk, a machine or a tool, not the task's fault) or
  `Failed: <why>`. `fab run status` reads it; the dispatcher requeues an
  `Infra:` run without asking anyone. The rerun (kind `repair`) continues
  from the branch the run pushed, or starts from the task's base when the
  run pushed nothing (fixed 11-01: it started from `origin/<branch>` only,
  which a run that never pushed lacks, so its start failed every tick).
- **Done means checked:** the branch is pushed and its checks passed inside
  the run (this repository: `bin/fab test`; fabrig: precheck and the merged
  readers' tests, `agents/implementer.md` in fabrig).

## 4. The flow grows

- **Places are indicative.** A builder's `places` in `fab/hosts.toml` is a
  hint, not a cap: the dispatcher's own target for runs in flight starts at
  the plan's places (integration.md 2), grows by one with each task landed on its first
  attempt, and halves with each rejection or infra outcome as in integration.md 2, never below
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

## 5. Several plans, calls in parallel

- **The tick takes every plan** listed in `FAB_HOME/plans` (one checkout path
  per line), then those named (`fab tick [PLAN_DIR...]`), each its own
  draft, in that order, under the tick's one lock (`fab/drafts.py`; the
  list is `fab.channel.plan_dirs`'). One fetch per checkout, one import of
  the queue's record over every plan's tasks, and one measure of the
  builders (4) serve them all. The import reads from the oldest of the
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
  calls; a ladder plan's walks and findings too (qa.md 2). A plan collects only its own runs, and its call limits (one answer,
  review or amend call at a time) count only its own calls. Runs no ticked
  plan owns are collected after every plan has ticked.
- **A plan that cannot load** (its plan.toml, a fetch, a second plan of the
  same draft) is printed and skipped; the others tick. It logs nothing,
  and `fab tick` exits 1. A retired plan is skipped, but its draft still
  owns its branches for the queue's import (landing.md 3), so the record
  of the landing that retired it, a queue plan's or an integration plan's
  retire through fabrig's queue, is imported (`branch.landed`, then the
  finish's `call.finished`) and nothing else runs for it (fixed 11-01, the
  probe `phase-case`: its retire landed on fabrig main at fc1651448b, and
  the log never said so).
- **A tick with no loaded plan** (none listed or named, or none that
  loads) imports the queue's unowned records (landing.md 3) and the after-landing
  records (after-landing.md 2), closes reds, and, when no listed plan failed to
  load, opens new reds against an empty owner map, so each is a page
  signal; then it rewrites the page and starts nothing: no measurement of
  the builders, no decisions, no foremen and no strays collected. On 11-01
  hel8 had no plan listed and its log held no `tiers.run` at all: the night
  of 10-31's situation, every suspect hand-pushed, which only the page can
  hear. Failed loads are still printed and still make `fab tick` exit 1.
- **Design calls run in parallel** for independent parts. A plan's
  skeleton and contract calls in flight number at most its flow target
  (4): two at its start, growing as the target does. The eligible parts
  are independent, since a part waits for its needs' design. They are
  started in plan order, each in its own role. A call's user unit is named
  by its role and subject (`fab-call-<role>-<subject>`), so one subject
  never has two calls running, even before the log shows the first. It
  carries the tick's `FAB_HOME` (`systemd-run --setenv`), so a tick with
  another home (a replay's) starts calls that write to it (fixed 11-01,
  found by the findings loop: calls wrote to the default home).

## 6. Events drive the tick

At the user's word (10-30): the loop reacts to what happens, and polling is
only the backstop.

- **An event wakes the tick** (`fab/wake.py`). Whatever ends work the
  dispatcher waits for appends a reason to the want file,
  `FAB_HOME/tick.want` on hel8, beside the log: a Codex run's unit when it
  stops (its ExecStopPost runs `fab wake codex <id>`, over ssh from the
  builder), a Claude call when it logs `call.ended`, the queue at the end of
  a cycle that recorded `landed` or `rejected` (one wake per cycle), the
  after-landing machine at the end of a run that recorded a red new or
  unattributed or a recovery (one wake per run, after-landing.md 2), `fab land`
  when it lands or refuses, the user's answer or clear (`fab page
  answer`, `fab page clear`), and a walk's result (`fab qa result`, qa.md 2).
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
  it; `finding.settled`, which makes a finding's repair task, qa.md 2;
  `finding.triaged` and `rung.passed` need none, being logged before the
  same round's decisions), the tick wakes itself at its end (`tick <n>: <kinds>`). Five such ticks in a
  row with no outside wake between them stop the chain with a note: a chain
  that long is a fault, and the next tick waits for an event or the
  backstop.

## 7. The timeline's flow

The user's example timeline (`execution-modes.md`, "Example") is the order of
things fab follows, whatever the clock says:

- **Intake:** the user starts a draft by hand (at the user's word of
  10-31): today with its cut, `fab call cut --plan PLAN_DIR --source PATH
  ...` (calls.md 3), which lists the plan in `FAB_HOME/plans`; before it,
  `fab plan inputs` for inputs not in the tree; for a fabrig integration
  plan, `fab trunk make` first and `fab plan inputs` on the directory it
  prints (integration.md 3). A draft
  landing in `docs/design/draft/` starts nothing by itself; the timeline's
  T+0:00 is the user's start. `fab draft start PATH`, which would run the
  draft's surveys and then its cut, is not built (8).
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
  - a consolidation is a spec marked `consolidation = true` (section 2), a
    group of its own whatever else holds of it;
  - a repair or rebase is a task whose next run carries a refusal (a
    `branch.rejected` since its last run); a rerun after an `Infra:`
    outcome is not, and keeps its part's place;
  - a red task (`<draft>/red-<n>`, kind `red`, after-landing.md 2) sorts into the
    repair group too, ahead of the plan's slice tasks, behind
    consolidations: a red reaches its owner at once;
  - within each group, tasks go by the first slice that holds their part,
    then their part's place in the plan, then their specs' order.
- **Then, as written:** contracts land alone and their readers are pulled;
  probes run beside and their decisions land before their readers' skeletons;
  answers come in batches, at once when they hold up work; slices complete
  on their story tests; QA walks the walkable slices (once QA is here); the
  last call retires the draft. Each is a part above or in section 8.

## 8. Later

- `fab draft start PATH`: the draft's surveys, then its cut (7).
- The tick's event and backstop units kept by fleet, as the queue's will be;
  lost-event notes counted in the code report; a wake retried before the
  backstop, if those notes show wakes are lost.
- The flow's target and each builder's calm in the code report, beside runs
  in flight per hour; the target shared across plans (5).
- The buffer's order across plans: each plan orders its own runnable tasks
  and plans start runs in their listed order (5), so one plan's
  consolidation can wait behind another plan's slice tasks.
- Claude implementer runs (`claude -p` in a slot, measured from its
  stream) for a replay of the Claude-only manual run (`coord/manual-kit/`).
