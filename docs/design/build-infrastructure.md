# Build infrastructure

Provisional, 2026-10-26. The host admission and recovery contract for the
owners' `heavy` commands. Runtime identity is specified by gate-policy.md.

## 1. In one page

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

A gate's hold is the ledger's gate token: saved before draining starts,
and cleared in the snapshot that commits the gate's release. While it is
set no build and no other gate is admitted, across crashes and restarts
alike. Operator holds are separate: a gate neither sets nor clears them.

## 4. Independent recovery and maintenance

`heavy --install-reconciler [INTERVAL]` probes real cgroup containment,
including a `setsid` child, and installs an enabled user service and timer
named from the state directory's hash. Installation is explicit. It
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
its own timer and service. `setup` checks recovery readiness without
installing it, and reports each lane's holds through `heavy
--group-held`; it neither needs nor checks a queue daemon. Tests use a
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
new machine runs `setup --fix`, then `heavy --install-reconciler`, which
writes the reconciler's units for the checkout's helper under the host lock,
then `setup` again.

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

Director-owned per-host configuration: hetzner, hetzner2 and hel8 use
`LAND_TURN_MODE=ssh`; hetzner3 uses `LAND_TURN_MODE=local`, allowed only on
hostname `debian-16gb-hel1-3`. Every host sets the explicit coordinator
`LAND_TURN_HOLDER`. A wrong local hostname fails open. Hetzner4 uses
strict SSH too and fails open until the director verifies its trust and
auth; no setup is attempted by the client.
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
PACKAGE_SELECTOR` through the `heavy` on PATH, selecting one unambiguous
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

Generators and checks run through the heavy on PATH, in the consumer root.
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
failing one is kept, and its path printed. Each child runs in its own
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
recorded landings and writes none. On success it removes its pin-only
worktrees and writes the proof,
`DEV_TMP/land-set/proofs/<URL-escaped-set-name>.json`: `schema`
(`land-set-proof-v1`), `set`, `machine`, `token`, `time`, and per
candidate its `base`, `commit`, `tree` and `pin_only`. A prove deletes the
set's earlier proof when it starts, and a run that lands the whole set
deletes it at the end.

The gates' evidence is `land`'s gate cache, per machine, by tree, gate and
policy (gate-policy.md 3), so the landing run gates again only what has
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
- `landed`: `repo` and `commit`;
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

Lines written before this version have no `event`; each is a `landed`. A feed
failure warns and never fails the run. A run killed by SIGKILL leaves no last
line. A fixture run (`HEAVY_RECOVERY_FIXTURE=1`) writes only to its fixture's
feed, or to none: never to hetzner3's.

**`landings`.** `scripts/devel/landings` reads the feed: on hetzner3
directly, elsewhere with one fixed `tail -n 5000` over the same ssh argv.
`LANDINGS_FEED`, a local path, replaces both, for fixtures. An unreadable
feed exits 4 at once; `wait` keeps polling, and exits 4 after five minutes
without a read. A run whose first line read is neither `waiting` nor
`started` is history, from before the events or cut off by the read: its
lines are printed, but it is never in flight, and `wait` passes over it.
A prove's run, first line `proving`, holds no lock: it is in flight, as
proving, but `wait` waits only for a landing run.
- `landings [--last N]` prints the last N events (20), dated `MM-DD
  HH:MMZ`, then each set whose latest run has not ended, as waiting or
  running, since when, its last event's time, and the last repository it
  gated or landed. A running set holds the set lock; a run killed without
  an ending shows its age in its last event.
- `landings wait SET [--timeout SECONDS]` reads the feed every 30 seconds. It
  exits 0 once the set's latest run is `done`, printing its landed commits; 1
  once that run has `stopped`, printing its status, repository and reason; 3
  at the timeout. A set not yet in the feed is waited for. The first read
  gets its full 15 seconds, so `--timeout 0` checks the feed once.
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

[landing-flow.md](landing-flow.md) 4, step 8 is the design: on one
machine, a runner follows each repository's `main`, runs its slow tier
on the newest one, reruns a red alone, bisects it over the landings it
passed over, and writes a verdict per landing to the feed. This section
is the tools' contract: `scripts/devel/after-landing`, each
repository's `scripts/after-landing.sh`, the runner's records in the
feed, and what `landings` and `setup` do with them.

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
- it exits 0 green, 3 when it lacks a tool, 2 on a NAME it doesn't
  know, and any other status red. A red with no `failed` line is the
  whole tier's, which the runner calls `*` and reruns whole;
- it reports to no one, and writes nothing outside the checkout's
  `target/`.

**The runner.** `after-landing follow REPO [--origin URL] [--director
ADDRESS] [--poll SECONDS] [--once]` follows one repository, by default
`git@github.com:fabrig-ai/REPO.git`, with a pass every 60 seconds, or
one with `--once`. It holds `locks/REPO.lock` for its life, so a
second follower of REPO exits 2. Under `DEV_TMP/after-landing/` it
keeps `runner/REPO/`, its own clone, whose `target/` stays warm between
runs; `state/REPO.json`; and `logs/`, one log per run. It refuses, with
exit 2 and deleting nothing, a clone of another origin, or a state it
can't read. It runs only on the runner's machine, the one with
`~/.config/agents-after-landing/director` (below); anywhere else it
exits 2.

A pass settles the pending posts, reads `main` with `git ls-remote`,
and when `main` moved, fetches it and runs the tier on it, M, with P the
last run's commit:
- **The landings** in (P, M] are the first-parent commits with a
  `Gate-Tree:` trailer, which `land` and `land-set` push, and M itself;
  only M when P is null or not an ancestor. One whose `Gate-Result:`
  starts `none` is a docs landing: never probed, never red.
- **The run** is `heavy -- scripts/after-landing.sh` at
  `HEAVY_CLASS=background`, in the clone checked out at M (forced,
  cleaned of untracked files but not of ignored ones). The script's
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

**Its records** go in the landing feed (section 10), beside the sets'.
None has a `set` key, so the readers of sets skip them. Each has `time`,
`kind`, `event`, `host` and `token`, a run's token shared by its records:
- `kind` `tier`, with `tier`, the repository:
  - `running`: `commit` M and `from` P;
  - `verdict`: `commit` the landing, `run` M, `verdict`, `tests`,
    `flakes`, `landing_set` (the set whose `landed` record names the
    landing, or null), `log`, and a red's `excerpt`, its failing output's
    last 60 lines, at most 8000 characters; `baseline` is true on a
    baseline run's;
  - `tier`: the run's end, with `commit` M, `state` (`green` or `red`),
    `last_green`, `reds` (each `landing` with its `tests`), `flakes`,
    `ran_s` (heavy's seconds, rerun and probes included) and `log`;
    `baseline` is true on a baseline run's;
  - `fault`: `commit`, `reason` and `since`, when a fault starts or its
    reason changes; `recovered`, when one ends with `main` unmoved.
- `kind` `watch`, event `watching`: `target`, a set or a commit, and
  `name`, the waiter's `POST_NAME` or null.

Lists of tests stop at 50 names, with `tests_more` or `flakes_more`
counting the rest.

**Its posts** go to `--director`, as `post send --as after-landing`; a
post that `post` queued counts as sent, and one that fails is tried
again at the next pass:
- a fault 15 minutes old, once per fault;
- a red nobody waits on: no `watch` record names its set or a prefix of
  its commit within the 2 hours before it, nor within the 15 minutes
  after.

**`landings`.** `landings` adds a `tiers:` section, a line per
repository: green or red at its last run, a red's standing tests and
the landing first charged, its last green, and a run in progress or a
fault newer than the last state. `landings wait --cleared TARGET
[--timeout SECONDS] [--post ADDRESS]` waits for a landing's verdict:
TARGET is a set, whose landings are its latest run's `landed` records,
or a commit, 7 to 40 hex digits. A landing's verdict is the first of
these (landing-flow.md 4, step 8):
- its own: the newest `verdict` record on its commit, of its
  repository, or of any for a commit target;
- no tier: its commit's tree has no `scripts/after-landing.sh`, and
  origin's `main` holds the commit: cleared;
- the run's: of the repository's runs that ended (a `tier` record, P
  from the `running` record of its token), the newest whose M holds the
  commit and whose P, if any, doesn't. A baseline's clears it;
  another's gives it the verdict of the oldest of its landings that
  holds it.

Ancestry is read in the workspace's checkouts: `REPO` under `DEV_ROOT`,
else under the directory that holds agents' checkout, for agents and the
five repositories. A commit target's repository is the checkout that
has its commit. Where a commit it needs is missing, the wait fetches
origin's `main` there, without `FETCH_HEAD`, at most once per poll. A
landing with no checkout, or a commit no checkout has, ends only with
its own verdict.

It writes its `watch` record first, then exits 0 once each landing is
cleared, 1 at the first red or on the set's `stopped`, 2 at once when a
landing's commit is not on its repository's `main` after a fetch, 3 at
the timeout, 2 hours by default, and 4 when the feed is unreadable, as
`wait` does. It prints a line per landing that says which rule gave
the verdict, and a red's tests and excerpt:

    10-26 07:30Z temper 1234567ab cleared by run 89abcdef0
    10-26 07:52Z agents 2345678bc cleared on landing: agents has no tier
    10-26 06:49Z temper d87b0f9dc cleared by run 7ca307b29, which holds it; baseline
    10-26 08:10Z temper 3456789cd red by run 89abcdef0, which holds it in landing 456789abc: TEST; log HOST:PATH

With `--post`, it then posts what it printed to ADDRESS, as `landings`,
its subject the outcome.

**The machine and its units.** The director names the runner's machine
by writing its own address in `~/.config/agents-after-landing/director`
there. On that machine `setup` checks the user unit
`agents-after-landing@.service`, whose instance per repository (skein,
smith, hearth, jig, temper) runs `after-landing follow REPO --director
ADDRESS` in a login shell, restarted on failure but not after exit 2;
`setup --fix` writes it and starts the five. Elsewhere it warns if one
runs.

**Fixtures.** `AFTER_LANDING_FIXTURE=DIR` puts the runner's every path
and its feed under DIR, lifts the machine check, and only then lets
`AFTER_LANDING_HEAVY` and `AFTER_LANDING_POST` replace `heavy` and
`post`; `AFTER_LANDING_FAULT_POST` and `AFTER_LANDING_RED_GRACE` replace
the 15 minutes. `scripts/devel/test-after-landing` runs the runner on
bare repositories as origins, with stand-ins for heavy and post and a
tier script that fails what the commit names: a green run and a pass
with nothing new, a repository without a tier, a flake, a red and its
repair, a bisect over four landings with a docs one, a red already
standing, faults (heavy refusing, a tool lacking, the origin away) and
their posts, an unwatched red posted and a watched one not, and its
meeting with `landings wait --cleared` on the same feed.
`test-landings` covers the `tiers:` lines, `wait --cleared` on a set
and on a commit, and `--post`; and, on scratch repositories as origins
and checkouts, the verdicts by ancestry: a repository with no tier, a
landing older than the baseline, a commit inside a landing's range, a
red that stays red under later clean runs, and a commit no `main`
holds. With the real heavy and origin, fixture
mode is also how a live run goes before the runner does.
