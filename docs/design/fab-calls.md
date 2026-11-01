# fab: Claude calls, review and the designer

2026-11-01, split from `docs/design/fab.md` (its section 6 maps the old
section numbers). Status: `docs/design/fab-calls.status.md`. Shared: the
overview, the event log and the tests are `docs/design/fab.md`'s.

## 1. In one page

- **A Claude call's output is reviewed before it lands,** by a session that did not write it; the foreman settles runs' questions and refusals.
- **The designer is four calls** (cut, contract, decision, retire), each with its role text in `fab/roles/`.
- **A probe** is a read-only, time-boxed Codex run whose report a decision call turns into design.

## 2. Design and acceptance are separate

- **A Claude call's output is reviewed before it lands.** A skeleton,
  answer, structure review or designer's call's branch (3) gets a
  read-only Codex review run (kind `review`, effort medium,
  `fab/roles/call-reviewer.md`). Its brief
  holds the call's brief and its diff from the merge base with main. It
  reports at most ten lines on contradictions with the design, layering
  breaches, gaps a task would hit, and duplicates of what the inventory
  already holds. Its report's first line is `Done: approve` or `Failed:
  <findings>`. Approved, the branch lands. Refused, the findings go back
  once, as an amend call (`fab/roles/amender.md`) on the same branch.
  Refused after its amendment, the chain goes to a settle call.
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
    `Infra:` holds the chain for one `settle` call (`fab call settle ROOT`,
    `fab/roles/settle.md`, effort medium, as the answerer's). Its subject is
    `<chain subject>/settle`; its `call.started` carries `settles`, the root.
    It shares the plan's answer-call limit and reserves nothing else. It
    runs report-only (fab-channel.md 3), changes no branch, and is not
    itself reviewed. Its brief holds the root call's brief path, the
    branch's diff from its merge base as the review brief does, every
    refusing review's report and the amend calls' reports (paths and
    excerpts), and the hold's reason.
  - Its report's first line is exactly `Done: land`, `Done: amend` or
    `Done: user`. Land names why the branch is good enough and any findings
    left as later work; the branch lands as approved. Amend gives guidance,
    resets the chain's counts as a user's answer does, and reviews the tip
    again; `fab.channel.answers_text` carries the guidance into the next
    amend brief. User gives one line saying why it is the user's: budgets,
    machines, what is hard to reverse, or a change of direction. Only then
    `call.parked` has reason `user: <that line>`. A failed call, missing
    guidance or explanation, or any other report parks with `settle failed`.
  - Each verdict logs `chain.settled`: call the root, its subject, settle
    the deciding call's id, verdict land, amend or user, and text the report
    after its first line. Land folds as approved; amend as a reset. A later
    queue refusal still follows the chain's ordinary refusal rules.
  - After settle says amend, a second hold gets one more settle, whose
    brief says amend is no longer an option: land or user only. No third
    settle starts before a user's reset; a forbidden amend or another hold
    after both attempts parks with `settle failed`.
  - A chain parked before settlement existed is held again when its last
    `call.parked` reason is `refused after its amendment`,
    `the amend call ended <outcome>`, or `3 review runs ended infra`, with
    no `call.answered` after it and no `chain.settled`. Its next plan tick
    settles it; its ask stays open until then. Reviews-off plans
    (fab-integration.md 3) still finish unreviewed chains and never reach
    a hold.
  - A `call.answered` naming the subject (fab-channel.md 2) starts the
    chain's counts and its settle allowance afresh: the branch's tip is
    reviewed again, and may be amended once more.
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
  - **A specless task's refusal** (fab-integration.md 3's `<draft>/repair-<n>`, a red
    task, fab-after-landing.md 2): its foreman's brief quotes the task's body under
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
    2 appends a refusal's section to the spec because the task's next
    run reads it there. A landed task has no next run; its repair is the
    red task, whose body carries the section. Appending to the owner's spec
    as well would cost a queue batch per red (fabrig's specs land through
    the queue) or a change to a trunk that has already landed (integration
    plans), for history the log (`red.settled`'s section) and the repair's
    commit already hold.
- **The foreman reads a QA finding too** (fab-qa.md 2): a finding the triage call
  puts on the path goes to a foreman of its own (`fab/roles/
  foreman-finding.md`) in the same form, its fix a new task
  `<draft>/finding-<n>` as a red's is.
- **The foreman settles what the options settle.** A run ending with a
  question first goes to a foreman run (Codex, medium, kind `foreman`,
  `fab/roles/foreman.md`; it writes no code, code records what it decides) with the task spec and the report: when
  the spec's pre-approved options answer it, the foreman's answer is
  recorded in the spec's Answers section and the task runs again (or, by
  `Accept:`, the pushed run is the task done: fab-integration.md 3); otherwise
  the question queues for the answerer: at once when it holds up other work
  (a task waits on the parked one, or nothing is running while work remains),
  otherwise at 4 queued or after 30 minutes (the user, 10-30; the model said 2
  hours).
  - `fab/foreman.py` folds where each open question stands: at the
    foreman, deciding, settled or queued. Questions of implement, repair and
    rebase runs go to the foreman; the rest (a park at the run limit, a
    failed implement, repair or rebase run that did not start early, one
    logged by hand) queue at once. A failed run parks as a park does
    (`fab.run.collect` logs its report's first lines as a `question.asked`
    with `park`): before (findings-loop, 11-01), a failed run's task parked
    with no question, which no foreman, answerer or page heard, and its
    dependents waited. As a backstop, `fab.dispatch.decide` parks the same
    way a task whose last run ended failed with no question asked since (a
    run collected before that, or by an older install: the playground
    replay's fe-world-remove, 11-01, sat parked 40 minutes). A park's `question.asked` carries
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
- **The structure review stays its own call** (fab-gates.md 2), never the
  skeleton author's.

## 3. The designer's calls

The designer of the user's model is four Claude calls (`fab/designer.py`),
each with its role text in `fab/roles/`. Like every call, each is reviewed
before it lands (2).

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
    `FAB_HOME/plans` (fab-tick.md 5) and runs; its subject is `<draft>/cut`.
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
  calls in flight (fab-tick.md 5).
- **The user's questions park parts, not the plan:** a part named by a
  question without an answer is not designed; its readers wait as for any
  need. A skeleton or contract brief shows the part's questions and their
  answers. The user's channel (fab-channel.md 2) lists the open ones.
- **decision:** a probe's report in, a design section out. `fab call
  decision PART --run RUN` for a probe part, its brief the probe's report
  (`FAB_HOME/runs/<run>/report.md`), its readers and their designs; its
  subject is `<draft>/<part>/decision`. It writes the section the readers
  cite and its status file, and changes the plan only where the measurement
  does. What starts it is the probe's (4).
- **retire:** when a plan's parts are all done, the tick starts one retire
  call (subject `<draft>/retire`). Its brief holds the designs changed
  since the plan started (those a commit since the one that added plan.toml
  changed, or whose status file it changed, as `changed_designs` finds
  them), each as the shorter of its diff since the plan started (`git diff
  <start>^ <rev> -- <design> <status>`, rev being `changed_designs`' rev,
  origin/main; against the empty tree when the start has no parent) and its
  text and status file at rev (`(removed)` when the design does not exist
  at rev). The section is filled in path order within a budget:
  `BRIEF_LIMIT` less the compiled text of every other section (headings and
  separators included) and less the list lines below. A design that does
  not fit is skipped and filling goes on with the later ones; each skipped
  design is listed instead, as the cut's design index does: `- <path> (<n>
  lines, diff <m> lines): read it in your worktree`, `<n>` its line count at
  rev (0 when removed). So the brief passes the limit only if its other
  sections alone do.
  Quoting every design whole did (11-01: trunk-overlaps' retire, 216k
  characters of fab.md and fab.status.md before the split; the tick
  started the failing call again every tick, nine units in three minutes,
  until the plan was retired by hand). A helper gives the plan's start and
  the diffs; `changed_designs` keeps returning paths. The retire role text
  (`fab/roles/retire.md`) says designs come as diffs or as a list, and that
  it reads a design whole in its worktree when it needs more. It brings the
  status files current and sets `retired = true` in plan.toml.
  The Codex consistency pass is its chain's review run, with its own role
  text (`fab/roles/consistency.md`) and the list of changed designs; a
  refusal goes back once as an amend call. Once it lands, the tick skips the
  plan.
- **Where they land:** as every call, through `fab land` for this
  repository, so they may change only what it allows (fab-landing.md 2).

## 4. Probes

- **A probe** is a read-only Codex run with a time box (the part's
  `minutes`, hard) and a success criterion from its design; its report is
  the measurement; a decision call (3) turns it into design.

## 5. Later

- A call whose brief cannot be compiled (past `BRIEF_LIMIT`, or any
  other deterministic failure before `call.started`) is started again every
  tick. Retire's brief is bounded (3); a park for such a start (a
  `call.parked` with no call, lifted by an answer, seen by the tick's
  parked set, triage and amend starts) waits until another call kind meets
  it.
- Retire's changed designs taken from the plan, not from main's window:
  the designs its parts cite (`design`) and those its own branches changed,
  rather than every design main changed since the cut, so a plan designed
  before its cut sees its designs and not another plan's (fab-calls.status
  11-01, paper-cuts' retire).
- (The self-critique is 2's, part `critique`, not later.)
- The foreman for plans whose specs live in another repository: its answers
  and repair sections landing through that repository's landing, not `fab land`.
- A repair run of this repository that starts without a foreman's section
  quoting `fab land`'s detail, as the foreman's brief does; it reads the
  detail as a queue log path today and quotes nothing.
- The cut started by the tick when a draft lands that no plan serves, once
  a draft can say where its plan goes.
- The designer's calls for repositories other than this one, once calls land
  through fabrig's queue.
- A plan `[[question]]` naming a direct part holds that part's tasks, not
  only its design: today a direct part's specs run while its question is
  open (the first dry cut of the component kit asked the user 6.1 and its
  task would have run anyway). cut-direct.md now tells the cut to decide
  what its sources settle and to make no task wait for a question.
- A cap on a call's context or turns, once the user sets one from the
  measurements (fab-reports.md 3); Claude and Codex usage against their plans' limits,
  once the limits are recorded somewhere fab can read.
