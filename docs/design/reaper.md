# Reaper

2026-10-30. Owner: s/deploy. Code: `tools/reap/`, `fleet/reap.toml`,
`fleet/units/reap.service`, `fleet/units/reap.timer`. Command reference:
`tools/reap/reap.md`. Departures: `docs/design/reaper.status.md`.

## 1. In one page

- **One reaper handles disposable output.** Discovery works without producer
  adoption; explicit lifetime records refine eligibility and protect live paths.
- **Age is necessary, never sufficient.** Fixed process, claim, borrower and
  never-path checks override every class and record. Unknown evidence keeps data.
- **Codex finality belongs to its producer.** A regular `final.json` declaring
  landed or withdrawn, an old UTC timestamp and an inactive or unknown run unit
  are all required. An `ended` marker or successful exit establishes nothing.
- **Dry-run is the fleet default.** Live requires a separate reviewed commit
  after ops reviews the first day's reports. Until then fleet-tend still runs.

The source decisions are the deployment plan at runtime path
`/home/free/src/fabrig/deploy/notes/reaper-plan.md`, including Changes after
review, and the reap-1b through reap-1e task contracts. The explicit `final.json` rule
supersedes the plan's original ended-marker and ended-record-only proposals.
The accepted independent review in reap-1e removes notes/tasks discovery until
authoritative finality exists; the plan's builder-copy proposal is deferred.

## 2. Discovery and retention

**Find existing output first.** HOME-relative roots and default retention are:

| Class | Evidence and retention |
|---|---|
| claude-jobs | `.claude/jobs/<id>`; directory mtime 24 h, absent from live Claude inventory and live PIDs |
| codex-runs | `src/rust/tmp/codex-run/<id>`; final JSON time strictly older than 7 d, final state, inactive/unknown unit |
| heavy-logs | `src/rust/tmp/logs/*`; mtime 7 d, excluding durable `heavy.tsv` |
| precheck-logs | `src/fabrig/slots/*.precheck-logs/*`; mtime 3 d |
| codex-sessions | `.codex/sessions/**/rollout*.jsonl`; mtime 14 d |
| recorded | ended producer paths; claude-session 1 h, ops-scratch/retired-scratch 3 d, qa-scratch/codex-run 7 d |

**Records do not weaken fixed guards.** An unended record keeps all intersecting
paths, including candidates found by another class. Ended records protect the
same paths until their kind's retention expires. All files in runtime
`~/src/fabrig/{notes,tasks}` stay, including paths named by ended records.
Discovery coalesces overlapping
candidates; a parent accounts for each byte once. No finality is inferred or
backfilled. `runs.tsv` and all other top-level non-directories under codex-run
remain untouched. Unknown Claude inventory keeps jobs; unknown Codex finality
keeps the run as `codex-run not final`.

## 3. Fixed keeps and preservation

**Keep active or borrowed data.** Inspect process cwd/fd links and mapped paths,
never descriptor contents or environments. A narrow sudo metadata helper can
complete otherwise unreadable process observations. Failure keeps candidates.
Claim authority is hel8: it reads its installed `claim list` locally; other
fleet hosts run that command there through bounded, noninteractive SSH, using
hel8's fleet SSH target and a login shell. Filter central rows to the builder's
fleet identity. Malformed, absent-host or failed observations keep every slot.
This follows fabrig's external `tools/slots/design.md`, section 3.

**Search for Git borrowers once per run.** Search runtime roots `~/src`,
`~/.claude/jobs` and `~/src/rust/tmp`, with six directory levels per root and
one total 20-second budget. Prune `target`, `node_modules` and `.cache`; never
walk Git object or pack trees. Read only `.git/objects/info/alternates`, bare
`*.git/objects/info/alternates`, and Git metadata pointers to linked worktrees'
common directories. Resolve relative object paths against the objects directory.
Protect every intersection with a borrowed object store: its ancestors,
object files, loose objects and pack descendants. Cache the result across all
candidates and final checks. Confirmed missing Git
directories (for example archived test worktree pointers) have no object store
to borrow; count them as absent. Pointer paths may contain embedded newlines.
Incomplete, unsafe,
quoted or unreadable metadata keeps everything; report the cause and elapsed
scan time in `runs.jsonl`. This scope is a fixed host-layout contract, not an
unbounded search. New clone layouts require review of the depth limit.

**Never paths are code rules.** Protect credentials and SSH/Codex private state,
primary/current/release clones, claims, leases, queue, heavy/post/login state,
QA scratch, reaper/fleet state, durable bookkeeping and archives. In particular
protect all of `~/src/fabrig/{archive,events,records,homes,notes,tasks}`, `~/src/rust/records` and
`~/src/rust/tmp/owners`. Protect their ancestors and descendants too. The command
reference lists the other exact paths. TOML cannot disable any keep rule.

**Never execute repository-defined programs.** Stop detecting dirtiness.
Every working tree is possibly dirty. Inspection uses only `rev-parse` and
`rev-list` (or equivalent `for-each-ref`/reachability plumbing), never status,
diff, checkout, stash porcelain, filters or index refreshes. All Git calls,
including bundle creation/verification, use the trusted system Git, a minimal
PATH/environment, no system/global config, no pager, disabled hooks/fsmonitor,
no replacement objects, and no protocol or lazy fetching. Repository clean,
process, fsmonitor and hook programs remain data, never executable helpers.

**Preserve every repository before live removal.** Always create a Python
working-tree tar under runtime `~/archive/reap/YYYY-MM-DD/`, excluding
`.git/objects` (and a bare repository's objects directory). Include a verified
`git bundle --all HEAD` whenever any ref, stash or HEAD has commits absent from
all remote-tracking refs. Explicit HEAD inclusion preserves detached commits.
Tar members come from the bounded iterative walk; file hashes read back from
the archive must match the copied bytes. Bundles must verify. Only verified,
fsynced artifacts are published. Dry-run keeps repositories as `would archive`.
Archive failures keep the original. The tar preserves working files and metadata;
commit reachability determines bundle coverage, not a dirtiness inference.

**Final checks follow every slow observation.** Archive, then refresh Claude,
claims and process observations. Acquire the same records-ledger exclusion used
by producer writes; reread records, check all keeps and Codex finality, then
fingerprint. Compare against the inspected metadata manifest only after those
observations. Hold the ledger lock through removal for every candidate, since
new records may name paths found by generic discovery too. The remover compares
every entry's device, inode, type, size, mtime and ctime before mutation, using
no-follow directory descriptors. It never unlinks an entry absent from the
manifest; new directory entries make rmdir refuse removal. Symlink candidates,
symlink parents and special files stay; nested symlinks are only unlinked.

**Traversal has finite budgets.** Walk, Git discovery, tar creation and removal
use iteration, not recursion or whole-directory sorted lists. A run has 300 s
and 1,000,000 entries; each candidate has 30 s and 100,000 entries, charged to
the shared run as well. Slow commands use the remaining deadline. Alternates
retain their additional 20-second bound. Process inspection is iterative with
an additional 20 s / 200,000-entry bound and charges observed entries to the run;
a budget failure never prompts a privileged retry. Exhaustion keeps affected
candidates as `budget`, preserving and mailing the partial report. Discovery
exhaustion reports a kept root marker for unenumerated data. Persistence/mail
are outside inspection budgets. Before mutation, reserve the finite removal
plan's entry allowance and check time; once admitted, finish that bounded plan
rather than interrupt it midway on a time-budget tick. Blocking kernel calls
are not a hard real-time guarantee.

These checks reduce observed races, not arbitrary concurrent filesystem writes.
The cached borrower observation cannot detect a new borrower created mid-run.
Ledger exclusion serializes successful starts; busy producers must retry, and
producers must keep data quiescent before ending a lifetime.

## 4. Producer lifetime interface

**Producers record identity, owner and paths.** `reap record start|end` appends
private, locked, fsynced JSONL under runtime `~/.local/state/reap/records.jsonl`.
Producer lock waits are bounded at two seconds; a busy write emits one stderr
line, exits 0 normally, and is retried at the next start. The CLI does not first
perform a blocking ledger read. The identity is `(kind, id)`; owner names may contain `/`. Repeated starts merge
paths without resetting a live record. Repeated ends preserve the earliest end
in that lifetime. A start after end resumes the record, keeps it live until the
next end, and starts a new retention epoch. Start requires an owner; end may
omit it and inherits the most recent start's owner. An explicit end owner must
match that start. A mismatch appends nothing and returns the normal best-effort
record diagnostic. An end without any matching start is retained in the ledger
but never contributes paths or eligibility, including to a later start.
Unknown/malformed rows are ignored.
Producers receive exit 0 with a diagnostic on recording errors; `--strict` is
available for checks. Detailed syntax remains in `tools/reap/reap.md`.

**Session hooks belong to s/multi-coord.** SessionStart records kind
`claude-session` with the full session ID, its direct-child jobs path
`.claude/jobs/<full-id[:8]>`, and an owner. Other paths are rejected. SessionEnd
supplies that same full ID without an owner, then requests
`systemctl --user start --no-block reap.service`. Hooks must remain best effort.
An explicit retired-role record hands over only stopped, private paths; it does
not authorize removal of a live or claimed path.

**Codex finality belongs to ops.** The producer publishes `final.json` by sibling
rename only after the task is landed or withdrawn. Its `time` is ISO-8601 UTC,
with or without fractional seconds and ending in `Z` or `+00:00`. Other times
keep the item. The reaper separately requires `codex-run-<id>` inactive or
unknown and keeps on systemctl failure. A codex-run record may add paths but
cannot substitute for this final evidence. Do not manufacture it for old runs.

## 5. Scheduling, reports and rollout

**The fleet timer and end hooks invoke the same command.** The all-role service
uses the current release through a login shell. The timer uses `OnActiveSec=1min`,
`OnBootSec=2min`, `OnUnitActiveSec=15min`, `RandomizedDelaySec=30` and
`AccuracySec=1s`. These settings bound activation scheduling at 91 seconds and
boot scheduling at 151 seconds, excluding service execution and host scheduling.
An existing timer must be reactivated to begin a new activation interval. Normal runs take a nonblocking private lock, write a
full candidate JSON list and last report, and append per-class counts, bytes,
kept reasons, errors, budgets and scan telemetry to `runs.jsonl`. Only a verified
timer invocation sends ops mail; manual invocations do not mail. The first
summary includes the complete candidate list grouped by class, with paths,
actions and kept reasons in its body. More than 50 items with the same class,
parent, action and reason collapse to a line with count, total reported bytes,
oldest/newest root mtime and directory. Early-kept candidates have no measured
recursive byte size; their reported bytes remain zero. Full JSON always keeps
every candidate. After successful first delivery, send only daily counts.
Reserve a date before sending to avoid same-day duplicates; if the first send
fails, retain full-list delivery for the next day's attempt.
`--dry-run --json --read-only` writes no reaper state, locks or mail.

**Ops reviews a full dry-run day first.** Inspect complete lists and safety
failures on all hosts, verify producer adoption and preserved state, and agree
on eligibility before enabling live mode. Live is a reviewed commit changing
`fleet/reap.toml`, not a one-off CLI override. Retire fleet-tend tidy and legacy
pruning only after live replacement is established; this branch does not stop
or alter them. Archive retention itself remains separate work.

## 6. Adding a class

**Keep discovery narrow.** Define explicit roots and retention in TOML, implement
one discovery branch, and document the producer's end evidence. Select only real
directories or regular files, route them through every common safety and archive
check, and preserve bookkeeping. Do not expose exclusion switches. Add temporary
HOME/fake-service tests for age boundaries, live/unknown evidence, fixed keeps
and safe deletion, then update this design, status and command reference.
Run `tools/check.sh tools/reap/test_reap.py` plainly, then the full gate plainly.
Review real read-only fleet reports before any class enters live use.

## 7. Later

- Restore notes/tasks discovery only for builder copies with authoritative landed/withdrawn evidence; keep every unknown task.
- Complete producer adoption and ops' first-day review before the live-mode commit.
- Retire legacy cleanup only after live replacement is demonstrated.
- Review archive retention and future layouts without broadening deletion roots.
