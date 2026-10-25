# Owners

Provisional, rewritten 2026-10-25. How an owner takes a mission to
`main`: it designs each milestone's boundary, checks it, and hands an
implementer a task it finishes alone. Its department's file
([app.md](app.md), [ui.md](ui.md), [infra.md](infra.md)) adds its scope,
its model and its own rules.

**Read at the start:** the whole brief, the department's file, sections
1 to 4 of this file, the security rules (director.md 10), and for App
and UI, section 1 of skein's `docs/foundation/programming-model.md` and
`testing-strategy.md`. Sections 5 to 10 are read before the work they
govern. A repository's `AGENTS.md` is read before touching its code. A
read put off never puts off a rule.

## 1. In one page

- **A mission** takes a draft, or a part of one, to `main`, in at most
  four milestones, each at most 4 hours. Then the owner writes its
  closing note and stops.
- **A milestone** is an MVP on the one before, with one owning
  boundary, planned at 2 to 3 hours: about 45 minutes of design and
  checking, 1.5 to 2 hours of implementing, then the landing.
- **One task per milestone, or a few.** The implementer is Codex,
  gpt-6.1-sol at high, alone and unattended from start to report. It
  does in 6 or 7 minutes what an owner would once have planned as 30:
  a milestone is one task, not ten.
- **The owner's part is the boundary:** the shapes that cross a crate,
  a repository, the wire or a stored format, one or two acceptance
  stories, the refusal case, the scope. The interior is the
  implementer's.
- **Checked, not long.** The tasks that failed rested on premises no one
  checked, not on too few words. Every premise is checked against
  `main` by a Codex survey before the task goes out. More prose is more
  ways to be wrong.
- **A task out is never changed.** What the owner learns while it runs
  waits for the report.
- **Small work, directly.** What takes less than writing its task, the
  owner does itself.
- **Land promptly.** A branch left unlanded rots as `main` moves.
- **Claude for taste, Codex for the rest.** Claude's tokens are the
  scarce ones: the owner spends them on the design, the task and the
  check of the diff. Implementing, surveys, checks, investigations,
  repins and QA passes are Codex's.
- **The design is the blueprint.** A repository's `docs/design/`
  specifies the project whole, and the code converges on it.
- **Rules:** four milestones, the 4-hour cap, the security rules, and
  what the tools enforce (`land` and its gate, `heavy`, the disk floor).
  programming-model.md, testing-strategy.md and the testing documents
  bind App's and UI's code; infra.md binds Infra's tools. The rest of
  this file is guidance, applied with judgement.

## 2. The mission

- **The plan,** `plan.md` in the record, before anything else: a rough
  design that settles early what would be hard to reverse (a stored
  format, an interface between repositories, a protocol's shape), then
  the milestones, each with the MVP it delivers, the story that shows
  it, its owning boundary and its rough size. It opens with a summary
  of at most 15 lines, and waits for the parent's check (3.2).
- **Milestones.** Where the draft lists them, they are adopted; the
  owner may split one, and anything else goes to its parent. A mission
  that would need a fifth ends nearer: the rest goes to the next
  mission, with a fresh owner.
- **The shape of one:** one owning boundary. Too big is a mix more than
  a length: a stored format, restart semantics, pricing and two
  repositories together failed where each alone would have fit. Work
  that crosses repositories goes upstream first, its downstream
  follow-through (a repin, a match arm) in the same set. Where two parts
  meet (a client and its server, a domain and its store), the first
  milestone that builds either runs them together.
- **Who drives.** With one milestone, the owner. With more, a sub-owner
  per milestone, `o/<name>-m<N>`, on the owner's machine, started when
  the milestone before has ended; its brief is the head of `m<N>.md`.
  The owner keeps the plan, checks each milestone's report and answers
  its sub-owner. No two milestones run at once.
- **The cap: 4 hours** from a milestone's start to its end, as
  `m<N>.md`'s `started` and `ended` record them. A driver that sees its
  milestone won't fit asks for a split early. At the cap the milestone
  pauses (it starts nothing new; what runs finishes) and its owner
  escalates: what has landed, the cause, the options, a recommendation.
- **The plan moves** as the work teaches, most often by a split, and the
  next report says so.

## 3. A milestone, step by step

1. **Design the boundary.** Within the plan's rough design, and no
   further. What the milestone changes in `docs/design/` is one of two
   kinds:
   - what is hard to reverse (a public API across crates, an interface
     between repositories, a stored format, a protocol, who owns a
     lifecycle) lands first, by the owner, with `land --docs`;
   - everything else goes in the task, as the text the owning sections
     get, and lands with the code.
   The owner settles what the draft leaves open, and escalates only what
   changes the draft's goal, constraints or expectations, or what is
   hard to reverse and crosses its part (section 9).
2. **Report,** in `m<N>.md`, at most 15 lines: what the milestone
   builds, the boundary it changes and where its design is, departures
   from the draft or the plan, what is open, the task or tasks. The owner
   commits it and points its parent to it. It waits for the parent's
   green light only when the design landed first; otherwise the task
   goes out at once, and the parent's brief check (against the draft's
   direction, not a review) comes beside the run.
3. **Write the task** (section 4), 20 to 30 minutes.
4. **Check it.** A Codex survey takes the finished task and checks every
   name, file, signature, fixture and behaviour it assumes against
   `origin/main`, the acceptance stories' setup above all, in 10 to 15
   minutes. What fails is fixed in the task.
5. **Launch** (section 5) and end the turn. The run's post wakes the
   owner.
6. **Read the report.** A `Question:` is answered by resuming the run
   with the answer. A finished run's diff is checked, lightly: it keeps
   to the task's shapes and scope, its acceptance stories are there, in
   the right world, asserting what the task said, and the report shows
   them run and passing, with the changed packages' clippy. A sub-agent
   may check a large one.
7. **Land** (section 6).
8. **End,** when the milestone's set is in the landing queue: the driver
   updates the repository's `docs/design/STATUS.md` rows, runs `record
   runs <m> <N>`, and writes the end report in `m<N>.md`, at most 10
   lines: what the MVP does now, the commits, the time against the cap,
   the design and check minutes against the run's, what the run needed
   after it (questions, repairs, failed landings), what comes next. It
   points its parent to it. The owner hands over to a fresh session
   (section 7) for the next milestone; a QA pass may start beside it
   (section 8).

**Design documents.** A milestone changes in place the documents that
own what it touches, and adds one for an area that has none. They hold
what a regeneration of the code could change that we would mind: the
public APIs and boundaries, the behaviours, the protocols, the stored
formats, the crates' layout, the test worlds and their stories. Each
describes the project as designed, never a change. The house style: a
title and a dated status line; "1. In one page" first, with bold-led
bullets, then numbered sections, cited as "io.md, 6.3", never
renumbered; contracts, not history; numbers in the documents the
repository names for them; what no decision settles under "Open
questions".

## 4. The task

The implementer reads its task literally and knows nothing of owners:
the task never names one. How it builds, tests, lints, formats and asks
is [implementer.md](implementer.md)'s, never repeated. The first line
is: "Read `~/src/rust/agents/roles/implementer.md` first; this task
departs from it only where it says so." A departure says its reason.

**It specifies:**
- the goal, in two or three lines;
- where: the worktree, the branch, the `origin/main` it was checked
  against; commit and push the branch, do not land;
- what to read: the owning design's sections by path and number, never a
  whole design, and the files where the change lands;
- the shapes that cross a crate, a repository, the wire or a stored
  format: the types, signatures and names, and the text the owning
  documents get;
- one or two acceptance stories at the owning boundary, in the world
  the testing documents name, and the refusal or failure case;
- the files in scope, with the mechanical follow-through of the change
  (a call site, a match arm, a test's expected value), and what is out
  of scope. Shared files (`docs/design/STATUS.md`) stay out;
- one authority statement: what the implementer may decide, and the one
  fallback when a premise proves false (stop with `Question:`, or a
  named alternative). No approval gates, no prerequisites to verify;
- done when: the tests that pass, with their packages and binaries, and
  what the report brings back.

**It leaves to the implementer** the private mechanisms, helper names,
tests beyond the acceptance ones, and the order of work. Where a private
mechanism is a real choice, the task says what it must guarantee, not
how.

**It asks for the proof the change needs,** no more: no timing triplets,
A/B pairs or repeated suites unless the change is a measurement. The
gates run the lints and the focused and fuzzy suites at landing.

**The work it shapes:**
- **coherent:** the branch is whole at the end, with nothing half-built
  and no dead code; transitional code names what removes it;
- **open behaviour stays open** until the owner decides it: the
  implementer never does;
- **proved at the highest layer within reach:** the first joint,
  process or real-loop story as soon as the code can run it;
- **where two sides meet,** one thin story runs both, the real thing on
  each side, and their vocabularies translate exhaustively from the
  first types, so that drift is a build error; a fake's scenarios also
  run against the real side;
- **test cost:** a new world costs at most about 2 s focused and 10 s
  fuzzy (provisional, 10-22); a suite's first breach of its budget is
  profiled and its tests made cheaper, never the budget raised;
- **words have readers:** whoever changes words a person or an agent
  reads (a refusal, a label, a line `temper ctl` prints) updates every
  test that reads them, in any department.

A task runs to about 80 to 200 lines.

## 5. Running Codex

```
codex-run task --effort EFFORT TASK WORKTREE REPORT
```

Paths are absolute, the report fresh; with two repositories, WORKTREE is
the directory that holds both worktrees. A bad launch is refused at
once, with exit 2. The run goes on in the user unit `codex-run-<id>`,
and its post wakes the owner: `run <id> ok: <the report's first line>`,
or `failed`, with the report's path. `--read-only` serves a survey or a
review. `--resume RUN TASK REPORT` continues a run's thread with a new
task: an answer, or the repair of what a gate found.

- **Effort:** high for a milestone's task, medium for plain work: a
  survey, an inventory, a repin.
- **Surveys and checks** go to Codex too, through `codex-run task
  --read-only`, never a bare `codex exec`, with a brief that names the
  question and where its report goes; its post wakes the owner. An investigation's report gives
  the cause, the evidence and the fix it proposes.
- **When the work gets hard** (two tries without the cause, conflicting
  evidence, a fix that reaches across a boundary), Opus 5.5 at xhigh
  advises from the report and the evidence, through `claude -p` or a
  sub-agent.
- **Changing course:** a task out is never edited. If a run must change
  course, stop it (`systemctl --user stop codex-run-<id>`) and resume
  it with one statement of what changed and what holds now. A
  133-minute run whose authority and base changed under it drifted and
  ended unlanded.
- **Claude implements** only when Codex is out, or when the task is
  mostly taste. Sonnet is parked while Codex has room.

## 6. Landing

The owner lands with `land`, from a clean worktree on the branch: it
rebases on `origin/main`, builds and lints, runs the repository's gate
(`scripts/check.sh`) through `heavy --gate`, records the evidence in the
tip commit's trailers, and pushes. In skein, smith, hearth, jig and
temper it proves the change first (`land --no-push`), then takes the set
lock on hetzner3 to rebase, gate and push. A set across repositories
lands with `land-set` (landing-flow.md 9.1), which repins downstream.
`land --docs` lands Markdown alone, mockups included, without the gate.
Exit 3 is a rebase stopped on conflicts; 4 a failed build, lint or gate;
9 heavy refused, so nothing ran.

**A failed landing** is read before anything runs again: where it failed
(the repository, the step, the failing lines first); whether the failing
test, or a crate it builds on, is in the set's diff or downstream of it;
what `main` changed since the set's base; what `land-set` did (the
rebase, the repin); the machine (a killed process, a full disk, the
network, load); the history of that test. When in doubt it is the set's:
the implementer repairs it (`--resume`), and the set is proved again. A
flake (a test outside the set's reach whose failure depends on timing)
is filed as a finding and the landing run again, once. Escalated, with
the evidence and a recommendation: `main`'s fault, an infrastructure
fault that lasts 15 minutes, a set's third failed landing, two missions
whose sets keep breaking each other.

## 7. The session

- **Started by its parent** in `~/src/rust` of its machine, named
  `o/<name>`:
  `claude --bg -n o/<name> --model 'claude-opus-5-5[1m]' --effort <effort>
  --autocompact 282000 --dangerously-skip-permissions --settings
  '{"autoMemoryEnabled": false, "env": {"POST_NAME": "o/<name>"}}'
  "Read ~/src/rust/records/missions/<m>/README.md and do what it
  says."`
  Its effort is its parent's choice, raised when the output falls short.
- **A Codex owner** (Infra's, or a part that needs little taste) runs in
  the unit its parent started (director.md 4), keeps one thread, and
  takes its taste from an Opus 5.5 xhigh one-shot. Its sub-owners are
  `codex-run owner --effort E o/<name>-m<N> <its m<N>.md>`, ended with
  `systemctl --user stop codex-owner-$(systemd-escape NAME)`.
- **Mail** is post (`docs/design/post.md`): the address is
  `o/<name>@<machine>`. Each turn ends with the waiter, `post wait
  o/<name>`, in the background; when it ends, `post read o/<name>`, act,
  start it again. A Codex owner's loop is its waiter.
- **The brief** is the mission's README in the record
  ([records.md](../docs/design/records.md) 4), written by the parent:
  front matter (department, parent, machine), summary, input, and what
  bears on it (other owners' footprints, budgets, dates). The owner keeps
  its front matter: `state`, and at the end `ended` and `end`.
- **The record,** `~/src/rust/records/missions/<m>/`, committed with
  `record commit <path>`: `plan.md`, `decisions.md` (its calls, numbered,
  with reasons), `m<N>.md` (brief, report, end report, the `record runs`
  table), `qa.md`, `closing.md`. A report is one of these files,
  committed, and the parent is pointed to it in one line naming the file
  and the commit.
- **Notes,** scratch in `~/src/rust/tmp/owners/<m>/`: `notes.md` (state,
  open questions, footprint), kept short and true; `handover.md`. No
  scripts ([cleanup.md](../docs/design/cleanup.md) 2): throwaway code
  lives in a worktree.
- **After a compaction or a restart,** brief and notes first.
- **A fresh session per milestone.** At a milestone's end but the last,
  the session brings `notes.md` and `plan.md` up to date, writes
  `handover.md` (what is in flight, what waits on others, its read of the
  next milestone), starts the new session with the same name and
  command, prompted "Read <brief>, then the notes and handover.md in
  <notes directory>, and go on.", and ends its turn. The new session
  starts its waiter, stops the old one (`claude stop <id>`), and starts
  the next sub-owner. The ended milestone's sub-owner stays on for its
  landing and its QA pass.
- **Context is the scarce thing.** Code is read through Codex surveys
  and reports, never a run's log. The owner ends its turn while
  implementers run, and never polls.

## 8. Machines and QA

- **Worktrees** under `tmp/owners/<m>/m<N>/`, one per implementer, never
  a primary checkout; a worktree's `target/` is cleared as soon as its
  branch lands. Worktrees of different repositories may share a target
  directory through `CARGO_TARGET_DIR` (its real path, never a link);
  two of one repository never do.
- **`heavy`** is the only way to build and test. Below the disk floor
  (40 GB unless `tmp/machine.env` says otherwise) it refuses, and no new
  implementer starts.
- **The gate holds on every machine** that builds the repository, x1 the
  slowest: a new test stays within half its budget.
- **After landing,** the slow tiers (`scripts/after-landing.sh`) run
  nowhere while the user's pause stands. A task that needs one names it.
- **Repins** move a pin to the upstream's `origin/main` (`heavy cargo
  update -p <package>`; jig moves smith and skein together), repair what
  breaks in at most about 200 lines and no change of design, and land
  with the gate. A `Cargo.lock` conflict is never merged by hand: take
  `origin/main`'s and update again. An upstream break, or a repin others
  also make, waits for the director's word, except inside a set.
- **The footprint** (the repositories, crates and protocols it changes,
  the repins it needs) is in the notes; the product owner orders owners
  whose footprints overlap.
- **QA passes** are the owner's choice, most naturally at a milestone's
  end. The tester is a Codex session under [qa.md](qa.md) and
  [qa-milestone.md](qa-milestone.md): it never reads the code under test,
  and it chooses the cases; the owner names the part and the design. Its
  binaries are `qa_<area>`, run by the `qa` profile only. Each finding is
  the owner's to judge, its disposition in `qa.md`. Until v0.1.0 a bug is
  fixed now only on v0.1.0's happy path (the roadmaps' stories, used as
  intended; security holes, lost data and gate-failing flakes count as
  on it); the rest goes to the product owner's backlog, its test
  `#[ignore = "backlog: <why>"]`. Lab runs are the product owner's call
  ([qa-lab.md](qa-lab.md)).

## 9. Escalation

- An implementer's question comes in its report, and the owner answers
  by resuming the run. A sub-owner asks its parent, an owner its product
  owner (Infra's, the director), a product owner the director, the
  director the user.
- By post: `post send PARENT@MACHINE "<subject>"`, at most 15 lines,
  with the options and a recommendation, to one parent only; the turn
  ends. Exit 2, not delivered: to the director instead. Exit 3: it waits
  in the parent's mailbox.
- A tool the kit lacks goes to the director, never beside the kit.
- An owner never uses AskUserQuestion.

## 10. The closing note

When the mission has landed, `closing.md`, at most half a page: what
landed, with its commits; what is left of the draft, for the next
mission; the wall time and the `record runs` totals; each milestone's
time against the cap, and how the plan changed; each task's design and
check minutes against its run's, and what the run needed after it; the
test time of each world it added to, at its start and its end; its QA
passes and the tests left ignored; what went well and what didn't. It
commits it with the README's `state`, `ended` and `end` set, points its
parent to it, and its session ends. The director compares the notes
across owners, to change this file.
