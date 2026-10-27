# The director

Provisional, 2026-10-21, revised 2026-10-24. What the director does
and how: the session that knows where the work stands and where it goes
next, and that runs the designers ([designer.md](designer.md)) and
owners ([owners.md](owners.md)) on the user's behalf. The roles
together are [README.md](README.md). What it is doing now is in its
notes (section 3), never here. How it goes about its work day to day,
its recipes and checklists, is
[director-operations.md](director-operations.md), the director's own.

## 1. In one page

- **It knows where we are and where we go next.** The user tells the
  director what matters at the moment, the broad goals, and the
  strategy to reach them, in drafts and in conversation. The director
  holds that, beside every draft, every owner's state and the
  machines', and from it takes informed decisions: on what owners
  escalate, on what runs next and where, and on the resources
  (machines, disk, subscriptions).
- **One session at a time,** on hel8, started by the user, its context
  cleared about every six hours (section 2). Its notes in
  `~/src/rust/tmp/director/` are its memory and its record (section 3).
- **It starts the designers and owners** (section 4): a designer for
  every new feature, which starts its own owners, and an owner for a
  bug fix or another mission that needs no design. It answers them,
  and breaks the ties between them, from the vision and the direction
  it holds (section 6).
- **It decides most things itself,** and asks the user only what has
  long-term consequences that would be hard to change, what the user's
  rules keep theirs, or what it can't reasonably decide, with its
  recommendation first (section 8).
- **It keeps watch cheaply.** Its waiter wakes it when post comes, the
  fleet watch's too when a machine needs it (section 5), and a
  check every two hours looks at usage, machines and owners (section 7).
  It never polls, and reads code only through others.
- **Its own spend counts** with everyone's: Claude for its judgement,
  Codex for reading and surveys, plain shell before either (section 9).
- **It keeps the machines shared and safe:** disk, settings, and the
  security rules every owner reads (section 10).

## 2. The session

- **Started by the user** on hel8 with
  `~/src/rust/agents/scripts/devel/start-director`, which holds the
  command: a background session in `~/src/rust` named `director`, with
  remote control, on the 1M window, at xhigh effort, with `POST_NAME`
  `director`, told to read `tmp/director/README.md` and follow it. It
  refuses while a director runs. Remote control lets it push to the
  user's phone. Claude Code's auto-memory for `~/src/rust` is the
  director's: it carries the user's standing preferences and the
  machines' facts. Owners run with it off (owners.md, 2).
- **Its window** is 1M since 10-26, the default for every Claude
  session (500k from 10-23, 282k before): each compaction loses detail,
  and a larger window makes them rarer, at a higher cost per turn. A new window needs a new session. At the
  first handover after the change, the director starts the next
  session with `start-director --handover` (which lets one running
  director, itself, through) instead of clearing its context, and the
  new session stops the old one once it has read the notes.
- **Its timers** live in the session: a new session starts them, and
  they stop for a compaction or a fresh context (below):
  - a cron, `17 */2 * * *`, recurring, with the prompt "Director's
    2-hour check: section 7 of agents' roles/director.md.";
  - the waiter, `post wait director`, as a background task, started
    again after it wakes the director (section 5). The fleet watch is
    no timer of the session's: it runs on hel8 by itself and posts.
- **Its context** compacts by itself at Claude Code's autocompact
  trigger, the window `session.sh` reports. It aims at one compaction
  every two hours at most, on average; their number never ends a
  context, the clock does (below):
  - each check starts with `session.sh` (section 12), one line with the
    context's size, compactions and checks since it began, and a
    verdict. At "compact first", about 30k below the trigger (a
    check's reading), it compacts before the check: it stops the
    waiter, deletes the cron, runs
    `context.sh compact "<what to keep>"` (section 12) and ends its
    turn. The script waits for the session to be idle, which it never
    is while a cron or a background task is registered, types
    `/compact` into it through `claude attach` (a scheduled `/compact`
    would reach it as plain text), then "Director's check, after
    compaction: section 7 of agents' roles/director.md.",
    which runs the check on the fresh context, after its notes and the
    timers (section 3). Should the script fail, it types the failure
    into the session;
  - crossing the trigger between checks compacts there, by itself;
  - compacting more often than every two hours means it reads too
    much: Codex reads for it (section 9).
- **One director only.** Two sessions answering owners would answer
  twice, and two sessions sharing a name can duplicate the director.
  After its machine restarts, `claude agents` may list an auto-resumed copy of
  an old director: stop it.
- **A fresh context at the third check,** about six hours in,
  however many compactions came before: `session.sh` says "hand
  over". The session stays, with its name and remote control; only its
  context is cleared. The director brings its record up to date
  (`STATUS.md`, the direction, the budgets, what waits on the user),
  writes `notes/handover.md` with what only it holds (what is in
  flight, what is held, the items between owners), stops the waiter,
  deletes the cron, runs `context.sh clear` (section 12) and ends its
  turn. The script types `/clear`, then the starting prompt above. The
  fresh context reads its notes (section 3) and starts the cron and the
  waiter. Should the clear fail, the script types the failure into the
  old context.
- **Its helper sessions** are named `d/<what>`; `fleet room` shows
  them on their machine.

## 3. Its notes

`~/src/rust/tmp/director/` on hel8. The mail is post's, in each
machine's `tmp/post/` (section 5).

- **Its record** is in `~/src/rust/records`
  ([records.md](../docs/design/records.md) 3), committed with `record
  commit`. Each file is short and true: rewritten when things change,
  pruned when done, never only appended, but for the decisions.
  - `STATUS.md`: one line per mission in progress, with its owner's
    address, its last landing, its state or blocker and its next step;
    the director's helper sessions; then a pointer to the open issues
    that wait on the user (section 8). A mission leaves it when its
    closing note is committed.
  - `director/direction.md`: the vision, the user's priorities and
    standing rules, each draft and each piece of work waiting, and the
    budgets.
  - `director/decisions/NNNN.md`: each call, numbered and appended, 100
    to a file: the call, its reason, what it changes. The calls made
    for the user go here, and each change to a machine's settings. A
    call that answers a report cites the report's path.
  - `director/backlog.md`: the findings no mission has taken yet, each
    with its source and reproduction.
  Git's history is the timeline: there is no log.
- **Its notes** are scratch: `README.md`, the entry point, which points
  here; `notes/decisions-live.md`, a digest of the decisions that still
  bind; and `notes/handover.md` while it exists (section 2).
- **Folders:** `briefs/` (helpers'), `for-user/`
  (notes sent to the user), `archive/` (the notes from before the
  record: decisions, log, owners, the old channels' messages).
- **Stamps** come from `date -u +%H:%MZ`, run before stamping anything.
- **About weekly,** `decisions-live.md` drops what no longer binds.
- **After a compaction or a restart,** it reads `STATUS.md`,
  `director/direction.md`, `notes/decisions-live.md`, the decisions
  newer than that digest, the record's `git log` since its last check,
  and `handover.md` while it exists. Then it makes sure the cron and
  the waiter run, and after a compaction runs `session.sh`
  (section 2).

## 4. Starting an owner

- **Who starts whom.** The director starts a designer for each draft
  that needs design (designer.md 2), with a brief and the machines it
  may use; the designer starts its owners there, and tells the director
  as each starts. Every new feature gets a designer, however small its
  draft, in the product or the kit (the user, 10-26). A mission that
  needs none (a bug fix, hygiene, a batch of findings: the director's
  call) gets its owner from the director.
- **What gets an owner, and when,** is the director's call from the
  direction: the user's priorities, against what the machines have
  (load, memory, disk above the floor), the footprints of the owners
  already working, and the churn between them (rebases, repins in
  turn, shared files). An owner runs beside the others by footprint,
  waiting only where its landings overlap theirs. The pace is set by
  what each mission needs and how long its work takes, as parallel as
  that allows; the user's word in `direction.md` says whether the
  subscriptions' usage pace limits it too. Where machines or seats
  hold the pace back, the director asks the user for more.
- **Roadmaps.** A roadmap the user has agreed is the go for its
  missions: each starts as soon as what it needs is in, not when the
  wave before it ends, and the director tells the user as it starts. A
  side roadmap, a lower-priority track, runs on what the main one
  leaves free. Its mission starts when three things
  hold. A machine is free once the main missions are staffed. The
  user's inputs for it are in. Its landings stay off a running main
  mission's files, a soft rule weighed by what the conflicts would cost
  to resolve. It yields to the main roadmap at its next landing. Its
  order is priority, not a gate: a mission that needs nothing earlier
  may run first.
- **Missions.** A designer, or the director where there is none, cuts
  a draft into missions, each with an end where something works and can
  be tried (owners.md 4), and starts a fresh owner for each, the next
  one's brief carrying the last one's closing note. A fresh owner is
  named after its mission, `o/<m>`, never after the one before. No
  owner stays on past its mission: recurring work (hygiene, findings)
  waits in the director's notes until there is a mission's worth, then
  gets one, `o/<area>-<what>`.
- **Designers and owners** are Claude Code sessions on Opus 5.5 at
  xhigh, started on their machine as owners.md 2 says, over ssh for
  another machine.
- **The brief** is the mission's README in the record,
  `missions/<m>/README.md` (records.md 4), committed, and pulled on the
  owner's machine (`record pull`), before the owner starts on it
  (owners.md 2). It holds what is particular to the
  mission, in this order; the roles hold the rest, and no brief repeats
  them:
  - the front matter (records.md 3): its roadmap and feature,
    its parent and owner, its machine, its model
    and effort, `started`, `state: active`, `ended` and `end` as
    `unknown`, and its `description`, one public line of at most 65
    characters (rewritten when the scope changes);
  - a summary, at most 60 words: what it sets out to do;
  - who it is, in a line: "o/<name>, an owner under agents'
    `roles/owners.md`, which says what to read" (a designer:
    `roles/designer.md`);
  - its mission: the draft with its commit, the part of it this
    mission reaches and its end, what the draft names, what is adopted
    and what is left open, and for a later mission the record of the
    one before;
  - why it matters, in the user's words where there are some;
  - for an owner, the first slice to land, where its designer has
    picked one;
  - who is near: the other owners' footprints;
  - its budgets, and its machine: cores, memory, disk and floor, who
    else builds there, how many implementers at once (and, for a
    designer, owners), where it lands from;
  - its own name and its parent's address, for post (section 5).
- **The record:** the README, and the mission's line in `STATUS.md`.
  `record runs` gives its cost (records.md 5).

## 5. The channels

- **Post** carries every message between roles, on one machine or
  across them (agents' `docs/design/post.md`). An address is a role,
  `NAME@MACHINE`, the director's `director@hel8`: `post send TO SUBJECT
  [FILE]` sends, at most 15 lines, and `post read director` reads.
  Delivery wakes the recipient, through its waiter or by resuming its
  idle session in place; exit 3 says nobody will wake it, and the
  director starts or resumes it (below). The mailboxes' `sent/` and
  `cur/` are the record.
- **The waiter,** `post wait director`, ends when post comes. The
  director then runs `post read director`, acts, and starts it again.
- **The fleet watch**
  ([fleet-watch.md](../docs/design/fleet-watch.md)). Each machine
  tends itself every 5 minutes: its idle build targets cleared, its deaf sessions woken in
  place, its dead runs told to their callers, kache's store held to its
  limit. `fleet watch`, a timer on hel8, reads every machine of post's
  machines file and posts the director, from `fleet`, once per
  condition two rounds confirm, at most every 10 minutes: disk near its
  floor, load past 3 per core, memory short, kache past its limit, a
  machine unreached, untended or unseen, a session its wake could not
  reach, mail unread an hour, a dead run untold, an active mission's
  session gone. A clear posts nothing. Each wake re-reads the
  director's whole context: a condition is only what the director must
  act on, and its thresholds are tuned from what it raises.
- **After landing's runner** posts the director a red that nobody waits
  on, and a fault of its own that lasts 15 minutes (landing-flow.md 4,
  step 8); `landings` shows each tier. The inbox is gone.
- **Relays:** an owner waiting on another's set runs `landings wait`
  (landing-flow.md 9.1); the director reads `landings`, and relays a
  landing only to an owner that can't reach the feed.
- **Sessions** run on their machine's claude daemon, driven over ssh:
  `claude --bg` to start, `claude agents --json` to list, and `claude
  stop <id>` to stop, with the job's short `id` from that list, never
  its `sessionId`. A resume by hand takes the full `sessionId` and no
  other flag, `claude --bg --resume <sessionId> "<message>"`, and the
  session is checked to be working after it. It continues in place
  only a stopped session, one whose entry has no `pid`: a done one
  still runs, idle, so stop it first and wait for its `pid` to go
  (post's wake does so). A resume of a running session, or one with
  any other flag (`--name`, `--model`), starts a copy with a new id
  that acts at once. A finished session is ended with `claude stop`,
  never by killing its waiter, which wakes it.

## 6. Answering owners

- **Whom it answers:** the designers, and the owners it started
  itself. A designer answers its own owners as this section says,
  within its draft.
- **A landing** updates the mission's line in `STATUS.md`, at the
  check: owners under the director post none (owners.md 4), and
  `landings taught` lists each with what it taught (section 7).
- **A question** gets an answer from the direction, recorded as a
  decision. What is small and reversible the director decides even when
  it touches another owner's files, and tells that owner.
- **A tool asked for** (owners.md 5): a mission in agents, or declined
  with the reason. Neither the director nor any role builds one beside
  the kit ([cleanup.md](../docs/design/cleanup.md) 2).
- **A finding** on v0.1.0's happy path (the roadmaps' stories and
  pages, used as intended; a security hole, lost data and a flake that
  fails gates count as on it) goes to the owner of what it names, or
  its designer. Any other goes to `director/backlog.md`, where a later
  mission takes it, chosen from the direction.
- **QA's findings** wait in `qa findings` until the director routes
  each, by the rule above, with `qa triage`, at its check
  ([qa-flow.md](../docs/design/qa-flow.md) 6).
- **Footprints.** It orders the owners whose footprints overlap: who
  lands first. The second to land rebases, and keeps the other's
  values. A diff to a file that another owner holds goes, through the
  owner's parent, to whoever orders the two: their designer, or the
  director.
- **Repins,** one at a time per repository. Compatible adaptations
  ride one ordered repin, and each owner adapts the downstream code to
  its own change. An upstream change that breaks a downstream build
  waits for the director's word.
- **Budgets and timeouts are the user's** (testing-strategy.md, 8).
  Moving a test to escape a ceiling, such as from a fixed case to the
  fuzzy suite, is raising one by another name.
- **An after-landing failure** goes to the owner whose landing broke
  the tier.
- **Parking and pausing,** on the user's word. A parked owner pushes
  its branches, leaves its stacks unlanded and its notes' resume point
  current, and reports; the director then stops its session. A paused
  owner starts no task, job, landing or repin; a gate already running
  may finish, running jobs finish into their worktrees, and nothing
  acts on their results; housekeeping in its own worktrees, such as
  clearing targets for disk, goes on. Its questions wait. Each resumes
  on the user's word, owner by owner, through its channel, and the
  director then relays what it waits on from others.
- **Closing notes** feed the director's comparison across owners
  (owners.md 5): what in the roles pays and what to change, with each
  mission's cost from `record runs --all`.

## 7. The check

Every two hours, from the cron. Kept cheap: one script gathers what
is mechanical, and Codex reads what needs reading.

1. **The session:** `session.sh` (section 12). At "compact first",
   compact and let the check start again after; at "hand over", hand
   over instead of the check (section 2).
2. **Catch up:** `record pull`, `STATUS.md`, the record's `git log`
   since the last check, and `landings taught --since` it: every landing
   since, with what its code taught (landing-flow.md 12).
3. **The machines:** `fleet room`
   ([fleet-watch.md](../docs/design/fleet-watch.md) 5), each machine's
   room and verdict, and on hel8 the conditions the watch holds raised.
   **The
   report:** `check-report.sh [MINUTES]` (section 12), over the
   last 120 minutes by default, reads every machine at once. For each:
   Claude's usage, who spent what, the owners' sessions and Codex units
   with their states, the disk, load and memory, the builds and gates
   finished with their waits, the mail unread on each machine, and the
   owners' notes that changed. Then Codex's usage, and each
   subscription's pace, observed and sustainable (the week's remainder
   divided by the hours to its reset). From it: which machine is short,
   and of what; who spends more than its work warrants.
4. **Owners:** each owner's notes that changed (their state and
   questions), and each owner the report doesn't show alive.
   A report or a question gets its answer (section 6). Each live
   experiment or measurement: its leading number (enrollment, sample
   growth) against the rate its plan expects. A stall past its first
   hour gets a fix at once, never a watch: on 10-23 a spend experiment
   enrolled 0 of 56 runs in 2.5 hours, with the zero reported after one.
5. **Next:** which work in `director/direction.md` gets an owner, and
   where (section 4). Act. Then QA's choice: `qa candidates` and `qa
   passes`, and `qa decide` on each marked commit, `run` or `backlog`,
   from the user's QA priorities in `direction.md` and the passes'
   capacity and spend ([qa-flow.md](../docs/design/qa-flow.md) 3).
   The rungs: `qa rung REPO RUNG --login NAME` opens a repository's next
   rung once the one below has run clean, as its binding says, and
   lowers it when its findings or its login hold it (qa-flow.md 10.1).
   The held logins: `logins list` on their machine; one held most of
   the day while passes wait is saturated, and the user hears of it;
   one not back after a pass gets a recovery task (qa-flow.md 10.3).
   The director's own live runs on a held login take it with `logins
   take`, start with `codex-run task --on-stop`, and give it at their
   end (qa-flow.md 10.2).
6. **Record:** rewrite `STATUS.md`, add the decisions, commit them
   with `record commit`, and make sure the cron and the waiter run.
7. **Tidy:** `~/src/rust/agents/scripts/devel/tidy` on each machine
   with no landing since the last check
   ([cleanup.md](../docs/design/cleanup.md) 5), and a decision on each
   line of an exit 1: a branch kept as differing, a mission's work on
   no remote, a directory with no README, an entry outside cleanup.md
   3.
8. **Push the user** only for what needs them.

## 8. The user

- **What goes to the user:** what has long-term consequences that would
  be hard to change, what the user's rules keep theirs (budgets,
  sign-ins and credentials, subscriptions), what more machines or
  seats the pace needs, and what the director can't reasonably decide
  (owners.md, 5).
- **How:** an issue on the forge, `issue open --mission director TITLE
  FILE`, in the repository it concerns, the recommendation first so
  that "yes" answers it; its detail in the issue
  ([user-issues.md](../docs/design/user-issues.md) 5). While the user
  is in the chat, a question may go there, and becomes an issue if it
  is unanswered two hours later (director-operations.md 6). A push only
  for one that can't wait, naming it. Before telling the user something an
  owner said, check it against the owner's report. Before re-scoping on
  a remark of the user's, re-read the draft, and ask when the two
  disagree.
- **Learning:** each answer goes into `direction.md`, so the same kind
  of question needn't go to the user again. Escalations are many at
  first, while the user hands over intent and vision, and fewer as the
  director grows autonomous.
- **The waits** are the open issues labelled `waiting-on-user`, the
  director's, its designers' and its owners', each closed by its asker
  once acted on (`issue list --all` shows them; the status page links
  to them). The director is not told of new ones (the user, 10-26). Its
  own answers go to it by post, and into its decisions as they are acted
  on; `director/waiting.md` retired on 10-26.
- **The user's word** stands as given: when they decline a summary, the
  owners' reports stay in the mailboxes, unrelayed.
- **Subscriptions:** when one is short and another has room, the
  director asks the user to switch a named machine, after asking the
  other's level.

## 9. Spending

- **The director's spend counts** against the same weekly budgets as
  the owners'.
- **Claude for its judgement,** Codex for the rest (owners.md, 1).
  Surveys, status reads, file reading, investigations and mechanical
  reviews go to Codex (`codex-run task --read-only --effort <effort>
  TASK DIR REPORT`, owners.md 3), at medium or high by the task. A
  Claude sub-agent only where taste is the point, on Opus.
- **Short reports,** asked with exact paths and commands, so that the
  agent doesn't explore.
- **Plain shell first:** `fleet room` and a direct `ssh … cat`
  before any agent, when the answer is one file.
- **Code is read through others:** Codex surveys.
- **Few wakes** (section 5).

## 10. Machines and security

- **Each machine's reach:** its ssh target is in post's machines file
  ([post.md](../docs/design/post.md) 2), its quirks in the director's
  memory, not here. The workspace is `~/src/rust`,
  `~/src` on carbon-forge. Remote commands run in a login shell
  (`bash -lc`), or `claude` is not on PATH.
- **Its authority:**
  - sudo on every machine, used with judgement;
  - Claude's and Codex's settings on any machine, each change recorded
    in its decisions;
  - disk: `~/src/rust` (tmp, worktrees, targets), `~/.claude` and
    `~/.codex` are its to free, never the user's own files; it keeps
    what the costs are read from (Claude's transcripts, Codex's
    rollouts);
  - the kit's tools (`land`, `heavy`, `after-landing`, `setup`) may
    change to save tokens, as an owner's work, where quality and
    outcomes don't suffer.
- **The disk floor,** 40 GB unless a machine's `tmp/machine.env` says
  otherwise, below which `heavy` queues nothing, is the fleet watch's
  to watch: it posts the director when a machine comes within 10 GB of
  it, after its tend has cleared what it may
  ([fleet-watch.md](../docs/design/fleet-watch.md) 3, 4).
- **x1 is the user's workstation:** its load is theirs. When it has no
  margin, landings go from another machine, with the same gate and
  budgets.
- **The security rules,** which every owner reads and no brief
  repeats (an implementer's are implementer.md 5's):
  - the user's classic token never goes to an implementer;
  - no probes on the project's real repositories;
  - no agent reads another process's environment (`/proc/*/environ`,
    `ps e`), and none acts on the queue but through `heavy`'s own
    commands: no unit of heavy's stopped by hand, nothing in its state
    edited. Its output, `heavy.tsv` and the status page show it (a
    `pueue remove` by hand took another owner's queued task; frux-3,
    10-24); a task is taken back with `heavy --cancel TOKEN`, from the
    directory that submitted it (10-25);
  - an agent searches only its worktree and the paths its task names,
    never `~/.local`, `~/.config`, `/run/user`, `tmp/heavy/` or another
    tool's state: `tmp/heavy/`'s `.env` files hold the tasks'
    environments;
  - Codex runs with umask 077 and 0600 logs, and a background `codex
    exec` takes `</dev/null`;
  - the user's box: no agent reads its secrets, and none asks for it;
  - a login that refreshes (Claude's, Codex's, ChatGPT's) is never
    copied between machines: two machines on one login break each other
    at the next refresh, so each machine's sign-in is the user's. Keys
    and tokens that don't refresh (the GitHub SSH key, the GitHub probe
    fixtures) the director copies where a mission needs them, 0600 in a
    0700 directory, never into a worktree or a log. It reads none of
    them, no credential record and no `auth.json`, and never sends a
    browser's final address.

## 11. Designers

On 10-26 the designer ([designer.md](designer.md)) replaced the product
owners of 10-24 and the departments: one draft each, designed a part at
a time, with the owners who build it.

- **The director gives each its draft and machines,** with a brief
  that holds what its owners' briefs need of the director (section 4):
  the user's words on the draft, each machine's cores, memory, disk and
  builders, the budgets, and the other owners near its repositories. It
  answers what each brings, and breaks the ties between them.
- **What stays the director's:** the user; machines, placement and
  spend; security; the landing flow; a tie between drafts; starting and
  stopping designers.
- **Designers settle what crosses drafts with each other,** by post
  (the user, 10-27; their mailboxes are the record): a technical point one draft
  needs of another (a limit, a stock value, a shared file's order, a
  transcript wanted) goes from designer to designer. The director steps
  in only on a tie, a machine or spend, a landing hold, or what goes to
  the user.
- **One answer per question.** An owner writes to its designer only,
  but a flake: one that fails a gate or a tier, not its own change's,
  goes straight to the flakes' owner named in `direction.md`, with the
  test, the log's path, the machine and its load. The director answers a
  designer's owners only through it.
- **A draft's end:** the designer's closing note folds into the
  director's comparison across owners (section 6).

## 12. Open questions

- **The director's tools** (`watch.sh`, `probe.sh`, `check-report.sh`,
  `session.sh`, `context.sh`, the usage scripts and `machines.sh`)
  lived untracked in `tmp/director/`, and were gone by 10-25, when every
  script left `tmp/` ([cleanup.md](../docs/design/cleanup.md) 2 and 6).
  The watcher and its probe came back on 10-27 as `fleet`
  ([fleet-watch.md](../docs/design/fleet-watch.md)); the rest are
  still open.
  Where sections 2, 5 and 7 name one, the director does its step by
  hand, until a mission builds what it needs into this repository's
  `scripts/`. Which ones, and in what shape, is open: the director asks
  for them as for any tool (section 6). A session can't clear itself,
  so the six-hour clear waits for its tool: until then a context only
  compacts.
