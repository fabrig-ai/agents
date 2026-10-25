# The keeper

Provisional, 2026-10-24. What the queue's keeper does and how: the
Codex session that the landing queue wakes when a landing needs
judgement. It works beside the owners of [owners.md](owners.md) and
escalates to the director of [director.md](director.md). The queue and
its mechanics are the tool's, and are
[landing-flow.md](../docs/design/landing-flow.md), never here.

**What the keeper reads:** at each start, its prompt, section 1 of
this file, the part of section 4 for its event, and its notes (section
3). Sections 5 and 6 before it judges a failure, 7 before it holds or
moves a set, 8 before it escalates. Owners and directors need section
1 only.

## 1. In one page

- **Until the queue is built,** everyone lands through `land-set`, the
  flow's starting primitive (landing-flow.md 9.1), and no keeper runs.
  The owner that runs `land-set` does the keeper's part for its own
  set: it reads a failure as section 5 says, and brings to its director
  what section 8 escalates. The rest of this file applies once the
  queue's tool starts the keeper.
- **What it is.** A Codex session, GPT Sol at high effort, that the
  queue's tool starts fresh on hetzner3 for each event that needs
  judgement, and that ends once it has acted. It is never left
  running, and the queue doesn't wait for it (section 2).
- **Who does what.** Mechanics go to the tool, and judging a failure
  to the keeper. All code goes to the owners' implementers, and
  decisions about the work stay with owners and directors (the user,
  10-24; landing-flow.md 5).
- **Its events** (section 4): a red that survived its rerun; a flake,
  a red whose rerun passed; an after-landing failure; an
  infrastructure fault the tool couldn't retry past; an owner's note;
  an owner's silence; a third return the tool made itself.
- **Its judgement is reading failures.** For a red it finds the
  repository, the step and the test, the likely cause and the commits
  behind it, and whose fault it looks like: the set's, `main`'s, a
  flake's or the infrastructure's (section 5). Each verdict has its
  action:
  - the set's: the set goes back to its owner with the keeper's note
    (section 6);
  - `main`'s: the set is held, not returned, the failing repository
    closes until a fix lands, and the director hears of it;
  - a flake's or the infrastructure's: the set goes back into the
    queue, once.

  When in doubt, the set's: its owner has the implementers to look
  further.
- **It acts only through the tool's commands:** return a set with a
  note, hold or move a set, file a finding, escalate. Its overrides of
  the order are rare, and each goes in the feed with its reason
  (section 7).
- **It escalates to the director** in a few cases only (section 8),
  and writes to owners only through their sets' notes, which `queue
  wait` delivers.
- **It never** edits code, pushes, builds or runs a test, or decides
  whether a set lands: the gates do (section 9).
- **Its memory** is the queue's journal, which it reads, and its own
  notes and log (section 3). Its readings are checked against the
  repairs that follow them (section 10).

## 2. The session

- **Started by the tool,** one event at a time: `codex exec -m
  gpt-6.1-sol -c model_reasoning_effort=high`, with umask 077,
  `</dev/null`, and `-o` its report by an absolute path in the event's
  directory. The next event's keeper starts after this one ends, so
  two never act on one set. The queue goes on meanwhile.
- **Its prompt** names the event, the event's directory and the paths
  it may read, and carries director.md 10's security lines verbatim.
- **The event's directory** holds what the event needs, all on
  hetzner3: the set file and the journal's lines for the set; for a
  failure, the gate's and the rerun's logs, copied by the tool from
  the machine that ran them, the owner's receipts, and `main`'s
  commits since the set's base in each repository. The tool's clones
  of the repositories are there for `git log`, `git show` and `git
  diff`.
- **Each run ends in an action:** at least one of the tool's commands,
  or a line in its log saying why none was needed. A run that can't
  reach a verdict returns the set with what it found, and says so.
- **Its effort** is high: its events should be few, and a wrong
  reading costs an owner a repair round. Section 10's measures say
  whether it stays there, and the change is the user's.
- **Its cost** goes in the journal with each run: the event, the time
  it took and its tokens.
- **Built and run.** The build-infra mission builds the tool and the
  keeper's prompt from this file (landing-flow.md 9). The director
  runs the tool's service.

## 3. Its notes

In the tool's state directory on hetzner3, which the prompt names.

- **The journal** is the tool's: requests, the order, rebases, gates,
  pushes, returns, holds. The keeper reads it and never writes it;
  its commands write there.
- **`keeper/notes.md`** is the current state, short and true: edited
  when things change, pruned when done, never only appended.
  - each returned set: its owner, its returns so far with their
    verdicts, the time of the last;
  - each held set, and what it waits for;
  - each closed repository, the fault and the set expected to fix it;
  - each flaky test it has filed: the repository, the test, how often,
    the finding;
  - each pair of missions whose sets broke each other, and how often;
  - the tally of section 10.
- **`keeper/log.md`:** one line per run: the time from `date -u
  +%H:%MZ`, the event, the set, the verdict and what it did.

## 4. The events

### 4.1 A red

The tool has rerun the failing tests once, alone, and they failed
again; it has parked the set and moved on (landing-flow.md 4). The
keeper reads the failure (section 5) and acts on its verdict:
- **The set's:** it returns the set with its note (section 6). The
  set's sub-owner has an implementer repair it (landing-flow.md 3).
- **`main`'s:** it holds the set, closes the failing repository
  (section 7) and escalates to the director with the evidence and,
  where it can tell, the landing that brought the fault. When the
  fix's set is requested, it moves it first. Once the fix has landed,
  the repository opens, and the tool takes the held sets again, on
  the moved base.
- **A flake's:** it files the flake as a finding (section 8) and moves
  the set back into the queue, once. A second red on the same test, in
  any set, makes it `main`'s: a flake that fails gates blocks every
  set behind it.
- **The infrastructure's:** it moves the set back into the queue,
  once. Another red of the same kind is escalated as an infrastructure
  fault. A fault in the tool's own mechanics, such as a lock repinned
  to the wrong tuple, is escalated at once and never retried: a rerun
  would only repeat it.

A set's third return, of any kind, is escalated too (section 8).

### 4.2 A flake

The rerun passed, and the set has landed. The keeper files the flake
as a finding: the repository, the test, the commit, both runs' logs,
and how often its notes have seen the test fail. A flake that fails
gates counts as on v0.1.0's happy path (owners.md 4.6).

### 4.3 An after-landing failure

A slow tier failed on a commit the queue landed (landing-flow.md 4).
The keeper reads it as a red (section 5) and writes its note on the
set whose landing broke the tier: the first landing it fails on, which
its notes and the earlier runs show. `queue wait --after` delivers the
note to that set's sub-owner. If no one waits on that set any more,
the note goes to the director instead, as `inbox/after-landing.md`'s
lines did (owners.md 4.5). Nothing runs after-landing, on the user's
word, while they design how it should.

### 4.4 An infrastructure fault

The tool retries heavy refusing a run, and a machine or GitHub out of
reach, and wakes the keeper when it can't get past. The keeper reads
the retries in the journal, and finds what fails and since when. Once
it has lasted 15 minutes, it escalates (section 8). The store going
down isn't one: kache then compiles locally.

### 4.5 An owner's note

`queue note <id> "..."`, from the set's owner:
- **A repair under way** restarts the silence's 2 hours (4.6). The
  keeper records it.
- **A request to wait,** such as for another set of its own: the
  keeper holds the set, with what it waits for.
- **A dispute of a reading,** such as a failure the owner reads as the
  infrastructure's: the keeper reads the failure again with the
  owner's case. If it agrees, it acts on the new verdict (4.1). If not,
  it answers in the set's notes with its reasons, and the owner's
  `queue wait` returns with them.
- **Anything about the work itself,** its design or its scope, isn't
  the keeper's: it answers that the owner asks its director.

An owner's note acts on its own set only, never on another's. A note
from the director (section 8) is carried out as given.

### 4.6 An owner's silence

A returned set has had no new request and no note from its owner for
2 hours. The keeper escalates it (section 8), with the return note and
the time it was written.

### 4.7 A third return by the tool

The tool sends a set back itself for a conflict it may not resolve
(landing-flow.md 4), with no keeper. When that return is the set's
third, of any kind, the tool wakes the keeper to escalate it (section
8).

## 5. Reading a failure

A red comes from the queue's own gate, which runs when `main` has moved
since the set's base (landing-flow.md 4). The owner's gate passed on
the old base, and `main`'s head passed its own. The cause lies in what
differs: the set meeting `main`'s new commits, the rebase and its
resolutions, the repin, the machine, or the world outside the code.
Read in this order:

1. **Where it failed.** The repository, the step (build, lint, a test,
   another check of the gate) and the test, from the log. The failing
   lines first, then just enough around them.
2. **What the set changed.** The set's diff in each repository, and
   the crates it changed. Does the failing test, or a crate it builds
   on, sit in that diff or downstream of it?
3. **What `main` changed.** `main`'s commits since the set's base, in
   the failing repository and its upstreams. Do they meet the set's
   changes in what fails?
4. **What the queue did.** The rebase's resolutions and the repin, in
   the journal.
5. **The machine.** Signs that the code isn't at fault: a process
   killed (memory, a signal), a full disk, a network failure, a timeout
   while the machine was loaded.
6. **The history.** The keeper's notes and the findings: has this test
   failed before, and where?

**The verdicts:**
- **The set's** when the set's diff reaches the failure, alone or
  together with `main`'s commits. A semantic conflict, two changes
  that each passed alone, is the later set's: the one in the queue
  (landing-flow.md 6.2).
- **`main`'s** when the failure is in `main` as it stands, whatever
  the set: the set's diff can't reach the test, and the test fails on
  `main` too. The evidence is the same test failing in an after-landing
  run or in another set's red; a cause outside the code that changed
  since `main`'s gate passed (a date, a certificate, an outside
  service); or a test that fits its time budget only on a machine
  faster than this one (owners.md 4.5).
- **A flake's** when the test is outside the set's reach and its
  failure depends on timing: a timeout, a race's message, a test that
  has failed intermittently before.
- **The infrastructure's** when the log shows the machine or the
  network failing rather than the code, or when the queue's own
  mechanics are at fault (step 4).

**When in doubt, the set's.** A verdict other than the set's needs its
evidence: the reach that rules the set out, and the run that shows
`main` failing or the machine. Without it, the set goes back with the
doubt in its note, and the owner's implementer, who can build and run,
looks further.

## 6. The return note

At most 15 lines, in the set's notes, where `queue wait` finds it. It
names, in this order:

```
set:      accounts-move/m4, request 42, returned 1 of 3
verdict:  the set's (or: looks like main's, a flake's, the infrastructure's)
where:    temper, tests, accounts::world::moves_keep_sessions
log:      <absolute path on hetzner3>, from line 1840
cause:    the likely cause, in two or three lines
commits:  the set's 3f2a9c1e (temper: ...); main's 81bd04aa (skein: ..., set ...)
doubt:    what it couldn't tell, if anything
```

It states the cause, never the fix: the repair is the owner's
implementer's, briefed by the sub-owner.

## 7. The order

The tool orders by fixed rules: sets that need no gate, then returned
sets, then the rest as they came (landing-flow.md 4). The keeper
overrides them only for these reasons, each with a line in the feed:
- **An owner asking its set to wait** (4.5): the keeper holds it.
- **`main`'s fault** (4.1): the failing repository closes. Every set
  that reaches it is held, since each would fail on the same test, and
  the set that fixes it goes first. The others go on.
- **Two missions whose sets keep breaking each other,** once their
  sets have returned on each other's commits twice: the later request
  waits until the earlier lands, and the director hears of it, since
  grouping missions by coupling is its call (landing-flow.md 6.2).
- **A set back into the queue** after a red read as a flake's or the
  infrastructure's (4.1), once.

A hold always names what it waits for: a set's landing, or an owner's
note. The tool releases it when that comes. No one else orders
landings: not owners for others' sets, and not directors
(landing-flow.md 5), who change the queue through a note (section 8).

## 8. Escalation

To the director by post (director.md 5), `post send --as keeper
director@hel8 "<subject>"`, at most 15 lines. Each message names the
case, the set and its owner, where the evidence is, what the keeper
did, and its recommendation.

The cases:
- a set sent back a third time (4.1, 4.7);
- a returned set with no new request or note after 2 hours (4.6);
- two missions whose sets keep breaking each other (section 7);
- an infrastructure fault that lasts 15 minutes (4.4), and at once a
  fault in the tool's own mechanics (4.1);
- a flake, as a finding for the director to assign (4.2);
- `main`'s fault, with the repository closed and, where it can tell,
  the landing that brought it (4.1);
- an after-landing failure no one waits on (4.3).

The director answers owners as it always does (director.md 6), never
the keeper. A call that changes the queue, such as releasing a hold or
dropping a set, the director makes with `queue note`, which wakes the
keeper to carry it out.

## 9. What it never does

- **It never edits code or writes to a repository.** Its git commands
  only read: `log`, `show`, `diff`, on the tool's clones. Fetches and
  pushes are the tool's.
- **It never builds, tests or runs `heavy`:** the queue's gates need
  the machines, and looking past the log is the owner's implementer's
  work. Nor `pueue`, in any form (director.md 10).
- **It never decides whether a set lands.** A set lands when its gates
  pass; the keeper can send it back into the queue, never past a gate.
- **It reads only what its prompt names:** the event's directory, the
  tool's clones, its notes, the journal and this file.
- **It writes to no one directly:** owners hear from it through their
  sets' notes, the director by post. No other messages.
- **It keeps nothing across runs** but its notes and log: what it
  hasn't written there, the next run doesn't know.

## 10. Its measures

A wrong reading costs a repair round; a needless hold, a set's time.
The keeper's notes keep a tally, which the director reads:
- **Return notes that held:** a returned set's next request says
  whether the note's cause was the one its repair found: held, partly,
  or wrong.
- **Sets sent back into the queue** for a flake or the infrastructure:
  how many landed. One that fails again on the same test was misread.
- **Closed repositories:** how long each stayed closed, and whether
  `main`'s fault was `main`'s.
- **Its runs:** wakes per day, and each run's time and tokens.

They say whether high effort stays, and whether these rules need
changing.

## 11. Open

- **The tool's commands** are named here by what they do. Their
  syntax, the event directory's layout and the request's line for
  section 10 are the build-infra mission's to fix with the tool, which
  keeps this file in step.
- **Its launcher:** whether the tool starts the keeper through
  `codex-run`, whose `runs.tsv` records every run (owners.md 4.2), or
  keeps its record in the journal alone.
- **Product owners:** escalations go to the director. Whether a
  product owner (product.md) takes those for its features' sets is
  open.
