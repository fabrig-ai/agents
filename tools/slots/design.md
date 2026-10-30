# Slot tools

Provisional, 2026-10-28. Builder disk cleanup and local slot bookkeeping.

## 1. In one page

- **Trim on the builder:** `tools/slots/trim [--older MINUTES] [SLOT ...]`
  deletes old test executables and prints each slot's count, decimal GB of
  file sizes removed, filesystem free GB, and skipped processes. Default age
  is 120 minutes; default slots are `~/src/fabrig/slots/*`.
- **Claim on hel8:** `tools/slots/claim claim HOST N OWNER WHAT` records a
  holder atomically, `release HOST N OWNER` removes its own claim, and
  `list` shows every configured slot and its age. No network operations.
- **State stays local:** claim records live in `~/src/fabrig/claims/`, named
  `<host>-<n>`, with mode 0600. `hosts` is the inventory; a claim does not
  grant remote access or start a build.

## 2. Trimming

### 2.1 Eligible files and open descriptors

Only regular files with the user-execute bit in `target/debug/deps` qualify.
Files ending in `.so`, `.rlib`, `.rmeta`, or `.d`, symlinks, directories,
nonexecutables, and files modified at or after the cutoff stay. A symlink
in a slot's deps path is an error; an absent deps directory removes nothing.
Immediately before deleting a slot's candidates, scan `/proc/*/fd` metadata
for processes owned by the current uid. Compare device and inode, so an open
file's hard links are protected too. A process is skipped if its metadata,
fd directory, or an fd link raises `PermissionError`, `FileNotFoundError`, or
`ProcessLookupError`. Count each such process once per slot's scan. Continue
scanning its readable fd links, whose inodes remain protected. Other errors
fail the slot before deletion.
Slots without candidates skip the scan and report zero skipped processes.
Never read descriptor contents or another process's environment.

Recheck each candidate's identity, mode, size, mtime and ctime before unlinking.
The descriptor scan is a snapshot: callers trim idle slots, keeping a build's
inputs still, rather than opening old executables during a trim. File sizes
removed and filesystem free space are reported separately, since hard links
and open mappings can affect when blocks become free.

### 2.2 Invocation

Use trim as a task's first step on its builder. When calling from hel8,
send the standalone standard-library script through stdin:

```sh
ssh HOST 'bash -lc "python3 -I - [ARGS]"' < tools/slots/trim
```

The script imports no repository modules. `--older` accepts finite,
nonnegative minutes. Errors report the slot, exit 1, and permit remaining
slots to be inspected. Trimming does not touch caches or incremental state.

## 3. Claims

### 3.1 Ownership and inventory

`hosts` lists `HOST N=OWNER ...`, one host per line; each slot's share is
a post name such as `lead/jig`, or `pool`. Blank lines and `#` comments
are ignored; malformed entries, duplicate pairs and empty owners fail.
Only configured pairs can be claimed or released. Owner and work
description are nonempty text; quote a description containing spaces.
Slots on a draining builder belong to `ops`: leads start no new work there,
while existing holders can still release their claims. Replacement slots
and shares are announced before use. Remove the drained builder from the
inventory after its last task finishes. Build admission remains capped by
the machine's heavy setting, independently of its slot count.
A claim may take its owner's share or a pool slot. Another owner's share
requires that owner's agreement and `--lent-by SHARE_OWNER`; the value
must equal the configured share owner. Refusal exits 1 and names the
share owner and the lend option. Records hold owner, what, and an
ISO 8601 UTC creation time, plus `lent_by` when supplied; records without
it stay valid. Claims use `O_CREAT|O_EXCL` with mode 0600;
an existing claim exits 1 and prints the holder. Release checks the owner
and refuses another owner's claim. Missing claims also exit 1.
`release HOST N OWNER --what WHAT` also requires an exact match of the
recorded work description. Both comparisons and deletion hold the same
claims lock. A mismatch exits 1 without changing the record. Automated
callers use a unique WHAT for each claim lifetime and supply it on release;
a prior `list` check alone cannot protect a successor with the same owner.
Owner-only release remains available for existing manual callers.

List prints every configured pair and its `[share]`, with `free` or the
owner, description, UTC creation time, elapsed age and lender when present.
`list --free OWNER` prints only free slots claimable without a lend,
the owner's share first, then the pool, in inventory order within each;
one `HOST N` per line, exit 0 even when empty.

Run `claim` from PATH on hel8: `tools/install` links it to the dedicated
main clone (`tools/codex-run/design.md, 6`), so its adjacent `hosts` comes
from main rather than the caller's clone. All operations coordinate through a
local advisory lock so readers and release cannot race a record's creation
or replacement. This lock also lives under the claims directory. There is
no expiry or automatic stealing: a holder releases its claim explicitly.

Operational CLI commands refuse on other hosts before reading inventory or
opening local claim state. The authority accepts `hel8` and its deployed hostname
`debian-8gb-hel1-1` (including their fully qualified forms). A builder uses SSH to
run `claim` on hel8 and fails closed if that request fails; it never treats a
builder-local list as central custody. Refusal does not copy or change local
records and does not route requests automatically.

## 5. Disk guard

Builder identity accepts the inventory aliases and their deployed hostnames
(debian-16gb-hel1-3, -6 and -7); other hosts cannot acknowledge targets.

`tools/slots/guard [--below GB] [--dry-run]` checks the filesystem holding
`~/src/fabrig/slots`. Below 80 decimal GB by default, ordinary executable
trimming runs first, largest slot first by allocated regular-file bytes.
It keeps its existing threshold plus 40 GB recovery margin. Only after
ordinary trimming is exhausted and free space remains below the threshold
can whole-target recovery run. Whole-target recovery orders slots by oldest
proven idle completion, then slot name, and stops immediately when measured
free space is above the configured threshold. Idle completion is the later
of Codex completion and the latest completed manual/precheck/task lifetime.
It has no extra 40 GB deletion aim. The operator's manual fallback remains
largest-first.
Neither file sizes nor allocated sizes promise reclaimed bytes; every
operation remeasures filesystem free space. Dry-run uses the same eligibility
checks and order without deleting; it cannot assume future freed blocks.

Ordinary trim retains `trim`'s policy, age-zero cutoff, descriptor protection
and identity rechecks (section 2). Its heavy observation lists service units,
ignores non-service names and the reserved heavy `-reconcile.service`
observer, and checks payload and queued wrapper working directories. A
successful explicit inactive loaded/not-found service observation permits a
vanished/inactive unit; unknown or incomplete active properties refuse the
operation. Active, activating, reloading, deactivating and refreshing slot
services remain busy. Codex between builds may still have executables
trimmed; whole-target recovery has the stricter rules below.

### 5.1 Explicit report acknowledgement

No pre-existing slot is automatically eligible. Ended metadata, a `Done`
report, a zero exit, and post delivery do not establish that a lead handled
the report or resolved a capacity resume. On the builder, after checking the
latest report and ownership, an operator/lead explicitly attests:

```sh
python3 -I -B ~/src/fabrig/main/tools/slots/guard --ack N \
  --by lead/AREA --reason 'review and ownership evidence' \
  --report-handled --no-pending-resume --exclusive-lease-use
```

`N` is a numeric slot number, never an arbitrary path. `--exclusive-lease-use`
asserts that subsequent direct/manual work uses the lifetime entry point
(section 5.2), and that legacy launchers or other uncoordinated commands are
excluded for this slot. If the operator cannot establish that coverage, do
not acknowledge it: automatic whole-target deletion stays blocked. This
assertion does not claim control over arbitrary external commands.

Acknowledgements bind the exact canonical slot and slots-root device/inode,
target device/inode, checkout HEAD identity/digest, builder host/inventory,
every matching run's metadata,
ended marker and report identity (including modification/change times) and
SHA-256 digest, latest run identity, owner/recipient, and completion time.
The run history is `${DEV_ROOT:-$HOME/src/rust}/tmp/codex-run`; only run
metadata, ended markers and named reports are inspected. Missing, corrupt,
symlinked or unknown history refuses recovery; every matching run must have
ended. Other slots' incomplete runs do not authorize this slot. A live
Codex unit mapped to this slot vetoes recovery even with an ended marker;
a live unit without trustworthy run metadata also vetoes it. Owner units
without a working directory cannot establish exclusion and fail closed.
A new run, changed report/ended marker, replaced slot/target or source/build
lease invalidates acknowledgement. Nonzero and capacity-stop reports require
the same explicit fresh assertion after pending work is resolved.

Launcher, lifetime, legacy history and service matching share one path
validator. It inspects the supplied components for symlinks before
normalizing `.`/`..` and repeated leading separators, so an equivalent slot
alias cannot escape leasing or history attribution. A symlink followed by
`..` is refused even when lexical normalization would cancel that component.
Launcher metadata records the canonical directory before detached startup;
retry sleep remains protected while Codex has exited and the parent cwd is
outside the slot. History validation applies this rule to legacy records too.

Every history record's protected report path is inspected before filtering
by slot. Eligibility refuses any report or run-history path overlapping
the candidate target, including another slot's report or a path alias.
Symlink evidence paths refuse recovery. These checks apply to existing
metadata and are repeated before mutation. Updated launchers also refuse
new report/run-history destinations inside any numeric slot's target, so
another slot cannot publish new protected evidence into a reclaiming target.

### 5.2 Source/build lifetime interlock

State lives outside sources and generated data in
`~/src/fabrig/slot-maintenance/N/` (0700), with 0600 lock, acknowledgement,
hold, completion, journal and notice files. Symlink paths and unsafe state modes are
refused. One global `sweep.lock` serializes sweeps, acknowledgements, notices
and hold reconciliation. The per-slot `lease` uses shared flock for source/
build lifetimes and exclusive flock for maintenance. Entrance contention
refuses immediately; no command or timeout is cancelled or changed.

`codex-run task` takes a lease before report reservation and run creation.
A durable launch hold bridges detached systemd startup, including a queued
unit. `_run` adopts that hold only after recording its own durable hold and
acquiring its inherited lock. The lease covers initial trim, shell, Codex,
all retry sleeps, child drainage and final report/post handling. With an
`--on-stop` callback, the launch hold remains until `_stop` acquires its own
lease and adopts it, covering the callback entrance too. A missing helper
refuses numeric-slot startup. Nested numeric-slot working directories and
read-only numeric-slot tasks participate as well.

Precheck loads the lifetime implementation before switching source. It
holds its shared lease through ownership checks, source preparation, every
selected command, verification and restoration. Existing selection,
restoration, worker/precheck markers and locks remain authoritative. An
unknown completion or unresolved restoration leaves its durable hold.
The reclaimer also acquires sibling `.queue.lock`/`.worker.lock` and any
existing `.git/worker.lock`/`.git/precheck.lock`, and refuses
`.git/mq-worker-unresolved.json`, `.git/precheck.unresolved`, worker/queue
unresolved markers and `.git/index.lock`, including dangling symlinks.
It creates no source metadata or claim files.

Manual commands use the foreground entry point:

```sh
python3 -I -B ~/src/fabrig/main/tools/slots/lifetime.py run SLOT -- COMMAND ARG...
```

The command chooses its cwd; `SLOT` selects its numeric-slot lease. For
example, put a source switch and all its builds inside one foreground shell
under this entry point, rather than releasing ownership between commands.
Do not detach work or deliberately close inherited lease descriptors.
The wrapper passes its lock descriptor through exec into the shell and
children. A supervisor killed while children live therefore retains both
kernel exclusion and a durable hold. A nonzero/signal exit leaves a hold;
a normal zero completion removes only its own hold. A failed/timed-out stop
callback marks its hold uncertain even though callback failure stays advisory
for the systemd unit. `launch`, `verify` and `uncertain`
are launcher support modes; `canonical`, `directory`, `protect` and `root`
validate paths for the launcher. Operators use `run`. Path-only modes use
the same validation functions without loading supervisor dependencies.

Before removing a normally completed hold, its holder fsyncs
`completed.json`, containing exact slot identity, completion time, hold
identity and purpose. `completion.lock` serializes short completion writes
from shared lease holders. Its released flock grants no maintenance
eligibility: exclusive slot ownership and absence of uncertain holds remain
required. Precheck publishes completion only after restoration. Recovery
binds the completion record and its file identity/digest into acknowledgement
and uses the most recent finished activity for idle ordering and age.
Missing completion records permit explicit acknowledgement of legacy runs;
corrupt, future-dated or replaced completion evidence refuses eligibility
and cannot be overwritten by a successful new lifetime. A crash before hold
removal remains blocked even if the completion record was published. The
expanded history evidence requires fresh acknowledgement after upgrading.

Released flock, absent controller and process absence never clear a hold.
After independently establishing completion and handling the report/resume,
Ops can release one exact hold token (the 32-hex basename of `*.hold`):

```sh
python3 -I -B ~/src/fabrig/main/tools/slots/guard --release-hold N --hold TOKEN \
  --by ops --reason 'completion and ownership evidence' \
  --report-handled --no-pending-resume --exclusive-lease-use
```

This requires exclusive maintenance ownership, matching slot identity,
completed run history and all normal live-work observations. It leaves a
private release receipt and does not grant eligibility; run `--ack` again.
Reconciliation also records a completed lifetime at the time of the explicit
completion attestation, conservatively refreshing idle age.
Missing/corrupt history, unresolved precheck/worker state or an interrupted
reclaim still refuse this API and require operator investigation. Never
remove heavy state or stop units to make these checks pass.

### 5.3 Final observations and deletion boundary

Only inventory slots on hetzner3/6/7 qualify. Hetzner2 and hetzner8 cannot
acknowledge or reclaim whole targets. Each candidate is checked under its
exclusive lease, then checked again after ordering and immediately before
mutation. Heavy payloads and queued wrappers, legacy Codex runs (including
retry sleep), durable holds, unresolved ownership and own-user cwd usage
veto recovery. `/proc` inspection reads uid, cwd links, comm and cgroup
metadata only, never environment or descriptor contents. Unreadable own-user
cwds fail closed except exact protected host parents: systemd/(sd-pam) in
the uid's init.scope, sshd-session in a session scope, and ssh-agent in its
service with a verified active loaded working directory outside slots.
Shells/task children in those scopes remain subject to ordinary checks.
A vanished process is harmless; unavailable enumeration or unknown
unreadable processes refuse recovery. The reserved heavy reconciler is an
observer, never a build payload.

Only `target/` beneath the validated numeric slot can be removed. Slot/root/
target identity is verified again using an open slot directory descriptor.
Deletion uses fd-relative symlink-resistant `rmtree`; target symlinks,
symlink ancestors, mountpoints (including same-device bind mounts) beneath
target and device boundaries are refused. Internal generated-data symlinks
are unlinked, never followed. Source, `.git`, refs, reports and claims stay.
Cooperating starters cannot replace paths under the exclusive lease; the
explicit operator exclusion covers direct commands outside that protocol.

A private fsynced `reclaim.json` records intent and acknowledgement before
mutation, and the acknowledgement is consumed before deletion. Interrupts
or errors leave uncertain intent and block subsequent automatic recovery;
there is no automatic partial-deletion retry. Operators must establish
quiescence before reconciling such a journal; no surviving target inputs
are cleaned merely because the previous process died.

### 5.4 Evidence, notices, installation and validation

`~/src/fabrig/notes/slot-guard.log` is private (0600). Each whole-target
attempt is logged durably before deletion; completion records owner,
acknowledger/provenance, run identity, target, idle age, allocated size,
measured free space before/after, reason and safety evidence. Each success
also leaves an addressed `N/owner-notice.json`; `guard --notices` prints
these local owner notices as JSON lines. The latest notice is retained per
slot; the log and reclaim journal retain the evidence. Ops/lead forwards
this evidence using existing post routing and tells the owner the target
is cold. Cleanup success never depends on network notification delivery.

The ordinary CLI and timer interface remain: `guard --timer [--below GB]`
replaces the five-minute transient `fabrig-slot-guard` timer, and
`guard --timer --stop` stops just its timer/service. Run from the dedicated
main clone. Exit 0 means space is at least threshold (or no numeric slots),
exit 2 means space remains low, including no trustworthy eligible targets
and dry-run, and exit 1 indicates a sweep infrastructure error. Per-slot
whole-target refusals log their reason and leave space low with exit 2.

Deploy `guard`, `trim`, `recovery.py`, `lifetime.py` and `hosts` together.
Normal `tools/install` updates the dedicated clone and existing codex-run/
precheck links; no new PATH link is required. Refresh/start the guard timer
from main on builders after review. Update callers to the installed launcher
and precheck before any `--exclusive-lease-use` attestation. Legacy live runs
are protected by metadata, services and cwd observations; legacy/manual
future starts must be excluded explicitly. No old slot becomes eligible on
installation, and no production install is part of the offline tests.

Offline suites: `python3 -I -B tools/slots/test_{guard,recovery,trim,claim}.py`
(run each separately), `bash tools/codex-run/test-codex-run`,
`python3 -I -B tools/queue/test_precheck.py`, `tools/queue/test_mq.py`, and
`tools/test_install.py`. Fixtures use real disposable files/processes/flocks,
FIFO barriers, synthetic service metadata and private proc inventories.
They build nothing. Guard/recovery, trim, claim, precheck and launcher
fixtures allocate scratch in the checked source directory's Fabrig parent,
never inside the checked source. Cleanup removes only each fixture's exact
directory; a SIGKILL regression verifies that abandoned scratch stays
outside source. Automatic entries retain the fixed 60-second gate limit;
the launcher also retains its existing CPU check. A builder dry run with a threshold above current free
space exercises pressure and busy checks without deleting. An ordinary
above-threshold sweep does not inspect services. No heavy floor, admission
cap, budget, timeout, cache or heavy-state policy changes here.

### 5.5 Automatic policy observation (FIRSTDAYDRYRUN)

The requested policy is generated targets of central-unclaimed numeric builder
slots idle strictly more than 24 hours, while available space is strictly below
80,000,000,000 bytes. Automatic destructive enforcement remains disabled behind
FIRSTDAYDRYRUN; section 5.6 defines its gated consumer. A central `claim list`
response describes a snapshot; it grants no deletion exclusion. Ended markers,
completed lifetimes, zero exits, delivered reports and manual acknowledgements
cannot substitute for verified terminal/no-resume evidence in automatic mode.

`guard --automatic-targets [observe] [--dry-run]` selects a separate observation
entrance. Omitting the optional mode means `observe`. It uses the private guard
log and reports numeric entries individually, including protected unsafe paths.
Only builder inventory slots on hetzner3/6/7 can have ages observed. It reports
exact free bytes and the fixed policy pressure boundary, independently of normal
trim's configurable threshold. Other `--below` values and manual, notice or timer
actions cannot be combined with this entrance. An ordinary invocation without
`--automatic-targets` keeps executable trimming and explicit-ack recovery unchanged.

Observations read run metadata, ended/report fingerprints and any completed
lifetime through the existing history validator without creating maintenance
state. Completion age describes that evidence; it does not prove finality.
Target-write age uses the newest mtime or ctime of the target and every descendant
entry, with mount/device checks and without following symlinks. It does not use
the root directory's mtime as a shortcut. `observed-idle-over24h` compares the later
of observed completion and target activity against the strict age boundary.
Missing, unsafe, future or failed observations print UNKNOWN and the reason.
These are unlocked metadata snapshots, not maintenance ownership or a guarantee
against concurrent activity.

Every candidate remains PROTECTED, even with old observations. Central claim and
claim age, central exclusion, terminal/no-resume, live processes (including cwd,
fd and maps), source safety and host-wide alternate borrowers are UNKNOWN: this
entrance neither queries the central service nor asserts proofs it has not
acquired. No acknowledgement is read as automatic consent. It performs no trim,
deletion, claim update, lease acquisition, journal update or notice consumption;
only its private observation log is written. Exit 2 means numeric entries remain
under the fixed pressure boundary, exit 0 means space is at least that boundary
or there are no numeric entries, and exit 1 means an observation infrastructure
or log failure.

`guard --automatic-targets live` refuses with exit 1 before filesystem
observation or sweep entry while FIRSTDAYDRYRUN is set, including when combined
with `--dry-run`. Installation and timer behavior do not activate or schedule
automatic observation. Ops reviews first-day observation lists and the section
5.6 protocol before any later activation. Stopping use of the
observation option rolls back this observational rollout without changing manual
recovery. Existing lease, source, history, interruption and acknowledgement guards
remain authoritative for the separate manual path.

Offline coverage is `python3 -I -B tools/slots/test_recovery.py
AutomaticObservationTests -v`, followed by the existing slot suites. Fixtures
cover strict byte/age boundaries, newest descendant change time, missing history,
ended-but-resumable/question reports, completed lifetimes, changed/unknown claims,
stale manual consent, protected paths, incompatible actions and live refusal.

### 5.6 Gated central-custody consumer

`recovery.py` keeps `FIRSTDAYDRYRUN = True`. No CLI, environment variable or
installation setting overrides it. The live CLI and the underlying consumer
both check it before acquiring a claim or creating maintenance state. Only
isolated fixtures change the gate in memory. Ops must review first-day lists,
producer compatibility, lifetime coverage and rollout before an explicit later
activation change. This implementation does not activate or install anything.
After activation, `live --dry-run` still enters only section 5.5 observation.

The consumer serializes intent with the existing sweep lock. Before requesting
custody it durably writes private `N/automatic.json` with slot, owner `ops`, host,
number, start UTC and a unique exact WHAT (`guard reclaim UTC NONCE`). It invokes
only HEL8's installed authority through the shared `authority_argv` helper and
fixed transport `ssh -o BatchMode=yes free@204.168.210.29 bash -lc`. This endpoint
is the same authority whose deployed hostname is `debian-8gb-hel1-1`; the short
`hel8` alias need not resolve on a builder. Ordinary SSH host-key checking remains
in force. Remote command argv is shell-quoted for the login shell. There is no
environment override, builder-local fallback or alternate authority protocol:

```
claim claim HOST N ops 'guard reclaim UTC NONCE'
claim list
claim release HOST N ops --what 'guard reclaim UTC NONCE'
```

There is no builder-local authority, force, stealing or `--lent-by`. A held slot
or a non-pool share not owned by ops refuses normally. Failed, refused or
ambiguous responses never authorize deletion. Before publishing intent, the
consumer filters known non-pool shares, centrally observed busy slots, and failed
local maintenance/safety observations. Probe leases are released before acquisition;
the central list snapshot grants no custody and every proof is repeated under the
successful persistent claim. Filtered candidates publish no acquisition journal.

If acquisition races that filter, only two diagnostics established by the unchanged
authority source prove no acquisition: exit exactly 1 with empty stdout and either
the exact normal `claim: HOST-N held by OWNER: WHAT (since ISO)` diagnostic, or
`claim: HOST N belongs to share SHARE; a lend requires --lent-by SHARE`. The latter
must repeat the same non-pool/non-ops share, and the former must contain a known
timezone-aware creation time. Other exit codes, mixed/extra output, transport or
session failure, unknown diagnostics and ambiguous success retain uncertain intent
and any own claim. A subsequent list can never downgrade that uncertainty.

Known refusal writes private archived and current `status=skipped` evidence with
`acquired=false`, `mutation_started=false`, `release=not-acquired` and the raw exit/
stdout/stderr proof. It never releases a claim, permits later passes and does not
block manual maintenance. Existing uncertain records receive no backfill or
automatic migration. Once acquired, or after any mutation, failure remains retained
for Ops reconciliation. Claim acquisition must return the exact normal success message.
Subsequent central list observations must contain exactly one matching inventory
row with exact owner/WHAT, a known creation time and the normal age suffix. List
is a recheck of persistent custody, never custody by itself. Losing SSH or the
guard process does not release the central claim.

After acquiring the claim, the consumer takes the existing exclusive slot lease
and worker/precheck entrance locks under the held sweep lock. Holds, unresolved
markers, interrupted manual journals and pending automatic journals refuse work.
It requires completed run history, a known completed source/build lifetime, and
explicit prior-run finality for EVERY matching run. The finality consumer accepts
an owned private regular `RUN/final.json` with:

- `state`: `landed` or `withdrawn`;
- `owner`: exactly metadata's nonempty `to`;
- `time`: an ISO 8601 timestamp with timezone, at/after the run's ended evidence
  and not in the future;
- `sha`: a full nonzero 40- or 64-hex object ID for `landed`, or a nonempty `reason` for
  `withdrawn`.

It binds each final file's identity/digest and never creates, updates or backfills
it. The separately owned producer is `codex-run final RUN --owner RECORDED_TO
(--landed SHA | --withdrawn REASON)`. Missing or incompatible records retain old
runs; ended/Done/exit-zero/post/manual acknowledgement/completed lifetime do not
replace finality. Active or unknown Codex/heavy service observations still veto
the operation. Producer integration must verify this exact JSON contract before
activation; the offline consumer tests supply explicit fixture declarations.
Second-precision producer timestamps that precede the ended file's nanosecond mtime
remain protected. The consumer does not round or relax `time >= ended`; producer
precision/schema compatibility is a pending activation prerequisite.

Automatic snapshots add the following stricter proofs to the manual snapshot:

- Every source and Git regular file outside target is fingerprinted, and source
  directory identities are bound. Symlink, unreadable and cross-device source
  inputs refuse. Candidate `.git/commondir` and managed/dormant common-directory
  indirections are unsupported and refused without following their pointers. SHA
  digests are retained; file contents are not logged.
- A full target inventory binds identities, modes, sizes and mtime/ctime, allocated
  bytes and regular-file count. Symlinks, externally linked regular files, special
  files, protected Git/credential entries, mountpoints and device boundaries
  refuse. Internal hardlinks qualify only when the complete inventory accounts
  for every link to an inode with consistent identity/time/size/link-count evidence.
  Allocated bytes count each such inode once; removed files count directory entries.
  The latest target write and completed run/lifetime must be strictly
  more than 24 hours old. Exact free bytes must still be below 80,000,000,000.
- Own-user cwd, open descriptors and maps are checked, including inode aliases
  and deleted-path spellings. Source directory identities, including slot/Git
  directories, join the protected target and file inode set; actual cwd identity
  is compared independently of its text. Unknown/unreadable/incomplete observations
  refuse; process environments and descriptor contents are never read.
  Only exact maintenance lock descriptors held by this invocation are exempt:
  current pid, fd number, device/inode, unchanged known lock path, active lease
  context and that open file description's own kernel FLOCK WRITE metadata must
  agree. No whole-PID exception exists. Other/duplicated descriptors, descriptors
  reused without their flock and records from closed contexts are not exempt.
  The fd directory scanner stays open during enumeration, so it does not report
  its own already-closed scan descriptor as an unknown entry.
- All Fabrig-managed clones, bare repositories and scratch under
  `~/src/fabrig/` are inspected for object-store alternates, including recursive
  alternate chains, dormant repositories beneath `.git/modules` and orphaned
  `objects/info/alternates` stores without a normal ref layout. Any borrower into
  target, cyclic/external/unknown store,
  symlink directory, unsupported commondir or linked checkout with an unrecognized gitdir refuses.
  Environment-based alternate borrowing also refuses. Other checkouts receive
  no Git commands or mutations. Unrecognized layouts remain protected.

Central custody, snapshots, exact byte pressure and target/source identities are
rechecked immediately before fd-relative symlink-resistant target deletion.
Cooperating starters remain excluded by the persistent central claim and local
leases. Arbitrary commands outside these entrance protocols are not licensed by
this consumer; Ops must establish fleet lifetime coverage before activation.

After deletion returns, target absence, source/Git identities and digests,
history/reports, finality and borrower evidence must still match. A failure or
death anywhere before this known terminal result leaves the claim retained and
status uncertain. Only then are a cold-build owner notice and private fsynced
terminal evidence written. `automatic.json` and an `automatic-NONCE.json` archive
record `status=completed`, exit, start/end UTC, exact claim, measured bytes before/
after and delta, regular files removed and preservation proofs. File counts are
the fully inventoried regular files in the successfully removed target; freed
bytes are the measured filesystem delta, not promised allocated sizes.

Exact claim release happens only AFTER both durable completed records. There is
no release in a finally block, trap, shell-exit or session-loss handler. Release
failure/ambiguity retains completed evidence and reconciliation state; death after
release but before recording its response leaves a conservative retained receipt.
Success updates both records to `release=released`. Pending automatic records
also block manual whole-target maintenance; proven no-acquisition skipped records
permit another pass. Existing executable trimming remains
unchanged. No automatic retry or release reconciles an uncertain attempt.
Ops inspects the exact WHAT and evidence: incomplete evidence requires an
independent investigation; completed evidence permits an operator's exact release.
The consumer reports an error on protected/failed live attempts, while measured
space alone controls its stop boundary (no additional recovery margin).

`AutomaticClaimTests` runs fake SSH against the existing claim CLI with a temporary
authority HOME and hostname. It verifies real claim contention, exact release
ordering, an actual child death after deletion, release failures, finality and
live-work/borrower/preservation vetoes. It performs no real service, claim or
cleanup operation. Ordinary/manual guard interfaces remain unchanged.
`SafetyRepairTests` adds commondir, cwd alias identity, real disposable maintenance
fd/self-scan, stale/reused fd, ordinary-refusal retry, uncertain-session retention,
complete/internal versus external hardlinks, and strict time/OID regressions.
`AuthorityEndpointTests` exercises all authority forms with a nonresolving short
alias and verifies the exact explicit endpoint/login-shell argv and WHAT quoting.

## 4. Later

- Coordination of claims across machines if leads move away from hel8.
- Finding executable mappings after all descriptors have been closed.
- Ops-reviewed automatic target activation after FIRSTDAYDRYRUN, finality producer
  integration and fleet entrance/lifetime coverage review. Section 5.6's consumer
  remains gated; section 5.5 observations do not acquire custody or eligibility.
