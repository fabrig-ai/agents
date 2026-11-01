# fab: after landing

2026-11-01, split from `docs/design/fab.md` (its section 6 maps the old
section numbers). Status: `docs/design/after-landing.status.md`. Shared: the
overview, the event log and the tests are `docs/design/fab.md`'s.

## 1. In one page

- **fabrig's slow tiers run on each new main** (`fab after-landing`), on their own machine and slot.
- **Their reds reach an owner:** a fab task's red goes to its foreman and a repair, a hand-pushed branch's to the user's page.

## 2. After landing

- **fabrig's slow tiers run on each new main,** ported from the agents
  repository's old `tools/after-landing` (its design at 7a7df4f) and
  fabrig's `tools/tiers/run`. `fab after-landing run --slot N` loops on one
  builder in one slot claimed for it (`fab slot claim N after-landing
  after-landing`); it refuses any other slot.
- **Its machine and slot are config:** the builder with the role
  `after-landing` in `fab/hosts.toml` names its `after_landing_slot`
  (hetzner8, slot 7). `fab after-landing install`, run by the deploy on
  every machine as `fab queue install` is (landing.md 2, `fab/units.py`),
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
  borrowed from the shelf (machines.md 3). `live-smith` awaits a signed-in live root.
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
  for default/fuzzy with report-only per-tree budgets (landing.md 2).
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
  queue sweeps its own (machines.md 2).
- **Left out from the old tool:** posts to coordinators and its resolver
  (the tick routes reds instead, below), bisection to a culprit commit,
  hourly coverage posts, the records writer and its detail files, heavy
  token cancellation, the guardian and replay of a half-run pair. Each
  attaches to the records above when numbers show it is needed (section 3).

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
  This is a rule of its own, not landing.md 3's: the queue import keeps out of
  `queue.*` every branch the log knows, loaded or not, while a red's
  suspect must belong to a loaded plan that can hold its repair, so a
  retired plan's branch is hand-pushed as a red's suspect.
- **A red with a fab suspect goes to a foreman** (calls.md 2, `fab/roles/
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
  n is the red's, so ids never collide across drafts or with integration.md 3's
  `<draft>/repair-<n>`.
  - Folded from the log (`fab.tier_reds.tasks(plan, events)`, joined to the
    plan's tasks as integration.md 3's repairs are, `fab.integration.with_repairs`
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
    questions fold into the body under `## Answers`, as integration.md 3's.
  - It runs as an implement run from `origin/main`, in a slot, whatever
    the plan's landing: everything integration.md 3 reads as the trunk is main for it.
    Done, it is readied for the queue like any fabrig task (`ready/<draft>/
    red-<n>`, `branch.ready`, its precheck receipt) and lands as `Merge
    <draft>/red-<n>`; an integration plan never merges it into its trunk,
    and its end check, checks along the way and repairs leave kind `red`
    out. After-landing runs only fabrig, so no red task lands through `fab
    land`. The queue import's tasks include every loaded plan's red tasks,
    so its `landed` and `rejected` become `branch.landed` and
    `branch.rejected`; a queue refusal goes to its refusal foreman as any
    task's (calls.md 2, specless).
  - **Two runs, then Claude:** its run limit is `RED_RUNS` (2), not
    `MAX_RUNS`: Fix mode wakes Claude after two failed tries
    (`execution-modes.md`). A park at the limit queues for the answerer as
    any park does, its thresholds applying; a question of its runs skips
    the foreman (no spec, no options) and queues, as a specless repair's
    does (integration.md 3). Answer calls list red tasks and their questions in both
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
  of the red's signal (channel.md 2) closes them all. A red closes on its last
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
    later (3).
- **Reds no task owns are signals, on the user's page** (channel.md 2): a red
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
  the owner among them (its report's `Owner:` line, calls.md 2), for the record
  and the report; one repair task, in the newest fab suspect's plan, fixes
  the group whoever the owner. Bisection to a culprit (the red tests run at
  each suspect's merge) stays left out: the foreman reads the suspects'
  diffs on main, and numbers will say whether it guesses wrong.
- **The after-landing machine wakes the tick** (tick.md 6): at the end of a run
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
  run=<foreman run>)`, which settles it (calls.md 2); renamed `examine-fix` and
  `remedy-fix` when `fab/fix.py` is factored out (qa.md 2). A closed red takes no
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
  - With no loaded plan the round still closes and opens reds (tick.md 5).
- **A fabrig plan retires after its verdict:** its retire call starts only
  once a `tiers.run` names its last branch to land on main among its
  `branches` (the trunk for an integration plan, its last task's for a
  queue plan) and none of its reds (`draft` the plan's) is in state
  foreman, deciding, decided, repairing or landed; a red that is a signal
  does not hold it. Otherwise an integration plan, retired as soon as its trunk
  lands (integration.md 3), would be unloaded before its reds arrive and every one
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

## 3. Later

- after-landing live: its unit on a builder and its slot (done, 11-01), the
  old tool stopped, fabrig's package map moved to `.config/tiers/`. New
  reds reaching their tasks through the dispatcher are designed (2, calls.md 2),
  and the landing report's after-landing figures (reports.md 2). Next, from their
  numbers: bisection when several branches are suspects (the red tests run
  at each suspect's merge in the lowest tier), if foremen name the wrong
  owner; a second repair round for an unfixed red instead of the page; the
  owner's spec gaining the red's section, if its history is wanted there;
  the session that readied a hand-pushed branch told of its rejection or
  red, once a ready records its pusher (`fab queue ready`, or a trailer);
  reds standing from before `reds` existed, which open nothing; Fix mode's
  gate waking Claude when a red's fix touches a public item (with the api
  gate, above). CPU accounting is present (2); the user sets the one total CPU budget
  from measurements after re-tiering lands. Default/fuzzy queue CPU now
  reuses the collector (landing.md 2); making its report-only excesses red awaits the
  user's decision and budget figures.
