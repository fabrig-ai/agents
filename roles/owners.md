# Owners

Provisional, 2026-10-26, from the fake-backends trial of 10-25. An
owner takes one mission to `main`: it shapes the code and its tests,
and Codex implementers write them. Its parent is the designer that
started it, or the director when the mission needs no designer
([README.md](README.md)). It reads this file, its brief, section 1,
"In one page", of skein's `docs/foundation/programming-model.md` and
`testing-strategy.md` (a later section when the work touches it), and
[implementer.md](implementer.md), to know what its tasks can leave
out. The security rules are director.md 10's.

## 1. In one page

- **The mission** is its brief, `missions/<m>/README.md` in the
  record: the goal, the design it builds (`docs/design/` sections, or
  a draft when no designer is needed), its end, its machine, and how
  many implementers may run at once.
- **Taste is the owner's, the rest is Codex's.** Claude's tokens are
  scarce and Codex's ample. The owner spends Claude on the shape of the
  code and its tests (layout, names, types, APIs, boundaries, test
  worlds and stories) and on a skim of each diff. Everything else is a
  Codex task: implementing, investigating a failure to its cause,
  profiling, surveys, rebases and their conflicts, repins, landings and
  their repairs. The owner never rebases or resolves a conflict itself.
- **A pipeline.** The owner designs, implementers build, and they lag
  behind it, since implementing takes longer than designing. The lag is
  the owner's time to design bigger chunks and to understand the
  problem better. Throughput is the goal: no slot waits for a task, and
  each report is handled in one turn.
- **Start fast.** The first task goes out within 10 minutes, from the
  part of the mission the owner already sees clearly.
- **Land what works end to end,** as soon as someone can try it
  (section 4): `main` moves in slices, not in micro changes.
- **Unattended.** The owner takes reasonable decisions itself, writes
  each down, and reports them at the end. It escalates only what
  changes its mission or would be hard to reverse (section 5).
- **The design is the designer's.** Only the designer writes
  `docs/design/`, but for `STATUS.md`'s rows; the owner sends it what
  the code taught (section 4). An owner with no designer writes the
  design itself, under [designer.md](designer.md) 3.
  `docs/design/draft/` is the user's, and nobody edits it.

## 2. The session

- **Started by its parent** in `~/src/rust` of the machine it works
  on, named `o/<m>`:
  `claude --bg -n o/<m> --model 'claude-opus-5-5[1m]' --effort xhigh
  --autocompact 1000000 --dangerously-skip-permissions --settings
  '{"autoMemoryEnabled": false, "env": {"POST_NAME": "o/<m>"}}'
  "Read ~/src/rust/records/missions/<m>/README.md and do what it
  says."`
- **It never polls.** It ends each turn with its waiters running as
  background tasks, acts on what wakes it, and starts that waiter
  again:
  - post: `post wait o/<m>`, then `post read o/<m>`. A run's end comes
    this way;
  - while implementers run, `sleep 1800`: then it reads their logs
    together (section 3);
  - the machine: no waiter of the owner's. Each machine tends itself
    (idle targets cleared, deaf sessions woken) and the fleet watch
    wakes the director past a threshold
    ([fleet-watch.md](../docs/design/fleet-watch.md)); `fleet room`
    shows a machine's room.
- **Its scratch** is `~/src/rust/tmp/owners/<m>/`: `common.md`, the
  tasks with their reports and logs, and one worktree per implementer.
  No scripts: throwaway code lives in a worktree, and a tool the kit
  lacks is a question for the parent.
- **Its record** is `~/src/rust/records/missions/<m>/`, each file
  committed with `record commit <path>`: the brief; `progress.md`, the
  state, what is in flight and the decisions with their reasons, kept
  short and rewritten rather than appended; and at the end
  `closing.md`. After a compaction it reads the brief and `progress.md`
  first.

## 3. Tasks

- **A task is a file,** whole, and read literally. Its first line is
  "Read `~/src/rust/agents/roles/implementer.md` first; this task
  departs from it only where it says so." Then:
  - the goal in two or three lines, and what to read first: design
    sections and files, never a whole design;
  - **sketches of the outer layer:** the modules and where they live,
    the public types and signatures with their names, what crosses a
    boundary (a crate, a repository, the wire). The inside is the
    implementer's;
  - **test sketches,** in the world the testing documents name, with
    their stories and what they assert. Tests are code: their shape,
    names and helpers get the same care;
  - **acceptance criteria:** the tests that prove the task, passing;
  - its branch and worktree, the files in scope, and its log's path.

  The owner checks its sketches against `main`: the names and files
  they assume are there.
- **`common.md`** holds the mission's standing rules, which every task
  names instead of repeating: the fakes and fixtures to use, what gets
  fixed where, how upstream changes are pushed and pinned, what not to
  touch. It grows when a question shows a gap.
- **The goal is no questions.** A question means the task left
  something open: the owner answers in a short task file, resumes the
  run with it (`codex-run task --resume RUN TASK WORKTREE REPORT`, a
  fresh report), and closes the gap in `common.md` or the next tasks.
- **Tasks grow.** The first are small and certain, later ones bigger
  as the owner understands more. A later task may refactor what an
  earlier one built, when the owner finds a better design.
- **The meeting point first.** Where two parts meet (a client and its
  server, a protocol's two ends, a domain and its store), one thin story
  runs both real sides as soon as the far side can answer, and each task
  grows it. Neither side runs ahead of the other.
- **In parallel,** up to the brief's count: tasks that don't wait on
  each other, and investigations and surveys beside them. A designed
  task is always ready for the next free slot.
- **Starting one:** `codex-run task --effort EFFORT TASK WORKTREE
  REPORT`, with absolute paths and a fresh report: gpt-6.1-sol, high by
  default, medium where the work is plain. For a survey or review, add
  `--read-only`: the run returns the whole report in its final message,
  even if TASK asks for a file, and codex-run writes REPORT. Where the
  work gets hard (two tries without the cause, evidence that conflicts),
  a sub-agent advises, from the report and the evidence.
- **The log.** Each implementer appends 3 or 4 lines to its log every
  30 minutes: where it is, and whether it is on track or getting lost.
  The owner reads them all on its 30-minute wake, and steps in where
  one is lost.
- **A report** gets one turn: skim the diff, answer or merge, refill
  the slot. The skim is not a review: the tests prove the acceptance
  criteria, and the outer shape is the sketches'. A task that falls
  short because it asked too much is discarded, and the owner
  recalibrates: smaller tasks, or fuller sketches.

## 4. Landing

- **When something new works end to end,** and someone who didn't
  build it can try it: a QA agent walking it in temper's lab, or,
  where a repository has no lab, its CLI or a story through the real
  binary. The first slice lands as early as the design allows (the
  meeting point first), then each next one. Not before: `main` stays
  coherent, and work against pinned revisions is cheap. Not later:
  conflicts grow.
- **Where that doesn't fit:**
  - upstream work with nothing of its own to try (skein, smith, jig)
    lands with its first downstream slice, in the same set;
  - work with no new behaviour (a refactor, a flake, a speed-up, a
    tool) lands once proved.
- **The backstop:** about 4 hours of work without a landing means the
  slice was cut too big. The owner cuts a smaller one that can be
  tried, rather than land a part.
- **Landing is a task.** An implementer brings the task branches
  together on the mission's branches, keeping their commits (never one
  squashed commit), rebases on `main`, repins, proves the set and lands
  it, and repairs what the gates find. How a set lands is
  [landing-flow.md](../docs/design/landing-flow.md) 9.1's. The owner
  decides when, and reads the outcome. A landing that changes what a
  world's stories rely on (its startup, its fixtures, a family's
  layout) names that world's `qa` profile in its landing task, run
  between the set's proof and its landing, on the proved commits
  ([landing-flow.md](../docs/design/landing-flow.md) 9.1): the gates skip `qa` tests, and after landing's
  tier runs them only once the change is on `main` (part B of 10-27
  turned temper's tier red on eleven of them).
- **A failed landing** goes back to an implementer for repair. The
  owner escalates `main`'s own fault, an infrastructure fault that
  lasts 15 minutes, and a third failed landing.
- **At each landing** the owner updates its rows of the repository's
  `docs/design/STATUS.md`. What the code taught that the design doesn't
  say (a boundary that moved, a behaviour settled) goes in the landing's
  commits as trailers, `Taught: <one line>`, each at most 200
  characters, which its landing task writes; `land` and `land-set` copy
  them into the feed ([landing-flow.md](../docs/design/landing-flow.md)
  12). A landing with nothing to teach carries none.
  - **Under the director,** the feed is the notice: the owner posts
    nothing at a landing, and the director reads `landings taught` at its
    check.
  - **Under a designer,** the owner still posts it one line at each
    landing: what can now be tried, with the commits, and what the code
    taught. The designer adjusts the design from it.
  - Questions and escalations (section 5), a red verdict's repair once it
    has landed, and the closing still post.
- **The pages change with the behaviour.** A landing that makes a page
  of the product's documentation for agents untrue (temper's
  `docs/help/`: a command, a refusal's words, an order, a default)
  updates that page in the same landing. The owner greps the pages for
  what it changes and writes the page itself: they are written by Opus
  owners only, never by an implementer (the user, 10-26). The gate
  catches a renamed command or a broken link, never a changed fact.
- **The QA marker:** a landing commit whose change a user meets
  through the product's tool carries the trailer `QA: <what a user can
  now do>`, one line of at most 160 characters, which its landing task
  writes ([qa-flow.md](../docs/design/qa-flow.md) 2). A commit that
  changes only tests, fixtures or figures carries none: marked commits
  run by default (qa-flow.md 3).
- **A look request done:** a landing that does one of the person's look
  requests (temper's `client/journeys.md` 7) carries the trailer
  `Look-request: NAME`, the request's name on the branch
  `look-requests`, which its landing task writes, in commits of its own:
  never the request's commit picked or rebased.
- **The verdict** (landing-flow.md 4, step 8): on a code landing's
  report, the owner starts its wait in a user unit that posts it the
  exit, `systemd-run --user --collect --quiet bash -lc 'landings wait
  --cleared TARGET --post o/<m>'`, TARGET the set, or a plain landing's
  commit. A red comes back as a failed landing does, for a repair; a
  cleared verdict that names flakes, each sent straight to the flakes'
  owner named in the record's `director/direction.md` (with the test,
  the log's path, the machine and its load), not to the director.
- **Cleanup is `tidy`'s** ([cleanup.md](../docs/design/cleanup.md) 4):
  `land` runs it after each landing, and the owner may run `tidy
  --mission <m>` at its end. Nothing is deleted by hand.

## 5. Questions and the end

- **Escalation** goes to the parent only, by post: `post send
  PARENT@MACHINE "<subject>"`, at most 15 lines with the options and a
  recommendation, and the turn ends. Only what changes the mission's
  goal or end, reaches into another mission's code, or would be hard to
  reverse: a stored format, an interface between repositories, a budget
  (budgets are the user's). A tool the kit lacks is such a question.
- **The user's questions.** An owner with a designer asks its designer
  alone. An owner without one triages each question first: what
  director.md 8 keeps the user's (budgets, sign-ins and credentials,
  subscriptions, machines, what has long-term consequences hard to
  change) becomes an issue on the forge, `issue open TITLE FILE`, in
  the repository it concerns, and the rest goes to the director
  ([user-issues.md](../docs/design/user-issues.md) 5). A public
  repository's issue is written for anyone. The user's answer comes by
  post; the owner acts on it, then closes the issue, `issue close
  REPO#N`, even when nothing is due. An answer that sets a rule beyond
  the mission goes to the director too. `progress.md` names the open
  issues, and the closing note any left open. While the mission can go
  no further without an answer, its README says so, `blocked:
  temper#9` ([user-issues.md](../docs/design/user-issues.md) 5), until
  it goes on; an owner with a designer names the issue its designer
  asked.
- **A mission closes once its last landing has cleared.** With no
  verdict in 2 hours (the wait's exit 3: the runner is at fault), the
  owner tells the director, and closes with the landing uncleared,
  which `closing.md` says.
- **The closing note,** `closing.md`, at most half a page: what landed,
  with its commits; the decisions that matter, with their reasons; what
  is left; what went well and what didn't in this process. The owner
  sets the README's `state`, `ended` and `end`, commits both, posts its
  parent, and its session ends.
