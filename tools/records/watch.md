# Pipeline watch

`tools/records/watch --once` evaluates section 3b of `director-records.md`.
The hel8 `pipeline-watch.timer` runs `pipeline-watch.service` every two minutes,
using the release's `tools/records/watch` executable. The installed command name
is reserved as `pipeline-watch` so it does not shadow procps `watch`.
Without `--once` the tool repeats every 120 seconds.
`watch --dry-run --once` prints the exact proposed post commands, bounded
metadata evidence and JSONL spool output. It never calls send, stop, resume, launch, kill or append,
changes the watch state, or advances the live records clone. Its one `record
pull` uses a disposable clone, deleted on exit. Durable drafts and questions use the sibling `record` reader. Raw events never
use that writer. No legacy code is imported.

`watch.toml` enables `[alerts] post = true`. Setting it to false still evaluates
conditions, persists episodes, and publishes alert events and heartbeats, while
logging proposed commands without sending or repairing. `--no-post --no-remedy` selects the same
observation mode; add `--dry-run` to preserve watch state/spools too. Silent episodes carry
their opening time. On enabling posts, only episodes confirmed active by fresh,
successful inputs receive a catch-up, once each, marked
`(was silent since <time>)`. Cleared conditions do not post while awaiting their
second clear poll. An overdue catch-up without a repair goes directly to the supervisor and
satisfies escalation. A suppressed repair runs first on enabling actions; otherwise it goes to the owner and the normal escalation
clock continues. Failed sends retry. Legacy silent state migrates using each
episode's original opening time, even if its suppressed actions were already
marked handled. Suppressed historical events in the publication outbox never
replay mailbox actions. Unlike `--dry-run`, silent mode updates state and the local spool.

`watch.toml` enables each rule and holds every timing threshold.
Conditions use strict "older than" comparisons. Deaf/gone/report-unread
escalation follows decision 0025: two failed remedies, or more than 30 minutes
after remedy; an unremedied reader escalates once after 30 minutes. Other
rules count their interval from opening. For escalations whose
interval is unspecified in 3b, the defaults use the condition interval (run
30, claim 45, ready 30, lease 240, handover 20 minutes); delivery uses
20 minutes. These values are adjustable independently. Question due posts only
to director; the director batches the question to the user.

| Rule | Evidence / first destination | Escalation |
|---|---|---|
| deaf | live session, missing live waiter, mail mtime >10m; restart idle Claude with confirmed saved full id/cwd | supervisor after two failures or >30m after remedy |
| gone | registered active draft, director or unfinished lead part, absent session; launcher dry run then restart | supervisor after two failures or >30m after remedy |
| report unread | completed run id in codex-run post header, mtime >15m; one episode per reader, unless deaf covers it | supervisor after >30m, once |
| run hung | output `events.jsonl` mtime >60m AND elapsed >3× median of at least 5 completed runs at that effort (else >90m); owner | supervisor |
| idle claim | >45m since claim or latest run/heavy/precheck activity, with no live run/heavy; holder | supervisor |
| unqueued | unchanged ready tip observed >30m with no attempt for that tip, or >20m without a batch while refs exist; ops | supervisor |
| lease stall | waiters and >4h without package events, or waiter >2h; holder | supervisor |
| handover late | >20m after recorded context hook without successor or files-current metadata; session | supervisor |
| question due | unanswered question past its deadline; director | director handles the user |
| waiter orphan | ended session, or pid-1 parent without a live mailbox session; report and safely clean up | none |
| waiter dead | no waiter process; report without changing post state | none |
| delivery failed | send exit 2 without successful retry/told marker; sender (run's session owner for codex-run) | supervisor |

Open sends go to the subject's mailbox or its owner. Every escalation uses the
owner's supervisor from the launcher, including director for coordinators, ops
and s/deploy. The post subject contains the rule and watched subject; its body
contains up to six lines of evidence, plus the silent marker for a catch-up.
The director has no escalation destination.

The launcher supplies identities and supervisors through
`session-start names --json`, an array of rows with `mailbox` and
`supervisor`, plus role-specific aliases, prefixes, handles, areas and paths.
Watch uses that contract directly: it does not infer supervisors, accept a
mailbox-keyed object, or add identities missing from the inventory. The
director's null supervisor becomes an empty escalation destination.
`paused` suppresses the role and its alerts; `always_watched` bypasses owns
for the launcher's fixed ops/deploy/multi-coord rows. Timestamped sessions match the
launcher's prefix, and renamed sessions also match the last waiter holder's
session id. Other names are checked with `session-start owns NAME`: exit 1
skips the role, while exit 2 freezes its episodes. A failed inventory freezes
all identity-dependent episodes, including fixed watched roles.
Active drafts and unfinished briefs (no closing, open work, or handed-over
closing) come from records.

Watch resolves `session-start` on PATH, falling back to `../session/start`
relative to this script's resolved directory; both names and owns use that
executable. Likewise, `lease` on PATH takes precedence over sibling `../lease`.
A selected executable's failure is reported without trying another copy. Each
heartbeat's `inputs` object records the selected paths as `session-start` and
`lease`.

The private watch state retains compact condition facts across spool expiry: last
claim/lease activity and batch time, attempted ready tips, pending handovers and
acknowledgements, and unresolved delivery dispositions. It stores the needed
identities/times, never copies raw streams or context readings. This preserves
long-running conditions and the 4-hour lease threshold after raw inputs expire.
Successful delivery tombstones expire after 2 hours; lease facts disappear when
the live lease disappears.

Inputs are independent. A failed command, malformed reading or unavailable
records stream freezes dependent episodes; it never opens an alert on its own.
A heartbeat names failed inputs and skipped rules. Missing lease is a skipped
input. Builders come from `post/machines`; SSH pipes this version of the probe
into a login shell, with host-key updates disabled. The probe reads run
meta, completion TSV/markers, output mtime, task header, live heavy state, and the
last 2 hours of `queue`, `heavy`, `sessions`, `post` and `post-sent` in each
host's `~/src/fabrig/events/` spool. Hel8 reads its local spool. Rule input names
are `spool/queue`, `spool/heavy`, `spool/sessions`, `spool/post`, `spool/post-sent`;
SSH failures name both source and host and freeze dependent episodes. Absent
source directories are valid empty streams. Malformed sources fail independently.
Live heavy is necessary to prove a claim idle; an unavailable snapshot prevents
that inference. All SSH reads have timeouts and run concurrently.

Ready refs have no creation timestamp in `ls-remote`, so age means continuous
observation of the same tip. A new tip starts its clock again; historical
attempts for another tip do not hide it. Run medians use completed runs in the
available producer ledgers, grouped by effort. `minutes`, `median_multiplier`,
`median_min_samples` and `fallback_minutes` configure both run-hung conditions.
Lease activity requires explicit package/subject
keys or an event for a branch lent by that lease; unrelated coordinator activity
does not prove package activity. The sessions collector supplies spooled `handover-needed` events from
`session-context --fired --json`, including updates with the same
`first_fired`. Watch uses that first time for ordering and the lateness
clock: later firings do not reset it or reopen an acknowledged handover.
Legacy `context-hook` events remain supported. A context sample alone never
proves firing. Sessions' `files-current` projection and lead post subjects
starting with `files current` acknowledge handover using header metadata;
mail bodies are never read. An explicit successor/session-start also clears it.
The `post-sent` stream supplies send exits from the port's `sent.jsonl`
metadata; exit 2 alerts the sender and escalates to its supervisor; a later successful
row for the same message clears the condition. Existing run completion/told
evidence and post delivery events remain supported.


The private `~/.local/state/watch/state.json` has mode 0600, written to a sibling,
flushed and renamed under a process lock. Each `(rule, subject)` has one episode:
one first action, one escalation, and a close event after two successful clear
runs. A recurrence alerts again. Post exit 0 or 3 counts as delivered; failed
sends are retried. Remedies run once successfully, with at most one retry on
failure at the configured interval. Silent/dry-run remedies consume no attempts. There is no additional
global throttle: independent subjects must not suppress one another. Persisted
pending events form an outbox; local retries reuse stable event ids. All alert
and heartbeat events append to `~/src/fabrig/events/watch/YYYY-MM-DD.jsonl` on
hel8 through `event_spool.py`, with the same 2-hour retention and atomic source
locking as the collector. A failed spool write exits 2 with a reason and keeps
the outbox; success drains it. There are no git push deferrals or counters.
A heartbeat is due on the first poll, any alert transition, a change in failed
input names, or after `[watch] heartbeat_seconds` (900 by default). Changing only
an error's text does not trigger one. Quiet polls still persist evaluation state
and prune the watch spool. A normal run prints `watch: spooled N events`.
The pipeline-watch timer adds up to 60 seconds of random delay.
Like post itself, sending and local state
commit cannot be one transaction: a process death immediately after send and
before state persistence can repeat that send after restart.

Run `python3 -I -B tools/records/test_watch.py`. Tests use temporary HOME,
fake producer commands/SSH, and a local bare records origin. The existing
`test_record.py` and `test_record_collect.py` suites remain required.

For leads with `kind="codex"`, live state comes from their registered user unit,
independently of Claude and post waiters. For both Claude and Codex, `gone`
requires an unfinished part for the lead's area in an active, unpaused draft;
registry presence alone never requires a lead to run. Part `brief.md` and
`closing.toml` in records supply this predicate: no closing, open work, or
handed-over outcome means unfinished; a completed closing removes that
expectation, including after a `files current` post. Scratch `brief.md` and
`state.md` are not read by this rule; `files current` alone acknowledges
handover, not completion of remaining work. Codex liveness uses its user unit.
`deaf` means unread mail
older than the configured threshold while the unit is inactive: skip `post wake`
and send to the owner; an unresolved episode escalates to the coordinator. Failed unit queries freeze dependent
episodes. Codex `handover-needed` threshold events drive the same handover clock
and acknowledgements; the coordinator remains the lead's supervisor.

Replay retained lifecycle events from one host spool without invoking any producers or post:

```sh
python3 -I -B tools/records/replay_watch.py /path/to/events --day 2026-10-29 --day 2026-10-30
```

This uses historical completions as they become available, seeds medians from
older retained days, and rebuilds two-minute polls within each day's observed
watch window. Lifecycle events lack output modification times, inventory and
probe availability. The replay gives runs a synthetic watched owner and assumes
output never changed after start, so its count is an upper bound for that input
reconstruction, not confirmed true hangs. It cannot establish the exact number
of real episodes or their truth. `test_watch_replay.py` uses synthetic spools
and a temporary HOME to check boundaries and prevent future median leakage.

## Automatic mail repair

`[rules.deaf] remedy = true` enables the in-place Claude restart. Eligibility
requires one live session, explicit `status=idle`, lifecycle `done` (or legacy
idle activity without lifecycle), and matching saved cwd/full id. Read
`~/.claude/jobs/<short-id>/state.json` only to confirm the full id and cwd.
`working`, `blocked` and `status=waiting` are not idle. This file is an unstable CLI detail, so unknown
or mismatched id or cwd refuse action; no transcript or credential is needed.
Saved permission mode does not affect eligibility. The watch never adds,
removes or changes a permission flag; it passes none. Resume uses the
session’s own saved options.
The [CLI state reference](https://code.claude.com/docs/en/agent-view#read-session-state-from-a-script)
distinguishes lifecycle state from process activity.

From its cwd, stop the full id, wait up to `stop_timeout_seconds = 60` for
`claude agents --json --all` to confirm `stopped`, then run exactly
`claude --bg --resume FULLID PROMPT`, with no extra flags. The prompt asks the
reader to restart `post wait MAILBOX` in the background, `post read MAILBOX`,
and carry on. Check the returned full id. Stop any copy and record the failed
remedy; never resume on a stop timeout. A failed attempt retries once after
`retry_seconds = 120`; `max_attempts = 2` bounds attempts per episode.

`[rules.gone] remedy = true` launches eligible missing roles from their files,
using `session-start lead H AREA`, `coordinator H`, or `director`, only after
that exact launch's `--dry-run` succeeds. Paused, retired, unregistered and Codex
roles are never launched. Fixed infrastructure without a launcher remains an
unremedied reader. A resume failure retains its original id rather than
starting a fresh gone-role copy. `remedy` events carry the result and attempt.

Waiter reconciliation preserves every waiter record. It reports dead records,
and reports live orphans whose recorded session ended, or whose parent is pid 1
without a live session for the mailbox. `[rules."waiter orphan"] remedy = true`
allows SIGTERM only if another live waiter exists or the mailbox session is
gone. Recheck the PID's process start, actual `post wait` argv, sessions and
other waiters before signalling. No post state file is edited.

Unread report episodes key on mailbox, carrying all unread count, oldest age,
and the current Codex turn length (`events.jsonl` start time corroborated by
`turns.tsv`; unavailable is explicit). Handover episodes key on fired session
id; a stopped owner, successor, or `files current` within 30 minutes before
firing or after it clears them. A predecessor's explicitly identified ack
cannot acknowledge a successor's hook.

`watch.fabrig_remote` and `watch.records_remote` configure network origins;
`RECORDS_ORIGIN` overrides records. Git uses SSH ControlMaster auto,
ControlPersist 600, and ControlPath `STATE/ssh-%C`. Records main is checked
with `ls-remote`; unchanged origin/main avoids fetch. Dry runs use disposable
records and SSH state. No host URL is embedded in the watch code.
