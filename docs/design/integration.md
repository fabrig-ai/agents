# fab: plans on fabrig and integration trunks

2026-11-01, split from `docs/design/fab.md` (its section 6 maps the old
section numbers). Status: `docs/design/integration.status.md`. Shared: the
overview, the event log and the tests are `docs/design/fab.md`'s.

## 1. In one page

- **A fabrig plan** lives in fabrig, is gated minimally and starts wide.
- **An integration plan** merges its tasks into one trunk (`<draft>/integration`), checks it along the way and at the end, catches it up with main, and readies it for the queue.
- **Drafts beside each other** see each other's overlaps, report only.

## 2. The entry path to fabrig

At the user's word (10-31): before the fabrig run (skein's component kit,
phase 1), fab runs a plan that lives in fabrig, gates its Rust branches
minimally, starts wide and early, and measures where the time and the
weight go. The api gate (rustdoc JSON) is out of scope.

- **A fabrig plan** is a plan directory inside a fabrig checkout, at any
  depth (`skein/docs/plan/<draft>`), with `repo = "fabrig"`, listed in
  `FAB_HOME/plans` (tick.md 5). Its checkout on hel8 is the dispatcher's fabrig
  clone, `FAB_HOME/repos/fabrig`; the tick fetches it once, as any checkout.
  Its tasks build in slots and are readied to fabrig's queue (landing.md 2).
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
  `findings`, as gates.md 2, and the foreman's repair path takes it.
- **The Rust digest** (`fab/rust_digest.py`, `FAB_HOME/digests/<run>.md`):
  public items added and removed (`pub fn|struct|enum|trait|type|const|mod`
  by grep over changed `.rs` files, base against tip), changed lines split
  into production, tests (`tests/`, `#[cfg(test)]` modules, `*_tests.rs`)
  and docs (`.md`), functions over 60 lines added or grown, paths outside
  the task's files and the ratchet's deltas per tree. Deterministic Markdown
  of at most 8,000 characters, as gates.md 2's.
- **Optimistic start:** a part's tasks start once its skeleton call has
  ended done and its tip passes the checks (agents: `bin/fab test` and the
  gates; fabrig: `fab precheck` and the Rust gates), with the Codex review
  running alongside. The tasks are read from the call's branch tip, their
  branches start from it, and they hold landing (or readying) until the
  skeleton has landed. A refusal becomes an amend call as now; when the
  amended skeleton lands, each started task's branch is rebased onto the
  plan's trunk (main, or an integration plan's `<draft>/integration`) by a
  rebase run before it lands; a rebase run that ended done from
  `origin/<trunk>` consumes the amendment (fixed 11-01: only a base of
  `origin/main` did, so an integration plan's rebase repeated forever).
  A chain that parks parks its tasks.
- **Start wide:** the flow target (tick.md 4) starts at the plan's places (the
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

## 3. The flow of a real run

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
    landed or readied, as in landing.md 2);
  - `ready` (default true): an integration plan readies its checked
    branch for the queue once; false leaves it unlanded (an experiment, as
    the replay of codex-kit);
  - `reviews` (default false): true sends every call's chain to a review
    run (calls.md 2) and starts structure review calls (gates.md 2). The code gates
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
- **The plan lives on its trunk.** The integration branch is made at the
  run's base with a worktree of hel8's fabrig clone on it, tracking it
  (`FAB_HOME/integration/<draft>`), and the plan directory inside that
  worktree is listed (the cut lists it). Its first commit holds the run's
  inputs that are not in the tree (below). Two commands do it (the user,
  11-01; until then an operator did it by hand, every replay and the
  first `ready` probe):
  Both are the operator's commands on hel8, never an implementer's.
  - `fab trunk make PLAN_PATH [--base REV]`: PLAN_PATH is the plan's path
    in fabrig (`temper/docs/plan/<draft>`, the draft its last segment).
    After a `fetch --prune` of `FAB_HOME/repos/fabrig` it refuses,
    changing nothing: when PLAN_PATH is not a relative
    `<prefix>docs/plan/<draft>` (the cut's own check); when REV holds
    `PLAN_PATH/plan.toml`; when `<draft>/integration` exists on origin or
    as a local branch of the clone; when the worktree path exists. It
    first adds the worktree, `git worktree add -b <draft>/integration
    FAB_HOME/integration/<draft> <REV>` (REV defaults to `origin/main`),
    then pushes from it, `git push -u
    --force-with-lease=refs/heads/<draft>/integration: origin
    <draft>/integration` (the empty lease creates the branch only if
    absent; `-u` sets the upstream). A push that fails, refused or not,
    removes the worktree and the local branch. Only after both succeed it logs `trunk.made`
    (draft, base the REV given, tip its sha) and prints the plan
    directory to give `fab plan inputs` and `fab call cut --plan`.
  - `fab plan inputs PLAN_DIR FILE...  [--replace]` (any plan): FILE is a
    file or a directory (copied whole, as the manual recipe's `reviews/`).
    It never commits in the plan's checkout. After a fetch it adds a
    temporary worktree of the checkout's repository, detached at
    `origin/<trunk>` (`<trunk>` being `<draft>/integration` for a checkout
    tracking `origin/<draft>/integration`, else main), copies the files to `PLAN_DIR/inputs/<name>` there,
    commits them (`<draft>: inputs`, author fab) and pushes; the worktree
    is removed in every outcome, so a refusal or a failure leaves no
    commit, file or local branch. The push depends on the checkout: one
    tracking `origin/<draft>/integration` pushes
    `HEAD:refs/heads/<draft>/integration`, fast-forward only; this
    repository pushes `inputs/<draft>` and runs `fab land inputs/<draft>`
    (a refusal deletes `inputs/<draft>` from origin and exits 1 with fab
    land's step); fabrig otherwise pushes `ready/inputs/<draft>`, which
    the queue takes as any two-segment ready ref and the dispatcher
    imports as an unowned `queue.*` record (a rejection shows on the page
    as `queue:inputs/<draft>`), and it prints that the cut waits for its
    `queue.landed` and for the plan's checkout to hold the files. After a
    trunk push or a landing it fast-forwards the plan's checkout to its
    upstream under `FAB_HOME/tick.lock`, so the cut finds the files
    (`designer._prepare` requires each `--source` to be a file under the
    checkout); a detached checkout, which the tick does not follow, is
    left for the operator to move. It refuses, changing nothing: when
    PLAN_DIR holds plan.toml or is listed in `FAB_HOME/plans` (the inputs
    are the cut's); when a FILE does not exist, or two FILEs share a name;
    when `inputs/<name>` exists at `origin/<trunk>` (unless `--replace`),
    or exists untracked or changed in the checkout (that would break the
    fast-forward); when the branch or ready ref it would push already
    exists on origin (after a queue rejection the operator deletes
    `ready/inputs/<draft>`, or `--replace` replaces the command's own ready
    ref); for a draft named `inputs`; for a checkout tracking any other
    branch (an agents checkout must track `origin/main`; a fabrig one
    `origin/main`, `origin/<draft>/integration`, or be detached). It prints the repository
    paths to give `fab call cut --source`.
  The tick follows a
  plan checkout that tracks a branch: after its fetch it fast-forwards the
  checkout to its upstream, so it always reads the plan and specs at the
  trunk's tip, until the trunk has landed (then it detaches the checkout at
  `origin/main`, 3).
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
  `findings`, so a rebase run follows (calls.md 2's refusal foreman first). Calls'
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
  an `Infra:` outcome and no growth (2's start-wide rule is the queue
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
    that stop a plan. A refusal at a newer main is a new repair.
  - **A catch-up repair is checked when it merges.** Right after the tick
    merges `<draft>/catch-up-<n>` into the trunk, it checks that the trunk
    contains that repair's main sha. If it does, it logs the clean catch-up:
    `branch.landed` for task `<draft>/integration`, branch `main`, tip the
    sha, `main` the trunk's tip, `by` `repair`. If not, the repair did not
    bring main in: it logs a catch-up refusal at that same sha (findings
    saying so), and a catch-up refusal at a sha whose repair has merged
    stops the plan for judgement. As a backstop, the plan also stops at the
    `CATCH_LIMIT`th (3) catch-up refusal since its last clean catch-up (any
    `branch.landed` for task `<draft>/integration`, branch `main`: the
    tick's own merge, a checked repair's, or a hand one), so a run of
    repairs that work never stops it (a conflict outside the old-form
    baselines, such as `Cargo.lock` when two drafts add crates, may come on
    many moves of main). A stop holds until a clean catch-up is
    logged after it or the answerer lifts it (below). For the first, the
    person resolving it merges main, at least the stopping refusal's sha,
    into the trunk and pushes it, and the next tick,
    finding the trunk containing that sha while the stop holds, logs that
    `branch.landed` (tip the sha, `main` the trunk's tip, `by` `hand`),
    which clears the stop; main may have moved again meanwhile, and the
    next catch-up takes that as usual.
  - **A queue rejection is checked again:** the trunk is caught up and
    checked once more, then readied again (the queue asked to forget its
    tried tip when the tip is unchanged). A red check goes to repairs as
    any red; the third rejection by the queue stops the plan for judgement.
  - Red: a repair task `<draft>/repair-<n>` (folded from the log, never a
    spec file; files `**`, its body the check's failing steps and report)
    runs as an implement run from the trunk's tip, is merged like any task,
    and the trunk is checked again. A third red parks the plan with a
    question.
  - **A stop asks** (fixed 11-01: it was a log note only, found by
    dogfood/design). A plan stops at the third red end check, at a
    catch-up refusal that stops it (above), or at the third queue
    rejection. The tick then logs `plan.stopped` (task
    `<draft>/integration`, `tip`, `why` one of `red`, `catch-up`, `queue`,
    `text` the stop's reason, `report` what to read: the last red check's
    `FAB_HOME/runs/<run>/report.md`; the queue rejection's `<gate
    host>:<log>`, the host being the first with role gate, as the import
    reads; "" for a catch-up, whose findings the text quotes, at most 20
    lines), and with it the stop's question: `question.asked` for task
    `<draft>/integration`, `run` the last red check's run for `red` and ""
    otherwise, `park` true, its text the record's. It logs
    them when the trunk stops and none has been logged since the stop's
    last lift; merges while it holds log none. While it holds, the trunk
    takes no further step (no catch-up, check or ready; of the plan's tasks
    only repairs of after-landing reds and QA findings start; runs in
    flight end and merge as usual).
  - **The answerer judges a stop,** as it does a repair's question
    (execution-modes.md: judgement comes in batches, from an answer call):
    `fab.foreman.questions` takes a `question.asked` whose task is
    `<draft>/integration` for a draft of the given tasks, queued at once,
    without a task for it (none is added to the plan's tasks, so nothing
    folds it); the answer brief shows it as `Question: <draft>/integration
    (stop)`, its text and `- Report:` the `plan.stopped`'s report, with no
    task spec; an integration plan answers it at once. Its id on the
    report's `Answered:` line, with `Answer <draft>/integration: <text>`
    giving the answer, is logged as that question's `question.answered`
    (`_finish`), as a repair's is, and lifts the stop; an answer call that
    cannot settle it ends `Question:`, which reaches the page as any call's
    (channel.md 2). After a lift the stop's counts start afresh (end reds,
    catch-up refusals since a clean catch-up, queue rejections; a main sha's
    catch-up repair counts as merged only when it merged after the answer),
    so the next red, refusal or rejection is a first; repair ids keep their
    numbering (`repair-<n>`, `catch-up-<n>` count on from before the
    answer). The answer is folded under Answers into every repair not merged
    when it was logged (the stopping red's own repair among them) and every
    later one, as a repair's own answers are. A clean catch-up after a
    `catch-up` stop lifts it too: the tick then logs the stop's
    `question.answered` (answer `lifted by a clean catch-up`, `by` `tick`),
    so it leaves the answerer's queue; the tick's own lift is folded into no
    repair. A later stop logs a new `plan.stopped` and question.
  - A check run counts as the draft's run in flight and takes a place.
  - A repair has no spec file, so its question skips the foreman (no
    options to settle by) and queues, and an answer logged with `answer`
    is folded into the repair's body under Answers, which its next run
    reads (the playground replay, 11-01: a repair's question crashed the
    foreman on its empty spec path, every tick). The answer call's brief
    lists the repairs' questions too (`fab.integration.with_repairs`), and
    it records a repair's answer as a report line `Answer <task>: <text>`,
    which the tick logs as that question's `answer`.
- **The cut's inputs.** `fab call cut --set KEY=VALUE ...` passes plan
  options that differ from the defaults (`ready=false` for a replay). Code
  writes them, not the cut (the user, 11-01). `fab.calls.start` takes a
  `seed` (repository path to text), written and committed (author fab,
  `<draft>: plan options`) after its `worktree add` and before
  `call.started`. Every cut is seeded, with or without `--set`: a
  plan.toml holding `draft`, `repo` and `sources` (from `designer.uncut`),
  then, only when options are given, under a comment `# Plan options,
  written by fab call cut --set; keep them`, each option as `<key> =
  <json.dumps(value)>`. The brief's `The draft` section says, replacing
  ``- Plan: write ...``:

  ```text
  - Plan: `<path>/plan.toml` exists on your branch with `draft`, `repo`,
    `sources` (and fab's plan options); add `[buffer]` and the tables
    below those lines, never repeating or changing them
  ```

  `fab/roles/cut.md` drops its `draft`, `repo`, `sources` bullet (keeping
  `[buffer]`), `fab/roles/cut-fabrig.md` drops ``set `repo = "fabrig"` ``,
  and `fab/roles/cut-run.md`'s "What you write" first bullet becomes
  "`plan.toml` exists on your branch with `draft`, `repo`, `sources` and
  fab's plan options; add below them:", its template dropping its
  `draft`/`repo`/`sources` lines and `# the plan options, verbatim`. The
  tick restores them where code may write: for an integration plan, every
  merge of the cut's branch (`_merge_branch`, its early releases and its
  last merge) restores the options in the trunk, never on the cut's branch:
  after a clean merge and before the push, the tick rewrites plan.toml's
  option lines from the root cut's `call.started` `options` (parsed with
  `parse_options`) and commits `<draft>: plan options restored` on the
  trunk; for a queue plan, the restore is a commit on the cut's branch
  before `_deliver`, the call having ended by then, with retire's guards and
  open finish (calls.md 3), worktree `FAB_HOME/options/<root>` (a missing
  plan.toml makes no restore and raises nothing; only retire's edit raises).
  Code never writes a branch while a call on it is in flight. Options
  compare by parsed value (a different spelling of the same value makes no
  commit); a restore removes every top-level line assigning one of the keys
  and writes them under the comment, putting the comment back before the
  first table line when the cut removed it; a branch with no plan.toml gets
  none. Its `call.started` carries them (`options`), so the tick reads
  `landing` and `reviews` for the cut's own chain before plan.toml exists.
  For a replay the operator gives the cut the manual run's inputs as
  `--source`: the draft (`skein/docs/design/draft/component-kit.md`),
  fabrig's `AGENTS.md` and `agents/lead.md`, `implementer.md`,
  `operations.md` at the base, and, committed under the plan directory's
  `inputs/`, the kickoff, the review and the manual run's brief, with a
  README saying the brief's How, Machines and Measure are fab's in this run.
  With `direct = true` the cut writes every task spec itself and puts notes
  several tasks share in the plan's `notes/`, cited from each spec (the
  lead's `common.md`, `stage-common.md`, `lib-common.md`); implementers read
  them in their checkout.
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
    designers in flight; the call's timeout is now 60 minutes, reports.md 3). It is one call throughout: it never waits for, watches or
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
  - The `files` gate is gone (gates.md 2 and section 2): a spec's `files`
    say what a task owns, for the cut and the implementer, and nothing
    refuses a branch for a path outside them.
  - An integration plan answers a queued question at once (an answer call
    as soon as the foreman cannot settle it), as the lead did in two
    minutes, not at 4 queued or after 30 minutes.
- **Retire waits for main.** An integration plan's parts are done when
  their tasks have merged, but its retire call starts only once the trunk
  has landed on main (`branch.landed` for task `<draft>/integration` from
  the queue's record), and after its verdict after landing (after-landing.md 2).
  It then works from main, not the trunk: the call starts from
  `origin/main` and its branch is delivered as a queue plan's call is
  (fabrig's queue: `ready/calls/<id>`, `call.finished` when the queue's
  record says it landed), never merged into the landed trunk; so is any
  other call of the plan delivered after its trunk landed. Once the trunk
  has landed (`fab.integration.trunk_landed`), the tick reads the plan from
  main: each fetch of the plan checkout moves it, detached, to
  `origin/main` (which holds the trunk's tip; the queue deleted the
  trunk), so the retire's
  `retired = true` ends the plan once the queue lands it. Fixed 11-01
  (found by dogfood/design): the tick merged the retire into the trunk, so
  the plan's status files and `retired = true` never reached main.
- **Departures from the user's drafts, at the user's word** (10-31;
  `execution-modes.md`): no surveys (not built), no skeletons or test
  vocabulary (every part direct), no Codex review of the cut, no structure
  review, and the code reaches main as one integration branch through one
  check instead of each task through the merge queue. The self-critique
  and test-writers are not built yet either. Each may come back as an
  option once a replay matches its run.

## 4. Drafts beside each other

At the user's word (11-01), after the catch-ups of 3. Several drafts run
at once, each on its own trunk, and nothing told one draft what another was
changing: on 10-31 each conflict between them surfaced only when the second
merged with main (3's numbers). fab keeps no leases (a spec's `files`
say what a task owns, and refuse nothing); it gives each draft a cheap,
early view of the others instead, in two pieces, neither of which builds
anything.

- **The overlap probe** (`fab/overlaps.py`). Once per tick, after every
  plan has ticked (`_round` in `fab/dispatch.py`), fab probes the loaded
  plans that are integration plans with `ready`, not retired, whose trunk
  is on origin and has not landed on main (no `branch.landed` for task
  `<draft>/integration` carrying `queue_ts`, as `fab.integration.queue_step`
  reads it). A replay (`ready` false) sits on an old base and is never
  probed. Pairs are formed within one `plan.repo`; every git command for a
  repository runs in the checkout of its first candidate plan in draft-name
  order (chosen before its trunk is resolved on origin), which the tick has
  fetched; the checkout is part of the cache's key, so cached tree ids always
  live in the object store they are used from.
  - **Each trunk as if caught up.** A trunk can lag main (3's catch-ups
    wait), and a trunk behind main would show main's changes it lacks as
    overlaps with every trunk ahead of it. So for each probed trunk fab
    first runs `git merge-tree --write-tree --no-messages origin/main
    origin/<trunk>`: exit 0 gives the trunk's tree with main merged in.
    Exit 1 with a tree id first means the trunk has a catch-up conflict of
    its own (3 repairs it): its pairs are skipped this tick. Any other
    result is a failure, as for a pair below: its pairs are skipped, and the
    note is logged only when it differs from that trunk's last one.
  - **Each pair:** `git merge-tree --write-tree --name-only --no-messages -z
    --merge-base=origin/main <tree a> <tree b>`. Exit 0 is no overlap. Exit
    1 is an overlap only when stdout's first NUL-separated field is a hex
    object id; the conflicting paths follow it (`-z`, so paths are never
    quoted). Any other result (exit 1 with no tree id, as for a missing
    ref, exit 128, an unreadable output) is a failure: printed in the
    tick's output, and logged as a `note` only when it differs from that
    pair's last failure note.
  - **Cost:** about 0.6 s per merge-tree on fabrig (measured 11-01), so n
    drafts cost n + n(n-1)/2 of them under the tick's lock (five drafts:
    15, ~9 s). To keep that off ticks where nothing moved, results are
    cached in `FAB_HOME/overlaps.json`, keyed by main's sha and the trunk
    tips; a pair or trunk whose key is unchanged is answered from the cache.
    It holds results, never failures: trunks' trees, pairs' `files` and
    `more`, and, in a third object `conflicts` (key to `true`), trunks whose
    catch-up conflicts, so such a trunk is not merged again every tick while
    nothing moved. A file without `conflicts` (the first format) still reads
    as valid. A cached tree is dropped when a pair that used it fails, and is
    not kept even though it was looked up. Each probe keeps only the entries
    it looked up or stored, so the file holds this tick's keys and never
    grows with old mains and tips, and it is written (with
    `fab.atomic.write`) only when it changed. Losing the file loses only
    time.
  - **The event:** `trunks.overlap` with `drafts` (the two drafts in name
    order), `tips` (their trunk tips, in that order), `files` (the
    conflicting paths in merge-tree's order, at most 40), `more` (how many
    were left out) and `reason` (`probe`, or `gone` below). It is logged
    only when a pair's (`files`, `more`) differ from its last
    `trunks.overlap`; a pair with none counts as empty, so a clean first
    probe logs nothing, and an empty `files` after a non-empty one says the
    overlap cleared.
  - **Closing pairs that leave:** in a tick where every listed plan loaded
    (tick.md 5's rule), a pair whose last `trunks.overlap` has files and that
    is not among this tick's pairs (a trunk landed, a plan retired or
    unlisted, `ready` turned off) gets a closing `trunks.overlap` with empty
    `files` and `reason` `gone`. This tick's pairs are those formed from the
    probed plans, whether run, answered from the cache, or skipped for a
    catch-up conflict or a failure.
  - The pure part (`fab/overlaps.py`): the plans to probe from the loaded
    plans and the log, the pairs, the parse of merge-tree's output, whether
    a result is news, and the pairs gone. The shell is one function the
    tick calls with its runner.
  - **A malformed record is ignored, never fatal.** The fold over
    `trunks.overlap` (for news, for pairs gone, and for the status page)
    takes only records whose `drafts` and `tips` are lists of two strings,
    `files` a list of strings and `more` a non-negative integer; others
    (hand-written, or a later format) are skipped, so one bad line can
    neither abort a tick nor break the public page. fab always writes
    complete records.
- **What it is for, for now: report only.** Nothing waits on an overlap
  and nothing is started by one: the trunk that lands second still meets
  the conflict at its catch-up and repairs it there (3). The status
  page (reports.md 4) shows each pair whose last `trunks.overlap` has files, in a
  panel after Drafts, from the snapshot key `overlaps` (a list of
  `{drafts, count}`, `count` being `len(files) + more`): the two drafts by
  their public labels (a draft not known from run starts shows as `other`,
  as reports.md 4's labels do) and that count, never a path (reports.md 4: the page is
  public, the repository private). Whether an overlap should also reorder
  work, or start an early repair, waits for the numbers: how often pairs overlap, and how often an
  overlap becomes a catch-up repair.
- **The cut sees the drafts beside it.** A cut's brief (calls.md 3, 3) gains
  a section `Drafts beside this one`, after `Sources` (or `The user's
  drafts`). `fab call cut` builds it: it takes `fab.channel.plan_dirs(())`,
  loads each plan as the tick does without fetching (retired plans and
  failed loads skipped, the cut's own plan left out), keeps those of the
  same `plan.repo`, and folds statuses with `fab.state.fold` over
  `fab.log.read()`; the rendered text is passed into `cut_brief` as a new
  argument. In the plans file's order, per plan: its draft; for an
  integration plan whose trunk has not landed, every task with its `files`
  (an integration plan whose trunk has landed is left out entirely),
  those merged into the trunk marked `merged` (they are not on main yet);
  for a queue plan, its tasks not landed, with their `files`; a plan whose
  cut is in flight, `cut in flight`, with the tasks its pushed plan
  already lists. Spec tasks only (the repair and catch-up tasks folded from
  the log name `**`, which tells the cut nothing), by id; at most 200 lines
  in all, the rest counted.
  A cut whose options set `ready=false` (a replay) gets no such section: a
  replay differs from its run only in who executes it (3). The cut's
  role texts (`fab/roles/cut-run.md` for direct integration cuts,
  `fab/roles/cut.md`) gain one line, which is fab's mechanics since it
  explains a section fab adds: prefer task boundaries and an order that keep
  this draft's early work off files another draft is changing, and say in
  `plan.md` which overlaps it could not avoid. It refuses nothing and asks
  nothing.
- **Later** (section 5): a build of the merged trees (a `cargo check` of
  each overlapping pair, in an idle slot like a check along the way), which
  would catch the semantic conflicts a textual merge misses, such as the
  jigq/debt compile red; landing a trunk at slice boundaries, so other
  drafts see its changes sooner; both once the probe's numbers ask for them.

## 5. Later

- Drafts beside each other (4): a `cargo check` of each overlapping
  pair of trunks; landing a trunk at slice boundaries; overlaps acting on
  the order of work, all once the probe's numbers ask for them.
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
- An integration plan's lighter checks (3): a workspace clippy of the
  trunk after each merge, the codex-kit run's lesson (two parallel branches
  meeting at clippy found only at the end check); once the replay matches
  the manual run.
