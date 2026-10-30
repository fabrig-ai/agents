# Fleet reaper

`reap run` discovers disposable output and applies fixed safety checks. The
fleet ships `fleet/reap.toml` with `mode = "dry-run"`; even `run --live` is
refused until a separate reviewed commit enables live mode. The fifteen-minute
timer uses that setting. Session end hooks may also start `reap.service`.
Dry runs never bundle or remove candidates, but normally write private reports.
`run --dry-run --json --read-only` also suppresses state writes, locks and mail;
use it for surveys. `status [--json]` reads the last report without changing it.

## Discovery and retention

| Class | HOME-relative discovery | Age |
| --- | --- | --- |
| claude-jobs | `.claude/jobs/<id>`, checked against `claude agents --json --all` and live PIDs | directory mtime, 24 h |
| codex-runs | `src/rust/tmp/codex-run/<run>` with regular `final.json`, `state` landed/withdrawn, unit inactive/unknown | final JSON UTC `time`, 7 d |
| heavy-logs | `src/rust/tmp/logs/*`, except durable `heavy.tsv` | mtime, 7 d |
| precheck-logs | `src/fabrig/slots/*.precheck-logs/*` | mtime, 3 d |
| codex-sessions | `rollout*.jsonl` below `.codex/sessions` only | mtime, 14 d |
| recorded | producer paths with an ended record | kind-specific, below |

Records allow ended Claude jobs to expire after one hour. Other kind defaults:
ops-scratch and retired-scratch three days; qa-scratch and codex-run seven days.
An unfinished record protects its paths even against generic discovery. A
resumed `start` merges paths and clears the previous end. Duplicate start/end
calls do not extend retention: the earliest end since the most recent start
sets the clock. A resumed start stays live until a new end starts a new clock.
Kind retention also protects ended paths from earlier generic discovery; an
old directory mtime cannot skip this wait.
Unknown/malformed JSONL lines are ignored. Notes/tasks discovery is removed:
all of `src/fabrig/{notes,tasks}` stays, including paths in ended records,
until authoritative landed/withdrawn evidence exists for disposable builder copies.
Overlapping candidates are counted and removed once; a parent owns its bytes.
Codex finality is never inferred from `ended` or mtimes. Missing, unreadable or
unknown `final.json` keeps the run as `codex-run not final`; failed systemctl
queries also keep it. UTC times accept optional fractional seconds with `Z`
or `+00:00`; other representations keep the item. Records cannot override this
guard, which runs again before removal. Top-level non-directories, including `runs.tsv`, stay intact.

Producers use these three commands (owner names may contain `/`):

```sh
reap record start --kind ops-scratch --owner lead/q/temper --id RUN --path "$HOME/scratch/RUN"
reap record end --kind ops-scratch --id RUN
systemctl --user start --no-block reap.service
```

Repeat `--path` to add paths. Record identity is `(kind, id)`; use unique IDs.
`claude-session` accepts only the direct child `$HOME/.claude/jobs/ID[:8]`,
while retaining the full session ID as record identity. Start requires `--owner`.
End may omit it for every kind and inherits the most recent start's owner; an
explicit owner must match. A mismatch appends nothing and produces one stderr
line with the usual best-effort exit 0 (`--strict` enables error exits). An end
without a matching start is recorded but never supplies paths or eligibility.
A later start cannot inherit that orphan end's paths or timestamp. Records use a 0600
append-only JSONL file with `O_APPEND`, flock and fsync. Ledger lock waits are
bounded at two seconds; a busy producer returns one diagnostic and retries at
the next start. Successful starts serialize against live final checks/removal. Producers always get
exit 0 on record errors, with one stderr line; `--strict` enables failure exits.
Producer rollout and integration gaps are tracked in `docs/design/reaper.status.md`;
no transient-unit cleanup is installed by this change.

## Safety and archives

Fixed code rules cannot be switched off in TOML. Keep anything in use through
`/proc/*/{cwd,fd,maps}`, anything that is or contains a claimed slot, and
anything borrowed through Git `objects/info/alternates` below HOME's `src`,
`.claude/jobs` or `src/rust/tmp`. Hel8 reads installed `claim list` locally;
other fleet hosts use its `fleet/hosts.toml` SSH target, noninteractive SSH and
a login shell, then filter for this host. Failed, malformed or incomplete claim
queries keep every slot. Incomplete process or
alternates inspection keeps all affected candidates, with a reported reason.
If permissions prevent full `/proc` inspection, a narrow passwordless-sudo
helper reads only process cwd/fd link targets and maps; no file contents through
fds or process environment are read. Failure still keeps candidates.
Alternates scanning runs once per invocation and is cached for all candidates.
It searches six directory levels per root, with a total twenty-second budget,
for working-tree `.git`, bare `*.git`, and linked-worktree gitdir/commondir
metadata. It prunes `target`, `node_modules` and `.cache`, and never descends
Git object or pack trees. Relative alternate paths use the objects directory.
A budget failure keeps everything. Reports, including `runs.jsonl`, include
`alternates_scan` completion, reason, elapsed seconds and discovery counts.
Quoted alternates paths also keep candidates for review. Confirmed missing Git
directories (for example archived test worktree pointers) have no object store
to borrow; count them as absent. Git metadata pointers preserve embedded
newlines in paths. Unknown Claude inventory keeps jobs. Symlink candidates, symlinked parents and special files are refused.
Nested symlinks are never followed; removal only unlinks them.

Never paths include `src/rust/tmp/{logins,qa*,heavy,post,owners}`,
`src/fabrig/{claims,leases,queue,main,agents,current,releases,archive,events,records,homes,notes,tasks,logins}`,
`src/rust/records`, `.config/fleet-scale` (fleet-scale credential source),
`.local/state/{fleet-sync,fabrig,heavy,reap}`, `.ssh`, `.claude/.credentials.json`,
`.claude.json`, Codex state outside `.codex/sessions`, and `archive`.
Claude jobs bookkeeping (`pins.json`) is also protected. Their ancestors are protected
too. The queue append targets and `logs/heavy.tsv` are also fixed exclusions.
Heavy reads its TSV for ID allocation and completed-task recovery, so it must
survive retention. Completed heavy logs are read for a waiting client's tail;
active processes protect those clients, and logs then get seven days.

No repository-defined helper may run. Git queries use sanitized reachability
plumbing only, never status/diff/checkout or dirtiness detection. Git receives
no caller overrides, system/global config, pager, replacement objects or network
protocols; PATH is `/usr/bin:/bin`, hooks/fsmonitor are disabled and Git is the
system binary. Clean/process filters and hook programs are never invoked.

Every working tree is possibly dirty. Dry-run keeps repositories as
`would archive`. Before live removal, always write and hash-verify a Python
worktree tar, excluding `.git/objects`; bare stores omit their objects directory.
Any local-only ref, stash or HEAD also requires `git bundle --all HEAD` and
verification. This includes detached HEAD recovery. Archives are private and
published under `archive/reap/YYYY-MM-DD` only after verification and fsync.
Failure keeps the source. Refresh slow observations first, acquire the records
ledger exclusion, check finality/records, then compare the complete fingerprint.
Hold the lock through fd-relative, per-entry identity/metadata-checked removal.
Borrowed object-store intersections protect both ancestors and descendants.

All traversal is iterative: run limits are 300 seconds / 1,000,000 entries,
and candidate limits are 30 seconds / 100,000 entries charged to the same run.
Alternates keep their 20-second limit; process metadata has a 20-second /
200,000-entry limit. Budget exhaustion keeps affected candidates as `budget`,
then persists and mails the partial report. Discovery exhaustion records a kept
root marker. Removal reserves its finite entry plan before mutation; admitted
removal finishes without a time tick interrupting it midway. This cannot bound
a blocking kernel call or exclude arbitrary concurrent non-producer writes.

## Reports and extension

Each normal run holds a nonblocking lock, saves a full private `run-*.json`
list and `last.json`, and appends a summary to `runs.jsonl` under
`.local/state/reap`. Busy runs exit 0 silently. Reports include per-class counts,
selected bytes, kept reasons and errors. `--json` prints every candidate.
The timer uses activation 1 min, boot 2 min, recurrence 15 min, jitter 30 s and
accuracy 1 s (activation bound 91 s, boot bound 151 s). Reactivate an existing
timer on reviewed deployment to start the new activation interval.
Only a systemd invocation whose start matches the timer's latest trigger may
send the daily summary to `summary_to` (initially `ops@hel8`); manual CLI runs
never mail. The first timer summary includes the complete candidate list grouped
by class, with paths, actions and reasons. More than 50 homogeneous items under
one parent collapse to count, total reported bytes, oldest/newest root mtime and
directory. Early-kept directories have unmeasured recursive bytes (reported 0).
The saved JSON retains every item. After the first successful delivery, mail
only daily counts. A date reservation before `post send --as reap` prevents
same-day duplicates; a failed first send retries the full list the next day.

Add a class by declaring its roots and nonnegative retention seconds in
`fleet/reap.toml`, adding its explicit discovery branch, and adding temporary
HOME/fake-service tests. Discovery must only select regular files or real
directories; it must use the common safety and removal path. Extend no exclusion
through configuration. Run `tools/check.sh tools/reap/test_reap.py`, then the
full gate. Review fleet dry-run reports before a separate live-mode commit.
