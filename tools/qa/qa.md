# Rung walks

`qa` starts and resumes rung walks on fabrig, admits a hand-held login for a
live story, starts deployment units, and watches walks to their end. It is a
standalone Python 3.13 tool using the standard library and local commands.

```
qa walk fabrig a [--kind forgejo] [--build REF] [--login POOL]... [--cap MINUTES]
qa walk fabrig a --resume rung-a-12 --build REF [--cap MINUTES]
qa take forgejo [--login chatgpt] --as walk/forgejo/WHAT [--note TEXT]
qa give NAME --as walk/forgejo/WHAT
qa deploy DIRECTORY NAME -- COMMAND...
qa watch --director NAME@MACHINE [--once]
```

Only `fabrig` is a repository, with origin
`git@github.com:fabrig-ai/fabrig.git`. Each walk uses an existing fleet clone
at `~/src/fabrig/slots/N`, independent of DEV_ROOT. The tool never creates,
replaces or deletes a slot checkout, clone or worktree, and never uses or
creates `tmp/qa/repos`. A claimed slot's origin is validated, fetched and
pruned in place before REF resolution. Symlink slot paths are refused.
REF defaults to `main`. An exact origin branch (bare or
`origin/BRANCH`) or a unique 4–40 digit hexadecimal commit resolves before
login admission. Tags, stale tracking refs and revision expressions do not supply
branches; ambiguous branch/commit spellings require an explicit origin
branch or full commit. A hexadecimal object must be a commit. The saved SHA
is checked out even if its branch subsequently moves.

## Roots, settings and admission

`DEV_ROOT` defaults to `~/src/rust`, independently of the executable's
installation directory. `DEV_TMP` defaults to `DEV_ROOT/tmp`; codex-run's run
root is always `DEV_ROOT/tmp/codex-run`, including with a separate DEV_TMP.
No records workspace or evidence repository is opened. No pass scheduler,
record writer, finding router, evidence scanner or `keep` command is present.
Walk scratch and reports stay on the machine; the tool does not prune them.

Settings come from environment variables, then `DEV_TMP/machine.env`, then
these defaults. The file is data, never shell code. Numeric file entries
must be exact `KEY=DIGITS` lines; an absent file supplies no values. Unsafe
or unreadable settings refuse the command.

| Setting | Default | Meaning |
|---|---|---|
| `QA_WALK_KINDS` | `forgejo=2:chatgpt claude=2:claude` | Ordered `KIND=COUNT:POOL[,POOL...]` entries; COUNT is accepted for compatibility, caps come from named slots |
| `QA_WALK_SLOTS` | empty | `KIND=N[,N...]` entries; each kind tries its named slots in this order |
| `QA_SLOT_HOST` | `hetzner6` | This builder's inventory host name |
| `QA_CLAIM_OWNER` | `s/qa` | Owner of the walk's claims |
| `QA_CLAIM_SSH` | `hel8` | Claims host's SSH target; empty runs installed `claim` locally |
| `QA_STOP_SECONDS` | 50 | Wrapper's lock wait and exporter share this bound; positive and below 60 |
| `QA_GIVE_BACK_SECONDS` | 90 | Wait for a unit's stop confirmation; nonnegative |
| `QA_INTERVAL_SECONDS` | 300 | Mailbox wait between checks; nonnegative |

A walk's cap is `--cap`, 180 minutes at a start and the saved cap at a resume;
it must be positive. Its clock starts again on resume. Kinds start with a
lowercase letter and contain lowercase letters and digits. Slot numbers and
the compatibility COUNT are positive; pools are unique login pool names,
never numbered members. Duplicate kinds, duplicate slot numbers (including
across kinds), controls and malformed entries refuse the configuration.
Mappings for a currently unconfigured kind are unused. Each configured kind's
slot count is its cap, including hand-held logins; a kind without named slots
cannot walk or take another login. The old COUNT does not limit that cap.
The first kind is the default. Pass settings, including `QA_LOGIN_RESERVE`,
are unused: no pass is admitted, so there is no pass reserve to validate.
An undersized login pool remains a broken-cap refusal at take time.

For hetzner6's shares, the data lines in `~/src/rust/tmp/machine.env` are:

```
QA_WALK_KINDS=forgejo=1:chatgpt claude=1:claude
QA_WALK_SLOTS=forgejo=8 claude=4
QA_SLOT_HOST=hetzner6
QA_CLAIM_OWNER=s/qa
QA_CLAIM_SSH=hel8
```

The fleet supplies clean fabrig clones in slots 8 and 4, and installed
`claim` on hel8 reads the fleet's current inventory. The SSH target must
provide noninteractive access and a login shell with `claim` on PATH.

`POST_NAME` supplies the starter's name; the machine comes from the `local`
entry in `DEV_ROOT/tmp/post/machines`, else the hostname. The starter, rung,
cap, requested pools and REF are checked before any login is taken.
Admission holds `tmp/qa/walks.lock`, shared by starts, resumes and manual
takes. A kind holds at most its slots' number of logins of each pool,
counting every holder `walk/KIND/...`, including stuck or manual holdings.
Pre-kind holders `walk/rung-...` count too; managed pre-kind walks must drain
before a new kind starts. Takes are `logins take POOL --any --now --as HOLDER`
and never wait in the login queue. The child inherits the admission lock,
so an orphan take still excludes another admission. A refused take names the
broken cap and undoes the attempt's requests and saved grants.

`qa take` selects the kind's first pool unless `--login` selects another of
its pools. WHAT is a lowercase slug and cannot belong to a saved walk.
It prints the granted name and resting path, without reading its contents.
`qa give` validates the name and holder under the admission lock. It refuses
with exit 2, without calling logins, if any saved walk owns the holder or
claims the login name, including foreign repositories and saved attempts.
Unreadable custody also refuses. These holdings are released only by service
cleanup. An unclaimed hand holder passes through `logins give`'s output and
status, even if current kind settings are invalid or retired.
Manual holders remain held across watcher checks.

## State, start and resume

State is `tmp/qa/walks/NAME.json`; focused scratch is
`tmp/qa-focused/NAME/` (0700). The default kind uses `rung-RUNG-N`, another
kind `rung-RUNG-KIND-N`. Existing focused paths and saved walk names count
for numbering, including unknown repositories and changes of default kind.
The next number follows the maximum occupied number for the rung/kind;
occupied filenames and manual holders cannot collide with generated names.

Unknown-repository states (including temper and jig) are opaque: they are
never resumed, ended, returned or rewritten, and their claims, including
saved attempt claims, protect logins from stray or conflicting gives. Their
names count for numbering. Invalid or unreadable state blocks admission;
the watcher isolates it, disables stray sweeping and continues other valid
walks' cleanup. State reads refuse links, nonregular or multiply linked
files, reads above 1 MiB and invalid custody or attempt histories. Conflicting
claims return a login for neither owner. No existing pass state is managed.

Every content read or copy opens the file without following its final link,
then checks that same descriptor for a regular file, exactly one link and
ownership by the current user before reading any byte. This includes machine
and settings metadata, state, briefs, pause markers, stuck addresses, run meta
and facts, deployment traces and clocks. Unsafe files are refused by path;
optional pause and stuck files log the refusal and supply no marker or extra
recipients. Other users' processes are excluded from launcher discovery; own
process cmdlines receive the same descriptor checks.

Each managed change is saved through a sibling file and rename. Attempts
retain REF/SHA, cap, start, numeric slot and claim, grants, pools,
moved/in-place kinds, run, cleanup progress, alert receipts and pause decision.
Admission first saves an attempt without a slot, then tries the kind's
configured numbers with `claim claim HOST N OWNER 'qa walk NAME attempt A'`.
A refusal, including a claim by the same owner, tries the next number;
when all refuse, the attempt takes no slot or login. A timeout or uncertain
transport result refuses the attempt for orphan repair rather than risking a second claim. Every claim
command has a 60-second bound. With QA_CLAIM_SSH set, the command runs through
`ssh -o BatchMode=yes TARGET` and `bash -lc`, quoting every claim word and
the login shell's command separately. An empty target invokes local `claim`.
The accepted claim, including host, owner, target and WHAT, is saved before
checkout preparation.

A slot must have the exact fabrig origin and no tracked changes or untracked
files outside `target/` (including ignored files). Missing, dirty, wrong-origin
or linked checkouts are refused and preserved. Preparation fetches and prunes
origin, resolves REF there and switches detached to the saved SHA without
forcing or cleaning. It runs `python3 -I -B SLOT/tools/slots/trim SLOT`, bounded
to 300 seconds; output and status go to `prepare-ATTEMPT.log` in the walk's
directory. Trim failure is advisory. Then `df -B1 --output=avail /` (30-second
bound) must show at least 80000000000 available bytes, and
`cargo fetch --locked` (300-second bound) must succeed before any login take.
A preparation refusal cancels the attempt and releases its claim, retrying
release through the watcher when necessary. REF refusals therefore retain a
cancelled start or a failed resume attempt, with no login taken.

Pools are taken in name order, each grant saved before the next. Resting
paths are inspected by stat alone: directory logins are used in place,
others moved. The kind-specific brief
`tmp/qa-focused/rung-RUNG-KIND-brief.md`, else `rung-RUNG-brief.md`, is copied
byte for byte to `brief.md`. `task.md` names the checkout, resolved build,
cap, report, grant paths, give-back protocol and `qa deploy`. The session
must plan and follow the brief and product binding, keep notes and report,
give moved logins back before stopping deployments, and check configuration
before every start. The task requires
`HEAVY_CLASS=background heavy cargo build --locked --offline -p temper`, forbids
`--release`, `--target-dir`, target cleaning and other checkout changes, and
requires the 80000000000-byte root disk check before each heavy command.
Below the floor, the session waits five minutes and checks again. Deployment
data and a private copy of its binary stay in the walk directory so a paused
box does not depend on the slot's executable. A branch confirms a fix; the
rung's final walk ends on main at the landed commit. No login is read, copied or printed by the tool;
only its name and resting path are printed.

The clock is `tmp/qa-focused/RUNG/loop.tsv`, headed
`time<TAB>rung<TAB>walk<TAB>event<TAB>note`. Walk numbers include the nondefault
kind. Its locked appends are fsynced and deduplicated by kind, attempt and
event, including a crash between append and progress save. Start writes
`walk-start`; resume writes `walk-resume`; cleanup writes `walk-end` or
`walk-pause`. Other loop events belong to the rung owner.

A valid `paused` marker is a nonlinked, singly linked regular file whose
first line is 1–200 characters without controls or Unicode line separators.
After complete cleanup, a pause frees the slot and logins but retains
scratch, notes, deployment commands and the paused line in state. Resume
requires the same repository and rung, a completed and posted pause, an
explicit build, and no pool or kind changes. It preserves the walk's number
and prior attempts, reclaims and prepares a kind slot through the same
protocol before taking fresh grants, archives the current
report as `report-ATTEMPT.md`, removes `paused` and the old give-back, and
writes a task carrying notes, earlier findings and saved deployment commands.
It tells the session to restart kept data with REF's binary, check its
configuration, and start fresh in the same scratch if the kept store cannot
open. Failed resume preparation or launch returns only the new grants and
restores paused state for another attempt.

## Deployment and cleanup

`qa deploy` requires an absolute directory, not a symlink, a safe stop path
(no `$`, `%`, quote, backslash or whitespace), a lowercase NAME starting with
a letter, and an executable COMMAND on PATH. It prints `qa-DIRECTORYNAME-NAME`.
For a saved walk it requires a running walk in that directory, saves the
absolute executable and arguments for resume, and refuses reuse while the
previous unit is busy or unknown. A manager refusal restores the saved
command. Before launch it appends the unit name once to `deployments`, a
trace only; the watcher never trusts that file for unit discovery.

The transient user unit uses `Type=exec`, `KillMode=control-group`, collection,
`--expand-environment=no`, the caller's PATH alone and DIRECTORY as its working
directory. Output appends to `NAME.log`. `ExecStop` invokes this executable's
`_give-back DIRECTORY SECONDS`, before systemd signals the program;
`TimeoutStopSec` is SECONDS + 60. There is no ExecStopPost. Literal dollars in
command arguments survive. The deployment is independent of the session.

The wrapper runs executable regular `give-back` from its own directory with
closed stdin, under `give-back.lock`. Lock wait and execution share one bound;
process-group leftovers are killed even after successful export. Output and
status append to `give-back.log`; unsafe logs cannot prevent export. An absent
or linked exporter is skipped. Wrapper errors never fail the unit. A child
that creates a new session can escape this process-group cleanup; systemd's
cgroup remains the enclosing limit. The session's on-stop runs the same wrapper.

The watcher requires `~/.config/agents-qa/director` to exist and an explicit
valid director ADDRESS. `--once` makes one check. Otherwise it waits on the
`qa-watch` mailbox with its PID and kind codex, reads delivered mail and
checks again; a replaced mailbox holder exits 2. A separate nonblocking
`tmp/qa/watch.lock` permits one service. A busy walks lock skips that check.

At the cap it stops the session and confirms its unit is inactive, including
the stop wrapper. `ended` alone is insufficient. Then it gives moved logins,
alerts for stuck ones, discovers deployments through systemd, stops them
only after moved logins are back, confirms every stop, and gives in-place
logins afterward. Discovery requires exact unit names and the scratch working
directory; failed, duplicate or malformed observations keep custody. Stops
are nonblocking followed by bounded show polls. Every systemctl call has a
30-second bound; login and post calls 60 seconds, codex-run 120 seconds.
The slot stays held until session and deployment units are confirmed stopped.
At that point local `released` records the stop confirmation, and
`claim release HOST N OWNER` releases the saved attempt's claim through its
saved SSH target. Claim release has its own saved `slot_claim.released` flag;
errors retry at every check, even for ended or paused states, and never gate
login returns or the pause/end notice. Resume waits for its prior claim's
release. Before releasing, `claim list` must still identify the same owner
and WHAT. A free slot or successor claim confirms that the old claim is gone;
a successor is never released, including one with the same owner.

Under the admission lock, each check also lists claims on this builder's
configured kind slots. This owner's exact `qa walk NAME attempt A` claim with
no saved slot for that attempt is released, repairing a crash after claim
acceptance and before state save. Unrelated descriptions, other owners,
other slots and foreign repository walks are preserved. Unreadable saved
custody disables orphan repair; list/release failures retry on the next check.
A queued or running unit job, including on a loaded inactive unit, keeps
custody and the slot. A live or uncertain task launcher also prevents stop
confirmation, even with an ended marker; the unit and job are rechecked after
the launcher scan. Unknown state keeps it held. A strict `logins list` precedes gives; invalid
inventory gives nothing. A grant missing from its managed owner's state after
a crash is returned, while manual and unknown-repository owners are protected.

Each stuck moved login alerts the director and addresses from
`~/.config/agents-qa/stuck`: one per line, comments allowed, at most 16 valid
unique addresses in file order plus the director. The file is nonlinked,
regular, at most 16 KiB; damaged or absent files leave the director alone.
Receipts are saved per login and attempt and retried at each check until
post exits 0 or 3. Alerts name the login, pool, holder, resting path, scratch,
units and cap. They precede the starter's completion post and still retry
when unit state becomes unknown. One recipient's error does not stop another.

The saved decision is `walk-pause` only with a valid marker, all grants back
and all units stopped; otherwise `walk-end`. Cleanup and notices continue for
a stuck end. The clock records the decision once; the saved starter receives
the report path, exit and anything still out, retried until accepted. Delivery
is at least once: a crash after acceptance but before its save may repeat it.
The rung owner reads the report and files findings; the tool commits no record.

## codex-run and installation

Dependencies (`codex-run`, `logins`, `post`, `systemctl`, `systemd-run`, `cargo`,
`git`, `claim`, `ssh`, `df` and `python3`) resolve on PATH. The deployed
codex-run is fabrig's
`~/.local/bin/codex-run`; qa lives at current's `tools/qa/qa` and assumes no
adjacent legacy executables. The task call supplies absolute TASK, DIR and
REPORT, explicit `--to qa-watch` and an executable `--on-stop` callback.

Fabrig's `ID RUN_DIRECTORY` output identifies the run. Recovery matches
`meta`'s `task` and `report`, excluding earlier attempts; `ended` marks worker
completion, before unit stop necessarily completes. Facts read the unchanged
13-column `runs.tsv` layout. A missing unit is a possible launch for ten
minutes after meta, and afterward while a matching launcher survives; the
unit is rechecked after scanning launchers. `--resume RUN` supplies the new
checkout, recipient, callback, task and report explicitly. Codex-run can recover
a thread from events; qa delegates that decision to it. Only its missing-thread
or missing-meta refusal falls back to a fresh session. REPORT must not exist,
so resumes archive it first. The checkout is a fabrig numeric slot;
qa prepares it with trim and codex-run applies its numeric-slot lifetime
interlock and normal startup trimming.

`tools/installed` links `qa` to `tools/qa/qa` through fleet-sync. Installation
does not start a watcher. A deployment stops the legacy agents-qa-watch unit
before starting the walk-only service; old pass state, foreign walks, their
custody and pending alerts require the director's reconciliation separately.
The existing director and stuck-address paths remain the service's settings.
`QA_FIXTURE` gates executable and local-origin overrides for isolated tests;
without it `QA_*` executable overrides are ignored. The real-command-line
test keeps systemd programs on PATH with no executable override.

Run `python3 -I -B tools/qa/test_qa.py`. Every unittest case runs in its own
process, session and temporary HOME/DEV_ROOT with local git origins, fake
services, fake local and remote claims, fake disk observations, slot clones
under the temporary HOME and fixture launcher observations; descendants are
killed and reaped. The suite runs at most eight cases concurrently. It never uses real logins, a real manager or network.
