# Post and codex-run

Provisional, 2026-10-24, proposed with the user. How agents send each
other messages, and how they start Codex and learn that a run ended:
- `post`, one durable mailbox per role name, on every machine;
- `codex-run`, the one way to start Codex, which reports by post.

Both are small scripts in `scripts/devel/`, under
[AGENTS.md](../../AGENTS.md)'s rules. They replace five channels and
four launchers. The survey behind this design is x1's
`~/src/rust/tmp/comms-survey/report.md` (10-24, seven machines since
10-16).

## 1. In one page

- **Why.** The survey's failures share three causes:
  - **We address sessions, not roles.** Names repeat after handovers,
    and sockets go stale at restarts: 98 sends hit a dead socket, 59
    found no session, four went to the wrong one, and one resume
    started copies that landed twice.
  - **Wakes depend on whoever remembers them.** Watchers died, matched
    themselves or were never restarted, and about 15 episodes stalled
    for 24 to 218 minutes. Codex runs ended unseen, and a launcher's
    refusal went unnoticed for 102 minutes.
  - **Each channel has its own rules.** There are five channels and
    four launchers, untracked and copied by hand to each machine, and
    one of the channels pays a Sonnet session to forward a file (376
    relays, 23.6M weighted tokens in one day).
- **An address is a role,** `NAME@MACHINE`: `director@hel8`,
  `o/first-run-ux@hetzner3`. The session that holds the name may
  change; the address doesn't (section 2).
- **A message is a file** in the recipient's mailbox on its machine,
  written atomically, with an id, a sender, a stamp and the id it
  answers. Delivery is a restricted ssh key that can only drop mail. No
  LLM is in the path, and nobody polls another machine (section 3).
- **The recipient is woken by its waiter,** `post wait NAME`, which a
  Claude session keeps running in the background and a Codex owner's
  loop is. When there's no waiter, delivery resumes an idle session in
  place, and otherwise says that nobody will wake it (section 4).
- **Stuck mail surfaces:** the director's watcher reports any message
  unread for 15 minutes, on any machine (section 4).
- **`codex-run` starts every Codex run** as a systemd user unit, so it
  outlives its caller. It refuses a bad launch at once, and retries
  the model's capacity errors itself. Whichever way the run ends, it
  posts the caller the report's path (section 5).
- **What goes away** (section 6): `tell.sh`, the inbox files and
  their watchers, `wake/`, `inbox-since.sh`, `subwatch.sh`, `start.sh`
  with its effort knobs (the experiment ended, 858; the spawner keeps
  its choice of model and effort), `codex-helper.sh`,
  `codex-owner.sh`, and SendMessage between roles.

## 2. Names and machines

- **A name** is a role, never a session: `director`, `p/<name>`,
  `o/<name>`, `d/<what>`, or the user's session, `user`. It matches
  `^[a-z][a-z0-9-]*(/[a-z0-9][a-z0-9-]*)*$`.
- **An address** is `NAME@MACHINE`; `NAME` alone is this machine. A
  brief names the parent's address, as it names the parent's machine
  today.
- **A session's own name** is `POST_NAME` in its environment, set when
  it starts: in a Claude session's `--settings` `env`, and by
  `codex-run` for a Codex owner. A session without a name, such as the
  user's, sends with `--as NAME`.
- **The machines file,** `~/src/rust/tmp/post/machines`, has one line
  per machine this one can reach, `MACHINE SSH-TARGET`, and its own as
  `MACHINE local`. The director writes it on each machine: the
  addresses stay out of this repository (director.md 10).
- **The key.** Each machine has `~/.ssh/post_ed25519`. Every other
  machine authorizes it only as
  `restrict,command="$HOME/.local/bin/post deliver --from MACHINE"`,
  so the key can drop a message and do nothing else. The machine that
  the key names becomes the sender's machine: a message that claims
  another is refused. Mail is what the inbox files carry today, so no
  new trust is given.
- **carbon-forge is left out:** it's unreachable since 10-24, and its
  sessions need their own scopes (the director's memory). It joins
  when the director adds a route for it.

## 3. post

The mailbox of `NAME` is `~/src/rust/tmp/post/<NAME, with / as +>/` on
its machine (`o+first-run-ux`), so that no name reaches inside another's
mailbox: `tmp/`, `new/`, `cur/`, `sent/`, with mode 0700 and 0600 files,
a `waiter` file and a `kind` file (`claude` or `codex`).

A message:

```
Id: 20261024T213500Z-7f3a90c1
From: o/first-run-ux@hetzner3
To: p/sign-in@hel8
Re: 20261024T210100Z-11c2e4d8
Subject: M2 design report

<the body: at most 15 lines by the roles' rule, 64 KiB by the tool's>
```

The commands:

- **`post send [--as NAME] [--re ID] TO SUBJECT [FILE]`** sends FILE,
  or stdin. The tool sets the id and the stamp (`date -u`), keeps a copy
  in the sender's `sent/`, and delivers over the post key, or locally.
  It prints the id and what happened:
  - `waiting`: a waiter will wake the recipient;
  - `woken`: an idle session was resumed in place;
  - `queued`: the session is at work, and its waiter starts when its
    turn ends;
  - exit 3, `queued, nobody will wake it: <why>`: the message is in the
    mailbox, but the waiter is dead and the session is absent, stopped,
    or failed to resume;
  - exit 2, `not delivered: <why>`: a bad name, no route, a refusal,
    or a transport that failed three retries (after 5, 20 and 60
    seconds, each try bounded to 60). A retry resends the same id, and
    a destination that already holds it with the same text counts it
    delivered, so a lost acknowledgement never duplicates a message.

  On exit 2, the sender tells its own parent, or the director when
  the parent was the recipient (owners.md 5). On exit 3 the message
  waits, and the director's watcher reports it if it stays unread.
- **`post deliver --from MACHINE`** is the key's forced command: it
  reads `deliver NAME` from `SSH_ORIGINAL_COMMAND` and the message from
  stdin (within 30 seconds), checks both, and that `To:` names this
  machine, and writes the message to `tmp/` and then renames it into
  `new/`. `post send` uses the same path for a local recipient. It then
  wakes the recipient (section 4).
- **`post wait NAME [--timeout SECONDS]`** makes itself NAME's waiter.
  It returns when `new/` holds a message, at once if one is there
  already, and prints one line per message: id, sender, subject. On a
  timeout it exits 1 and prints nothing. A newer waiter for the same
  name replaces it, and the older one exits 4.
- **`post read NAME`** prints the new messages, oldest first, and moves
  them to `cur/`. Reading through it is what marks a message read.
- **`post list [--older MINUTES]`** lists this machine's unread
  messages, for every name: their age, name, id, sender and subject, and
  whether the name's waiter is alive.
- **`post wake NAME`** wakes NAME for the mail already in its `new/`,
  as delivery does (section 4), and prints `NAME` and what happened:
  `waiting`, `woken`, `queued`, or exit 3 with `queued, nobody will
  wake it: <why>`. With no unread mail it prints `NAME no mail` and
  wakes nothing. **`post wake --older MINUTES`** does the same for
  every name of this machine with an unread message between MINUTES
  old and a day old, and whose waiter is dead, but `user`, whom nothing
  wakes; it exits 3 when any of them could not be woken, after trying
  them all. Mail a day old wakes nothing: a session deaf that long has
  been raised by the fleet watch long before, and one left running
  after its mission ended would be resumed to read it (10-27: such
  mail waited 38 hours in ended missions' mailboxes).

Each command takes the mailbox's lock (`flock`) while it moves files.
An id is the stamp and eight random hex digits; a sent copy never
overwrites another.
`cur/` and `sent/` are the record that the inbox files are today.

## 4. Waking

- **A Claude session** ends each turn with its waiter running:
  `post wait $POST_NAME` as a background task. Each time the task ends,
  the session runs `post read $POST_NAME`, acts on what it read and
  starts its waiter again. The waiter needs no working directory and
  almost no memory.
- **A Codex owner's loop is its waiter,** during its turns too: mail
  that arrives in a turn is read when the turn ends (section 5).
- **Delivery wakes the recipient** on its own machine, right after the
  message is in `new/`, holding the mailbox's wake lock throughout, so
  that two senders never resume one session twice:
  - the waiter is alive (the pid in `waiter` runs, as `post wait` for
    that name or as a Codex owner's loop): `waiting`;
  - a Codex owner without a waiter: exit 3, since only its parent
    restarts its unit;
  - a Claude name: the newest session of that name in `claude agents
    --json --all`. A `done` session with a pid still runs; a stopped
    one stays `done` but has no pid and isn't woken. The tool checks a
    running `done` session again, stops it with `claude stop <short id>`
    and waits up to 10 seconds for its pid to go, then resumes it from
    its directory (a resume of a running session would start a copy),
    `claude --bg --resume <full id> "Post for NAME: run post
    read NAME and act on it, then start post wait NAME in the
    background, and do the same each time it ends."`. The resume passes
    no flag, since a flag starts a copy with a new id; the woken session
    keeps its id. The tool checks after 10 seconds that the newest
    session of that name is working or blocked: `woken`, or exit 3.
    If it's working or blocked, the message is `queued`, since a resume
    then would start a copy (director.md 5). If it's stopped, failed,
    interactive or absent: exit 3. A stopped session was ended on purpose,
    and its parent decides.
- **At a handover** the outgoing session doesn't restart its waiter.
  The new session starts one, which replaces any that is left.
- **Stuck mail.** Each machine's tend runs `post wake --older 15` every
  5 minutes ([fleet-watch.md](fleet-watch.md) 4): a waiter that died
  during a turn, or that a memory crunch stopped, leaves its session
  idle and deaf once the turn ends, and the wake resumes it in place.
  The fleet watch raises a name the wake could not reach, and mail
  unread an hour: a session that shows working but sits idle
  (fleet-watch.md 3.1).

## 5. codex-run

- **`codex-run task [--model M] [--effort E] [--read-only] [--to ADDR]
  [--resume RUN] [--on-stop FILE] TASK DIR REPORT`** starts one run.
  - **It refuses at once,** with exit 2 and the reason, before anything
    starts:
    - a path that isn't absolute;
    - a TASK that can't be read, or a DIR that isn't a directory;
    - a REPORT that exists, or whose directory doesn't;
    - no recipient, neither `--to` nor `POST_NAME`, or one that isn't
      an address;
    - a tab or a newline in a path or the model;
    - for `--resume`, a run with no thread.

    It then reserves REPORT, creating it with one line, `codex-run: run
    <id> is writing this report.`, so that a second launch on the same
    path refuses.
  - **The spawner chooses the model and the effort,** by the task
    (owners.md 3): `--model`, by default gpt-6.1-sol, and `--effort`,
    medium, high or xhigh, by default high. The tool never changes
    them, as `start.sh`'s knobs did. `--read-only`
    (for surveys) runs Codex with `--sandbox read-only`, and every
    other run with `--dangerously-bypass-approvals-and-sandbox`.
  - **It returns at once.** It starts `systemd-run --user --collect
    --service-type=exec --unit codex-run-<id>`, whose command runs
    through a login shell, so that the run sees the machine's profile
    as an owner's shell does, and prints the run's id and directory,
    `~/src/rust/tmp/codex-run/<id>/`. The caller ends its turn: the end
    comes by post.
- **The run itself:**
  - It runs with umask 077, in DIR. Its prompt comes on stdin from a
    file, so that no prompt is too long for an argument, and nothing
    else can reach stdin.
  - Its command is `codex exec --json -o <run dir>/last.md`, with the
    events and stderr written to the run directory, and the thread's id
    kept from its first event. Each event gains `ts` as its first key,
    when it arrived, UTC to the millisecond, so that a run's steps can be
    timed: Codex's own events carry no time (an implementers' trial,
    2026-10-25).
  - Its prompt is `start.sh`'s search rule, then "Read TASK and do what
    it says. Write your report to REPORT.", so a task never lacks its
    report's path.
  - `--resume RUN` continues that run's thread, with that run's
    settings, but for `--on-stop`, which a run has only if its own call
    gives it.
  - **`--on-stop FILE`** gives the unit a stop command
    (`ExecStop=`), which systemd runs before it signals what is left in
    the unit: at a stop (a cap, a person, a shutdown) and after the run
    ends on its own. It runs FILE if FILE is then a regular executable
    file, not a link, in FILE's directory, for at most 60 seconds, its
    output in the run directory's `on-stop.log` and its outcome in
    `on-stop` (`exit N`, or `absent`). FILE is absolute, and need not
    exist at the start: the session writes it once it holds something
    to give back, such as a held login (qa-flow.md 10.3). A failing
    FILE never fails the unit. The stop command is codex-run itself,
    with no shell and no `$`: a `daemon-reload` rewrites a transient
    unit's stop command with its `$$` doubled (systemd 257, 10-26), so
    a kit path holding `$`, `%`, a quote, a backslash or a space is
    refused. FILE runs outside any login shell, so it names each program
    by its absolute path.
- **Capacity.** A turn that fails because the model is at capacity
  resumes its thread after 2, 5 and then 15 minutes, "Go on with the
  task: the model was at capacity.", three tries at most.
- **The end, whichever it is,** a TERM or an INT among them (exit 143
  or 130), each step tried even if one before it failed:
  - if REPORT is gone or still holds only the reservation, `last.md` is
    copied there, and the copy says so in its first line;
  - a row goes to `~/src/rust/tmp/codex-run/runs.tsv`: id, caller,
    start, end, exit, tries, model, effort, TASK, REPORT, thread, and
    tokens from the events;
  - a post goes to the caller, with the subject `run <id> ok: <REPORT's
    first line, without control characters>` or `run <id> failed <exit>:
    ...`, and the report's path, the run directory and the minutes in the
    body.
- **`codex-run stale`** lists the runs that will never post: those
  without an end whose unit is gone (killed, out of memory, a reboot, a
  unit that never started), and those whose post failed. A run whose
  meta is under 2 minutes old is not listed: its unit may not have
  started yet. Nor is one whose meta is more than a day old: whoever
  waited for it has moved on, and its directory goes with `tidy`'s
  step 5 (cleanup.md 4). A post failed on any exit but 0 and 3: on exit 3 the
  mail is in the caller's mailbox, and another exit than post's own
  (a crash, 127) leaves delivery unknown, so the end writes
  `post-failed` for every exit but 0 and 3, and a `post-failed` from
  before that holding `queued, nobody will wake it` counts as told.
  **`codex-run stale --post`** tells each one's caller once, as its end
  would have: a run whose post failed sends that post again, and a run
  whose unit is gone posts `run <id> failed stale: <why>` with the
  end's body. A post that goes through (exit 0 or 3: the mail is in the
  caller's mailbox) writes `told` in the run's directory, which takes it
  off the list; one that doesn't leaves it for the next sweep. It
  prints `ID told: LINE` or `ID not told: LINE`, LINE post's own, and
  exits 1 when any was not told. Nothing else of the end is replayed:
  `runs.tsv` has no row for a run whose unit died.
  Each machine's tend runs it every 5 minutes, and the fleet watch
  raises a run still listed (fleet-watch.md 3.1, 4).

  The caller reads REPORT, never the events. An implementer with a
  question writes it as its report's first line and ends, so the
  question arrives as the post's subject.
- **`codex-run owner [--model M] [--effort E] NAME BRIEF`** runs a Codex
  owner, or a QA agent, as the unit `codex-owner-<NAME, escaped by
  systemd-escape>`:
  - its first turn is "You are NAME: read BRIEF and do what it says.
    Your messages come by post.";
  - between turns it rests in `post wait NAME --timeout 3600`;
  - the next turn's prompt is what `post read NAME` printed, or the
    hour's prompt ("check your running tasks...", as now);
  - the batch of post a turn takes is kept in `pending.md` until the
    turn succeeds. A failed turn keeps it, the loop rests five minutes
    instead of an hour, and the next turn's prompt holds it before any
    new post. A restart takes a batch left from before first;
  - it sets `POST_NAME` and the mailbox's kind to `codex`, and keeps
    the thread, `turns.tsv` and the events in
    `tmp/owners/<NAME's last part>/codex/`, as `codex-owner.sh` does,
    with the full name in a `name` file there: another name that would
    share the directory is refused;
  - capacity errors are retried as a task's are;
  - its parent ends it with `systemctl --user stop codex-owner-<...>`,
    once its closing note is in.
- **Claude sessions** still start with `claude --bg`, as the roles say,
  with `POST_NAME` added to their `--settings` `env`.

## 6. What it replaces

- **Retired:**
  - `tell.sh` and its Sonnet relay;
  - the inbox files (`tmp/director/inbox*/`, the owners' `inbox/`),
    with `inbox-since.sh`, `subwatch.sh`, `probe.sh`'s inbox key and the
    product owners' inbox watchers;
  - `wake/` and `codex-owner.sh`;
  - `start.sh` (and `effort2.py`, the knobs that lowered an effort at
    launch), and `codex-helper.sh`;
  - SendMessage between roles. Claude's own sub-agents are unaffected.
- **The roles' edits,** in one docs change at go-live:
  - director.md: 2 (the watcher and the waiter), 4 (starting a Codex
    owner), 5 (the channels, rewritten short), 9 (Codex for surveys),
    and 12, whose question these two scripts answer;
  - owners.md: 2 (the start command's `POST_NAME`, the waiter, no
    `inbox/`), 4.2 (the launcher), 4.3 (a doubt goes in the report) and
    5 (escalation by post);
  - product.md 2 and 5, qa.md 4, and implementer.md
    wherever they name an inbox.
- **Kept:** `watch.sh` and `probe.sh` for the machines, sessions and
  usage, with the stuck-mail trigger in place of the inbox key; `claude
  --bg` and the session rules of director.md 5.

## 7. Going live

1. **Infra builds both tools** in `scripts/devel/`, with fixtures that
   use a scratch workspace, a fake `claude`, a fake `codex` and a fake
   `ssh`, and never a machine's live sessions. `setup`'s tool list links
   them. They land unused.
2. **The director installs the routes,** one quiet machine at a time:
   the machines file, the post key, the authorized lines and the known
   hosts, and lingering (`loginctl enable-linger`), so that user units
   outlive a logout; then a `post send` to `t/ping` on each machine,
   checked with `post list` and cleaned up.
3. **The roles' edits land** (section 6). New sessions follow them.
   Running sessions switch at their next handover, told once by the old
   channel. The old scripts move to `tmp/director/archive/` once no
   session uses them.

## 8. Measures

From the mailboxes and `runs.tsv`, against the survey:
- the time from `new/` to `cur/` per message, its median and p90 (the
  survey: 3 to 6 minutes median, p90 9 to 13, the director's 53);
- the stuck-mail triggers per day, and their causes;
- exits 2 and 3 per day, by reason;
- runs that failed, by exit, and the capacity retries;
- the Sonnet relays: none.

## 9. Left out, on purpose

- **Read and answered receipts** beyond `new/` and `cur/`. Stuck mail
  surfaces anyway, and `Re:` links an answer to its question.
- **A registry of names across machines:** the address carries the
  machine.
- **A relay daemon,** and polling another machine for mail.
- **Durability past a power loss** (fsync), and limits per sender on
  mail's rate and storage: the keys' holders are our own machines.
- **A reconciler** that finishes a killed run: `codex-run stale`
  surfaces it, and its owner decides.
- **A Stop hook** that refuses to end a turn with mail unread. It
  would close the race between a turn's end and its waiter's start,
  which the waiter already closes by returning at once on mail
  that's waiting. It comes back if the measures show the need.
- **A launcher for Claude sessions.**
