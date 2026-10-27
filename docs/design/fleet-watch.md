# The fleet watch

Provisional, 2026-10-27. What keeps the fleet's machines healthy
without the director reading them by hand: each machine tends itself
(its idle build targets cleared, its deaf sessions woken, its dead runs
told to their callers), one watch on the director's machine reads every
machine and wakes the director only past a threshold, and one command
shows each machine's room before an owner is placed. `fleet`, in
`scripts/devel/`, reads, judges and shows; `tidy`, `post` and
`codex-run` act, each under its own design.

## 1. In one page

- **Why.** On the evening of 10-26 four builders reached heavy's 40 GB
  floor (kache's local stores past their cap, owners keeping finished
  targets, after landing's runner target at 180 GB), load reached 33 to
  38 on 8 cores and starved gates, Garage held 9 GB of hetzner3's
  memory, and a memory crunch left sessions deaf for 30 to 40 minutes.
  The director found each by hand, reading `df`, `/proc/pressure/cpu`,
  `free`, `uptime`, `du`, `kache stats`, `ps`, `claude agents --json`
  and heavy's ledger machine by machine, and cleared targets by asking
  owners. "hardware monitoring? automatic disk cleanup? scripts for
  placement?" (the user, 10-27).
- **Each machine tends itself** (section 4). `fleet tend`, a user
  timer every 5 minutes on every machine, runs three of the kit's
  commands: `tidy --targets` clears the build targets nobody uses,
  `post wake --older 15` wakes a session whose mail waits with no
  waiter, and `codex-run stale --post` tells a dead run's caller. Each
  rule is its tool's ([cleanup.md](cleanup.md) 4, [post.md](post.md) 3
  and 5); the timer only runs them, and records what they did.
- **One reading, piped.** `fleet probe` reads one machine: load,
  pressure, memory, disk against its floor, kache's store against its
  cap, heavy's queue, sessions and implementers, unread mail and its
  waiters, stale runs, build targets by owner, and its last tend. The
  reader pipes its own source to each machine, as the status page does,
  so that every machine is read by the version that judges (section 2).
- **The machines are post's machines file's** on the machine that
  reads: a machine added there (hetzner7) is read at the next round. No
  tool names a machine.
- **The watch wakes the director only past a threshold** (section 3).
  `fleet watch`, a timer every 5 minutes on the director's machine,
  reads every machine and raises a condition when its threshold holds
  two rounds running: disk near its floor, load past 3 per core, memory
  under a tenth, kache's store past half again its cap, a machine
  unreached or untended, a session its wake could not reach, mail
  unread an hour, a dead run nobody was told of, an active mission's
  session gone. A raise posts the director once, one post at most
  every 10 minutes, carrying every raise since the last; a condition
  clears by itself and posts nothing.
- **The room is shown, never pushed** (section 5). `fleet room` prints
  one line per machine and a verdict, `room`, `tight` or `full`, for
  whoever places an owner: the director, or a designer.
- **What tending never touches:** a target in use, anything outside
  `tmp/owners/` and `tmp/director/`, the user's worktrees, the primary
  checkouts, and after landing's runner, which caps its own targets
  ([build-infrastructure.md](build-infrastructure.md) 11).
- **Private.** The reading names sessions, missions and mailboxes: it
  is the director's and the designers', in the terminal and by post,
  never the status page's, which stays the public view.

## 2. The reading

`fleet probe` prints one JSON object for its machine. `fleet room` and
`fleet watch` read each machine of `tmp/post/machines` as the status
page's writer reads its collector ([status-page.md](status-page.md) 1
and 4): their own source piped into `bash -lc 'exec python3 -I -
probe'` over SSH, with `landings`' SSH options and the reader's own
key, which reaches each machine with a shell; in-process for the line
that says `local`. The machines are read in parallel, each within 60
seconds. One that fails is unreached, with why in a few words
(refused, timed out, key refused, an answer of the wrong shape), and
the others stand.

| Field | Source |
|---|---|
| `cores`, `load` | `os.cpu_count()`; `/proc/loadavg`'s 1, 5 and 15 minutes |
| `pressure` | `/proc/pressure/cpu`'s `some` and `/proc/pressure/memory`'s `some` and `full`, each `avg60` |
| `memory` | `/proc/meminfo`'s `MemAvailable` and `MemTotal` |
| `disk`, `floor` | free and total bytes of the workspace's filesystem, where heavy measures its floor; the floor as heavy reads it: `PLAN_MIN_DISK_GB` in the environment, then in `tmp/machine.env`, else 40 GB (build-infrastructure.md 2) |
| `kache` | `kache stats --json`: `disk.store_bytes` and `disk.store_limit_bytes`; absent without kache |
| `heavy` | `tmp/heavy/state.json`'s live tasks, as the status page reads them: running, queued, the oldest queued one's wait, a gate's hold; absent without heavy |
| `sessions` | `claude agents --json --all`: each live session's name and state; and each Codex owner's unit that is active, `codex-owner-*` (post.md 5), by its name |
| `implementers` | `tmp/codex-run/*/meta` without `ended` whose unit is active, counted by mission |
| `mail` | `post list`: for each name with unread mail, how many, the oldest's age in minutes and whether its waiter lives |
| `stale` | `codex-run stale`: the runs that will never post, and since when |
| `targets` | each target that `tidy --targets` would weigh (cleanup.md 4, step 9): its path under `tmp/`, its owner, its last build and whether it is in use; its size only when asked (`--sizes`), by `du`, within 30 seconds for all |
| `tend` | `tmp/fleet/tend.jsonl` (section 4): the tends that ended after the time the reader asks from (`probe --since TIME`), or the last one |

- **One failure leaves the rest,** as on the status page: a source that
  fails, or answers with a field of the wrong type, is left out and
  named in the reading's `errors`, with its kind alone.
- **Cheap.** Every source is a file or a local command answered in a
  second or two, and nothing walks a tree but `du` when sizes are asked.
- **No text but names.** The reading carries names, numbers and times:
  no message's subject or body, no command line, no environment.

## 3. The watch

`fleet watch` runs one round and exits. `fleet-watch.timer` runs it
every 5 minutes, two minutes after the tends (`OnCalendar=*:2/5`), on
the one machine `setup` was given the director's address on (section
6): hel8.

### 3.1 Conditions

A condition belongs to a machine, or to a name or a run on it. It is
raised once its raise test holds in two rounds running, and cleared
once its clear test holds in two rounds running; between the two
thresholds it stays as it was. A machine whose reading lacks a field
keeps that field's conditions as they were.

| Condition | Raised when | Cleared when |
|---|---|---|
| `disk` | free under its floor plus 10 GB | free at its floor plus 20 GB or more |
| `load` | the 15-minute load at 3 per core or more | under 2 per core |
| `memory` | available under 10 % of total | 15 % or more |
| `kache` | the store at 1.5 times its limit or more | at 1.1 times or less |
| `unreached` | the machine not read | read |
| `untended` | its last tend ended 15 minutes ago or more, or never, or a command of it refused (exit 2) or could not start | a tend within 15 minutes whose three commands ran |
| `deaf NAME` | its tend's `post wake` could not wake NAME (exit 3): raised in the round that reads it, since the mail has waited 15 minutes already | NAME's mail read |
| `mail NAME` | NAME's oldest unread message 60 minutes old or more | none that old |
| `stale RUN` | RUN listed by `codex-run stale`, its caller not told | no longer listed |
| `session NAME` | an active mission's session absent from its machine's live sessions | present, or the record no longer holds an active mission owned at that address (ended, paused, moved) |
| `blind MACHINE SOURCE` | a source of the reading failing on that machine (its `errors`) | read |

- **`session`** reads the record on the watch's machine, pulled once a
  round (`record pull`, read as it stands when the pull fails): each
  mission whose README says `state: active`, by its `owner` address,
  `NAME@MACHINE`. A session that is stopped or gone was ended on
  purpose or died; the watch wakes none, and the director decides
  (post.md 4).
- **A condition's subject gone** clears it: a mailbox, a run's
  directory or a machine's line in the machines file that no longer
  exists, as the record's mission does for `session`.
- **`blind`** keeps a failing source from passing for a quiet one: a
  machine whose `kache stats` or `post list` has failed for ten
  minutes is one the watch no longer sees there.
- **`user`'s mailbox** raises nothing: the user reads post when they
  choose. Nor does the watch's own, `fleet`.
- **`x1` and its like:** a machine whose `tmp/machine.env` says
  `FLEET_QUIET=1` is read and shown, and raises nothing but
  `unreached`.

### 3.2 The post

- **To the director,** at the address `setup` was given, from the name
  `fleet`: `post send --as fleet DIRECTOR SUBJECT`, the body on stdin.
- **Once per raise.** A round that raises posts every condition raised
  since the last post, unless the last post went less than 10 minutes
  before: then its raises wait for the first round past that. A
  condition raised and cleared before its post goes is dropped from it.
  A clear posts nothing.
- **The subject** names what was raised, machine by machine, at most
  120 characters: `fleet: hetzner disk 38 GB free (floor 40), hetzner6
  load 4.2/core`, then `and 2 more`.
- **The body,** at most 15 lines: each raise with its reading; for a
  `disk` raise, that machine's targets by owner, largest first, read
  again with their sizes; then what the tends did since the last post
  (targets cleared and the space now free, sessions woken, callers
  told); then the conditions still raised, and those cleared since.
- **A failed post** (exit 2) is tried again the next round. Exit 3,
  nobody will wake the director, goes to the journal and is not
  retried: the post waits in its mailbox.

### 3.3 Its state

In `tmp/fleet/` on the watch's machine, each file replaced atomically,
mode 0600:

- `watch.json`: per condition, the rounds its test has held and
  whether it is raised; the raises not yet posted; the last post's
  time; per machine, the end of the last tend read. A round without
  it starts from nothing, so a restart raises only what two of its own
  rounds confirm.
- `rounds.jsonl`: each round's figures per machine (time, load,
  pressure, memory, disk, kache, the conditions raised), kept 7 days,
  for reading back what a machine went through.

## 4. Tending

`fleet tend` runs, on its own machine and from its checkout, three
commands of the kit, in this order, each whatever the others' exits:

1. `tidy --targets`: the build targets past their use (cleanup.md 4,
   step 9); with `--room GB` while a landing's task in heavy's ledger
   waits for its floor (`disk_wait`, build-infrastructure.md 2, "A
   landing's room"), GB that task's `floor_gb` plus its `room_gb`;
2. `post wake --older 15`: each name whose mail has waited 15 minutes
   with no waiter, woken as delivery would wake it (post.md 3, 4);
3. `codex-run stale --post`: each run that will never post, told to its
   caller (post.md 5).

It appends one line to `tmp/fleet/tend.jsonl`: its start and end, and
each command's argv, exit and output lines (at most 200 each, then how
many more), under a lock, keeping 7 days. Its exit is 0 when all three
exited 0, else 1. `fleet-tend.timer` runs it every 5 minutes on every
machine `setup` sets up (section 6).

- **What the watch reads of it:** each tend once. The watch keeps, per
  machine, the end of the last tend it has read, and asks the probe for
  those after it, so a tend that falls between two rounds, or two
  tends in one, is never lost. The lines it reads are the tools' own:
  `tidy: deleted target …` (cleanup.md 4), `NAME woken` and `NAME
  queued, nobody will wake it: …` (post.md 3), and the runs told
  (post.md 5).

- **Why each machine:** what tending decides needs only its own
  machine, and runs its own kit's rules: a machine whose watch is down,
  or which no SSH reaches, still tends itself.
- **What it leaves:** a target in use, or held beyond its owner's two,
  stays (tidy reports it); a session that is stopped, or interactive,
  stays as it is (post reports it); the watch raises what it reports.

## 5. The room

`fleet room [--json] [--targets] [MACHINE...]`, from any machine whose
key reaches the others with a shell (hel8, the builders): every machine
of the machines file, or those named.

- **One line per machine:** cores; load (1, 5, 15 minutes) and load
  per core; CPU pressure; memory available of total; disk free over its
  floor; kache's store of its limit; heavy's running and queued tasks
  and the oldest wait; the Claude sessions (the director, designers and
  owners by name) and implementers by mission; then its verdict.
- **The verdict:**
  - `full`: a raise test of section 3.1 holds now for disk, load,
    memory or kache;
  - `room`: free disk at least 60 GB over its floor, the 15-minute load
    at most 1.5 per core, memory available at least a quarter, and
    heavy's oldest queued task waiting under 10 minutes;
  - `tight` otherwise, naming what falls short.
  The `room` machines come first, the least loaded per core first; an
  unreached one last, with why.
- **On the watch's machine** it adds the conditions raised now and the
  last round's time, from `tmp/fleet/watch.json`.
- **`--targets`** adds each machine's targets by owner with their sizes
  (section 2), their last build and whether each is in use.
- **`--json`** prints the readings and verdicts instead.
- **Its exit:** 0; 1 when a machine was not read; 2 for a usage error.

## 6. Installing

`setup` (agents' `scripts/infra/setup`), on each machine:

- **links `fleet`** with the kit's tools;
- **writes and starts `fleet-tend.service` and `fleet-tend.timer`**
  everywhere: a oneshot service running the checkout's `fleet tend` in
  a login shell (agents' `AGENTS.md`), `OnCalendar=*:0/5`;
- **writes and starts `fleet-watch.service` and `fleet-watch.timer`**
  only where `~/.config/agents-fleet/director` holds one address,
  `NAME@MACHINE`, as QA's service has its own (qa-flow.md 4):
  `fleet watch --director ADDRESS` in a login shell,
  `OnCalendar=*:2/5`. Elsewhere it warns if the watch's timer is
  active.

To take either down: `systemctl --user disable --now` its timer,
remove its two units from `~/.config/systemd/user/` (and for the watch,
the address file, or `setup` writes them again), and `tmp/fleet/`.

## 7. Testing

`scripts/devel/test-fleet`, in `scripts/check.sh`, on scratch trees:
three machines in a scratch machines file, a fake `ssh` that runs the
piped source in each machine's tree and refuses the third; fake
`claude`, `kache`, `post`, `codex-run`, `tidy` and `record`; `/proc`'s
files and the disk's figures from the fixture's tree, through
environment variables the fixture alone sets. It never reads the
machine's own.

- **The reading:** each field from its source; a machine without
  kache or heavy; a source failing alone, named in `errors`, the rest
  read; a field of the wrong type left out; no subject, command line
  or environment in the JSON.
- **The room:** each verdict, `tight` naming what falls short; the
  order; an unreached machine last, exit 1; a machine added to the
  machines file read with nothing else changed; `--targets`' sizes, and
  a `du` past its budget shown as unknown; the watch's conditions on
  the watch's machine.
- **The watch:** a test holding one round raises nothing, two rounds
  raise and post once, a third posts nothing; a clear after two rounds
  past the clear threshold, and a reading between the two thresholds
  changing nothing; two raises five minutes apart within the 10-minute
  gap carried by one post; a raise cleared before its post dropped from
  it; a failed post tried again, an exit 3 not; each condition of 3.1
  from its fixture; `deaf` raised in its first round; `session` from an
  active mission's README and not from a paused one's, cleared when
  the README says paused; `blind` from a source failing twice; a
  mailbox or a run's directory gone clearing its condition; two tends
  between rounds both read, and none read twice; `user` and
  `fleet` never raised; a `FLEET_QUIET` machine raising only
  `unreached`; a round with no state raising nothing in its first
  round; the subject's length; the body's 15 lines; `rounds.jsonl`
  pruned at 7 days.
- **The tend:** the three commands in order, each run when one before
  fails; its line in `tend.jsonl` with each exit and at most 200 lines;
  lines past 7 days dropped; exit 1 when any failed.
- **The units:** what `setup` writes, the watch's only with its
  address file (`test-after-landing-units` covers setup's units today;
  the owner picks the fixture).
- `test-tidy`, `test-post` and `test-codex-run` prove their tools'
  parts (cleanup.md 4, step 9; post.md 3 and 5).

## 8. Going live

1. **The tools' parts land:** `tidy --targets`, `post wake` and
   `codex-run stale --post`, each with its fixture. Until a tend runs
   them, only the director's full `tidy` reaches step 9, and the end of
   a run marks `post-failed` for every exit but 0 and 3.
2. **`fleet probe` and `fleet room` land.** The director reads the
   machines with `fleet room` from then on, at its check and before
   placing an owner.
3. **`fleet tend` and its timer land,** and reach each machine with the
   kit's rollout, one quiet machine at a time (`setup --fix`, twice).
   Before a machine's first tend the director reads there what it will
   do: `codex-run stale` (the runs of the last day its callers will be
   told of), `tidy --dry-run --targets` and `post list --older 15`; it
   stops any ended mission's session still running, and reads (`post
   read NAME`) the mail waiting for an ended mission, so that the watch
   raises none of it. A machine whose kit lacks step 1's tools tends
   with what it has: the commands it lacks exit 2, and the watch raises
   its `untended` until the rollout reaches it.
4. **`fleet watch` lands,** and hel8 gets its address file, `director@hel8`.
   The director's by-hand readings of the machines end.
5. **The roles' edits,** with step 4: director.md 2, 3 and 5 (the
   watcher is this timer, no task of the session's), 7 (the check reads
   `fleet room`), 10 (the floor is the watch's to watch) and 12 (the
   watcher and the probe answered); director-operations.md 3 and 8;
   owners.md 2 (the machine's line: the watch and the tend, no watcher
   of an owner's own); README.md 2 (the resource watcher). director.md
   is the user's, so its edits go to the director first.

## 9. Open questions

- **The director itself deaf or gone:** the watch posts it, and
  nothing tells the user. A push to the user's phone when the
  director's own mail waits an hour, perhaps.
- **The director's other tools** (director.md 12): `check-report.sh`,
  `session.sh` and `context.sh` remain open; the check's report might
  grow from `fleet room` and the status page's `--json`.
- **The room's memory:** a machine's last hour (its peak load, its
  lowest disk) from `rounds.jsonl`, where the room runs beside the
  watch.
- **The full `tidy`,** which the director's check runs on each machine
  with no landing (cleanup.md 5): whether a tend runs it, every few
  hours, and the watch raises its exit 1.
- **The thresholds** are first guesses from 10-26: the director tunes
  them from what the watch raises in its first days.
