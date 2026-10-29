# Build infrastructure

Provisional, 2026-10-26. The host admission and recovery contract for the
owners' `heavy` commands. Runtime identity is specified by gate-policy.md.

## 1. In one page

- **Optional, never a precondition** (the user, 10-26). Builds, the
  repositories' scripts and `land` work with plain commands where heavy
  isn't installed; there `heavy CMD` runs CMD directly. A machine has
  heavy once `heavy --install-reconciler` has recorded it in the ledger,
  and the build machines keep everything below, unchanged (section 12).
- **Weights, not slots** (build-efficiency.md, 5). Every task builds as
  wide as the machine, and builds take no slot unless the machine sets
  `HEAVY_BUILD_SLOTS`. Each task's systemd unit carries a CPU weight: a
  landing's gate (`heavy --land`) 10000; an agent's builds, and a
  landing's prebuild and regeneration, 1000 (the director, 10-26,
  decision 1210); `HEAVY_CLASS=background` 100, `HEAVY_CLASS=idle` only
  idle cores.
  When the cores are contended, landing work takes them first; when they
  are not, nothing waits. `cargo fmt` builds nothing and runs at once.
- **heavy is its own queue.** Its host ledger admits every task, and
  numbers it, never reusing a number. Each task's wrapper runs as a user
  unit of its own, which outlives the client. No queue daemon stands
  between them: pueue's role ended on 10-26 (section 7).
- **A lane keeps submission order.** Each lane, `build` and `gate`,
  admits its waiting tasks oldest first, as far as it has room.
- **A landing has its room** (section 2, "A landing's room"). While a
  landing's task waits or runs on a machine, other builds start only
  with a reservation free above the floor, and wait for it, while the
  landing starts on the floor alone and waits for that, rather than
  being refused.
- **One exclusive gate, by choice.** `heavy --gate` still runs alone, one
  at a time: for what needs a quiet machine, a kache setup or a
  measurement. Host admission counts task lifetimes in the ledger, not
  processes.
- **Intent precedes effects.** An exclusive gate records its token, boot
  identity and owned systemd unit as the ledger's gate hold, in a durable
  atomic snapshot, before it drains the machine. Every hold, a gate's or
  an operator's, lives in the ledger and nowhere else.
- **Containment owns descendants.** Every payload executes in a user
  systemd service with `ExitType=cgroup`, `KillMode=control-group` and no
  delegated subtree. Changing sessions does not escape it. A wrapper's or
  a payload's exit triggers recovery; neither proves descendants ended.
- **Recovery is independent.** A user systemd timer reconciles the same
  host ledger as admission and normal completion: it releases what ended,
  recovers what lost its wrapper, and cancels what no wrapper claimed. Its
  approved polling default is five seconds (director 586). It is not a
  task timeout or a gate budget.
- **Release is replayable.** Under the host lock, mark the task closing,
  kill its owned cgroup, prove it empty, drop its gate hold, and commit
  one logical release outcome per token.
- **Evidence is durable and narrow.** JSONL events carry task identity,
  phases, capacity and safe policy identity. They carry no task
  environment, command or output. The eleven-column TSV remains available
  for diagnostics; land accepts token-owned receipts.

## 2. Ownership and admission

heavy's queue is its own: the host ledger in its state directory, and the
user units it starts. Every task enters through `heavy`; a unit started
by hand under heavy's prefix is outside this contract. Unsupported
containment refuses admission visibly. The helper requires Python 3.11
or newer and uses only its standard library.

`DEV_ROOT` selects the workspace and `DEV_TMP/heavy` holds host state.
All callers sharing a queue share this state directory, which is the
queue: its identity is the SHA-256 of the directory's canonical path,
whose first twelve digits also name its units (`skein-heavy-…`). A ledger
that records another identity belongs to an older generation, and is
taken over only once it is drained (section 7). The host lock serializes
admission, reconciliation and explicit maintenance operations.

Submission, under the host lock, saves a unique token, the ledger's next
task number, safe context and the task's environment file, in state
`queued`. It then starts the wrapper, `heavy --task TOKEN`, as a
transient user service, `PREFIX-TOKEN-wrapper.service`: collected when it
ends, reading that environment file, in the submitting directory, with
umask 077. Only then does the client print the task's number and token.
A wrapper unit that fails to start releases its task, refused, before the
client returns. The wrapper claims its token under the host lock, and
only a `queued` one, recording its PID, process start tick and boot
identity; payload start is a separate event inside the payload's own
unit. The wrapper's unit belongs to the user manager, not to the client:
a client may disappear without losing task ownership or completion
evidence.

A token still queued whose wrapper unit is not running was never
claimed: the reconciler cancels it, code 137 (section 4). That covers a
client killed between saving the task and starting its unit, and a
wrapper stopped or dead before its claim. A wrapper that starts after
its token was cancelled refuses replay. Client death after the unit
starts does not cancel the task, and no task age limit is imposed; an
interrupted client, or `heavy --cancel`, does (section 4).

Each lane admits its waiting tasks oldest first, by task number. A task
is admitted only while fewer older tasks of its lane are still queued or
waiting than the lane has room for:
- the `build` lane has room for `HEAVY_BUILD_SLOTS` live builds (0, the
  default: no limit), and for none while a gate holds the machine or an
  operator holds the lane;
- the `gate` lane has room for one gate, while no other gate is live, no
  other exclusive gate holds the machine and no operator holds the lane.

Gates of both kinds therefore start in the order they were submitted.
A build never takes room that an older build waits for: with one slot,
builds too start in submission order, and those admitted together start
in any order among themselves. A live task is one launching, active,
finishing or closing: it keeps its room until its cgroup is proved
empty.

An exclusive gate (`--gate`), once its lane admits it, records itself as
the ledger's gate hold, which blocks every other admission, then drains
the ledger's live lifetimes, builds and landing gates alike, and waits
for the load to settle. A landing's gate (`--land`) takes the same
policy, candidate checks and receipt, but no hold: it starts beside the
builds, first by its CPU weight, and alone among gates, since two would
split the machine against wall-time budgets. Every payload unit but a
landing's also carries `OOMScoreAdjust=500`: out of memory, the kernel
kills an agent's build, which reruns, before a landing's work. Every
task builds with `HEAVY_BUILD_JOBS` jobs, the machine's CPU count by
default, and its unit carries its class's `CPUWeight` (section 1).

The disk floor is 40 GB by default, overridden by `PLAN_MIN_DISK_GB` in
`DEV_TMP/machine.env`, with the environment taking precedence, and measured
on the workspace's filesystem (`DEV_ROOT`'s). Installed heavy checks it at
submission (where a landing's task waits for it instead, "A landing's room"
below) and again inside the owned cgroup immediately before the requested
command starts, after any lane wait or gate settling.
A below-floor landing therefore starts no prebuild, even when space fell
while that prebuild waited. The refusal keeps heavy's exit 2, its free-space,
floor and largest-directories diagnostic, and land's exit 9. The gate keeps
both checks: a prebuild can itself consume the remaining room. Cancellation,
recovery and plain execution still skip the floor. A queued refusal releases
through the usual ledger and receipt path, with no payload-start evidence.

The current target size is measurable with `du`, but it is occupied space,
not an estimate of the next build's additional space: warm targets reuse
files and clean targets predict nothing. Adding that whole size to the floor
would reject useful warm builds and scan large targets at every landing.
Keep the floor check; no target-size reservation is added.

This change adds no ledger or unit format and needs no setup or state
migration. The director rolls out the kit; reverting the change restores
submission-only checking without editing state.

**A landing's room.** On 10-26 and 10-27 sets first in line stopped at
the floor again and again: four times in three hours on hetzner6, where
other owners' builds swung the free disk by about 25 GB at a time
(decision 1365). A landing refused at the floor loses its place, and
the build that took its room goes on. So the room is the landing's,
and the others wait for it:

- **A landing's task** is one labelled `land REPO`, or `land REPO
  STEP` for a step of a landing, `prebuild` or `regenerate`
  (`HEAVY_LABEL`, as `land`, `land-set` and `land-resolve
  --regenerate` submit them), in either lane. A regeneration is a
  landing's step: as a build it would wait on its own set's
  reservation, or outlive it before the next prebuild (o/land-room's
  review, 10-27).
- **The reservation** holds on a machine while a landing's task is in
  the ledger and not released, and for 2 minutes after the last one's
  release, so that a landing's next step (its gate after its prebuild,
  a set's next repository) finds its room. It is `PLAN_LAND_ROOM_GB`
  (the environment, then `machine.env`, as the floor: `kit.sh`'s
  settings take it), 30 GB by default: the swing of a temper build,
  with some margin.
- **Settings travel with the task.** Every task records at submission
  the floor and the reservation it was submitted under, `floor_gb` and
  `room_gb`, so that admission, the reconciler and the machine's tend
  judge it by the settings its caller had, environment overrides
  included, and not by their own environment.
- **Others wait for room.** While the reservation holds, the build lane
  admits a task that is not a landing's only with its `floor_gb` plus
  the largest `room_gb` among the reserving landings' tasks free;
  otherwise it stays queued, and the lane's order holds behind it:
  with unlimited slots too, admission checks the older builds' room
  before a younger one's, so none passes a build that waits. Its
  submission's check and its payload's check stay the floor's alone: a
  build is refused only below the floor, as before. A build already
  running goes on.
- **A landing goes first.** A landing's task is admitted on its own
  floor, and the lane's order counts, for it, only the older landings'
  tasks still queued: never the builds that wait for room, which would
  otherwise hold back the landing that is to release them (with
  `HEAVY_BUILD_SLOTS` set, a slot still counts its live tasks). Among
  landings, submission order holds as before.
- **A landing waits for its floor.** A landing's task below the floor
  at submission is not refused: it is queued, and admitted once its
  floor is free. Its ledger entry's `disk_wait` is the time its current
  spell below the floor began: set when admission or the reconciler
  first finds it queued with its floor short, cleared when the floor is
  free again (even while a lane hold keeps it queued), so that 20
  minutes is the time below the floor alone. The machine's tend reads it
  to make room ([fleet-watch.md](fleet-watch.md) 4).
- **Refused after 20 minutes, durably.** The reconciler, under the host
  lock, releases a queued landing's task whose `disk_wait` is 20
  minutes old as refused (code 2, refusal `disk-floor`), through the
  usual release and receipt path, as a queued refusal is today; a crash
  of the client or the reconciler loses nothing, since the time is in
  the ledger. The waiting client, finding its token refused, prints the
  floor's diagnostic and `heavy: disk floor refused before payload
  start`, the line `land` maps to its exit 9, and exits 2; the wrapper's
  unit writes only to the journal. A wrapper dead before its
  claim is cancelled as today (code 137, section 2).
- **The payload's check** stays the floor's, with no wait: a landing
  admitted on its floor that finds less just before its command starts
  is refused, as before. It judges by the task's `floor_gb`, as
  submitted, and its diagnostic says so.
- **Wall time.** The 2 and 20 minutes are wall-clock times, as the
  ledger's others are: a clock step shifts them. A monotonic pair
  would be a ledger change, not made.
- **What it costs:** a landing's wait under the set lock holds other
  landings for as long, at most 20 minutes, where today the set stops
  and loses the lock. Others' builds wait while a landing reserves and
  the disk is short; the tend's clearing (cleanup.md 4, step 9) and the
  landing's end release them.
- **Its format:** the ledger gains, on a task, `floor_gb` and
  `room_gb`, numbers, and `disk_wait`, a time or absent; readers that
  don't know them ignore them, and a task without them (submitted
  before) is judged by the machine's settings. Reverting the change
  leaves them unread.
- **Its fixture,** in `test-heavy-recovery`'s scratch ledger and a disk
  whose free space the fixture sets: a build queued behind a landing's
  task while the reservation is short, and admitted once it isn't; a
  landing's prebuild admitted past it, with one build slot as with
  none; the reservation held 2 minutes after the last landing's task
  and not after; settings from the submitter's environment judged by
  the reconciler without it; a landing below its floor queued with
  `disk_wait`, the wait cleared when the floor frees under a lane hold,
  admitted when the floor frees, refused by the reconciler after 20
  minutes below it with exit 2 and the line that makes `land` exit 9,
  also when the client was killed meanwhile; a build still refused only
  below the floor; a landing's payload check refusing as before.

## 3. Durable state and release

The version 1 host snapshot contains the queue identity, the next task
number, task records, the current gate hold, maintenance holds,
installation proof and an event outbox. Files are created with umask
077. Save writes a sibling temporary file, flushes and fsyncs it, renames
it over the snapshot and fsyncs the directory. A leftover temporary file
is never read as state.

Each task records its unique token, number, queue identity, boot
identity, wrapper identity, wrapper and payload unit names, lane, label,
repository, tree, policy identity, log path and command. Commands are
private task metadata and remain in the TSV for compatibility; events
exclude commands and output. Task states are queued, waiting, launching,
active, finishing, closing and released.

Admission captures both the candidate commit and its Git `HEAD^{tree}`.
A versioned gate requires a clean index and worktree, with no merge or
rebase in progress, at admission, contained entry, immediately after
settling before command start, and at command completion. A changed
commit, tree, index, worktree or merge/rebase state refuses completion
with an instruction to rerun land. The receipt's tree remains separate
from the commit identity retained in task metadata. Runtime preparation
compares a supplied policy with the computed policy at submission and
inside containment; payload entry also compares with the persisted
submitted identity. It never replaces that expected identity.

A wrapper identity ending, or a changed boot ID, marks the task closing.
Normal payload completion takes this same path. Closing is saved before
killing the token's unit. Recovery checks both the systemd unit's
cgroup and its recorded cgroup path, using cgroup v2 `populated` evidence.
A release occurs only after neither contains processes. Old boot IDs do
not authorize skipping the current unit check.

**The payload adopts its orphans** (10-27: three user managers exited
in an hour, each killing every heavy unit and runner on its machine: a
test's process whose parent had died was adopted by `systemd --user`
and signalled "its parent", and a user manager exits on SIGTERM). The
payload unit's top process, the guard below, makes itself a child
subreaper (`PR_SET_CHILD_SUBREAPER`) before it starts the requested
command, and stays as its parent: an orphan of the payload is adopted
by it, a stray signal to "the parent" ends that one task, and the guard
reaps what it adopted before the payload ends. The wrapper, in a unit
of its own, is no ancestor of the payload and cannot do it.

The cgroup payload guard takes the host lock and verifies an unreleased
launching token, a live wrapper, the boot identity and its owned populated
cgroup before any policy preparation or requested command. It durably
marks that scope active before executing Chromium, compiler, Cargo or
other policy version launchers. Their descendants, including detached
helpers, belong to the same scope and its release proof. A systemd unit
creation delayed past orphan release cannot execute policy tools or the
requested payload. The task's environment file, written at submission for
its wrapper's and its payload's units, is removed at release; the removal
is replayed for released tokens after a crash between durable release
and unlink, and does not change a sealed log or receipt.
Unit names are unique for the token and are never reused. Finishing a
payload kills private daemons in the same cgroup before freeing capacity.
The shared kache daemon runs in its own active user service; heavy refuses
an effective kache wrapper if that service is inactive, and never lazily
starts kache inside a task. Selection follows Cargo's increasing config
precedence, `[env]` force/relative settings and PATH, generic
`CARGO_BUILD_*` overrides, then dedicated wrapper overrides. An empty
dedicated override disables only its wrapper slot; the workspace wrapper
is independent. Masked global settings do not require kache. Refusals give
the caller the service/override remedy without printing configuration or
environment values. Collection connects to the existing service.

**The snapshot holds what is live** (10-27: ledgers of 6-11 MB and
4,500 tasks, parsed by every waiting client ten times a second, cost
each client half a core). A released task shrinks once nothing in
heavy reads the rest of its record: its TSV row durable, its release
complete, its receipt written, and its landing's room no longer kept
(section 2, "A landing's room"). At the first save after all of these
it keeps only its token, number, state, code, `row_durable` and
release time, enough for a late wrapper's refusal and for the
release's replays; 24 hours after its release it leaves the snapshot.
Every reader inside heavy takes a shrunk task as released. Its history is the TSV row, the receipt
and the events, which every reader of the past reads instead. The next
task number never goes back, so no number is reused.

**A waiting client reads the snapshot at most once a second**, under
the lock or not: while it waits for admission, and while its payload
runs, when it may instead block on its launcher and read once at its
end. Admission keeps submission order whatever the clients' timing.

A gate's hold is the ledger's gate token: saved before draining starts,
and cleared in the snapshot that commits the gate's release. While it is
set no build and no other gate is admitted, across crashes and restarts
alike. Operator holds are separate: a gate neither sets nor clears them.

## 4. Independent recovery and maintenance

`heavy --install-reconciler [INTERVAL]` probes real cgroup containment,
including a `setsid` child, and installs an enabled user service and timer
named from the state directory's hash. Installation is explicit. It
records the installation in the ledger before it writes or enables a unit,
so that one cut short leaves heavy installed and refusing, until it is run
again, rather than absent (section 12). It
changes no credentials, caches or runtime profile. The service reads a
private file containing only the required workspace configuration.
Admission requires the timer to be active and a containment probe for the
current boot. After reboot, reconciliation and admission repeat the probe
before accepting new work. Reconciliation can recover old holds first. A
missing user bus or unsupported systemd capability fails visibly.

`heavy --reconcile` runs the common recovery path: it releases the tasks
whose payload ended, recovers those whose wrapper identity ended or whose
boot changed, and cancels the tokens no wrapper claimed (section 2). The
timer survives a killed wrapper and a killed submitter.

Existing waiting clients inspect systemd's reported recovery service and
timer state. A failed/missing service, an inactive timer or an unreadable
snapshot produces actionable recovery instructions. Clients continue
waiting on reported service/timer failures, retaining task ownership;
an unreadable snapshot returns nonzero without cancelling the task.
Elapsed task age and delayed ticks never establish failure or a timeout.
For storage failure, free space, restore/restart the same recovery service
if needed, and run `heavy --reconcile` with the same `DEV_TMP`. Retain
the ledger; do not delete/reset it. Reconciliation is replayable. Rerun
land when completion is recovered with exit 137.

`heavy --maintenance-pause LANE`, for `build` or `gate`, saves an
operator hold: the lane admits nothing until `heavy --maintenance-resume
LANE` clears it, while its running tasks go on. A hold on `gate` also
keeps an exclusive gate from taking the machine. A gate's hold and an
operator's never clear each other. `--maintenance-resume` clears any held
name, including one an older ledger holds for a lane that no longer
exists. `heavy --group-held LANE` exits 0 while an operator holds LANE,
or while a gate holds the machine and LANE is not `gate`.

`heavy --cancel TOKEN` takes back one task, queued or running, by the
token printed at submission (10-25). A malformed or unknown token, or a
caller whose working directory is not the task's recorded repository,
is refused in fixed words, changing nothing. Under the host lock it marks
an unfinished task closing, outcome `cancelled`, code 130, then releases
it on the common path: owned scope killed and proved empty, a gate's
hold dropped, TSV row and receipt published. A wrapper that starts later
finds its token released and refuses replay. The waiting client ends
with 130 and its usual summary. The command exits 0 once the task is
released, 1 if it had already ended (finishing, closing or released: its
result stands), 2 on a refusal; past 60 seconds it leaves the release to
the reconciler. It skips the disk floor. SIGINT or SIGTERM to a waiting
client cancels its task the same way, between host-lock sections; a
second one leaves the release to the reconciler and exits 130. land's
capture ignores SIGINT, so Ctrl-C on land cancels its gate and land fails
with 4.

`heavy --remove-reconciler` refuses unfinished tasks, then removes only
its own timer and service. Where heavy is installed (section 12),
`setup` checks recovery readiness without installing it, and reports
each lane's holds through `heavy --group-held`; it neither needs nor
checks a queue daemon. Tests use a
distinct state directory and unit names; no live ledger or unit is
touched.

Every hold has one owner, the ledger, so none has to be inferred from a
process list or restored by hand. Taking over an older generation's
ledger is section 7's.

## 5. Events and compatibility

Optional collection has one 60-second monotonic deadline for service readiness
and the GC RPC together. Timeout or execution failure preserves the payload exit;
only the operation's own client is killed and reaped, with output discarded.
The existing GC end event records a fixed outcome and reason. Server-side GC may
continue; release still requires the owned cgroup to be empty.

`DEV_TMP/heavy/events.jsonl` records submit, wrapper start, admission,
scope entry, phase begin/end for drain, settle, payload, release and
collection, task completion, cancel, unclaimed tokens, refusal, recovery
and migration. Records include a unique event ID, token, timestamp, boot
and queue identity, lane, label, repository, tree, effective safe policy
ID, whether the task is an exclusive gate, free disk and memory capacity,
and the entrypoint recording the event; admission adds the task's CPU
weight, jobs and build slots. A contained gate sources
`gate-policy.sh` and calls `gate_policy_prepare`, both at submission and
inside the contained task. Policy errors prevent payload entry. The
recovery fixture can
use a fake Chromium 147 repeatedly, while its combined land/cache and
policy overhead cases use the installed Chromium 147. Missing policy
helpers or runtimes refuse gate submission visibly.

The snapshot outbox precedes journal appends. Appends are flushed and
fsynced; replay deduplicates by event ID. An interrupted final JSONL line
is truncated before replay. The TSV uses its unique per-token log path
for the same recovery property. The snapshot retains a completed task's
row until it is durable. Repeated reconciliation creates neither another
release outcome nor another TSV row.

The TSV columns remain task number, lane, UTC completion, wait seconds,
run seconds, exit code, available memory GiB, working directory, log
path, command and label. Task numbers come from the ledger and are never
reused within it; tokens and log paths are the durable identities. Heavy
prints its task number, the requested log tail, and its task completion
summary. The phase events distinguish wrapper startup, drain/settle time
and payload execution; TSV wait time ends at payload start and run time
includes completion cleanup.

After cgroup-empty proof and durable terminal release, events and TSV are
flushed before receipt publication. Recovery seals the service's private
capture into a separate immutable `TOKEN.log`, fsyncs it, hashes its complete
bytes and atomically publishes the private 0600
`DEV_TMP/heavy/receipts/TOKEN.json`. Publication is replayed after crashes.
A delayed service can write only its capture, never the sealed log. The
receipt follows the exact 17-field heavy-receipt-v1 contract in
gate-policy.md, section 3.1. Cancelled, recovered and unstarted payloads
always have nonzero codes. After tail and summary the client prints the
receipt path and token as its final output line, outside the hashed log.

## 6. Fault verification

`scripts/devel/test-heavy-recovery --evidence NEW_DIRECTORY`
exercises the production heavy entrypoints with disposable state
directories and user systemd units, and no queue daemon. It covers a
killed hold intent, fsynced intent before rename, setsid/private
descendants, release and release snapshot windows, a wrapper unit stopped
while its payload runs, boot identity change, client death before the
wrapper unit starts, a wrapper unit stopped before its claim, submission
order in each lane, maintenance holds on either lane and during a gate,
two gates with builds, journal replay, late systemd creation, the
takeover of a drained and of an undrained older ledger, and the
rollback. Assertions check exclusion through cgroup release,
progress, one release per token, task numbers never reused, private
descendant death and shared daemon survival. The fixture uses short
reconciler intervals without
changing production task timeouts or test-suite budgets. ENOSPC injection
at snapshot, journal and log-sealing writes requires the same isolated
fixture flag/path contract; it never fills the shared filesystem. These
cases assert caller diagnostics, retained ownership, no false successful
receipt, and progress/idempotence after restoring the same service and
ledger. A release-flush crash followed by delayed launch checks that no
policy launcher/helper runs, the late cgroup empties and transport cleanup
replays. Active policy-helper descendants also undergo cgroup release.
Candidate cases mutate commits, index/worktree and rebase state after
settling, during payload and after receipt, including expected-old ref
failure. Raw artifacts
include each case's ledger, event journal, logs, probe, descendant cgroup
evidence and cleanup receipt.

The combined cases also exercise receipt-publication crash and real
land/cache entrypoints in disposable Git repositories. The unclaimed-token
case runs at the approved five-second interval: it anchors a live
reconciliation, then observes recovery on the subsequent periodic tick.
Other recovery fixtures use 0.2 seconds and are labelled accelerated.
Runtime, semantic policy and
missing-runtime changes before payload refuse without cache or ref advance.
Receipt faults cover before publication, a fsynced temporary receipt before
rename, and after atomic publication. The rollback case runs the previous
generation's entrypoints, unchanged, against a drained ledger of this
one, then section 7's way back.
Recovery fixtures also cover real Chromium 147 receipt/cache reuse.
`test-after-landing` proves the runner with stand-ins for heavy and post. Cancel cases cover a
queued task (below the disk floor, then its late wrapper's refused
replay), running build and gate scopes with a `setsid` child, every
refusal, a waiting client's SIGINT and SIGTERM, and Ctrl-C on land.
Land-entry storage and missing-reconciler cases require the warning on
the waiting caller's stream before restoring the same service/ledger,
with no receipt/green while broken. The capture write uses guarded `/dev/full` to obtain kernel
ENOSPC without consuming disk space; both prebuild and gate paths refuse
landing after that capture failure.

Overhead measurements run the same lightweight payload directly and
through heavy in interleaved pairs, at least three times. Event counts
and bytes accompany timings. Individual case elapsed times are single
samples, not performance budgets. Cache collection uses a fixture executable, leaving the shared store alone.
Fault barriers and boot overrides require the explicit recovery-fixture
flag and paths beneath the isolated DEV_TMP. No full repository gate is
part of this recovery fixture.

## 7. Quiet migration, queue replacement and rollback

One generation of the kit runs on every machine (the user, 10-25):
`scripts/devel/`'s `heavy`, `heavy-recovery.py`, `land`, `land-capture.py`,
`land-turn.py`, `gate-policy.sh`, `receipt_inputs.py`,
`recovery_message.py` and `kit.sh`, with their `test-*` fixtures;
`after-landing`, proved by `test-after-landing` with stand-ins for heavy
and post; `scripts/infra/setup` and `kache-setup`; and the workspace files
in `scripts/infra/workspace/`. `setup --fix` links the tools on PATH and
the workspace files to the primary agents checkout (agents' `AGENTS.md`),
and each tool finds its helpers beside it, so `heavy`, `land` and their helpers
always move together. There is no installed copy.

Until 10-25 the fleet ran a frozen release of the kit, copied under
`~/.local/share/agents-kits/`. Every machine moved to the checkout that day,
keeping its queue, ledger and state directory, and the releases are gone. A
new build machine runs `setup --fix`, then `heavy --install-reconciler`, which
writes the reconciler's units for the checkout's helper under the host lock,
then `setup` again. A machine that runs no heavy, a person's laptop, stops
after `setup --fix` (section 12).

A change to `heavy`'s ledger or units must stay compatible with tasks in
flight, because each machine takes it as its checkout moves. One that can't
lands only once every machine is drained, and its commit says so
(agents' `AGENTS.md`).

Until 10-26 heavy ran each wrapper as a pueue task, and its ledger's
identity hashed pueue's configuration. The current generation takes such
a ledger over only drained: when every task in it is released, it
records a migration event with the old identity, sets its own, numbers
the next task above every number in the ledger, and keeps every row and
hold. Until then it admits nothing new, and says why (`drain first: N
tasks from the pueue generation`), and it leaves the ledger's identity
as it is, so that the older generation's processes still running can
finish. It releases the older tasks on the common path: a task whose
wrapper claimed it keeps its units and cgroup and is released when it
ends, or recovered if its wrapper dies; a task never claimed (submitted,
enqueuing or queued) is cancelled with 137, which its client reruns. A
wrapper that pueue starts later for an older token finds it cancelled
and refuses replay. The current generation never calls pueue: pueue's
daemon, its data and its groups stay as they were, and their removal is
a separate step on each machine. A pueue pause that the ledger doesn't
record has no owner and does not carry over, so before the machine
moves, the older generation's `setup` reports each lane running or held
by heavy.

Never reset or replace a live queue or erase its ledger. A fresh state
directory, or a retired ledger, requires a drained machine first: no
caller, wrapper or unfinished token. Retain the retired ledger and
evidence. After reboot the user manager restores the reconciler's timer,
and the shared kache service when selected; reconciliation then recovers
the old boot's tasks with the same configuration and state. Resolve
recovered nonzero completions by rerunning land.

Rollback is reverting the commit on a drained machine. The pueue
generation refuses a ledger of another identity in fixed words and
writes nothing, so the revert comes with a way back: on the drained
machine, the ledger is retired beside itself (`state.json` renamed to
`state.json.retired-DATE`, and kept), then `heavy --install-reconciler`
and `setup --fix` start the pueue generation on a fresh ledger. Unit
names, the journal, the TSV and the receipts carry over; the retired
ledger's operator holds don't. A hold on `build` is applied again with
the older generation's `heavy --maintenance-pause build` before the
machine takes work; that generation cannot hold its gate lane, so a hold
on `gate` is resolved before the rollback, or the machine stays out of
work. pueue's daemon and groups must still be there, which is why their
removal waits until this generation has run cleanly on that machine.
Rollback requires no destructive cache or ledger cleanup.

## 8. Advisory landing turn

`land`'s opt-in advisory turn is the set lock, land-set's (section 10): a
landing that pushes to skein, smith, hearth, jig or temper takes it before
its host repository lock, so that every write to those `main`s is ordered
and none moves under a set's run (landing-flow.md, 9.2). The repository is
its checkout's directory, or a bare clone's name less `.git`; it is the
set's by that name or by `origin`'s.

- **A code landing proves first,** without the lock: `land --no-push` with
  the same arguments and `LAND_TURN_ACTIVE=1`, its prebuild and gate
  included. A red or a refusal never takes the lock, and its result is
  land's. A green proof's output goes to stderr, so that stdout and
  `LAND_RESULT` hold only the landing's.
- **Under the lock it lands only while the proof holds:** the gate is a
  cache hit, and the tip is the proof's commit, its trailers already in
  place. When `main` moved meanwhile, that pass runs no build and exits
  10 (`LAND_PROVED=1`), and land gives the lock back and proves again.
  The third landing pass gates under the lock, so that a busy `main`
  cannot starve a landing. Otherwise a `main` that moved during a prove
  would make the landing gate while holding every set repository's lock;
  a temper regate after a moved `main` took 161 s bare on an idle
  hetzner2 (the build-efficiency session, 10-25), and longer through
  queues.
- **`--docs`** takes the lock for its rebase and push, with no proof.
- **No turn:** `--local`, `--no-push`, other repositories (agents), and
  land-set's own commands, which run with `LAND_TURN_ACTIVE=1` under the
  lock land-set holds. `--no-push` takes no host repository lock either:
  it moves no `main`, and a prove holding it would leave a landing under
  the set lock waiting on that machine.

`~/.config/agents-land-turn/enabled` containing `ssh` or `local` enables
it, overriding environment mode and holder with that mode and the
`land-turn.py` beside `land`. Removal turns off future ordinary
invocations; without it, the `LAND_TURN=1` environment fixture interface
below remains available. Invalid contents or read failure fail open. The
original arguments are retained across the guarded child entry. The gate,
receipt validation, retry and fast-forward push remain land's protection;
the advisory turn does not authorize a push.

Director 612 approves hetzner3 as the coordinator. There is one process
per connection, a retained repository-specific flock, and no listener,
queue, fairness promise, origin lease ref or failover. The bounded
current-holder record is diagnostic: stale bytes after a killed holder
never establish ownership. The coordinator's lock and journals use
`/home/free/.local/state/agents-landing-turn` across kit updates.
Never unlink or replace a live lock file or select a different state
path while callers exist: that would split the flock identity.

The holder is `/home/free/src/rust/agents/scripts/devel/land-turn.py` in
the coordinator's primary checkout, and `LAND_TURN_HOLDER` must name
exactly that path. Every fleet machine keeps its checkout there, so the
`land-turn.py` beside its `land` has that path too. Other paths, shell
syntax and invalid modes fail open with a fixed reason. Missing helpers
and failed connections also fail open; there is no fallback holder.

`LAND_TURN_MODE` defaults to `ssh`. The client builds an argv for `ssh -T`
to the fixed `free@2.29.124.199`, with `BatchMode=yes`,
`StrictHostKeyChecking=yes`, `ConnectTimeout=5`, `ServerAliveInterval=5`
and `ServerAliveCountMax=2`. `UpdateHostKeys=no` prevents opportunistic
trust updates; `LogLevel=QUIET` and discarded transport stderr keep SSH
and remote interpreter diagnostics out of the narrow turn records. The
remote command is shell-quoted from validated argv and starts
`python3 -I -B` with the exact holder path. No key, trust or SSH
configuration is changed. Trust/auth/connect/start failures surface on
the caller as fixed fail-open reasons without raw remote output.

Per-host configuration, kept by setup (the director, 10-28): every fleet
machine has `~/.config/agents-land-turn/enabled`, `local` on hetzner3
(hostname `debian-16gb-hel1-3`, the coordinator) and `ssh` on every other
builder and hel8; `setup` checks it and its strict ssh to the coordinator,
and `--fix` writes a missing file. On 10-28 four builders had lost it in
their redeploys and provisioning, and their single landings moved `main`s
under three sets' runs. A person's laptop without heavy takes no turn.
Until every machine's kit carries the set lock, an older kit's temper
landing takes the `temper` turn instead, which orders temper landings
only among themselves, and its other landings take none.

The SSH client sends a single zero byte immediately and every five
seconds while queued or granted. The holder consumes these bytes and
releases after ten seconds without input, even if a blackholed TCP
session leaves remote stdin open. EOF releases immediately. These are
connection-liveness bounds, independent of task/gate age; healthy
connections may remain indefinitely. Local holders use pipe EOF without
heartbeats. Grant spans ordinary land and all retries. Land, heavy and
after-landing inherit no transport descriptors. A lost connection or
invalid protocol produces one visible fail-open, then ordinary land
starts or its admitted work continues. Connection loss never cancels
heavy. Normal completion and handled signals close and reap the client's
transport. A killed client loses its pipes; a remote holder also has its
independent input-liveness bound.

When land spawns its after-landing helper, the child closes inherited
host-turn FD6 and unused push/follow FD9; the parent keeps its host lock
until landing ends. The helper's own FD7 serializes its after-tier lane
through target cleanup without retaining the landing's host turn.

Request, grant, confirmed release and fail-open appear on caller stderr
and in private `DEV_TMP/landing-turn/events.jsonl` (0600, umask 077).
The caller confirms release only after its owned transport exits zero.
A nonzero exit or transport reap timeout records a fixed fail-open reason
without claiming the coordinator's lock was released; land's exit status
is retained. Release is also emitted on the holder's stderr and stored at
`/home/free/.local/state/agents-landing-turn/landing-turn/events.jsonl`;
transport stderr is discarded at the client. Join these journals by
token. Queued EOF/liveness expiry also records release without runtime.
A killed holder cannot record release; the caller's fail-open provides
its terminal failure evidence. Records contain only token, repository,
holder, timestamp, event, fixed reason, elapsed wait and optional runtime.
Journal failure is visible and does not prevent ordinary land.

`HEAVY_RECOVERY_FIXTURE=1` with `LAND_TURN_FIXTURE_DIR` strictly below
isolated `DEV_TMP` selects only the local acceptance holder.
`test-land-turn --evidence NEW_DIRECTORY` exercises protocol faults,
production command construction, real-value heartbeat expiry and
ordinary disposable Git landings. Simulated SSH cases run through the
production constructor with a fixture executable; they do not prove
real SSH connectivity or the coordinator's holder. The full repository
gate and real temper landings are outside these fixtures.

## 9. Explicit dependency repins

`scripts/devel/repin` is a standalone Python 3.11 command, invoked explicitly
from a committed agents checkout. It prepares and commits one exact tuple in
a consumer's clean linked worktree:

```text
scripts/devel/repin --consumer ABS_LINKED_WORKTREE --base FULL_SHA \
  --pin skein=FULL_SHA [--pin smith=FULL_SHA] \
  [--generated REL_FILE ...] [--regenerate JSON_ARGV ...] \
  --check JSON_ARGV [--check JSON_ARGV ...] [--land]
```

Each command is a nonempty JSON array of strings, passed as argv without a
shell. Pins and base are full 40- or 64-digit hexadecimal identities. Source
names are repository basenames with `.git` removed. Each must resolve to one
git URL/ref identity in the base lock, including its URL query. Duplicate,
absent and ambiguous names refuse. At least one pin must change and at least
one focused check is required. The command prints base, tuple, phase argv,
results and prepared commit; it does not print environments.

The consumer must be on a named branch other than main, with HEAD and
origin/main at the explicit base. Local main may be an older ancestor;
its initial identity is retained and must not move during preparation.
Staged, untracked, submodule and
merge/rebase state refuse. No fetch or policy lookup selects a base or tuple.
Owners and the director choose their slot and pins; there is no timing,
batching, scheduling, persistent job state or configuration file here.

Current consumers pin solely in Cargo.lock; selected `?rev=` sources refuse.
The command starts with `git show BASE:Cargo.lock`, never another consumer's
lock or a whole-lock regeneration, and never rewrites a manifest. For each
selected source it passes `cargo update --precise FULL_SHA -p
PACKAGE_SELECTOR` through the `heavy` beside it (section 12), selecting one unambiguous
package and checking every package from that source afterward. A manifest
constraint Cargo cannot honor refuses; there is no automatic manifest fix or
network API probe.

Parsed TOML records outside selected source identities must remain equal,
including registry versions/checksums, other git SHAs, workspace records and
lock metadata. All selected identities must still exist at exactly their
requested full SHAs, with no new source identity. New nonselected dependencies
refuse conservatively, even when a resolver would normally add them.
Pins apply in the order given. Between them only the worktree's scope is
checked: updating one source can move a later pinned source's packages, when
the first names the second without a rev (jig names skein so, and Cargo then
takes skein's branch). The whole lock is checked once the last pin is in, as
it is after each generator and check. So a source others name goes last
(`--pin jig=... --pin skein=...`); in the other order the run refuses.

Generators and checks run through the heavy beside it, in the consumer root.
Only Cargo.lock and explicitly named generated regular files may change.
The allowlist rejects absolute paths, traversal, `.git`, directories, prefixes,
symlinks and manifest/lock aliases (all TOML and lock outputs refuse).
Status checks include staged, untracked and deleted paths after every phase;
branch/HEAD or local base-ref movement, unexpected staged paths or a changed
lock tuple refuse. The full lock comparison repeats after each generator/check.
These commands are trusted local programs, not a sandbox;
transient writes restored between checks and concurrent malicious actors are
outside the boundary. Keep the worktree exclusively owned during preparation.

Default success commits only the lock and allowlisted files, after checking
branch/HEAD again. Failure before that point commits nothing and preserves
reviewable changes: no reset, clean or retry. Inspect `git diff` and status.
`--land` then invokes the `land` on PATH with no arguments or custom
prebuild; the ordinary full gate is authoritative. A temporary,
process-scoped pre-push guard requires the pushed commit's sole parent to
remain BASE and its lock blob to equal the prepared lock. Existing hooks
are retained and the original pre-push hook is chained. A conditional Git include scopes this temporary
override to the consumer's Git directory; other repositories keep their hooks.
A later-base rebase therefore refuses before push; focused checks never claim
validation of that later base. The temporary hook directory is removed on
normal/error exit; repository/global configuration is not changed.
If main moves, land rebases/conflicts or the guard refuses, inspect the diff
and start a fresh branch from updated main with an explicit new base. A land
failure may leave its amended/rebased candidate; do not rerun it unguarded.

## 10. Landing a set

`scripts/devel/land-set` is the landing flow's tool
(landing-flow.md 9.1). It is a standalone Python 3.11 command, run from a
committed agents checkout like `repin`. It lands one milestone's set across
skein, smith, hearth, jig and temper under one lock, and gates every
repository of the set before it pushes any of them:

```text
scripts/devel/land-set [--prove] SETFILE
```

With `--prove`, it runs phase 1 (below) without the lock and pushes no
`main`; a later run of the set on the same machine then lands it
(**Proving a set**, below).

A proof samples every repository's main once, at its start: it fetches all of
them, then builds and gates that tuple alone. A main that moves during the
proof is the locked run's re-gate's to catch, never the proof's to chase (10-28:
two proofs failed on tuples of mains that no one had made).

The set file is JSON with exactly two keys:

```json
{"set": "accounts-move/m4",
 "repos": {"skein": "/abs/worktree", "smith": "/abs/worktree",
           "hearth": "pin-only", "jig": "pin-only", "temper": "/abs/worktree"}}
```

`set` matches `[A-Za-z0-9][A-Za-z0-9_./-]{0,79}`. Each repository maps to the
absolute root of a worktree, or to `pin-only`. The set must name every
repository downstream of each one it names: skein's are smith, hearth, jig and
temper; smith's are jig and temper; jig's is temper. A worktree must be clean,
on a named branch other than `main`, with no rebase or merge in progress, and
its `origin` must name its repository. A pin-only repository's primary
checkout, `DEV_ROOT/<repo>`, must have that origin. The `land` on PATH must
take `--no-push` (below). Every check precedes the lock; a failure exits 2.
So does a second run of the same set on the same machine, while the first
holds the set's file lock at `DEV_TMP/land-set/state/<URL-escaped-set-name>.lock`:
a prove takes no set lock, and two runs would rebase the same worktrees.

**The lock.** The run holds a turn named `set` from the landing turn's
holder on hetzner3 (section 8): the `land-turn.py` beside the resolved
`land` on PATH, which must be section 8's holder path. On hetzner3 it runs
locally; elsewhere over section 8's ssh argv, with its heartbeat. The
client fails closed: a missing holder, a transport closed or a message
invalid before the grant exits 5 with nothing fetched. A transport lost after
the grant lets the step in progress finish, then stops with exit 5. Sets
therefore land one at a time. The run's children carry `LAND_TURN_ACTIVE=1`,
so a temper `land` inside it doesn't also wait for the temper turn; a plain
`land` that pushes temper meanwhile is phase 2's race (below).

**Phase 1, the gates.** For each repository, in the order skein, smith,
hearth, jig, temper:
1. A pin-only repository gets a worktree at
   `DEV_TMP/land-set/worktrees/<set>/<repo>` from its primary checkout, on
   branch `land-set/TOKEN/<repo>` at `origin/main` after a fetch. The path
   is the set's, not the run's: the gate policy names the gate's absolute
   path (gate-policy.md), so a proof's cached gates hold only in the same
   worktree. A killed run's leftover there is removed first.
2. Fetch, then rebase on `origin/main`. A stop keeps the side being rebased
   onto for the root `Cargo.lock`, and has `land-resolve.py` settle its other
   conflicted paths (landing-flow.md 3), as `land` does; when every stop is
   settled the rebase completes, and otherwise it aborts and exits 3.
3. Repin the root lock. Each upstream of the repository has a target: this
   run's candidate of that upstream (step 5) where there is one; else its
   landed commit recorded by an earlier run of the set (below); else the
   upstream's current `main`, as `git ls-remote origin refs/heads/main` gives
   it from the upstream's primary checkout, read once per round so that
   every downstream of the round pins the same commit. `cargo update
   --precise` moves each source to its target, the sources others name
   last, and `cargo metadata` then completes the lock for the rebased
   manifests. Both run directly, not through `heavy`: they build nothing. Every package of each
   upstream source must then be at its target, with one revision per source.
   A changed lock is committed as `land-set: <set>: pin <repo> to ...`.
   Then, when step 2 took `main`'s side of generated files, `land-resolve.py`
   rewrites them on the repinned tree; its refusal stops the run with exit
   3, the branch back where it was before the rebase.
4. A branch now equal to `origin/main` is skipped. A downstream with no
   change although an upstream has a candidate, or a recorded landing, fails
   explicitly, naming the downstream.
5. Otherwise `land --no-push` runs, with no other argument: its own rebase, a
   no-op unless `main` has just moved, its build lane, its gate and its
   trailers. A nonzero exit stops the run with land's status, and no `main`
   has been pushed. Its tip is the repository's candidate, and the
   `origin/main` it rebased on is the repository's base. If `land` rebased
   onto another `main` than the one step 3 pinned on, the repository goes
   round again, a round toward phase 2's bound.
6. A candidate that a later repository of the set pins is pushed to
   `refs/heads/land-set/TOKEN/<repo>` on origin, a new name, so that the
   downstream's Cargo can fetch it. A later round replaces only this run's
   previous staging tip, with a lease on that tip.

The first round fetches every repository of the set and resolves its
`origin/main` before any of these steps. Steps 1 and 2 use those commits
without fetching again, and step 5 passes the sampled commit to `land
--no-push` as `LAND_SET_BASE`, so that its rebase uses the same base without
a fetch. A skipped repository's sampled main also supplies downstream
pins. A proof ends after this round; a locked run checks for moved mains
and re-gates as below, with fresh fetches in those later rounds.

**Phase 2, the pushes.**
1. Fetch every repository with a candidate. If any `origin/main` is no
   longer its base, phase 1 runs again from the most upstream such
   repository to the end of the set. After three rounds that each found one,
   the run exits 6, having pushed no `main`.
2. Then, upstream first, the ordinary `land` runs in each repository with a
   candidate, with no arguments. Its rebase is a no-op, its gate's result is
   cached for the tree, and it amends nothing, so it pushes the candidate
   itself and follows the local `main`. It starts no tier after landing,
   as no `land` does (landing-flow.md 4, step 8).
3. If `land` landed a commit other than the candidate, because a `main`
   moved between steps 1 and 2, every later repository of the set runs phase
   1 again, against what has landed, before its own push. A failure there,
   the three-round bound included, leaves the set half-landed: the run
   stops with that status.
4. Each landed commit is recorded (below) and written to the feed. The
   evidence is `land`'s result, `pushed` with the commit at the
   worktree's tip, when `origin`'s push URL names the repository; without
   it, the commit or the candidate found on `origin/main` after a fetch.
   A fetch alone missed a landing on 10-25: configuring-3's clones fetch
   from another URL than they push to, and the fetch didn't see the push
   yet. A `land` that exits nonzero after its push is checked the same
   way. On exit 5, the local `main` failing to follow, the run goes on,
   and its summary and `done` say so; on any other status it stops, the
   landing recorded. Every fetch is tried three times, 1, 2 and 4
   seconds apart: proves share the primaries' refs with landing runs.
5. On every exit, the run deletes the staging branches it pushed. A
   deletion that fails warns, naming the origin, the branch and its commit,
   and never changes the exit status; that branch, or one a SIGKILL left,
   stays until deleted by hand.

A pin-only worktree is removed, its target with it, once its repository
lands or is skipped, or when the run fails in another repository. The
failing one is kept, and its path printed. A successful `--prove` keeps
every pin-only worktree, at its proved commit, so that the set can run
what its owner names there before it lands (landing-flow.md 9.1); the
proof file records each one's path beside its base and commit. The
set's next run replaces it, as a leftover, at the same commit where its
`main` hasn't moved; the set's landing removes it; and `tidy` removes
one whose set has since landed, or whose proof is over 24 hours old,
while no run of the set holds the set's file lock and nothing uses it
(cleanup.md, step 9). Each child runs in its own
process group, which a signal to the run reaches whole before the lock goes.

The run appends its last feed event, then releases the lock, on every
exit, SIGINT and SIGTERM included, and
prints each repository as landed (with its commit), gated (with its
candidate, not pushed), skipped, failed (with its status and worktree) or not
reached. Exit statuses: 0 all landed or skipped; 2 refused before the lock; 3
a rebase conflict that no rule settles; 5 the lock; 6 `main` kept moving;
land's own status otherwise; 1 an unexpected failure. Landings made before
a failure, in phase 2 only, stay landed. Their commits are recorded by set
name at `DEV_TMP/land-set/state/<URL-escaped-set-name>.json` until the whole
set completes. A rerun after the repair checks that each recorded commit is on
its repository's `origin/main`, reports `recorded landed COMMIT`, and uses
that commit for downstream pins without landing it again.

**Proving a set.** `land-set --prove SETFILE` runs the checks and phase 1
as above, with no lock: nothing it does moves a `main`. Its staging
branches are pushed and deleted as a landing run's. It reads the set's
recorded landings and writes none. On success it keeps its pin-only
worktrees (below) and writes the proof,
`DEV_TMP/land-set/proofs/<URL-escaped-set-name>.json`: `schema`
(`land-set-proof-v1`), `set`, `machine`, `token`, `time`, and per
candidate its `base`, `commit`, `tree` and `pin_only`, and a pin-only
one's `worktree`, its absolute path. A prove reads the set's earlier
proof, if any, before it replaces it, and resets a pin-only repin to
that proof's commit where the repin has its parent and tree, as the
landing run does (below): so a prove after the set's qa run proves the
very tuple the qa run tested. A run that lands the whole set deletes
the proof at the end.

The gates' evidence is `land`'s gate cache, per machine, by tree, gate and
policy (gate-policy.md 3). A previous tree's evidence survives changes only
in `docs/` Markdown outside the repository's optional `scripts/gated-docs`
list (landing-flow.md 9.1); declared paths require a fresh gate in both
plain and heavy runs, and `land --docs` refuses them with `use land`.
Without a declaration, the existing Markdown exemptions hold. Changing
the declaration itself also requires a gate. So the landing run gates again only what has
changed since: on the same machine, where no `main` moved, every step of
its phase 1 is a no-op or a cache hit, and nothing builds. A branch's tip
is already its candidate. A pin-only repository's repin commits afresh,
with new dates, and every downstream would pin that new commit and gate
again; so where the repin's commit has the proof's parent and tree, the
run resets its branch to the proved commit, which differs from it only in
its dates and the gate's trailers. The proof is only that pointer: the
cache stays the evidence, and a stale or foreign proof costs a regate,
never a wrong landing. Statuses are as above; 0 once every repository is
proved or skipped.

**`land --no-push`.** `land` takes `--no-push`: everything up to and
including the trailers, then land's summary with `not pushed` in place of
where it landed, and exit 0. It pushes nothing and moves no local `main`;
`--docs` or `--local` with it exits 2. And
`land` amends the tip only when the trailers it would write differ from the
tip's, so that landing again, on an unchanged `main`, a commit it gated
pushes that very commit.

**The feed.** Each line is one JSON object, appended under `flock` to
`/home/free/.local/state/agents-land-set/feed.jsonl` on hetzner3 (0600 in a
0700 directory), over the same ssh from elsewhere. Every line has `time`,
`set`, `event`, `host` and `token`. The events:
- `waiting`: the lock is requested;
- `started`: the lock is granted;
- `gated`: `repo` and `commit`, a candidate (phase 1, step 5);
- `landed`: `repo` and `commit`, and `taught` with `taught_more`, what
  that repository's commits taught (landing-flow.md 12);
- `stopped`: `status`, `repo` when the run stopped in one, and `reason`, the
  first line of what the run printed for it, at most 200 characters;
- `done`: every repository landed or skipped, with `warnings` when a
  `land` exited 5 after its push;
- `proving`, then `proved`: a prove's start and its success, in place of
  `waiting`, `started` and `done`. Every line of a prove carries `mode`,
  `prove`; a landing run's `started` carries `proof`, the prove's
  token, when it read a proof.

`gated`, `landed` and a failed `land`'s `stopped` also carry `result`,
the object `land` wrote to `LAND_RESULT` ([landing-flow.md](landing-flow.md)
10), when it wrote one.

A plain `land` that pushes appends its own line, `kind` `land`, with no
`set` (landing-flow.md 12); `land-set` runs its `land`s with `LAND_FEED`
empty, so that they write none.

Lines written before this version have no `event`; each is a `landed`. A feed
failure warns and never fails the run. A run killed by SIGKILL leaves no last
line. A fixture run (`HEAVY_RECOVERY_FIXTURE=1`) writes only to its fixture's
feed, or to none: never to hetzner3's.

**`landings`.** `scripts/devel/landings` reads the feed: on hetzner3
directly, elsewhere with one fixed `tail -n 5000` over the same ssh argv.
`LANDINGS_FEED`, a local path, replaces both, for fixtures. An unreadable
feed exits 4 at once; `wait` keeps polling, and exits 4 after five minutes
without a read. A run whose first line read is not `waiting`, `started`
or `proving` is history, from before the events or cut off by the read: its
lines are printed, but it is never in flight, and `wait` passes over it.
A prove's run, first line `proving`, holds no lock: it is in flight, as
proving. Both wait modes follow the newest proof or landing run, ordered
by its first feed record. A newer `proving`, `waiting` or `started` run
supersedes an older stop, even if that stop arrives later. A successful
proof waits for a landing; a stopped proof ends the wait as a stopped
landing does.
- `landings [--last N]` prints the last N events (20), dated `MM-DD
  HH:MMZ`, then each set whose latest run has not ended, as waiting or
  running, since when, its last event's time, and the last repository it
  gated or landed. A running set holds the set lock; a run killed without
  an ending shows its age in its last event.
- `landings wait SET [--timeout SECONDS]` reads the feed every 30 seconds. It
  exits 0 once the set's latest run is `done`, printing its landed commits; 1
  once that run (proof or landing) has `stopped`, printing one line with its
  status, repository (when present) and reason; 3
  at the timeout. A set not yet in the feed is waited for. The first read
  gets its full 15 seconds, so `--timeout 0` checks the feed once.
- `landings taught [--since TIME]` lists every landing since TIME, a
  set's per repository and plain `land`'s, each with what it taught
  (landing-flow.md 12).
- `landings report [--since DATE] [--repo NAME] [--tsv]` summarizes the
  results in the feed, per repository and per set (landing-flow.md 10).
  Proves have their own table, from `proving` to their end, and the
  landing runs' table counts those that started from a proof.

**Tests.** `scripts/devel/test-land-set` runs its cases on disposable
repositories with `file://` origins, real Cargo and stand-ins for `heavy` and
`land`: a whole set with pin-only repositories, a moved lock, a conflict
outside the lock, a failing land, a missing downstream repository, two
concurrent runs, an absent holder, a pin-only repository with nothing to
land, and a resumed partial set. With this version it adds:
- a downstream's failing gate after its upstream's, which pushes no `main`;
- a `main` moved between the phases, gated again before any push;
- a `main` moved during the pushes, whose later repositories are gated again;
- a pin-only repository whose upstream the set doesn't touch, pinned to that
  upstream's current `main`;
- the staging branches, deleted on success and on failure;
- the feed's events for each of these.

With the prove, it adds:
- a prove, then its landing, whose every gate, pin-only repositories'
  included, is a cache hit and whose commits are the proved ones;
- a `main` moved since the prove, gated again, its upstream not;
- a failing prove, which writes no proof;
- a second run of a set while a prove of it runs, refused;
- a `land` exiting 5 after its push, after which the set lands;
- a fetch URL lagging behind the push URL, where `land`'s result is the
  evidence.

`scripts/devel/test-landings` covers the status view, `wait` ending `done`,
`stopped` and at its timeout, lines with no `event`, proves in flight, and
the report's proves. With
`HEAVY_RECOVERY_FIXTURE=1` and `LAND_SET_FIXTURE_DIR` strictly below
`DEV_TMP`, the lock is `land-turn.py`'s local fixture holder and the feed is
that directory's `feed.jsonl`.

## 11. After landing's runner

[landing-flow.md](landing-flow.md) 4, step 8 is the design: on the
runner's machines, a follower per repository, or per part of a
repository's tier, follows its `main`, runs its slow tier on the newest
one, reruns a red alone, bisects it over the landings it passed over,
and writes a verdict per landing to the feed. This section is the
tools' contract: `scripts/devel/after-landing`, each repository's
`scripts/after-landing.sh`, the runner's records in the feed, and what
`landings` and `setup` do with them.

**A follower's name** is its repository's, `REPO`, for a whole tier,
and `REPO.KofN`, `temper.1of2`, for part K of N, 1 ≤ K ≤ N, N ≥ 2. It
names the follower's lock, state, clone, logs, heavy label, unit
instance and records, so that two followers share nothing but the
feed and their origin.

**The tier's script.** A repository with slow tiers has
`scripts/after-landing.sh`; one without (smith and hearth today) is
green at every commit. Run from the root of a checkout:
- with no argument it runs every tier; `--only NAME`, repeatable, runs
  those alone. A NAME it printed is valid for `--only` at any commit, and
  one gone at that commit passes;
- it prints `after-landing: failed NAME` per failed test, or per failed
  phase that names no test (a build, a crash), and `after-landing:
  lacks WHAT` per tool it needs and doesn't find, checked before it
  builds anything. NAME is opaque to the runner: for a nextest test,
  `PROFILE BINARY_ID TEST_NAME`, from the profile's JUnit; for a phase,
  its name;
- it exits 0 green, 3 when it lacks a tool, 2 on a NAME or an argument
  it doesn't know, and any other status red. A red with no `failed`
  line is the whole tier's, which the runner calls `*` and reruns
  whole;
- it reports to no one, and writes nothing outside the checkout's
  `target/`;
- a script whose tier is split takes `--part K/N`, for any N ≥ 1: with
  no `--only`, it runs part K of its tier in N parts, and with `--only`
  the part changes nothing. The split is the script's, a function of
  the commit's files and N alone, so that every follower deals the
  same: the parts are disjoint in the tests they run and whole
  together, a phase they need (a build) may run in several, and a part
  with nothing in it is green. It splits by phase, weighed by times
  measured once and written in the script, ties broken by the phases'
  order; phases that share a build may be dealt as one group, so that
  no part builds what another already does (temper's QA and browser
  tiers, its bundle). A NAME keeps its meaning across parts. A commit that moves a
  test to another part lands while that test is green: a red standing
  in its old part drops there, and its new part, which never saw it,
  would bisect it anew onto an innocent landing;
- it prints `after-landing: starved NAME` per test that passed starved
  (skein's `testing-strategy.md` 2.8: a real-loop run that waited for
  a CPU it wasn't given passes and says so in its output), read from
  the profile's JUnit with passing tests' output kept. A starved pass
  is green.

**The runner.** `after-landing follow REPO [--part K/N] [--origin URL]
[--director ADDRESS] [--poll SECONDS] [--once]` follows one
repository's tier, or its part K of N, by default from
`git@github.com:fabrig-ai/REPO.git`, with a pass every 60 seconds, or
one with `--once`. With NAME its follower's name, it holds
`locks/NAME.lock` for its life, so a second follower of NAME on the
machine exits 2. Under `DEV_TMP/after-landing/` it keeps `runner/NAME/`,
its own clone, whose `target/` stays warm between runs;
`state/NAME.json`; and `logs/`, one log per run, `NAME-COMMIT-TOKEN.log`.
It refuses, with exit 2 and deleting nothing, a clone of another
origin, or a state it can't read. It runs only on a runner's machine,
one with `~/.config/agents-after-landing/director` (below); anywhere
else it exits 2. A part with no state starts from its repository's
whole state on its machine, `state/REPO.json`, which it reads itself
at its first start, without the pending posts or fault, when that
state's last run is on a commit whose script takes `--part` and no
standing red of it is `*`: its first run then bisects over the
landings since. Each part keeps the standing reds its runs confirm,
and drops the rest at its first run. With no such state, a part's first
run is a baseline.

A pass settles the pending posts, reads `main` with `git ls-remote`,
and when `main` moved, fetches it and runs the tier on it, M, with P the
last run's commit:
- **The landings** in (P, M] are the first-parent commits with a
  `Gate-Tree:` trailer, which `land` and `land-set` push, and M itself;
  only M when P is null or not an ancestor. One whose `Gate-Result:`
  starts `none` is a docs landing: never probed, never red.
- **Its target is bounded** (the director, 10-27: temper's grew
  unpruned to 180 GB and took hetzner3 under its floor). Before a run,
  a follower whose clone's `target/` holds more than its cap, its files'
  allocated bytes, removes that `target/` whole, so that the run builds
  afresh from the build cache ([build-cache.md](build-cache.md)). The
  cap is 50 GB, or what the follower's line in the `follow` file gives
  (below). Only between runs: a run's rerun and probes share its
  target. The runner keeps no receipt of what its builds use (kache's
  `clean --units`): what the tier builds is the repository's script's,
  and the cap needs nothing from it. A follower reads its cap from
  its follow line each pass. A measurement or removal that fails is a
  fault, and after a failed removal the next pass removes `target/`
  whole whatever its size.
- **The run** is `heavy -- scripts/after-landing.sh` at
  `HEAVY_CLASS=background`, in the clone checked out at M (forced,
  cleaned of untracked files but not of ignored ones). A part's run
  that names no test, its first and a `*` rerun or probe, adds
  `--part K/N`; one that names tests passes `--only` alone. The script's
  lines are read in the task's whole log, which heavy's summary line
  names, not in the tail heavy prints.
- **A red** is rerun at M with `--only` each failed NAME. What fails
  again is confirmed; the rest are flakes. A confirmed test already
  among the tier's standing reds keeps the landing it was charged to;
  a new one is bisected over the landings in (P, M), halving, each probe
  `--only` the tests still undecided, so that each is charged to the
  first landing where it fails. With one landing, it is that one.
- **A baseline.** A run with no landings before M (the first, or one
  after a history rewrite) has no range to bisect: its reds stand,
  charged to no landing, and M is cleared of them, its records marked
  `baseline`.
- **A fault** is heavy refusing (no summary line), exit 3 with `lacks`
  lines, or the origin out of reach. It ends the run with no verdict
  and P unchanged, so the next pass tries again.
- **The verdicts:** one per landing in (P, M], `red` with the new
  tests charged to it, else `cleared`, each naming the run's flakes.
  These are per-commit verdicts. A tool landing owns every commit in
  its pushed range (base, tip], including repins and resolver commits,
  and its verdict is the worst over that range. A red charged to any
  such commit belongs to that landing, even with `landing_set` null
  and the tip cleared. A commit's first landing is the landing whose
  range holds it; an existing failure still counts against that first
  landing alone.

**The follower adopts its orphans,** as heavy's payload does (section
3): it makes itself a child subreaper at its start, so that an orphan
of what it runs outside heavy (git, ssh, post) never reaches the user
manager, and reaps them.

**Its records** go in the landing feed (section 10), beside the sets'.
None has a `set` key, so the readers of sets skip them. Each has `time`,
`kind`, `event`, `host` and `token`, a run's token shared by its records:
- `kind` `tier`, with `tier`, the follower's name: the repository, or
  `REPO.KofN` for a part. A reader that knows no parts finds no record
  of REPO's in a part's, so it waits on a landing rather than clear it
  on one part; but it takes any verdict on a bare commit, so parts go
  live once every machine's `landings` knows them:
  - `running`: `commit` M and `from` P; `fresh` is true when the
    run starts on a target the cap removed;
  - `verdict`: `commit` the landing, `run` M, `verdict`, `tests`,
    `flakes`, `starved`, `landing_set` (the set whose `landed` record names the
    landing, or null), `log`, and a red's `excerpt`, its failing output's
    last 60 lines, at most 8000 characters; `baseline` is true on a
    baseline run's;
  - `tier`: the run's end, with `commit` M, `state` (`green` or `red`),
    `last_green`, `reds` (each `landing` with its `tests`), `flakes`,
    `starved`, `ran_s` (heavy's seconds, rerun and probes included) and `log`;
    `baseline` is true on a baseline run's;
  - `fault`: `commit`, `reason` and `since`, when a fault starts or its
    reason changes; `recovered`, when one ends with `main` unmoved.
- `kind` `watch`, event `watching`: `target`, a set or a commit, and
  `name`, the waiter's `POST_NAME` or null.

Lists of tests stop at 50 names, with `tests_more`, `flakes_more` or
`starved_more` counting the rest. A run's `starved` are the starved
passes of its runs at M, the first and the rerun; a reader that
predates them ignores the key.

**Its posts** go to `--director`, as `post send --as after-landing`; a
post that `post` queued counts as sent, and one that fails is tried
again at the next pass:
- a fault 15 minutes old, once per fault;
- a red nobody waits on: no `watch` record names its set or a prefix of
  its commit within the 2 hours before it, nor within the 15 minutes
  after.

**`landings`.** `landings` adds a `tiers:` section, a line per
follower, by its name: green or red at its last run, a red's standing tests and
the landing first charged, its last green, and a run in progress or a
fault newer than the last state. Per repository it shows only the
followers of its newest split, the split whose newest record is the
newest: a whole tier's line goes once its parts have run, and a
split's once another has; the join still reads every split. It and
each verdict line below name a run's starved passes as they name its
flakes, `starved N: TESTS`. `landings wait --cleared TARGET
[--timeout SECONDS] [--post ADDRESS]` waits for a landing's verdict:
TARGET is a set, whose landings are its latest run's `landed` records,
or a commit, 7 to 40 hex digits. A `landed` event's `base` and `commit`
record its actual pushed range, (base, commit], for that repository;
the same pair in a matching `result` with `pushed: true` also suffices.
The base is the main its successful push rebased onto, even after a
rebase under the lock, never an earlier gate's base. `landings` displays
the landing's worst verdict over every commit in this range, and
`wait --cleared` uses it for a set or a recorded tip. A red decides
immediately; clearance requires every pushed commit to clear. A missing
checkout, missing range objects or unknown ancestry leaves the range
pending. The exclusive base and older commits contribute no reds.
If `land-set` recovers a publication without its matching push result,
it writes `base: null` to mark an unknown new range; set waits, tip
waits and status all leave it pending rather than using tip clearance.
Past feed events are never rewritten; an older event without a range
keeps its former judgement. For each pushed commit, or a legacy
single-commit landing, the verdict is the first of these
(landing-flow.md 4, step 8):
- its own: the newest `verdict` record on its commit, of its
  repository, or of any for a commit target;
- no tier: its commit's tree has no `scripts/after-landing.sh`, and
  origin's `main` holds the commit: cleared;
- the run's: of the repository's runs that ended (a `tier` record, P
  from the `running` record of its token), the newest whose M holds the
  commit and whose P, if any, doesn't. A baseline's clears it;
  another's gives it the verdict of the oldest of its landings that
  holds it.

**Parts.** A repository's runner records group by split: N parts, or
one for a whole tier's records and for those older than parts. Under a
split, the rules above judge a commit within each part's records alone,
its own verdict and its run's both read in that part's; no tier is
judged once, for the commit. The commit is red once any part of any
split has judged it red, and cleared once every part of one split has
cleared it; else it waits. So a commit a whole tier judged before the
split keeps that verdict, and a part that never runs leaves its commits
waiting until the wait's timeout. `wait --cleared` prints a line per
part, its follower's name where the repository's stands, and
`landings cleared REPO` gives, under parts, the newest commit that
ended an all-cleared run of some part and that this join clears.

Ancestry is read in the workspace's checkouts: `REPO` under `DEV_ROOT`,
else under the directory that holds agents' checkout, for agents and the
five repositories; a shallow checkout counts as none. A commit target's
repository is the checkout that has its commit, found without a fetch.
The wait fetches origin's `main` into `refs/remotes/origin/main` alone
(no `FETCH_HEAD`, tags, submodules or maintenance): once before it
trusts that ref, and again, at most once per poll, where a commit it
needs is missing; one still missing after a fetch stays missing. Each
git call is killed with its children at its timeout, cut to the wait's
deadline with no floor, and none starts past it: a wait with
`--timeout 0` decides by its records alone. A call its timeout cut
answers nothing: not an absence, not a checkout missing, not a run
that doesn't hold the commit; the question stays open for the next
poll, and a run whose relation to the commit is unread keeps an older
run from deciding, newest first. The display and `landings
cleared`, which have no deadline, keep each call's own timeout. A landing with no checkout, or a commit no checkout has, ends
only with its own verdict under the legacy single-commit judgement;
a recorded range whose ancestry git can't answer waits.

It writes its `watch` record first, then exits 0 once each landing is
cleared, 1 at the first red or when the set's newest proof or landing run
has `stopped` (one line with its status, repository when present, and reason),
2 at once when a landing's commit is not on its repository's `main` after
a fetch, 3 at the timeout, 2 hours by default, and 4 when the feed is unreadable, as
`wait` does. It prints a line per landing that says which rule gave
the verdict, and a red's tests and excerpt:

    10-26 07:30Z temper 1234567ab cleared by run 89abcdef0
    10-26 07:52Z agents 2345678bc cleared on landing: agents has no tier
    10-26 06:49Z temper d87b0f9dc cleared by run 7ca307b29, which holds it; baseline
    10-26 08:10Z temper 3456789cd red by run 89abcdef0, which holds it in landing 456789abc: TEST; log HOST:PATH

With `--post`, it then posts what it printed to ADDRESS, as `landings`,
its subject the outcome.

**The machines and their units.** The director names each of the
runner's machines by writing its own address in
`~/.config/agents-after-landing/director` there, and what the machine
follows in `~/.config/agents-after-landing/follow`, a follower's name
per line, then optionally its target's cap in GB (`temper.1of2 60`);
with no such file, the five repositories whole (skein, smith, hearth,
jig, temper), each at the default cap. A follower runs on one machine at a time, which
only the director's files ensure. On a runner's machine `setup` checks
the user unit `agents-after-landing@.service`, whose instance per
follower, by its name, runs `after-landing follow REPO [--part K/N]
--director ADDRESS` in a login shell, restarted on failure but not
after exit 2; `setup --fix` writes it, starts the listed instances and
stops those no longer listed. Elsewhere it warns if one runs. A
follower off the coordinator writes the feed and reads it over the
landing turn's ssh, as `land-set` does.

**Fixtures.** `AFTER_LANDING_FIXTURE=DIR` puts the runner's every path
and its feed under DIR, lifts the machine check, and only then lets
`AFTER_LANDING_HEAVY` and `AFTER_LANDING_POST` replace `heavy` and
`post`; `AFTER_LANDING_GB` replaces the cap's gigabyte, so that a
story needs no real one; `AFTER_LANDING_FAULT_POST` and `AFTER_LANDING_RED_GRACE` replace
the 15 minutes. `scripts/devel/test-after-landing` runs the runner on
bare repositories as origins, with stand-ins for heavy and post and a
tier script that fails what the commit names: a green run and a pass
with nothing new, a repository without a tier, a flake, a red and its
repair, a bisect over four landings with a docs one, a red already
standing, faults (heavy refusing, a tool lacking, the origin away) and
their posts, an unwatched red posted and a watched one not, and its
meeting with `landings wait --cleared` on the same feed; and a tier in
two parts, each followed apart: `--part` passed only on runs that name
no test, a red in one part bisected while the other clears, and a part
started from a whole tier's copied state, or not, for a `*` standing;
and a starved pass, green and recorded; and a target past its cap,
removed before the next run and never during one, the run marked
`fresh`.
`test-landings` covers the `tiers:` lines, `wait --cleared` on a set
and on a commit, and `--post`; and, on scratch repositories as origins
and checkouts, the verdicts by ancestry: a repository with no tier, a
landing older than the baseline, a commit inside a landing's range, a
red that stays red under later clean runs, and a commit no `main`
holds; and under parts: one part cleared and the other not yet, a red
from either deciding at once, a commit a whole tier judged before the
split, a part's records hidden from a reader that knows no parts,
`landings cleared` over two parts, and the verdicts' report (landing-flow.md
10). Both suites hold under any load: a story proves a deadline
with a stand-in that blocks until killed, never with work that must
fit inside it, and waits on a handshake or the fixture's one clock,
never on real work racing a timer. With the real heavy and origin,
fixture mode is also how a live run goes before the runner does.

## 12. A machine without heavy

The user, 10-26, on a laptop where heavy had never been installed and
refused every build, so that `land` exited 9 for any code change: "this
needs to work on my machine with no heavy and just simple plain commands
or scripts (that heavy itself can build upon if appropriate)". The plain
commands are the base, and heavy is a layer a machine adds: the build
machines keep its queue, containment and receipts, unchanged.

- **Installed is explicit.** heavy is installed on a machine when its
  ledger records an installation, which `heavy --install-reconciler`
  sets and `--remove-reconciler` clears (section 4). No state directory,
  no ledger, or a ledger with no installation is a machine without heavy:
  absent, not a failure. An installation cut short is recorded already,
  so it is installed and refusing (section 4). `heavy --installed`
  answers: exit 0 installed, 1 not, 2 when it can't tell (a ledger it
  can't read, or of another version). It reads the snapshot without the
  host lock and writes nothing, not even the state directory.
- **Installed but broken still refuses.** An installed heavy whose timer
  is inactive or whose probe fails refuses as section 4 says, and `land`
  exits 9: a build machine whose recovery broke is repaired, never
  quietly demoted to plain. "Can't tell" counts as installed.
- **Where it isn't installed, heavy runs the command directly,** as it
  runs `cargo fmt`. `heavy [--gate | --land] [--tail N] [--] command...`
  prints `heavy: not installed here; running it directly` on stderr and
  executes the command in the caller's directory and environment, which
  exits with the command's status. No ledger, unit, event, TSV row,
  receipt, disk floor or gate policy. An instruction written `heavy cargo
  nextest run …` therefore holds on every machine. The management forms
  are unchanged.
- **The repositories' scripts never need heavy.** `scripts/check.sh`,
  `scripts/bundle.sh` and the like run plain commands, and a caller that
  wants the queue runs the whole script through it, `heavy
  scripts/bundle.sh`. A script that can't run inside a task queues its
  own builds instead: one a person drives, whose prompts must show as
  they come (the live proofs), or one that builds, then works for long
  after (the lab's judges). It runs each build through `heavy` where
  `heavy` is on `PATH`, and plainly where it isn't, and its caller runs
  it directly, since heavy refuses a task inside a task. The kit's own
  tools (`land`, `repin`, after landing's runner) call the `heavy` beside
  them, never the one on `PATH`, so that they need none there.
- **`land` without heavy** asks `heavy --installed` once, before its
  first rebase:
  - 0: its build lane and gate go through heavy (sections 2 to 5), and a
    refusal is exit 9, as before;
  - 2: it refuses with exit 9, and nothing runs;
  - 1: it runs its prebuild and its gate itself, each `bash -c COMMAND`
    as its own child, into a log of its own under `DEV_TMP/logs/land/`.
    It prints the log's last 60 lines and one summary line, `land: plain
    gate exit N, ran S s, log PATH` (`plain build` for the prebuild), and
    judges by the exit status. Candidate and policy checks, trailers, the
    cache, the set lock and the exit statuses are a contained gate's;
    what its evidence proves is gate-policy.md 3.2's.

  `land-set` lands through `land`, and needs nothing of its own.
- **Plain takes the machine as it finds it.** A plain run has no CPU
  weight of heavy's: on a machine busy with heavy's builds (weight 1000)
  it gets a session's share, and a suite's own global timeout can cut
  it. Plain is for machines without heavy, where nothing outranks it; a
  build machine gates through heavy.
- **`setup`** asks the same question. Installed, it checks recovery,
  lingering and the lanes as section 4 says; not installed, it says so
  in one `ok` line and checks none of them; can't tell, it fails. It
  links `heavy` on `PATH` either way. kache stays optional: without its
  wrapper `setup` warns, and the build is plain cargo.
- **After landing's runner** is a build machine's (section 11): the
  machine the director names for it has heavy installed, and its tiers
  go through it.
- **Fixtures.** `test-heavy-plain` runs the real `heavy` against
  hand-written ledgers, with no unit installed or started: absent,
  empty, installed and unreadable ledgers, the direct run's status,
  streams, options, directory and environment, the disk floor skipped,
  and an installed heavy with no reconciler still refusing.
  `test-gate-policy` lands with a stand-in heavy that answers
  `--installed`: plain landings, their cache and trailers, a failing
  plain gate, a plain record never serving a contained gate nor the
  reverse, and "can't tell" refusing. The whole path is proved on a
  build machine in a state anyone can reproduce: `DEV_TMP` a fresh
  directory, so no ledger, `PATH` without `~/.local/bin`, so no
  `heavy` on it, and kache's wrapper on or off.
