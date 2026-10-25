# Build infrastructure

Provisional, 2026-10-22. The host admission and recovery contract for the
owners' `heavy` commands. Runtime identity is specified by gate-policy.md.

## 1. In one page

- **Two build slots, four jobs each.** Builds run through pueue's `build`
  group. An exclusive gate uses the `gate` group, one at a time, with
  eight jobs. Host admission also counts task lifetimes, independently of
  the queue daemon's view of its wrappers.
- **Intent precedes effects.** A gate records its token, boot identity,
  queue identity, owned systemd unit and the groups found running in a
  durable atomic snapshot before pausing any group. Groups already paused
  remain paused when the gate releases.
- **Containment owns descendants.** Every payload executes in a user
  systemd service with `ExitType=cgroup`, `KillMode=control-group` and no
  delegated subtree. Changing sessions does not escape it. PID exit and
  queue completion trigger recovery; neither proves descendants ended.
- **Recovery is independent.** A user systemd timer reconciles the same
  host ledger as admission and normal completion. Its approved polling
  default is five seconds (director 586). It is not a task
  timeout or a gate budget.
- **Release is replayable.** Under the host lock, mark the task closing,
  kill its owned cgroup, prove it empty, resume only owned holds without
  maintenance holds, and commit one logical release outcome per token.
- **Evidence is durable and narrow.** JSONL events carry task identity,
  phases, capacity and safe policy identity. They carry no task
  environment, output or full queue records. The eleven-column TSV remains
  available for diagnostics; land accepts token-owned receipts.

## 2. Ownership and admission

The supported queue is dedicated to `heavy`. Its groups must contain
only tasks submitted through this admission path. Deployment requires a
quiet migration from an older queue: arbitrary queued commands have no
owned cgroup ledger, so their completion cannot be proved through this
interface. Calling pueue directly to submit or restart tasks bypasses
this contract. Unsupported containment refuses admission visibly. The helper requires
Python 3.11 or newer and uses only its standard library.

`DEV_ROOT` selects the workspace and `DEV_TMP/heavy` holds host state.
All callers sharing a queue must share this state directory. An alternate
queue must use a distinct state directory. The queue identity hashes the
canonical config path, profile and endpoint-selection lines. The config
and data directory must
retain their identity across daemon restarts. Replacing a queue at the
same config path requires a drained migration, rather than erasing the
ledger. The host lock serializes admission, reconciliation and explicit
maintenance operations.

Submission first saves a unique token and safe context, adds a stashed
queue entry, saves the returned ID and enqueue intent, then enqueues it. Reconciliation
repeats a persisted enqueue intent, allowing the wrapper to claim the
known ID if its submitter dies. A lost add response can leave an
unactivated stashed queue entry; its released token cannot run a payload,
and the ledger cannot remove an unknown queue ID without a safe metadata
API. The queued wrapper
has a PID, process start tick and boot identity; payload start is a
separate event inside its cgroup. A client may disappear without losing
task ownership or completion evidence.

A token-owned user service observes `pueue wait --quiet ID` while a token
is queued and unclaimed. Only a successful wait return is used: a terminal
or absent queue entry triggers cancellation under the host lock if the
token is still unclaimed. Transport failure retries through the timer.
The observer stops once a wrapper claims the token. Client death does not
cancel queued work, and no task age limit is imposed; an interrupted
client, or `heavy --cancel`, does (section 4). A reused numeric ID
can never establish success. Completion does not wait on or remove an ID
after token release: without a safe identity API, a queue row cannot be
removed without risking an unrelated replacement. Completed queue rows
therefore require operator retention handling on the dedicated queue.

A gate saves pause intent, pauses every non-gate group without stopping
running tasks, then drains the ledger's live build lifetimes. Persisted
gate holds also block build admission if the queue restarts and forgets
its group pause. Builds occupy at most two ledger slots until their
cgroups are empty, regardless of the queue's slot accounting. Gates
serialize through both the queue and the host ledger.

## 3. Durable state and release

The version 1 host snapshot contains the queue identity, task records,
current gate token, maintenance holds and resume intents, installation proof and
an event outbox. Files are created with umask 077. Save writes a sibling
temporary file, flushes and fsyncs it, renames it over the snapshot and
fsyncs the directory. A leftover temporary file is never read as state.

Each task records its unique token, queue ID, boot identity, wrapper
identity, unit name, lane, label, repository, tree, policy identity, log
path and command. Commands are private task metadata and remain in the
TSV for compatibility; events exclude commands and output. Task states
are submitted, enqueuing, queued, waiting, launching, active, finishing, closing
and released. A gate additionally records the groups found running and
the groups found paused before its pause intent.

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
requested payload. Transport environment-file removal is replayed for
released tokens after a crash between durable release and unlink; this
cleanup does not change a sealed log or receipt.
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

Before resuming a group, recovery checks the durable maintenance holds.
The gate remains durable through every resume until the final release
snapshot. A crash there replays pauses and resumes under the same lock;
no build payload can enter while that gate is held. Initially paused
groups are excluded from the gate's resume list.

## 4. Independent recovery and maintenance

`heavy --install-reconciler [INTERVAL]` probes real cgroup containment,
including a `setsid` child, and installs an enabled user service and timer
named from the state directory's hash. Installation is explicit. It
changes no queue lanes, credentials, caches or runtime profile. The
service reads a private file containing only the required queue/workspace
configuration. Admission requires the timer to be active and a
containment probe for the current boot. After reboot, reconciliation and
admission repeat the probe before accepting new work. Reconciliation can
recover old holds first. A missing user bus or unsupported systemd capability
fails visibly.

`heavy --reconcile` runs the common recovery path. The timer survives a
killed queued wrapper and a killed submitter. It does not depend on queue
terminal rows. A temporarily unavailable queue fails closed: the next
timer activation retries without releasing its persisted gate hold.

Existing waiting clients inspect systemd's reported recovery service and
timer state. A failed/missing service, an inactive timer or an unreadable
snapshot produces actionable recovery instructions. Clients continue
waiting on reported service/timer failures, retaining task ownership;
an unreadable snapshot returns nonzero without cancelling the task.
Elapsed task age and delayed ticks never establish failure or a timeout.
For storage failure, free space, restore/restart the same recovery service
if needed, and run `heavy --reconcile` with the same queue configuration
and `DEV_TMP`. Retain the ledger; do not delete/reset it. Reconciliation
is replayable. Rerun land when completion is recovered with exit 137.

`heavy --maintenance-pause GROUP` saves an operator hold before applying
it. `heavy --maintenance-resume GROUP` clears that hold and resumes only
when no gate holds it. A resume intent remains durable until applied,
including when requested during a gate. These are the maintenance interfaces
while gates run. A direct pueue pause made during a gate cannot be
distinguished from the gate's pause and is outside this contract.

`heavy --cancel TOKEN` takes back one task, queued or running, by the
token printed at submission (10-25). A malformed or unknown token, or a
caller whose working directory is not the task's recorded repository,
is refused in fixed words, changing nothing. Under the host lock it marks
an unfinished task closing, outcome `cancelled`, code 130, then releases
it on the common path: owned scope killed and proved empty, a gate's
holds resumed, TSV row and receipt published. It uses no queue ID; a
queued entry that starts later finds its token released and refuses
replay. The waiting client ends with 130 and its usual summary. The
command exits 0 once the task is released, 1 if it had already ended
(finishing, closing or released: its result stands), 2 on a refusal;
past 60 seconds it leaves the release to the reconciler. It skips the
disk floor. SIGINT or SIGTERM to a waiting client cancels its task the
same way, between host-lock sections; a second one leaves the release to
the reconciler and exits 130. land's capture ignores SIGINT, so Ctrl-C
on land cancels its gate and land fails with 4.

`heavy --remove-reconciler` refuses unfinished tasks, then removes only
its own timer and service. `setup` checks recovery readiness without
installing it; its group repairs use `heavy --repair-group` under the host
lock, preserving gate and maintenance holds. Tests use distinct config, data, socket,
state and unit names; no live owners' daemon or groups are touched.

A pause that no ledger records has no durable owner. An empty process list
or absence of Cargo does not authorize resuming it. Migration must be quiet:
an operator accounts for the older queue's work and pause intent, drains
the dedicated queue and explicitly restores groups or records maintenance
holds before enabling admission. The root cause of incident 587 is
unknown; the stale pause fixture demonstrates recovery of a durable owned
hold without inferring that incident's cause.

## 5. Events and compatibility

Optional collection has one 60-second monotonic deadline for service readiness
and the GC RPC together. Timeout or execution failure preserves the payload exit;
only the operation's own client is killed and reaped, with output discarded.
The existing GC end event records a fixed outcome and reason. Server-side GC may
continue; release still requires the owned cgroup to be empty.

`DEV_TMP/heavy/events.jsonl` records submit, wrapper start, admission,
scope entry, phase begin/end for pause, drain, settle, payload, release
and collection, task completion, cancel, refusal and recovery. Records
include a unique event ID, token, timestamp, boot and queue identity,
lane, label, repository, tree, effective safe policy ID, free disk and
memory capacity, and the entrypoint recording the event. A contained gate sources
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

The TSV columns remain queue ID, lane, UTC completion, wait seconds, run
seconds, exit code, available memory GiB, working directory, log path,
command and label. Queue IDs may be reused by pueue; tokens and log paths
are the durable identities. Heavy prints its queued ID, the requested
log tail, and its task completion summary. It never reads pueue task
records or task logs. The phase events distinguish wrapper startup,
drain/settle time and payload execution; TSV wait time ends at payload
start and run time includes completion cleanup.

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
exercises the production heavy entrypoints with disposable pueued instances and user
systemd units. It covers killed pause intent, fsynced intent before
rename, paused groups, setsid/private descendants, release and release
snapshot windows, queue restart, boot identity change, pre-paused groups,
maintenance holds during a gate, two gates with builds, journal replay and
late systemd creation. Assertions check exclusion through cgroup release,
progress, one release per token, private descendant death and shared
daemon survival. The fixture uses short reconciler intervals without
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

The combined cases also exercise queued cancellation with real numeric ID
reuse and a replacement task, client death before wrapper start, terminal
queue completion with live private descendants, receipt-publication crash,
and real land/cache entrypoints in disposable Git repositories. The stale
pause case uses the approved five-second interval; other recovery fixtures
use 0.2 seconds and are labelled accelerated. Runtime, semantic policy and
missing-runtime changes before payload refuse without cache or ref advance.
Receipt faults cover before publication, a fsynced temporary receipt before
rename, and after atomic publication. The five-second case anchors a live
reconciliation, then observes recovery on the subsequent periodic tick.
Recovery fixtures also cover after-landing's helper lookup from a relocated
kit and real Chromium 147 receipt/cache reuse. Cancel cases cover a
queued task (below the disk floor, then its late entry's refused
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
`recovery_message.py`, `after-landing` and `kit.sh`, with their `test-*`
fixtures; `scripts/infra/setup` and `kache-setup`; and the workspace files
in `scripts/infra/workspace/`. `setup --fix` links the tools on PATH and
the workspace files to the primary agents checkout (infra.md 2), and each
tool finds its helpers beside it, so `heavy`, `land` and their helpers
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
(infra.md 2).

Never reset or replace a live queue or erase its ledger. Enqueue recovery
uses a persisted bare numeric queue ID; it cannot prove identity after a
reset/replacement. Replacement requires stopping submissions and a
complete accounting/drain, including callers, wrappers, observers,
unfinished tokens and pause/resume intent, before changing queue identity
or selecting a fresh state directory. Retain the retired ledger and
evidence. A normal daemon restart keeps its config/data identity and
ledger. After reboot restore that queue and its user services, including
recovery and the shared kache service when selected, then reconcile with
the same configuration and state. Resolve recovered nonzero completions
by rerunning land.

Rollback is reverting the commit, under the same rule for the ledger and
units. It requires no destructive cache or ledger cleanup.

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

`scripts/devel/land-set` is the landing flow's starting primitive
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
2. Fetch, then rebase on `origin/main`. A stop whose only conflicted path is
   the root `Cargo.lock` keeps the side being rebased onto and continues; any
   other conflict aborts the rebase and exits 3.
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
   as no `land` does (owners.md 4.5).
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
a rebase conflict outside `Cargo.lock`; 5 the lock; 6 `main` kept moving;
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
