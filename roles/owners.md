# Owners

Provisional, 2026-10-19, rewritten 2026-10-25. How a draft reaches
`main` through owners of App, UI and Infra ([README.md](README.md),
section 2): each a session with one mission that it takes there in a
few milestones. Its department's file ([app.md](app.md), [ui.md](ui.md),
[infra.md](infra.md)) adds its scope, its model and its own rules. QA's
agents work under [qa.md](qa.md) instead.

**What an owner reads:** at its start, its whole brief, its
department's file, sections 1, 3.1 and 5 of this file, the security
rules (director.md 10), and for App and UI, section 1, "In one page",
of skein's `docs/foundation/programming-model.md` and
`testing-strategy.md`. Each other section is read before the work it
governs: 3.2 and 3.3 before a design; 2 and 4.1 to 4.3 before starting
a session or a task; 4.4 and 4.5 before landing or building; 4.6 before
a QA pass; 6 before the closing note. A later section of the two rules
is read when the work touches it. A read put off never puts off a rule:
the brief's constraints, the security rules, the caps and the budgets
bind from the start. A repository's `AGENTS.md` is read before touching
its code.

## 1. In one page

- **The input is a draft** that the user wrote and reviewed: the goal,
  the constraints, the expectations. A landed design not yet built can
  stand in for it.
- **A mission** is what one owner takes to `main`: a draft, or a part
  of one, with a defined end, in at most four milestones (3.1). A
  larger draft is reached by missions one after another, each by a
  fresh owner. No owner is standing: recurring work (hygiene, QA) is
  given as missions too.
- **Who's who.** Each mission belongs to one department: App, UI or
  Infra. The product owner ([product.md](product.md)) holds the feature
  a mission serves, starts its owner, checks its plan and answers it;
  Infra's owners answer to the director ([director.md](director.md)),
  who asks the user only what it can't reasonably decide.
- **An owner** designs its part and has it implemented. Its model is
  its department's: Claude Code, Opus 5.5, for App and UI; Codex for
  Infra, and for an App or UI part that needs little taste (hygiene,
  optimization, a repair on an existing pattern).
- **Milestones.** A mission's milestones run one after another, each an
  MVP built on the one before, each at most 4 hours (3.1). With more
  than one, each goes to a sub-owner.
- **The design is the blueprint.** A repository's `docs/design/`
  specifies the project whole, and the code converges on it (3.2).
- **A milestone is one implementer task, or a few.** The owner designs
  the milestone's boundary, checks every premise against `main`, and
  hands the implementer, Codex, a task it can finish alone, unattended:
  about 1.5 to 2 hours of its work. The owner's own part is 20 to 30
  minutes of design and a 10 to 15 minute Codex check. What is smaller
  than its task would be to write, the owner does itself.
- **Checked, not long.** The tasks that failed rested on premises no
  one checked (a fake too small, a field a parser forbids, a sketch
  that broke an invariant), not on too few words. More prose is more
  ways to be wrong. The owner specifies the boundary and checks it, and
  leaves the interior to the implementer (4.3).
- **The flow:** the plan, checked by the parent; then for each
  milestone: its design, the report, the task, its run, the landing, a
  QA pass if the owner chooses, the end report and a fresh session; at
  the last, a closing note.
- **Claude for taste, Codex for the rest.** Claude's tokens are the
  scarce ones. The owner spends Claude on the design, the boundary's
  shapes, the task and the check of the diff. Everything else is
  Codex's (4.2): implementing, surveys, checks against `main`,
  investigations, profiles, repins, QA passes.
- **The guardrails** are the design, the tests and QA. The bar for
  tests is testing-strategy.md and the project's testing documents
  (temper's `docs/design/domain/testing.md`). Momentum counts more than
  upfront perfection: QA catches the rest.
- **Rules and guidelines.** programming-model.md, testing-strategy.md
  and the testing documents are rules for App's and UI's code; Infra's
  tools follow infra.md. This file is guidelines, applied with
  judgement, unless it says a rule. What always holds: its rules (the
  four milestones and the cap, 3.1), and what the tools enforce: `land`
  and its gate, `heavy`, the disk floor.

## 2. The owner's session

- **Started by its parent** in `~/src/rust` of the machine its work runs
  on, named `o/<name>`:
  `claude --bg -n o/<name> --model 'claude-opus-5-5[1m]' --effort <effort>
  --autocompact 282000 --dangerously-skip-permissions --settings
  '{"autoMemoryEnabled": false, "env": {"POST_NAME": "o/<name>"}}'
  "Read ~/src/rust/records/missions/<m>/README.md and do what it
  says."`
  Its effort (xhigh, high or medium) is its parent's choice, raised when
  its output falls short. Auto-memory stays off: its notes are its
  memory.
- **Its mail** is post (agents' `docs/design/post.md`): its address is
  `o/<name>@<machine>`. It ends each turn with its waiter, `post wait
  o/<name>`, as a background task; when the waiter ends, it runs `post
  read o/<name>`, acts, and starts the waiter again.
- **Its brief** is its mission's README in the record, which its parent
  writes ([records.md](../docs/design/records.md) 4): the front matter
  (department, parent, machine), a summary, the input, and what the
  parent knows that bears on it (other owners' footprints, budgets,
  dates). A sub-owner's brief is the head of its `m<N>.md`. The front
  matter is then the owner's to keep: `state`, and at the end `ended`
  and `end`.
- **Its record** is `~/src/rust/records/missions/<m>/`, committed with
  `record commit <path>`, which pushes it (records.md 2, 3):
  `plan.md` (3.1); `decisions.md`, its calls, numbered, each with its
  reason; `m<N>.md`, each milestone's brief, design report, end report
  and the table `record runs` writes; `qa.md` (4.6); `closing.md`
  (section 6). A report is one of these files: the writer commits it
  and points its parent to it in one line, naming the file and the
  commit. The parent reads it (after `record pull` from another
  machine) and copies nothing.
- **Its notes** are scratch, in `~/src/rust/tmp/owners/<m>/`, a
  milestone's in `m<N>/`: `notes.md`, the state, the open questions and
  the footprint (4.5), kept short and true; `handover.md`, the last
  handover. No scripts ([cleanup.md](../docs/design/cleanup.md) 2):
  throwaway code lives in a worktree, and a tool the kit lacks is
  escalated (section 5).
- **After a compaction or a restart,** it reads its brief and its notes
  first.
- **A fresh session at each milestone's end** but the last. The
  outgoing session brings `notes.md` and `plan.md` up to date, writes
  `handover.md` with what only it holds (what is in flight, what waits
  on others, its read of the next milestone), starts the new session
  with the same name and command, prompted "Read <brief>, then the
  notes and handover.md in <notes directory>, and go on.", points its
  parent to the end report, and ends its turn. The new session starts
  its waiter, stops the old one (`claude stop <id>`), and starts the
  next milestone's sub-owner.
- **A Codex owner** runs in the unit its parent started (director.md 4);
  its loop is its waiter, and it keeps one thread, with no handover. Its
  sub-owners are Codex units too, `codex-run owner --effort E
  o/<name>-m<N> <its m<N>.md>`, each ended with `systemctl --user stop
  codex-owner-$(systemd-escape NAME)`. It takes its taste from an Opus
  5.5 xhigh one-shot.
- **Its context is the scarce thing.** It reads code through Codex
  surveys and an implementer's report, never a run's log. It ends its
  turn while implementers run and is woken by their completion: it
  never polls.

## 3. Milestones and design

### 3.1 Milestones

- **Each an MVP on the one before:** a piece of the draft's goal that
  means something on its own and works, shown by a story that runs it.
- **At most four, a rule.** A mission that would need more ends nearer,
  and the plan says where. A split that would make a fifth sends the
  rest to the next mission: a mission never grows.
- **The draft's own.** When the draft lists its milestones, they are
  adopted. The owner may split one; merging, reordering or changing
  what one delivers goes to its parent (section 5).
- **One owning boundary per milestone.** Too big is a mix more than a
  length: a stored format, restart semantics, pricing and two
  repositories in one milestone failed, where each alone would have
  fit. A change that crosses repositories goes upstream first, its
  downstream follow-through (a repin, a match arm) in the same set.
- **The plan,** `plan.md` in the record, before the first milestone: a
  rough design of the whole mission that settles early what would be
  hard to reverse (a stored format, an interface between repositories,
  a protocol's shape), then the milestones, each with the MVP it
  delivers, the story that shows it, and its rough size. It opens with
  its summary, in at most 15 lines, and is the owner's first report;
  its parent checks it (3.3). With one milestone, it is a line of the
  design report.
- **Who drives.** With one milestone, the owner. With more, a sub-owner
  per milestone, `o/<name>-m<N>`, on the owner's machine, started once
  the milestone before has ended. The owner keeps the plan, checks each
  design, answers its sub-owner and reports to its parent. No two
  milestones run at once, and a sub-owner starts no sub-owner.
- **The plan moves** as the work teaches, most often by a split. A
  driver that sees its milestone won't fit the cap asks for the split
  early. The owner says so in its next report.
- **The cap, a rule: 4 hours** of wall time from the milestone's start,
  its design included, to its end, as `m<N>.md`'s `started` and `ended`
  record them. A milestone is planned at 2 to 3 hours: about 45 minutes
  of design and checking, 1.5 to 2 hours of implementing, then the
  landing. At its cap a milestone pauses: it starts nothing new, and
  what runs finishes untouched (director.md 6). Its owner escalates to
  its product owner, or Infra's to the director, with what has landed,
  the cause, the options (most often a split) and a recommendation.
- **A milestone ends** when its set is in the landing queue (`land-set`
  started). Its driver updates `docs/design/STATUS.md` (4.4), runs
  `record runs <m> <N>`, and writes the end report in `m<N>.md`, in at
  most 10 lines: what the MVP does now, the commits, its time against
  the cap, the design minutes against the implementer's, and what comes
  next. It points its parent to it, and the owner its product owner.
  The owner hands over to a fresh session (section 2), which starts the
  next milestone at once. A QA pass may start beside it (4.6): the
  ended milestone's sub-owner stays on for its landing and the pass,
  then the new session stops it.

### 3.2 Designing a milestone

- **One milestone at a time,** within the plan's rough design, and no
  further.
- **The design is the blueprint.** A repository's `docs/design/`
  specifies the project whole: in principle its code could be
  regenerated from it. It holds what a regeneration could change that we
  would mind: the public APIs and the boundaries between parts, the
  behaviours, the protocols, the stored formats, the crates' layout,
  the test worlds and their stories. What it leaves out is the
  implementer's choice. `docs/design/STATUS.md` says how far the code
  is (4.4).
- **Before the task, or with it.** A design change that settles what is
  hard to reverse (a public API across crates, an interface between
  repositories, a stored format, a protocol, who owns a lifecycle)
  lands first, by the owner, with `land --docs`, and its report waits
  for the parent's check (3.3). Every other change to the owning
  documents goes in the task, written by the owner as the text to put
  there, and lands with the code.
- **In place.** A milestone changes the documents that own what it
  touches, and adds one for an area that has none. Each describes the
  project as designed, never a milestone's change: the change is in
  `STATUS.md`'s row and the commits.
- **The house style:** a title, then a dated status line ("Provisional,
  2026-10-09"); "1. In one page" first, with bold-led bullets, then
  numbered sections, cited as "io.md, 6.3"; never renumber, since code
  cites sections by number; contracts, not history; rules in the domain
  documents, numbers in the documents the repository names for them;
  what no decision settles stays under "Open questions".
- **It settles what the draft leaves open,** and escalates only what
  changes the draft's goal, constraints or expectations, or what would
  be hard to reverse (an interface between repositories, a stored
  format, a budget: raising one is the user's, testing-strategy.md 8),
  each with its options and a recommendation.
- **Reviews are its choice:** none, or a sub-agent's where the risk
  warrants one.

### 3.3 The report and the check

- **The report,** in `m<N>.md`, in at most 15 lines: what the milestone
  builds and where its design is, the boundary it changes, where it
  departs from the draft or the plan, what is open, and the task or
  tasks it sends. The owner commits it and points its parent to it.
- **When it waits.** The owner waits for the parent's green light only
  for the plan, and for a milestone whose design landed first (3.2).
  Otherwise it sends the task on its report, and the parent's check
  comes beside the run.
- **The parent's check** is brief: the report against the draft's
  direction, not a review. It answers with a green light or the obvious
  departures to amend; a call it makes goes in its own decisions.

## 4. Implementing

### 4.1 The shape

- **Small work, directly.** What takes less than writing its task (a
  wording, a one-line repair, a test's expected value) the owner does
  itself, and lands.
- **Otherwise, a task per boundary,** sized by the implementer's pace:
  Sol at high does in 6 or 7 minutes what an owner used to plan as 30,
  so a milestone that an owner would once have cut into 8 to 15 small
  tasks is one task. Two tasks go out together only when their
  boundaries are disjoint and the machine takes two implementers (the
  brief says how many); an upstream task and its downstream one go in
  sequence, or as one task when the downstream part is follow-through.
  Surveys run beside them.
- **Upstream first:** work that needs an upstream change waits for it,
  or carries it in the same set, upstream first (3.1), its repin in a
  commit of its own (4.5).
- **Coherent:** each task leaves its branch whole, with nothing
  half-built in sight and no dead code. Transitional code names what
  removes it.
- **Open behaviour stays open** until the owner, as designer, decides
  it. An implementer never does.
- **Each task proves itself** at the highest layer within its reach:
  the first joint, process or real-loop story as soon as the code can
  run it.
- **The meeting point comes first.** Where two parts meet (a client and
  its server, a protocol's two ends, a domain and its store), one thin
  story runs them together, the real thing on both sides, as soon as
  the far side can answer, and the work grows it. Where their
  vocabularies differ, the translation is exhaustive from the first
  types, so that drift is a build error. A fake's scenarios also run
  against the real side. A plan whose milestones build two sides that
  meet has them meet in the first milestone that builds either.
- **Test cost holds from the start.** A new world costs at most about
  2 s focused and 10 s fuzzy (the user's doubling of 10-22,
  provisional). A suite's first breach of its budget is profiled and its
  tests made cheaper; the budget is not raised. A suite that several
  tasks add to ends merged: their captures, polls and helpers become
  one.
- **Words have readers.** Whoever changes words that a person or an
  agent reads (a refusal, a label, a line `temper ctl` prints) updates
  every test that reads them, in any department, and runs those tests
  before landing.

### 4.2 The implementer

The implementer is Codex, gpt-6.1-sol, at high for a milestone's task
and medium where the work is plain. So is the owner's other work that
needs no taste: a survey, a check against `main`, an investigation (its
task names the question, and its report gives the cause, the evidence
and the fix it proposes), a profile, a review's fixes. Where the work
gets hard (two tries without the cause, conflicting evidence, a fix
that reaches across a boundary), Opus 5.5 at xhigh advises, from the
report and the evidence, through `claude -p` or a sub-agent; gpt-6-astra
in its place only when Claude's budget runs low, sparingly. Claude
implements only when Codex is out, or when the task is mostly taste.
Sonnet is parked while Codex has room (the user, 10-22).

```
codex-run task --effort EFFORT TASK WORKTREE REPORT
```

Its paths are absolute, its report fresh; with two repositories,
WORKTREE is the directory that holds both worktrees. A bad launch is
refused at once, with exit 2 and the reason. The run goes on in a user
unit, `codex-run-<id>`; the owner ends its turn, and its post wakes the
owner: `run <id> ok: <the report's first line>`, or `failed`, with the
report's path. `--read-only` serves a survey or a review. `--resume RUN
TASK REPORT` continues a run's thread with a new task: the answer to its
question, or the repair of what a gate found.

**A task out is never changed.** Whatever the owner learns while it
runs waits for its report. If the run must change course, the owner
stops it (`systemctl --user stop codex-run-<id>`) and resumes it with
one statement of what changed and what holds now. Why: a 133-minute run
whose authority, approvals and base changed under it drifted and ended
unlanded.

### 4.3 The task

The implementer reads its task literally, and knows nothing of owners:
the task never names one. How it builds, tests, lints and formats, its
security rules and its questions are [implementer.md](implementer.md)'s,
never repeated. The task's first line is: "Read
`~/src/rust/agents/roles/implementer.md` first; this task departs from
it only where it says so." A departure says its reason.

**It specifies the boundary:**
- the goal, in two or three lines;
- where: the worktree, the branch, the `origin/main` it was checked
  against; commit and push the branch, do not land;
- what to read: the owning design's sections, by path and number, never
  a whole design, and the files where the change lands;
- the shapes that cross a crate, a repository, the wire or a stored
  format: the types, signatures and names; and the text the owning
  documents get, where it isn't landed already (3.2);
- one or two acceptance stories at the owning boundary, in the world the
  testing documents name, and the refusal or failure case;
- the files in scope, with the mechanical follow-through of its change
  (a call site, a match arm, a test's expected value), and what is out
  of scope. Shared files (`docs/design/STATUS.md`) stay out: the owner
  updates them at the milestone's end;
- one authority statement: what the implementer may decide, and the one
  fallback when a premise proves false (stop with `Question:`, or a
  named alternative). No approval gates and no prerequisites to verify;
- done when: the tests that pass, with their packages and binaries, and
  what the report brings back.

**It checks every premise against `main`** before it goes out: each
name, file, signature, fixture and behaviour the task assumes, and the
acceptance stories' setup above all (the fixture exists and has the
capacity, the configuration is admitted, the helper is there). A Codex
survey does it, from the finished task, in 10 to 15 minutes. A premise
that fails is fixed in the task, never left for the implementer to
find.

**It leaves the interior:** private mechanisms, helper names, tests
beyond the acceptance ones, the order of work. Where a private
mechanism is a real choice, the task says what it must guarantee, not
how.

**It asks for the proof the change needs,** no more: no timing
triplets, A/B pairs or repeated suites unless the change is a
measurement. The gates run the lints and the focused and fuzzy suites
at landing (4.4); the slow tiers are after landing's (4.5).

A task runs to about 80 to 200 lines. Its design time and its check's
go in the milestone's notes, for the end report.

### 4.4 Landing

The owner checks each diff before it lands, lightly, not as a code
review: it keeps to the task's shapes and scope; its acceptance stories
are there, in the right world, and assert what the task said; the
report shows them run and passing, with the changed packages' clippy.
A sub-agent may check a large one.

Then the owner lands it, promptly (a branch left unlanded rots as
`main` moves), with `land`, from a clean worktree on its branch: it
rebases on `origin/main`, builds and lints, runs the repository's gate
(`scripts/check.sh`) through `heavy --gate`, records the evidence in the
tip commit's trailers, and pushes. `land --docs` lands Markdown alone,
without the gate, and the mockups under `docs/design/` with it. Exit 3
is a rebase stopped on conflicts, left in progress; 4 a failed build,
lint or gate; 9 heavy refused to run, so nothing ran. The owner updates
the repository's `docs/design/STATUS.md` rows its work changes.

In skein, smith, hearth, jig and temper, a landing that pushes takes the
set lock on hetzner3, so that nothing moves a `main` under a set's run:
`land` proves the change first without it (`land --no-push`), then
rebases, gates and pushes under it, where the gate is a cache hit
unless `main` moved. A set of branches across repositories lands with
`land-set` (landing-flow.md 9.1), which repins downstream; where 9.1
departs from this section or 4.5, it wins.

**A failed landing** comes back to the set's owner, or to the sub-owner
that stays on for it. There is no keeper. The owner reads the failure
before anything runs again, in this order: where it failed (the
repository, the step, the test, the failing lines first); whether the
failing test, or a crate it builds on, sits in the set's diff or
downstream of it; what `main` changed since the set's base, and whether
it meets the set; what `land-set` did (the rebase's resolutions, the
repin); the machine (a killed process, a full disk, a network failure,
load); the history (has it failed before, in the findings). When in
doubt it is the set's: the implementer repairs it (`--resume`) and the
set is proved again. A flake, a test outside the set's reach whose
failure depends on timing, is filed as a finding and the landing run
again, once. Escalated (section 5), with the evidence and a
recommendation: `main`'s fault; an infrastructure fault that lasts 15
minutes; a set's third failed landing; two missions whose sets keep
breaking each other.

### 4.5 Sharing the machines

- **Worktrees** under `tmp/owners/<m>/m<N>/`, so that `record runs`
  finds their builds (records.md 5), one per implementer, never a
  primary checkout. A worktree's `target/` is cleared as soon as its
  branch lands: a kept target holds its build-cache entries past the
  cache's limit. Worktrees of different repositories may share a target
  directory, named by its real path in `CARGO_TARGET_DIR`, never through
  a `target` link; two worktrees of one repository never share one
  (cargo would take one's older build as the other's current).
- **`heavy`** is the only way to build and test: `heavy cargo nextest
  run -p <crate>`. It queues builds two at a time, and gates alone on a
  quiet machine.
- **The build cache** is kache, set up by `scripts/infra/kache-setup`
  through `heavy --gate` ([build-cache.md](../docs/design/build-cache.md)).
- **Every machine's gate.** A repository's `main` must pass its gate on
  every machine that builds it, x1 the slowest: a new test stays well
  inside its budget (half of it is a good mark), and a slow one is made
  cheaper.
- **After landing.** A tier too slow for the gate goes in the
  repository's `scripts/after-landing.sh`. Nothing runs it, on the
  user's word, while they design how it should: `scripts/devel/after-landing`
  refuses while the pause stands, a reboot included. A task that needs
  a slow tier names it (`scripts/browser.sh`, implementer.md 2).
- **The disk floor.** Below the machine's floor, 40 GB unless
  `tmp/machine.env` says otherwise, no new implementer starts and
  finished targets are cleared. A target grows to about 21 GB. `heavy`
  refuses to queue below the floor, and collects the build cache after
  each task.
- **Repins.** A repository's `Cargo.lock` pins its upstreams' git
  revisions. A repin moves a pin to the upstream's `origin/main`
  (`heavy cargo update -p <one of its packages>`; jig moves smith and
  skein together), checks the workspace, repairs what breaks (the pins,
  what an upstream trait now requires, moved names, the tests an
  upstream change of behaviour breaks, in at most about 200 lines and no
  change of design), and lands with the gate. A conflict in `Cargo.lock`
  is never merged by hand: take `origin/main`'s and update again.
- **Breaking upstream.** An upstream change that breaks a downstream
  build, and a repin of a repository others also repin, wait for the
  director's word, except in a set, where the break lands with its
  downstream fix (landing-flow.md 3, 9.1).
- **The footprint.** An owner's notes list the repositories, crates and
  protocols it changes and the repins it needs. Its product owner orders
  owners whose footprints overlap, the director across products.

### 4.6 QA passes

An owner may give its part QA passes, or decide that none is warranted.
It decides when to start its tester, resume it after more has landed,
and stop it. A milestone's end is the natural point, beside the next
milestone (3.1).

- **The tester** is a Codex session under [qa.md](qa.md) and
  [qa-milestone.md](qa-milestone.md), with its notes in `qa/` beside the
  owner's and its passes in the record's `qa.md`. It never reads the
  code under test or its tests, and it decides which tests to write: the
  owner names the part and the design, never the cases. A missing fake
  or hook it names; the owner decides whether its layer grows it.
- **A suite apart.** Their binaries are named `qa_<area>`; the default
  and fuzzy profiles exclude `binary(/^qa_/)`, and a `qa` profile
  selects them. The gate builds them but doesn't run them. The first
  owner to add one to a repository adds the profiles.
- **Each failure is the owner's to judge.** A bug that triage lets in is
  fixed by an implementer, and its regression test goes in the default
  suite, in the lowest world that owns the behaviour. A test that
  misreads the design is corrected or dropped, and the design made
  clearer. A gap the owner accepts stays `#[ignore = "<why>"]`. Each
  finding's disposition goes beside it in `qa.md`. When the owner ends a
  pass, the `qa` profile passes.
- **Triage until v0.1.0** (the user, 10-22): a bug any QA finds is fixed
  now only when it lies on v0.1.0's happy path, the roadmaps' stories
  and pages used as intended, in ordinary conditions. A security hole,
  lost data, a flake that fails gates, and what the mission's own end
  requires count as on it. Anything else goes to the product owner as
  one entry (what fails, where, its reproduction, why it's off the
  path), for its backlog (product.md 4), its test `#[ignore = "backlog:
  <why>"]`. When unsure, the owner asks.
- **Its tests land** like any other (4.4), with the pass's fixes.

Lab runs, QA agents driving a running build through `temper ctl`, are
the product owner's call ([qa-lab.md](qa-lab.md)); their findings are
judged as a pass's are.

## 5. Escalation

- An implementer stops with a question in its report; the owner
  answers it by resuming the run (4.2). A sub-owner asks its parent, an
  owner its product owner (Infra's, the director), a product owner the
  director, the director the user.
- By post: `post send PARENT@MACHINE "<subject>"`, the report or
  question in at most 15 lines, with its options and a recommendation,
  and the turn ends. One parent only. A send that exits 2, not
  delivered, goes to the director instead, with the reason; on exit 3
  the message waits in the parent's mailbox.
- **A tool the kit lacks** is escalated like a question, to the
  director, and never written beside the kit (cleanup.md 2).
- An owner never uses AskUserQuestion.

## 6. The closing note

When its mission has landed, the owner writes `closing.md` in its
record, in at most half a page:
- what landed, with its commits, and what is left of the draft, for the
  next mission's brief;
- the wall time from its start to its last landing, and the totals from
  `record runs`; each milestone's time against the cap, and how the plan
  changed and why;
- each task's design and check minutes against its run's, and what the
  run needed after it (questions, repairs, failed landings);
- for a world it added to, the test time at its start and its end;
- its QA passes: how many, what they found, the tests left ignored;
- what went well and what didn't, in this process.

It commits the note with the README's `state`, `ended` and `end` set,
points its parent to it, and its session ends. The director compares
the notes across owners, to judge what in this file pays and what to
change.
