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
| notes | files below `src/fabrig/{notes,tasks}`, except `queue.jsonl` and `queue.out` | mtime, 7 d |
| codex-sessions | `rollout*.jsonl` below `.codex/sessions` only | mtime, 14 d |
| recorded | producer paths with an ended record | kind-specific, below |

Records allow ended Claude jobs to expire after one hour. Other kind defaults:
ops-scratch and retired-scratch three days; qa-scratch and codex-run seven days.
An unfinished record protects its paths even against generic discovery. A
resumed `start` merges paths and clears the previous end. Duplicate start/end
calls do not extend retention: the earliest end since the most recent start
sets the clock. A resumed start stays live until a new end starts a new clock.
Unknown/malformed JSONL lines are ignored.
Overlapping candidates are counted and removed once; a parent owns its bytes.
Codex finality is never inferred from `ended` or mtimes. Missing, unreadable or
unknown `final.json` keeps the run as `codex-run not final`; failed systemctl
queries also keep it. Records cannot override this guard, which runs again
before removal. Top-level non-directories, including `runs.tsv`, stay intact.

Producers use these three commands (owner names may contain `/`):

```sh
reap record start --kind ops-scratch --owner lead/q/temper --id RUN --path "$HOME/scratch/RUN"
reap record end --kind ops-scratch --owner lead/q/temper --id RUN
systemctl --user start --no-block reap.service
```

Repeat `--path` to add paths. Record identity is `(kind, id)`; use unique IDs.
`claude-session` accepts only `$HOME/.claude/jobs/ID`. Records use a 0600
append-only JSONL file with `O_APPEND`, flock and fsync. Producers always get
exit 0 on record errors, with one stderr line; `--strict` enables failure exits.
No producer hooks or transient-unit cleanup are installed by this change.

## Safety and archives

Fixed code rules cannot be switched off in TOML. Keep anything in use through
`/proc/*/{cwd,fd,maps}`, anything that is or contains a claimed slot, and
anything borrowed through Git `objects/info/alternates` below HOME's `src` or
`.claude/jobs`. Failed claim queries keep every slot. Incomplete process or
alternates inspection keeps all affected candidates, with a reported reason.
If permissions prevent full `/proc` inspection, a narrow passwordless-sudo
helper reads only process cwd/fd link targets and maps; no file contents through
fds or process environment are read. Failure still keeps candidates.
Alternates scans have depth limits (64 under `src`, 32 under jobs) and a shared
thirty-second deadline; reaching a limit fails closed. Quoted alternates
paths also keep candidates for review rather than risk missing a borrower. Unknown Claude inventory
keeps jobs. Symlink candidates, symlinked parents and special files are refused.
Nested symlinks are never followed; removal only unlinks them.

Never paths include `src/rust/tmp/{logins,qa*,heavy,post}`,
`src/fabrig/{claims,leases,queue,main,agents,current,releases,events,records}`,
`src/rust/records`,
`.local/state/{fleet-sync,fabrig,heavy,reap}`, `.ssh`, `.claude/.credentials.json`,
`.claude.json`, Codex state outside `.codex/sessions`, and `archive`.
Claude jobs bookkeeping (`pins.json`) is also protected. Their ancestors are protected
too. The queue append targets and `logs/heavy.tsv` are also fixed exclusions.
Heavy reads its TSV for ID allocation and completed-task recovery, so it must
survive retention. Completed heavy logs are read for a waiting client's tail;
active processes protect those clients, and logs then get seven days.

Repositories with dirty files, stashes or branches absent from every remote
need a verified `git bundle create --all` under `archive/reap/YYYY-MM-DD`.
Dry runs report `would bundle` and keep them. Dirty trees also get a verified
worktree tar alongside the bundle, preserving uncommitted/untracked contents.
Archive failures keep the candidate. Process, claim and alternates checks run
again immediately before deletion, and metadata fingerprints reject changes
during inspection or archival. Removal uses directory descriptors and no-follow
opens, checking the candidate inode before unlink/rmdir. These checks reduce
observed races; producers must still stop before marking output ended.

## Reports and extension

Each normal run holds a nonblocking lock, saves a full private `run-*.json`
list and `last.json`, and appends a summary to `runs.jsonl` under
`.local/state/reap`. Busy runs exit 0 silently. Reports include per-class counts,
selected bytes, kept reasons and errors. `--json` prints every candidate.
Only a systemd invocation whose start matches the timer's latest trigger may
send the daily summary to `summary_to` (initially `ops@hel8`); manual CLI runs
never mail. A date reservation before `post send --as reap` prevents duplicate
mail after interruption; failed sends are recorded and are not retried that day.

Add a class by declaring its roots and nonnegative retention seconds in
`fleet/reap.toml`, adding its explicit discovery branch, and adding temporary
HOME/fake-service tests. Discovery must only select regular files or real
directories; it must use the common safety and removal path. Extend no exclusion
through configuration. Run `tools/check.sh tools/reap/test_reap.py`, then the
full gate. Review fleet dry-run reports before a separate live-mode commit.
