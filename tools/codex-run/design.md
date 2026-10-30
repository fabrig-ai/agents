# Codex runs

Provisional, 2026-10-28. Detached task workers and persistent owners on the fleet.

## 1. In one page

- `codex-run task [OPTIONS] TASK DIR REPORT` reserves a report and starts a
  detached user unit. TASK, DIR and REPORT are absolute paths; REPORT must
  not exist, and its parent must exist. The task runs in DIR.
- `codex-run owner [--model M] [--effort E] NAME BRIEF` starts an owner that
  receives post between turns. BRIEF is an absolute readable file.
- `codex-run stale [--post]` lists unfinished inactive runs and refused
  completion messages; `--post` retries notification.
- `codex-run final RUN --owner ADDR (--landed SHA | --withdrawn REASON)`
  declares a completed, inactive run's task final on its recorded owner's word.
- Runs live under `~/src/rust/tmp/codex-run/`; `DEV_ROOT` replaces
  `~/src/rust`. Writable slot tasks trim their own slot before Codex starts.
- Dependencies are Bash, Python 3, jq, Perl, GNU coreutils, flock, systemd
  user units, Codex and `post` on PATH. Units start through a login shell.
  No adjacent agents checkout or sibling post executable is required.

Path validation, lease supervision, subreaper bootstrap and finalization use
isolated Python without site initialization; their dependencies are in the
standard library. Finalization loads liveness and publication dependencies
when its checks reach those steps. Slot trimming retains its isolated invocation.

## 2. Tasks and arguments

Task options are `--model M`, `--effort E` (medium, high or xhigh),
`--read-only`, `--to ADDRESS`, `--resume RUN`, and `--on-stop FILE`.
Defaults are `gpt-6.1-sol`, high effort, writable execution, and the recipient
in `POST_NAME`. Paths and model names must not contain tabs or newlines.

A resume names a previous run under the same run root. It reuses that
thread and inherits model, effort, read-only mode and working directory
unless supplied anew. With a resume, `TASK REPORT` can omit DIR.
A resume inherits its recipient unless `--to` or `POST_NAME` supplies one,
with `--to` taking precedence.
Each resume gets its own run directory and report. A thread missing from
its saved file can be recovered from its events.

Writable tasks use Codex's bypass-approval mode. Read-only tasks use its
read-only sandbox and return their complete report as their final message;
the worker publishes it outside the sandbox. Both receive the task path
and the restriction to search only their worktree and task-named paths.
Prompts reach Codex on stdin from a private file.

`--on-stop` records an absolute callback path for the unit's stop step.
A regular executable callback runs from its own directory with closed stdin,
logging stdout and stderr in `on-stop.log` and its result in `on-stop`.
It is killed after 60 seconds; absence and failure do not fail the unit.
Resume does not inherit the callback. Unsafe installation paths are refused
when building the systemd stop command.

## 3. Runs, reports and completion

Task launch prints `ID RUN_DIRECTORY`; the unit is `codex-run-ID`. The ID
combines a UTC timestamp and random suffix. The directory holds `meta`,
`prompt`, timestamped `events.jsonl`, `stderr.log`, `thread`, and `last.md`.
Directories are private and files are mode 0600 through umask 077.

Launch reserves REPORT exclusively. If the task leaves the reservation or
no report, completion publishes `last.md` or a diagnostic, retaining the
fallback at `report.md` in the run directory. Completion posts the report
path, run directory, thread, elapsed minutes and attempts to its recipient.
It appends settings, exit status, usage and post status to `runs.tsv` under
an advisory lock and writes `ended`. A failed completion step is recorded
in `finish-errors` without skipping later steps.

Capacity failures with a saved thread retry after 120, 300 and 900 seconds;
`CODEX_RUN_RETRY_DELAYS` overrides those delays. Other failures finish.
TERM and INT finish with their signal status. A killed worker can be
reported by `stale`; that command considers metadata aged at least two
minutes and less than one day. Post exits 0 and 3 count as delivered;
refused delivery remains retryable. Stale notification records `told`
without replaying report publication or accounting.
Completed runs without `post-failed` are skipped before reading metadata age;
their age-stat failures are silent. Stale checks notification candidates, so
this filtering grants no finality, retention, deletion or slot-release authority.
Completion records a refused post before writing `ended`, keeping that
notification retryable throughout completion.

### 3.1 Reaper producer hooks

After saving a new task run's metadata and resume thread, the launcher checks
`command -v reap` and, when available, calls
`reap record start --kind codex-run --owner OWNER --id ID --path RUN_DIRECTORY`.
OWNER is the recorded `--to` recipient, including when POST_NAME names a
different launching caller. The explicit final declaration uses that same owner.
Only that invocation's new run directory is registered. Task files, reports,
callbacks, slot checkouts and targets, primary clones, credentials, persistent
owner resume state, claims, leases and heavy state are outside its authority.
Arguments retain their boundaries, including paths with spaces.

Completion may trigger `systemctl --user start --no-block reap.service`.
Without a callback this follows accounting and the attempt to write `ended`.
With `--on-stop` it follows the callback result and any attempt to mark a
failed callback's lease uncertain. A failed launch may trigger discovery
before the existing removal of its private directory and report reservation.
Normal completion, failure, resume, TERM, INT and stop handling never emit
`record end`. Neither a turn finishing, `ended`, exit zero nor successful post
establishes task finality. A killed worker may leave discovery to deployment.

The frozen record contract is
`reap record start|end --kind K --owner O --id ID [--path P]...`: both forms
require an owner. End means that the task is final (landed or withdrawn).
A run directory becomes eligible only seven days after that task-final end;
resumable and uncertain tasks remain protected indefinitely. There is no
generic cleanup based on the age of a run's `ended` marker. Only the explicit
declaration in section 3.2 emits an end. Run completion infers no landing or
withdrawal and grants no authority to reclaim a slot.

Lease release remains the lifetime helper's decision. The reaper preserves
metadata, shared `runs.tsv` accounting, pending resumes and sessions referenced
by an owner. It owns discovery, retention and deletion, including older runs
without producer records; missing records establish no deletion authority.
The launcher neither scans nor deletes retained evidence.

Each optional notification uses GNU `timeout` with the existing 60-second
stop bound and KILL signal, closed stdin and discarded output. Missing,
broken or hanging tools and units cannot change the caller's exit status,
report, delivery, accounting, callback result, lease decision or end marker.
The hooks can deploy before the `reap` CLI and unit, without a storage
migration or backfill by this producer. The reaper's deployment owns adoption.

Retention policy belongs to that deployment: task-final runs seven days after
record end, heavy logs seven days,
precheck evidence three days, landed or withdrawn notes and tasks seven days,
Codex sessions fourteen days, and ended Ops scratch three days. Heavy logs'
seven days takes precedence over generic old logs' three days. Keeps still
protect resumable and referenced evidence beyond these ages.

### 3.2 Explicit task finality

`codex-run final RUN --owner ADDR (--landed SHA | --withdrawn REASON)` accepts
a run ID under the configured run root. ADDR must equal its metadata's unique
`to` recipient. The owner declares landing with a full nonzero 40- or 64-digit
hex commit OID (stored lowercase), or withdrawal with a nonblank reason.
Exactly one declaration is required. The command checks no Git repository,
queue, task file or report and performs no backfill. After reading a read-only
review/survey report, its owner explicitly uses `--withdrawn report-read`.

Finality requires a private regular `ended` file as completion evidence;
that file alone never declares finality. The command takes an exclusive,
nonblocking lock on metadata. Workers and stop callbacks hold shared locks
while running, so a misleading unit snapshot cannot finalize a running worker.
The user manager must successfully enumerate the exact unit using
`list-units --all --plain --no-legend --no-pager --full`. Only loaded
inactive/dead, loaded failed/failed, or confirmed absence after collection is
accepted. Active, transitional, malformed, missing-manager and timed-out states
refuse with exit 2. A configured callback also needs a private known stop
result (`exit 0` or `absent`); a failed or unknown callback remains protected.
These checks do not clear any signal, resume or lease holds. Reaper keeps
remain authoritative, including indefinite protection for uncertain inputs.

The run directory and evidence must be owned by the invoking user with modes
0700 and 0600 respectively. Symlink path components, unsafe IDs, nonregular
evidence, hard-linked files and conflicting declarations refuse. The finalizer
reads only the named run's metadata and completion/stop/final evidence.

It writes `final.json` through a private temporary file, fsyncs its complete
bytes, renames it atomically with Linux `RENAME_NOREPLACE` and fsyncs the
directory. An existing marker is never replaced. Its JSON fields are `state`, `owner`,
`time` (UTC `YYYY-MM-DDTHH:MM:SS.ffffffZ`), and exactly one of `sha` or `reason`.
The declaration samples the wall clock in nanoseconds and floors it to the
consumer's microsecond datetime precision. Before publication its parsed time
must be at least the private completion file's nanosecond mtime and no later
than the sampled clock. If the clock is behind completion, or no representable
microsecond falls between completion and now, it refuses without a marker;
it never rounds upward to manufacture a future declaration.
An interrupted prepublication write cannot expose a partial final marker.
Valid durable finality returns exit 0. Identical declarations preserve exact
marker bytes, inode, mtime, ctime and JSON time; conflicting state, content or
owner returns exit 2 and leaves the marker untouched.
Repeats parse the stored timezone-aware ISO time and apply the same completion
and nonfuture checks. A valid whole-second marker can remain valid; an invalid
old or fractional marker refuses without rewriting or repairing that evidence.

Only creation of a new durable marker attempts
`reap record end --kind codex-run --owner ADDR --id RUN`, guarded by
`command -v reap`, then the best-effort service trigger. Notification absence,
failure or timeout cannot invalidate the durable declaration. Identical calls
do not replay end notifications, so neither the marker's finality time nor a
reaper record's end time can be reset by repeats. Retention is anchored to the
original final declaration; the consumer must also require an old enough
final marker and an inactive unit. Deployment discovery must reconcile durable
final markers whose optional notification was missed. This command implements
no notification backfill or deletion and changes no existing registry owner.

## 4. Slot trimming

Before its first Codex turn, a writable task resolves DIR and checks that
it is exactly `~/src/fabrig/slots/<n>`, with a numeric final component.
It runs `python3 -I <fabrig>/tools/slots/trim <slot>`, where fabrig is the
repository containing the resolved codex-run executable. This uses the
slot trim rules in `tools/slots/design.md, 2`.

The trim's one-line result and any diagnostic go to the run's `trim.log`.
A nonzero exit adds `trim failed: exit N` and the task continues. Missing
trim scripts are handled the same way. Read-only runs, owners, named
directories and directories nested inside a slot do not trim. `DEV_ROOT`
changes run storage, not the slot directory convention or the trim script.

## 5. Owners

Owner launch prints its escaped unit name. State lives under
`<root>/tmp/owners/<last-name-component>/codex/`, where root defaults to
`~/src/rust` and can be replaced by `DEV_ROOT`. A stored full owner name
refuses collisions. The owner registers its holder with post before its
first turn, reads BRIEF, then waits for mail for an hour between turns.
An idle hour prompts it to check its work. Failed turns wait five minutes;
pending mail is retained until a successful turn, including across restarts.
Replacement of the holder ends the loop. Turn accounting is in `turns.tsv`.
Neither a turn ending nor a holder replacement ends persistent owner state.
This producer emits no owner lifecycle record, including on final loop exit;
MC owns that lifecycle and its pending resume references.

## 6. Installation and verification

`tools/install [--dry-run]` uses its own repository's origin URL. It clones
into `~/src/fabrig/main` when absent, otherwise fetches that dedicated clone,
then switches it to detached `origin/main`. It refuses symlink checkouts,
dirty checkouts, different origins and directories inside another checkout.
The task's checkout and the agents repository are left in place.

`tools/installed` lists `TOOL DIRECTORY`: `codex-run codex-run` and `claim slots`.
The installer points `~/.local/bin/TOOL` at the corresponding executable in
the dedicated clone, printing each link's old and new target. Existing
non-symlink programs are refused. Dry-run prints proposed git commands and
links using the invoking checkout's manifest, without fetching, cloning,
switching, creating directories or changing links. A real install reads
the manifest from the updated clone.

`bash tools/codex-run/test-codex-run` tests workers, owners, notifications,
signals and trimming against fake Codex, post and systemd executables.
`bash tools/codex-run/test-codex-run --reap-only` runs the producer adoption
checks with the same isolated fixtures. `--final-only` also runs explicit
finality fixtures, including atomic publication faults and immutable repeats.
The full suite also checks mixed stale history, completion ordering and
candidate age/metadata failures through the public CLI, retaining its history.
All selections assert CPU below
15 seconds and wall time below 60 seconds. Only private fixture copies
shorten the timeout when proving hanging tools and callbacks are killed.
All fixture processes use a private executable allowlist with no host PATH
directories. Removing reap or systemctl leaves them absent; it cannot fall
through to host services. A shell startup guard independently audits PATH
before fixture and launcher shell bodies run, including worker and stop
supervision. `CODEX_RUN_ISOLATION_LOG` saves that audit for either selection.
`python3 -I tools/test_install.py` tests installation using local fixture
repositories and a temporary home. Neither command uses real fleet state.
These scripts run directly on hel8; they build nothing.

## 7. Later

- Move other fleet tools and add their entries to `tools/installed`.
- Move run and owner storage into fabrig with a separate migration that
  preserves resumable runs and accounting.
- Reaper deployment adoption of durable final markers with missed notifications
  and reconciliation of older registry owners remain the deployment owner's work.
