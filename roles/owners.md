# Owners

Provisional, 2026-10-19, revised 2026-10-24. How a draft reaches
`main` through owners of App, UI and Infra ([README.md](README.md),
section 2): each a session with one mission, the draft or a part of
it, that it takes there in a few milestones, each designed and then
implemented. Its department's file ([app.md](app.md), [ui.md](ui.md),
[infra.md](infra.md)) adds its scope, its model, what it reads and its
own rules. QA's agents work under [qa.md](qa.md) instead.

**What an owner reads:** at its start, its whole brief, its
department's file, sections 1, 3.1 and 5 of this file, the security
rules (director.md 10), and the rules
its department's file names: for App and UI, section 1, "In one page",
of skein's `docs/foundation/programming-model.md` and
`testing-strategy.md`, the rules for the code's shape and its tests;
for Infra, none. That is enough to start. Each
other section of this file is read before the work it governs: 3.2 and
3.3 before a design; 2 and 4.1 to 4.3 before starting a session or an
agent; 4.4 and 4.5 before landing or building; 4.6 before a QA pass; 6
before the closing note. A later section of the two rules is read when
the work touches it (a new protocol, a world's checks, a memory bound),
and skein's `docs/foundation/notes.md`, the reasons and open questions
behind the rules, when a rule's reason matters. A read put off never
puts off a rule: the brief's constraints, the security rules, the caps
and the budgets bind from the start. A repository's `AGENTS.md` is read
before touching its code: an owner's session doesn't load it.

## 1. In one page

- **The input is a draft** that the user wrote and reviewed: the goal,
  the constraints, the expectations. A landed design not yet built can
  stand in for it.
- **A mission** is what one owner takes to `main`: a draft, or a part
  of one, with a defined end, in at most four milestones (section 3.1),
  so about 16 hours at most. A larger draft is reached by missions one
  after another, each by a fresh owner, so that each keeps its context
  and its focus on one end. No owner is standing: recurring work
  (hygiene, QA) is given as missions too, such as `o/hygiene-<what>`.
- **A department.** Each mission belongs to one: App, UI or Infra
  (README.md, section 2). A feature that needs several gets a mission
  in each.
- **The product owner** holds the feature a mission serves, across the
  departments. It starts one owner per mission, checks its plan and
  designs, answers it, and brings to the director what crosses
  products. Its role is [product.md](product.md). Infra's owners answer
  to the director itself.
- **The director** knows every draft and the direction, gives the final
  call on what is escalated to it, and asks the user only what it
  can't reasonably decide. Its role is [director.md](director.md).
- **An owner** designs and implements its part: its mission, or one
  milestone of it. Its model is its department's: Claude Code, Opus
  5.5, for App and UI; Codex for Infra. Its effort is its parent's
  choice (section 2). An App or UI owner whose part needs little taste
  (hygiene, optimization, a repair on an existing pattern) is a Codex
  session instead, under this same file. A Codex owner takes its taste
  from an Opus 5.5 xhigh one-shot, and brings its significant code and
  test decisions to its parent.
- **Milestones.** A mission is reached through one to four milestones,
  one after another, each an MVP built on the one before: something
  meaningful that works on its own. The owner drives a single milestone
  itself; with more, it gives each to a sub-owner, a session like
  itself, and holds the whole mission's plan (section 3.1). No milestone
  runs past 4 hours. Milestones never run in parallel; within one,
  whatever can run in parallel does.
- **The design is the blueprint.** A repository's `docs/design/`
  specifies the project whole, and the code converges on it. Each
  milestone first brings the design to what it delivers, then the code
  (section 3.2).
- **The flow:** the milestone plan, its check by the parent; then for
  each milestone: design, report, a brief check by the parent, its
  green light, implementation with the QA passes the owner chooses,
  landings, a report at its end and the owner's handover to a fresh
  session; at the last, a closing note, and the owner stops.
- **Claude for taste, Codex for the rest.** Claude's tokens are the
  scarce ones; Codex's are ample, and throughput grows with what moves
  there. The owner spends Claude on what needs taste: the design, the
  shape of the code and its tests (their organization, names, APIs and
  boundaries), the tasks' sketches, the check of each diff against
  them, and its part's calls. Everything else goes to Codex (section
  4.2): implementing, investigating a failure or a slow test down to
  its cause, profiling and optimizing, surveys of code and logs,
  repins, fixes after a review, QA passes.
- **The compass and the guardrails** are the intended design and
  architecture, and the tests and QA. The bar for tests is
  testing-strategy.md and the project's testing documents (temper's
  `docs/design/domain/testing.md`). Momentum and tokens count more than
  upfront perfection: QA (section 4.6) catches the rest, and what is wrong is
  corrected as it shows.
- **Rules and guidelines.** programming-model.md, testing-strategy.md
  and the project's testing documents are rules for App's and UI's
  code: they shape the code and its tests, and a departure needs its
  reason, stated in the design or the commit. Infra's tools follow
  infra.md's rules instead. A department's file holds rules too, and says which. This
  file is guidelines, unless it says a rule: good
  practice for the owner to apply with judgement, case by case, as the
  work goes, partly, later, or not at all where it doesn't pay. None of
  it is upfront work to complete before starting. What holds: its
  rules (a milestone's cap, 3.1), and what the tools enforce: `land`
  and its gate, `heavy`, the disk floor.

## 2. The owner's session

- **Started by its parent** in `~/src/rust` of the machine its work runs
  on, named `o/<name>`:
  `claude --bg -n o/<name> --model 'claude-opus-5-5[1m]' --effort <effort>
  --autocompact 282000 --dangerously-skip-permissions --settings
  '{"autoMemoryEnabled": false, "env": {"POST_NAME": "o/<name>"}}'
  "Read ~/src/rust/records/missions/<m>/README.md and do what it
  says."`
  Its notes are its memory: Claude Code's auto-memory stays off, since
  in `~/src/rust` it would share the director's.
- **Its mail** is post (agents' `docs/design/post.md`): its address is
  `o/<name>@<machine>`, and it ends each turn with its waiter, `post
  wait o/<name>`, running as a background task. When the waiter ends,
  it runs `post read o/<name>`, acts on what it read, and starts the
  waiter again.
- **Its effort** is the parent's choice by the part's difficulty: xhigh,
  high or medium. The parent may raise it after the first report, when
  the output falls short.
- **An advisor.** An owner below xhigh may start an advisor, a session
  at xhigh under the same discipline (notes, compaction), and consult
  it on what it judges delicate. Sparingly: tokens count.
- **Its brief** is its mission's README in the record, which its parent
  writes ([records.md](../docs/design/records.md) 4): the front matter
  (its department, its parent, its machine), a summary, then the input
  (draft sections, designs, a README to grow) and anything the parent
  knows that bears on it: other owners' footprints, budgets, dates. A
  milestone's sub-owner's brief is the head of its `m<N>.md`. The
  README's front matter is then the owner's to keep: its `state`, and
  at the end `ended` and `end`.
- **Its record** is `~/src/rust/records/missions/<m>/`, each file
  written by its writers and committed with `record commit <path>`,
  which pushes it (records.md 2 and 3):
  - `plan.md`, the plan (section 3.1), rewritten when it changes;
  - `decisions.md`: its calls and its sub-owners', numbered, each with
    its reason, appended;
  - `m<N>.md`, each milestone's: its brief at the head, then its design
    report (3.3), its end report and the table `record runs` writes
    (3.1);
  - `qa.md`, its QA passes (4.6), and `closing.md` (section 6).
  A report is one of these files: the writer commits it and points its
  parent to it in one line, naming the file and the commit. The parent
  reads it, after `record pull` from another machine, and copies
  nothing. There is no ledger: `record runs` takes the sessions,
  tokens, builds and landings from the tools (records.md 5). A mission
  started before the record (10-24) keeps its notes in `tmp/` to its
  end, and is backfilled.
- **Its notes** are scratch, in `~/src/rust/tmp/owners/<m>/`, a
  milestone's in `m<N>/` beneath it:
  - `notes.md`: the state, the open questions, and the footprint
    (section 4.5). Kept short and true: corrected, pruned, never only
    appended.
  - `handover.md`: the last handover (below), replaced at the next.
  - No scripts, the owner's own included
    ([cleanup.md](../docs/design/cleanup.md) 2): throwaway code lives
    in a worktree, and a tool the kit lacks is escalated (section 5).
- **After a compaction or a restart,** it reads its brief and its notes
  first.
- **A fresh session at each milestone's end.** An owner with more than
  one milestone hands over to a new session at each milestone's end but
  the last, so that each milestone starts on a fresh context. The
  outgoing session brings `notes.md` and `plan.md` up to date, and
  writes `handover.md` with what only it holds: what is in
  flight (the ended milestone's QA pass, its sub-owner still at work),
  what waits on other owners or the director, and its read of the next
  milestone. It starts the new session with the same name and command
  (above), prompted "Read <brief>, then the notes and handover.md in
  <notes directory>, and go on.", points its parent to the milestone's
  end report (3.1), naming the new session, and ends its turn. The new
  session reads the brief, the notes and the handover, starts its
  waiter, which replaces the old one's, stops the old session once its
  turn has ended (`claude stop <id>`, the job's short id in `claude
  agents`), so that one session answers to the name, and starts the
  next milestone's sub-owner (3.1). Its children's post to `o/<name>`
  reaches it.
- **A Codex owner** runs in the unit its parent started (director.md 4).
  Its loop is its waiter, so it starts no `post wait`, and it keeps one
  thread, with no handover. Its sub-owners are Codex units too,
  `codex-run owner --effort E o/<name>-m<N> <its m<N>.md>`, each ended
  with `systemctl --user stop codex-owner-$(systemd-escape NAME)`.
- **Its context is the scarce thing.** It reads code through Codex
  surveys (short reports) and a Codex task's report, never its log. It
  ends its turn while implementers work, and is woken by their
  completion: it never polls.
  Between designing and implementing, it may write its notes and go on
  in a fresh session rather than carry the design conversation.

## 3. Milestones and design

### 3.1 Milestones

- **One or more, in sequence.** The owner reaches its mission's end
  through milestones, one after another, each an MVP on the one
  before: a piece of the draft's goal that means something on its own
  and works, shown by a story that runs it. Wherever a meaningful piece
  can be delivered alone, there is a candidate milestone, and the
  draft's end is reached through a series of them, across missions
  where it takes more than four.
- **At most four, a rule.** A mission holds at most four milestones:
  at 2 to 3 hours each under the cap (below), it ends within about 16
  hours. Its end is the brief's. Where reaching it takes more
  milestones, the plan's report proposes a nearer end, and the mission
  stops there. A split later that would make a fifth milestone sends
  the rest to the next mission: a mission never grows. The next mission
  gets a fresh owner, whose brief carries this one's notes and closing
  note.
- **The draft's own.** When the draft lists its milestones, they are
  adopted. The owner may split one; merging, reordering or changing
  what one delivers changes the draft's expectations, and goes to its
  parent (section 5).
- **The plan,** `plan.md` in the mission's record, before the
  first milestone: a rough design of the whole mission, reaching into
  the rest of the draft where it settles what later missions build
  on, and the
  milestones, each with the MVP it delivers and the story that shows
  it, the design documents it adds or changes, and its rough size. The
  rough design settles early what would be hard to reverse (a stored
  format, an interface between repositories, a protocol's shape), so
  that no milestone has to undo an earlier one's; the rest waits for
  its milestone's design. The plan is the owner's first report to its
  parent: `plan.md` opens with its summary, in at most 15 lines, and is
  checked as a design is (3.3). With a single milestone, the plan is a
  line of the design's report.
- **Who drives.** With one milestone, the owner drives it. With more,
  each goes to a sub-owner, `o/<name>-m<N>`, its brief the head of
  `m<N>.md`, started by the owner's fresh session once the milestone
  before has ended (below, and section 2).
  The owner keeps the plan and the whole mission's picture: it checks
  each milestone's design, answers its sub-owner, and reports to its
  parent. A sub-owner starts no sub-owner of its own, and no two
  milestones are designed or implemented at once. A sub-owner runs on
  its owner's machine.
- **Parallel within.** Inside a milestone, whatever can run in parallel
  does (4.1): that is where an owner finds its throughput.
- **The plan moves** as the work teaches. Most often, a milestone
  turns out too large or too long, from a finding or a change not
  known before, and is split. A sub-owner that sees its milestone won't
  fit the cap asks its parent for the split early, rather than run into
  the cap. The owner changes the plan, and says so in its next report.
- **The cap, a rule: 4 hours.** No milestone runs past 4 hours of wall
  time, from its start, its design included, to its end, as
  `m<N>.md`'s `started` and `ended` record them. Milestones are planned
  at 2 to 3 hours, so that the cap leaves room. A milestone at its cap
  pauses: it starts no task, job, landing or repin, and what runs
  finishes untouched (a pause, director.md 6). Its owner escalates
  through its parent to its product owner, or Infra's to the director
  (section 5): what has landed, the cause, the options (most often a
  split: what has landed as the milestone, the rest as the next) and a
  recommendation. It resumes on the answer.
- **A milestone ends** when its set is in the landing queue (`land-set`
  started). The end is a checkpoint:
  - its driver updates the repository's `docs/design/STATUS.md` (4.4),
    runs `record runs <m> <N>` for the table, and writes the end report
    in `m<N>.md`, in at most 10 lines: what the MVP now does, the
    commits, its time against the cap, and what comes next. It commits
    it and points its parent to it; the owner points its product owner
    to it, or Infra's the director;
  - the owner hands over to a fresh session (section 2), which starts
    the next milestone at once;
  - a QA pass on what has landed may start (4.6), beside the next
    milestone. The ended milestone's sub-owner stays on for its landing
    and the pass: it judges the pass in `qa.md` and lands its fixes,
    telling the owner's new session, which then stops it (`claude stop`).

### 3.2 Designing a milestone

- **One milestone at a time.** A milestone's owner designs fully what
  its milestone delivers, within the plan's rough design, and no
  further: a later milestone's design waits for that milestone.
- **The design is the blueprint.** A repository's `docs/design/`
  specifies the project whole: in principle, its code could be
  regenerated from it alone. It holds whatever a regeneration could
  change that we would mind: the public APIs and the boundaries between
  parts, the behaviours, the protocols, the stored formats, the crates'
  layout, the test worlds and their stories. What it leaves out is the
  implementer's choice. The code lags behind the design and converges
  on it, and `docs/design/STATUS.md` says how far it is (4.4).
- **New documents or existing ones.** A milestone changes in place the
  documents that own the areas it touches, and adds one for an area
  that has none. Each describes the project as designed, never a
  milestone's change: the change is in `STATUS.md`'s row ("Takes the
  design to") and in the commits.
- **The owner is its part's designer.** It writes the design documents
  in `docs/design/` and lands them with `land --docs` (4.4), from a
  worktree on a branch. The house style:
  - a title, then a dated status line ("Provisional, 2026-10-09");
  - "1. In one page" first, with bold-led bullets, then numbered
    sections, cited as "io.md, 6.3";
  - never renumber: code cites sections by number, so new material goes
    in an existing section, a new subsection, or a new last section;
  - contracts, not history: no spikes, findings or benchmark numbers;
  - rules in the domain documents, numbers in the documents the
    repository names for them;
  - what no decision settles stays under "Open questions".
- **It settles what the draft leaves open.** It escalates to its parent
  only what changes the draft's goal, constraints or expectations, or
  would be hard to reverse: an interface between repositories, a stored
  format, a budget (testing-strategy.md, 8: raising a budget is the
  user's decision). Each question goes with its options and a
  recommendation.
- **Reviews are its own choice:** none, or a cheap sub-agent's where the
  risk warrants one.

### 3.3 The report and the check

- **The report.** When a milestone's design has landed, its owner
  writes it in `m<N>.md`, in at most 15 lines: what is designed and
  where, the commits, where it departs from the draft or the plan, what
  is open, and how it means to implement, with what will run in
  parallel. It commits it and points its parent to it.
- **The parent's check** is brief: the report and the design's summary,
  or the plan, against the draft's direction, not a review. It answers
  with a green light, or names the obvious departures to amend; a call
  it makes goes in its own decisions.

## 4. Implementing

### 4.1 The shape

After the green light, the owner implements directly what is small.
Otherwise it breaks the milestone into tasks, all upfront, as it goes,
or both. Whatever can run in parallel does, and the owner shapes the
tasks so that more can: tasks that don't wait on each other go out
together, up to the implementers its machine takes (its brief says how
many), investigations and surveys run beside them, and the next tasks
are prepared while implementers work.

These guidelines (section 1) serve its tasks, applied as the work goes
and where they pay:
- **Settle first** what the tasks rest on: the scope, the APIs that may
  break and who repairs them, credentials and live services, the
  interface sketches.
- **Small tasks,** each merged on its own, leaving its branch coherent:
  nothing half-built in sight, no dead code. Transitional code names
  the task that removes it.
- **Upstream first:** a task that needs an upstream change waits for
  it, and repins in a commit of its own (4.5). Dependencies are named
  by capability, never by a task's number alone.
- **Open behaviour stays open** until the owner, as its designer,
  decides it. An implementer never does.
- **Each task proves itself** at the highest layer within its reach,
  and layers open as early as they can: the first joint, process or
  real-loop story as soon as the code can run it.
- **Test cost holds from the first task.** A new world costs at most about 2
  s (1 s before the user's doubling of 10-22, provisional) focused and 10 s
  (5 s before the user's doubling of 10-22, provisional) fuzzy. A suite's
  first breach of its budget is profiled and its tests made cheaper; the
  budget is not raised. A bound over a sum of several tasks' parts is
  computed by the first task that can, and kept current. A suite that
  several tasks add to ends merged: their copies of captures, polls and
  helpers become one.
- **Words have readers.** Whoever changes words that a person or an
  agent reads (a refusal, a label, a line `temper ctl` prints) updates
  every test that reads them, in its own department or another's, and
  runs those tests before it lands.

The one that pays most often: **the meeting point comes first.** Where two parts
meet (a client and its server, a protocol's two ends, a domain and its
store, a service and its host), one thin story runs them together, the
real thing on both sides, as soon as the far side can answer, and each
task grows it. Neither side runs ahead of the other. Where their
vocabularies differ, the translation is exhaustive from the first
types, so that drift is a build error the day it happens. A fake's
scenarios also run against the real side. A plan whose milestones build
two sides that meet has them meet in the first milestone that builds
either.

### 4.2 The implementer

The implementer is Codex: gpt-6.1-sol, through `codex-run` (below) in
its own worktree. So is the owner's other work that needs no taste
(section 1): an investigation, a profile, a survey, a review's fixes. An
investigation's task names the question and what its report holds: the
cause, the evidence that shows it (a measurement, a trace, a failing
test), and the fix it proposes, in a few lines. Codex's effort, medium
or high (`--effort`), is the owner's choice by the task, as the owner's
own is its parent's (section 2): medium where the work is plain, high
where it is harder, and raised when a report falls short or the quality
suffers. Where the work gets hard (two tries without the cause, evidence
that conflicts, a fix that would reach across a boundary), Opus 5.5 at
xhigh advises (`claude -p` or a sub-agent), from the report and the
evidence rather than the whole history. gpt-6-astra costs more than
Opus: it advises in Opus's place only when Claude's budget runs low
while Codex's has room, and sparingly. Claude (Opus 5.5, through
`claude -p` or a sub-agent) implements only when Codex is out, or when
the task is mostly taste: an API's shape, a test suite's organization
and names. Sonnet is parked while Codex has room (the user, 10-22): GPT
Sol does what Sonnet would, reports and surveys among them.

An implementer starts through `codex-run`, on every machine (agents'
`docs/design/post.md` 5):

```
codex-run task --effort EFFORT TASK WORKTREE REPORT
```

Its paths are absolute, and its report is fresh. It refuses a bad
launch at once, with exit 2 and the reason. The run goes on in a user
unit, so the owner ends its turn, and whichever way the run ends, its
post wakes the owner: `run <id> ok: <the report's first line>`, or
`failed`, with the report's path. `--read-only` serves a survey or a
review, and `--resume RUN TASK ...` continues a run's thread with a new
task, a review's fixes for one. The model's capacity errors are retried
by the tool. The model and the effort stay the owner's choice.

### 4.3 The task

An implementer other than Opus 5.5 at xhigh reads its task literally.
How it builds, tests, lints and formats, its security rules and its
questions are [implementer.md](implementer.md)'s, never repeated in a
task. The task file's first line is: "Read
`~/src/rust/agents/roles/implementer.md` first; this task departs from
it only where it says so." A departure says its reason: a stability
trial, a measurement, a profile the change needs, a wider run after an
upstream change. Beyond that, the task file is whole, and holds:
- the goal, in two or three lines;
- what to read first: the design's sections and the files, never a
  whole design, and of the rules, the sections the task touches beyond
  their one-page summaries;
- sketches of what matters: the public types and signatures with their
  names, what is internal and what crosses a boundary (a crate, a
  repository, the wire), and each test's sketch in the world the testing
  documents name. The owner checks them against `main` before the task
  goes out: the names, files and behaviours they assume are there (a
  Codex survey may check a large task's);
- the files it may touch and the branch its commits are pushed to, and
  that the mechanical follow-through of its change in the same crate is
  in scope: a call site, a match arm, a test's expected value;
- done when: the focused tests that pass, with their packages and
  binaries, and for a repair the failing check's (implementer.md 2);
  what else it proves (the commit's trailers, the figures it compares).
  The gates run the lints and the focused and fuzzy suites at landing
  (4.4); the slow tiers, the browser's among them, are after landing's
  (4.5).

### 4.4 Landing

The owner checks each diff before it lands, lightly and cheaply, and
not as a code review:
- it keeps to the task's sketches: the names, the signatures, the
  boundaries;
- its tests ran and pass, and that proof is in the implementer's report;
- its tests follow the testing documents and the stories and test
  sketches the task gave, in the right world.

A sub-agent may check a large one. Then the owner lands it, or tells
the implementer to, with `land`, from a clean worktree on its branch:
it rebases on `origin/main`, builds and lints, runs the repository's
gate (`scripts/check.sh`) through `heavy --gate`, records the evidence
in the tip commit's trailers, and pushes. `land --docs` lands Markdown
alone, without the gate, and the mockups under `docs/design/` (a
directory named `mockups`) with it: they need no tests or builds (with
the user, 2026-10-23). Its exit status 3 is a rebase stopped on
conflicts, left in progress; 4 a failed build, lint or gate; 9 heavy
refused to run the build or gate, so nothing ran. The owner
updates the repository's `docs/design/STATUS.md` rows its work changes.

In skein, smith, hearth, jig and temper, a landing that pushes takes
the set lock on hetzner3, `land-set`'s, so that nothing moves a `main`
under a set's run: `land` first proves a code change without it, as
`land --no-push`, then rebases, gates and pushes under it, where the
gate is a cache hit unless `main` moved (landing-flow.md 9.2).

Until the landing queue is built, landing-flow.md 9.1 says how a set
of branches lands (`land-set`) and what owners do by hand; where it
departs from this section or 4.5, it wins.

**A failed landing** comes back to the set's owner, or to the
sub-owner that stays on for it (3.1): `land-set`'s summary and the
feed say where it stopped and why. There is no keeper (the user,
2026-10-25). The owner reads the failure before anything runs again,
in this order:
1. where it failed: the repository, the step and the test, from the
   log, the failing lines first;
2. what the set changed, and whether the failing test, or a crate it
   builds on, sits in that diff or downstream of it;
3. what `main` changed since the set's base, in that repository and its
   upstreams, and whether it meets the set's changes;
4. what `land-set` did: the rebase's resolutions and the repin;
5. the machine: a process killed, a full disk, a network failure, a
   timeout under load;
6. the history: has this test failed before, in the findings?

When in doubt, it is the set's, and an implementer repairs it, then
proves the set again. A flake, a test outside the set's reach whose
failure depends on timing, is filed as a finding and the landing run
again, once. Escalated (section 5), with where the evidence is and a
recommendation: `main`'s fault (the test fails on `main` too, whatever
the set); an infrastructure fault that lasts 15 minutes; a set's third
failed landing; two missions whose sets keep breaking each other.

### 4.5 Sharing the machines

- **Worktrees** under `tmp/owners/<m>/m<N>/`, the milestone's, so that
  `record runs` finds their builds (records.md 5), one per implementer,
  never a primary checkout. A worktree's `target/` is cleared when done
  with, as soon as its branch lands: the build cache's limit leaves out
  the entries a target shares blocks with (cloned or linked, since
  evicting them frees nothing), so a kept target holds its entries on
  the disk past the limit until it goes and the cache is next collected.
  Worktrees of different repositories may share a target directory,
  named by its real path in `CARGO_TARGET_DIR`, never through a `target`
  link: a test that refuses a path reached through a link fails on its
  scratch directory then. Two worktrees of one repository may not share
  one. Cargo names a workspace member's artifacts by a hash that leaves
  out the worktree's path and judges them fresh by their sources'
  mtimes, so one worktree takes another's older build as current: a
  false failure, or a false pass.
- **`heavy`** is the only way to build and test, for everyone: `heavy
  cargo nextest run -p <crate>`. It queues on pueue in two lanes:
  builds, two at a time, and gates, alone on a quiet machine.
- **The build cache.** `scripts/infra/kache-setup` pins kache
  `1.2.2-gitrev.1`. The director places its binary at
  `tmp/kache/kache-1.2.2-gitrev.1` on each machine; setup checks its
  digest before stopping the daemon. Run setup through `heavy --gate`
  so no build is running when it swaps the wrapper and clears a store
  of another version. A user-owned 0600 `~/.config/kache/store.env`
  enables the shared S3 store through a config section and a service
  drop-in; without that file setup removes both and keeps caching local
  ([build-cache.md](../docs/design/build-cache.md), section 7).
- **Every machine's gate.** A repository's `main` must pass its gate
  on every machine that builds it, x1 the slowest. A test that fits
  its time budget only on a fast machine breaks other owners' and
  runs' landings: keep a new test well inside its budget (half of it
  is a good mark), and make a slow one cheaper rather than raise the
  budget.
- **After landing.** A tier too slow for a repository's gate goes in
  its `scripts/after-landing.sh`: the browser tier, the process and QA
  tiers, the exhaustive profile (landing-flow.md 4, step 8).
  **Nothing runs it,** on the user's word, while they design how it
  should run: not `land` or `land-set`, which start no tier after
  landing since 10-25, and no one by hand. `scripts/devel/after-landing`
  stays, unused: given a commit, it runs the script through `heavy
  --gate` in a worktree under `tmp/after-landing/`, and a failure adds
  a line to `tmp/director/inbox/after-landing.md`.
  `scripts/devel/after-landing` refuses while the pause stands. A reboot
  does not lift the pause. So no tier outside the gate runs on `main`
  by itself. A task that needs one names it, such as `scripts/browser.sh`
  (implementer.md 2).
- **The disk floor.** Below the machine's floor, 40 GB unless
  `tmp/machine.env` says otherwise, no new implementer starts, and
  finished targets are cleared. A target grows to about 21 GB. `heavy`
  refuses to queue below it, naming the floor, what is free and the
  ten largest targets, worktrees and caches. It also collects the
  build cache (`kache gc`) after each task and every two minutes of a
  gate, since the cache holds its limit only when collected.
- **Repins.** A repository's `Cargo.lock` pins its upstreams' git
  revisions. A repin moves a pin to the upstream's `origin/main` (`heavy
  cargo update -p <one of its packages>`; jig moves smith and skein
  together), runs `heavy cargo check --workspace --all-targets`, repairs
  what breaks, and lands with the gate. Its repairs: the pins, what an
  upstream trait now requires, names that moved, and the tests an
  upstream change of behaviour breaks, in at most about 200 lines and
  no change of design. A conflict in `Cargo.lock` is never merged by
  hand: take `origin/main`'s and update again.
- **Breaking upstream.** An upstream change that breaks a downstream
  build, and a repin of a repository others also repin, wait for the
  director's word: it orders them across owners and runs. In a set
  they wait for no one's: the break lands with its downstream fix
  (landing-flow.md 3, 9.1).
- **The footprint.** An owner's notes list the repositories, crates and
  protocols it changes, and the repins it needs. Its product owner
  orders owners whose footprints overlap, the director across products
  (product.md 3), and the set lock their landings (landing-flow.md
  9.1).

### 4.6 QA passes

An owner or a sub-owner may give its part QA passes while it
implements, or decide that none is warranted. It decides only when: when
to start its tester, resume it after more has landed, stop it, and when
it is happy with what the passes have done. A milestone's end is the
natural point for one, beside the next milestone (3.1).

- **The tester** is a QA agent, a Codex session under
  [qa.md](qa.md) and [qa-milestone.md](qa-milestone.md), which say how
  it works, with its notes beside the owner's, in `qa/`, and its passes
  in the record's `qa.md`. It never reads the code under test or its
  tests.
- **The tester decides which tests to write,** not the owner: the owner
  names the part and the design, never the cases.
- **A missing fake or hook** that a test needs, the tester names, and
  the owner decides whether its layer grows it, as ordinary work under
  that layer's own tests.
- **A suite apart.** Their test binaries are named `qa_<area>`. The
  repository's nextest default and fuzzy profiles exclude
  `binary(/^qa_/)`, and a `qa` profile selects them: `cargo nextest run
  --workspace --profile qa`. The gate builds them but does not run them,
  and no test-time ceiling counts them. The first owner to add one to a
  repository adds the profiles.
- **Each failure is the owner's to judge.** A bug that triage lets in
  (below) is fixed, by an implementer task (landing-flow.md 3), and its
  regression test goes in the default suite, in the lowest world that
  owns the behaviour, under testing-strategy.md. A test that misreads the design is corrected or
  dropped, and a design that let it is made clearer. A gap the owner
  accepts stays, as `#[ignore = "<why>"]`. Each finding's disposition
  goes beside it in `qa.md`: fixed in a commit, sent to the backlog, a
  gap kept, or not a defect. When the owner ends a pass, the `qa`
  profile passes.
- **Findings are triaged until v0.1.0** (the user, 10-22). A bug that
  any QA finds is fixed now only when it lies on v0.1.0's happy path.
  That covers an owner's pass, the external loops and an after-landing
  run alike. The happy path is the roadmaps' stories and pages, used
  as intended, in ordinary conditions. A security hole, lost data and
  a flake that fails gates count as on it, and so does what the
  mission's own end requires. Anything else waits: a
  corner case, a race under load, a rare condition. Its owner sends it
  to its product owner (a sub-owner, through its parent) as one entry:
  what fails, where, its reproduction, and why it is off the happy path.
  The product owner keeps it in its backlog (product.md 4), Infra's the
  director, and its test stays `#[ignore = "backlog: <why>"]` where one
  exists. When unsure, the owner asks its product owner.
- **Its tests land** like any other (section 4.4), with the pass's
  fixes, by the owner.

Lab runs, QA agents driving a running build through `temper ctl`, are
the product owner's call, and their findings come to an owner through
it ([qa-lab.md](qa-lab.md)). They are judged as a pass's are.

## 5. Escalation

- An implementer asks its owner, a sub-owner its parent, an owner its
  product owner (Infra's, the director), a product owner the director,
  and the director the user.
- By post, on one machine or across them: `post send PARENT@MACHINE
  "<subject>"`, the report or question in at most 15 lines, and the
  turn ends. A message goes to one parent only, never to two. The
  answer comes by post. A send that exits 2, not delivered, goes to the
  director instead, with the reason; on exit 3 the message waits in the
  parent's mailbox, and the director's watcher reports it if it stays
  unread.
- **A tool the kit lacks** (a watcher, a launcher, a sweep) is
  escalated like a question, through the parents to the director, and
  never written beside the kit: the director gives it to Infra or
  declines it (cleanup.md 2).
- The director asks the user only what has long-term consequences that
  would be hard to change, or what the user's rules keep theirs. An
  owner never uses AskUserQuestion.

## 6. The closing note

When its mission has landed, the owner writes `closing.md` in its
record, in at most half a page:
- what landed, with its commits;
- what is left of the draft past the mission's end, for the next
  mission's brief;
- the wall time from its start to its last landing, and the sessions'
  and builds' totals from `record runs`;
- with more than one milestone, each one's time against the cap, and
  how the plan changed and why;
- for a world it added to, the test time at its start and at its end;
- its QA passes: how many, what they found, and the tests left ignored;
- what went well and what didn't, in this process.

It commits the note with the README's `state`, `ended` and `end` set,
points its parent to it, and the owner's session ends. The director
compares the notes across owners, to judge what in this file pays and
what to change.
