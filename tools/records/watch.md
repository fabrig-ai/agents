# Pipeline watch

`tools/records/watch --once` evaluates section 3b of `director-records.md`.
The hel8 `pipeline-watch.timer` runs `pipeline-watch.service` every two minutes,
using the release's `tools/records/watch` executable. The installed command name
is reserved as `pipeline-watch` so it does not shadow procps `watch`.
Without `--once` the tool repeats every 120 seconds.
`watch --dry-run --once` prints the exact proposed post commands, bounded
metadata evidence and JSONL publication. It never calls send, wake or append,
changes the watch state, or advances the live records clone. Its one `record
pull` uses a disposable clone, deleted on exit. All publications use the
sibling `record` executable from this checkout. No legacy code is imported.

`watch.toml` enables `[alerts] post = true`. Setting it to false still evaluates
conditions, persists episodes, and publishes alert events and heartbeats, while
logging proposed commands without sending or waking. Silent episodes carry
their opening time. On enabling posts, only episodes confirmed active by fresh,
successful inputs receive a catch-up, once each, marked
`(was silent since <time>)`. Cleared conditions do not post while awaiting their
second clear poll. An overdue catch-up goes directly to the supervisor and
satisfies escalation; otherwise it goes to the owner and the normal escalation
clock continues. Failed sends retry. Legacy silent state migrates using each
episode's original opening time, even if its suppressed actions were already
marked handled. Suppressed historical events in the publication outbox never
replay mailbox actions. Unlike `--dry-run`, silent mode updates state and records.

`watch.toml` enables each of the ten rules and holds every timing threshold.
Conditions use strict "older than" comparisons; escalation is due at its
interval after opening, regardless of the wake result. For escalations whose
interval is unspecified in 3b, the defaults use the condition interval (report
15, run 30, claim 45, ready 30, lease 240, handover 20 minutes); delivery uses
20 minutes. These values are adjustable independently. Question due posts only
to director; the director batches the question to the user.

| Rule | Evidence / first destination | Escalation |
|---|---|---|
| deaf | live session, dead/missing waiter, mail mtime >10m; wake once | supervisor, 20m |
| gone | registered active draft or unfinished lead part, absent session; owner | supervisor, 30m |
| report unread | completed run id in codex-run post header, mtime >15m; owner, unless deaf covers it | supervisor |
| run hung | output `events.jsonl` mtime >60m AND elapsed >3× median of at least 5 completed runs at that effort (else >90m); owner | supervisor |
| idle claim | >45m since claim or latest run/heavy/precheck activity, with no live run/heavy; holder | supervisor |
| unqueued | unchanged ready tip observed >30m with no attempt for that tip, or >20m without a batch while refs exist; ops | supervisor |
| lease stall | waiters and >4h without package events, or waiter >2h; holder | supervisor |
| handover late | >20m after recorded context hook without successor or files-current metadata; session | supervisor |
| question due | unanswered question past its deadline; director | director handles the user |
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
for the launcher's fixed ops/deploy rows. Timestamped sessions match the
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

Inputs are independent. A failed command, malformed reading or unavailable
records stream freezes dependent episodes; it never opens an alert on its own.
A heartbeat names failed inputs and skipped rules. Missing lease is a skipped
input. Builders come from `post/machines`; SSH pipes this version of the probe
into a login shell, with host-key updates disabled. The probe reads only run
meta, completion TSV/markers, output mtime, task header, and live heavy state.
Live heavy is necessary to prove a claim idle; an unavailable snapshot prevents
that inference. All SSH reads have timeouts and run concurrently.

Ready refs have no creation timestamp in `ls-remote`, so age means continuous
observation of the same tip. A new tip starts its clock again; historical
attempts for another tip do not hide it. Run medians use completed runs in the
available producer ledgers, grouped by effort. `minutes`, `median_multiplier`,
`median_min_samples` and `fallback_minutes` configure both run-hung conditions.
Lease activity requires explicit package/subject
keys or an event for a branch lent by that lease; unrelated coordinator activity
does not prove package activity. The sessions collector supplies durable `handover-needed` events from
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
sends are retried, while wake is attempted only once. There is no additional
global throttle: independent subjects must not suppress one another. Persisted
pending events form an outbox; append retries reuse stable event ids. All
alert-open/escalate/close events publish immediately through `record append --as
watch watch hel8`, with owner, supervisor and available join keys. A heartbeat
publishes at most once per `[watch] heartbeat_seconds` (900 seconds by default),
unless an alert opens, escalates or closes, or the set of failed input names
changes, including recovery. Changing only an error's text does not trigger one.
Changes in watch's publication-deferral count also make a heartbeat due.
The first run publishes a heartbeat. The two-minute poll observes the fifteen-
minute threshold on the next run (normally sixteen minutes). Each run still
persists its evaluation state. Events and any pending retries share one append;
quiet runs with an empty outbox do not append. Record makes up to five attempts
on push races, pausing a random 1–5 seconds between tries. At most one push
succeeds per run; retries cost only rejected attempts. Exhaustion or a rebase
conflict retains pending events and prints `watch: deferred (k/6): <record's reason>`.
State counts consecutive deferrals in `deferrals`: the first five exit 0, the
sixth and later exit 2. Successful publication or a real publication error resets
the count; real failures exit 2 immediately. Error and deferral lines include
record's stderr. A confirmed publication prints `watch: published N events`;
empty runs print `published 0 events`. Pending events drain only after record
fetches origin and confirms that it contains the commit, even after a lost
acknowledgement.

Heartbeat `inputs.publication` exposes watch's preceding deferral count and
reason, and `inputs.record-collect` exposes each collector's publication status
and `deferrals`. A change in watch's count also makes a heartbeat due. These are
snapshots taken before the current publication attempt; queued heartbeats are
never rewritten during a retry. Reasons in heartbeat inputs are capped at 1024
characters, and automatic record errors omit the saved event payload to avoid
embedding earlier heartbeats recursively. The pipeline-watch timer adds up to 60
seconds of random delay.
`watch` is an append-only writer. Like post itself, sending and local state
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

Replay retained lifecycle records without invoking any producers or post:

```sh
python3 -I -B tools/records/replay_watch.py /path/to/records --day 2026-10-29 --day 2026-10-30
```

This uses historical completions as they become available, seeds medians from
older retained days, and rebuilds two-minute polls within each day's observed
watch window. Lifecycle events lack output modification times, inventory and
probe availability. The replay gives runs a synthetic watched owner and assumes
output never changed after start, so its count is an upper bound for that input
reconstruction, not confirmed true hangs. It cannot establish the exact number
of real episodes or their truth. `test_watch_replay.py` uses synthetic records
and a temporary HOME to check boundaries and prevent future median leakage.
