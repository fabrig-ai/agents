# fab: QA findings

2026-11-01, split from `docs/design/fab.md` (its section 6 maps the old
section numbers). Status: `docs/design/qa.status.md`. Shared: the
overview, the event log and the tests are `docs/design/fab.md`'s.

## 1. In one page

- **QA walks** of a ladder plan's rungs raise findings as events; triage decides each one's path; repairs and reruns accept a rung by itself.

## 2. QA findings

At the user's word (11-01, after qa-ladder): QA of temper v0.1.0 ran by hand.
A session wrote rung briefs, had a Claude subagent walk each, triaged the
findings itself, surveyed their causes, had Codex repair the on-path ones,
landed them as hand-pushed ready refs and reran each brief unchanged; the
off-path ones piled up in a file with no owner (`coord/qa-ladder/
findings.md`, 48 entries). fab runs that loop: a walk's findings enter the
log, a director's call triages them, on-path ones become Fix-mode repairs
through the foreman path reds use (after-landing.md 2, calls.md 2), and fab says when a
rung's brief is due again, unchanged. `temper/docs/design/draft/v0.1.0.md`,
2-4, is the process; `execution-modes.md`'s Fix mode ("a finding, a red, a
bug"; one finding the unit of flow; the finding's own walk, rerun unchanged)
and "QA's findings enter Fix mode" are the model. In the first build a
session still walks by hand; walks run by fab are the section's last part.

- **The ladder is a plan,** a fabrig plan (integration.md 2) with `landing = "queue"`,
  listed in `FAB_HOME/plans`, whose plan.toml names its rungs: v0.1.0's is
  `temper/docs/plan/v0.1.0-ladder/`. A plan owns its draft's work (tick.md 5), so
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
  after-landing.md 2), title, severity, area, blocking, reproduction, expected,
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
    triage `Question:` of the plan is open (an ask of kind call, gates.md 2,
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
  user's page: the page is for what is the user's (channel.md 2) and 48 entries
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
    as a call's branch's do (integration.md 2). `ladder/` joins the fab branch forms
    kept out of `queue.*` (landing.md 3).
  - A rejected or failed commit is tried again, as a new n, on a later
    round; no triage waits for it. After two rejections of the same render
    (its sha256 recorded as `render` on `branch.ready`), the page raises
    `backlog:<draft>` (channel.md 2: the branch, the step, the queue's log) and the
    tick readies no more until the render changes or the signal is cleared.
    The page shows the backlog's count and path only.
- **On the path is a Fix-mode repair through the reds' foreman path,** a
  new kind beside `red` sharing its machinery: a finding's lifecycle
  (walks, rungs, reruns, merges) shares nothing with a red's (tips, keys,
  suspects, tiers runs, coverage), while what follows the decision is the
  same.
  - **What moves out of `fab/tier_reds.py`** into `fab/fix.py`, Fix mode's
    shared steps, so both kinds call one copy (factored out after
    red-routing's wiring landed, red's behaviour unchanged, its tests
    kept):
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
    - `fab.fix.sections(events)`: each task's `refusal.settled` fix
      sections in log order, which a repair's body carries after its
      foreman's (a finding's repair goes to the specless refusal foreman
      as a red's does);
    - `FIX_KINDS = ("red", "finding")` and `RUNS = 2`
      (`tier_reds.RED_RUNS` kept as its name for it).
    `fab/fixes.py` then holds only the finding's: its foreman's brief, its
    repair's body, and their fold.
  - **One action pair for both kinds:** `Action("examine-fix", task=<repair id>,
    detail=<red or finding id>, run_kind=<kind>)` and `Action("remedy-fix",
    run=<foreman run>, run_kind=<kind>)`; `fab.dispatch.red_actions` and
    `finding_actions` (both pure) make them, and `fab.dispatch._fix_steps`
    sends each to its kind's start or settle against one log snapshot,
    reading main's tip once for the round's finding foremen (a round that
    cannot read it notes so and starts none): after-landing.md 2's
    `examine-red` and `remedy-red`, renamed with the move. Its foreman
    runs and their ends are folded by `fab.fixes.foremen(events)`, which
    the tick and the page read.
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
    `tasks/TEMPLATE.md`, which every hand repair carried. It also says the
    plan's rung briefs are not the repair's: a fault in one is a `brief`
    decision of triage, asked of the user, never a repair's edit.
  - **A repair leaves the briefs** (11-01, found by fabrig/qa:
    `v0.1.0-ladder/finding-17` edited `kit.md`, which changed every rung's
    edition and reset 13 passes). Before a finding repair is readied, code
    compares the branch with its merge base: a path among the plan's rung
    brief files (`plan.rungs`' `brief`, under the plan directory) refuses it
    (`branch.rejected`, step `gate:briefs`, findings naming the paths), as
    a failed gate refuses, and its refusal foreman and repair run drop the
    edit. Only a finding repair (`fab.fix.FIX_KINDS`' `finding` kind) is
    checked; a brief's own change lands by hand or from a `brief` decision.
  - **Everything after-landing.md 2 gives kind `red` holds for each of
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
    it" (`temper/docs/design/qa.md` 3), and "down before up";
  - **holding:** a finding holds it;
  - **due:** otherwise, a `first walk` when no walk at its current edition
    has ended pass or fail, else a `rerun`, at a main containing each
    landed repair of its findings (the newest such `branch.landed`'s main).
  The rerun does not wait for after-landing's verdict on that main: the
  walk is its own check on real backends, a red after landing reaches its
  owner by after-landing.md 2, and the tiers would add an hour to each round.
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
  line per rung (channel.md 2, `## The ladder`): `<rung> (<backend>), edition <e>:
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
    login"), the tick deciding who gets one as it does places (machines.md 3). The
    walk returns them at its end (`fab logins return`) after its give-back
    has exported the account; one that cannot be returned stays lent with
    an `error` record, as a pair's (machines.md 3);
  - its timeout is the kit's wall cap, 3 hours: `fab.calls.TIMEOUTS`, new,
    a timeout per role (`walk` 3 hours), `fab.calls.TIMEOUT` (60 minutes)
    for the rest.
- **Built in this order; what waits for red-routing** (after-landing.md 2's code:
  `fab/tier_reds.py` and the page's red and fault signals are on main,
  21e391c; its wiring into the tick followed, 11-01):
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
    `_tick_plan` wiring if that lands first; the page's `finding` asks, `backlog:<draft>` signal and
    `## The ladder` (`fab/channel.py`); the landing report's QA figures
    (reports.md 2). With these alone, findings enter, are triaged, the backlog lands,
    questions reach the page and rungs show their state; an on-path finding
    waits at its foreman, holding its rung.
  - **After red-routing's tick wiring lands** (`red_actions`, red tasks run
    from main and readied, `RED_RUNS`, the specless refusal foreman, the
    answer call seeing red tasks; built by plan `docs/plan/findings-repair`,
    retired 11-01): `fab/fix.py` factored out of
    `fab/tier_reds.py`, then `fab/fixes.py` and
    `fab/roles/foreman-finding.md`, `finding_actions` and the
    `examine-fix`/`remedy-fix` pair in `fab/dispatch.py`, and the page's
    `finding-<n>` signal, which opens at `finding.settled` left: the repair
    path.
  - **Last, separable:** walks run by fab.

## 3. Later

- QA findings (2), next:
  - **Then it holds** (v0.1.0.md 3): a passed rung's story joins the live
    tier after-landing runs (`live-temper`'s stories, once the user says
    which run with `--run-ignored`, 11), and its fake twin goes into the
    worlds from the passing walk's transcripts (`qa-live.md`, 8): a task
    made from `rung.passed`, for Codex, kind feature, its body the walk's
    report and transcript paths. Waits for the first ladder fab runs.
  - Walks run by fab (2's last part), if the cut leaves it: the walk
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
