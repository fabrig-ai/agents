# The stuck-work watch

2026-10-30. Owner: s/multi-coord. Code: `tools/records/watch` and
`tools/records/watch.toml`. Command reference: `tools/records/watch.md`.

## 1. In one page

- **Watch detects abandoned progress.** Sessions, mail, runs, slots, leases,
  branches and questions each have an owner and a timed escalation.
- **Live state and events are different evidence.** The launcher supplies
  identity and supervision; probes supply liveness and recent host-spool events;
  records supply durable draft and question facts.
  Missing evidence freezes dependent alerts instead of inventing a failure.
- **One episode per rule and subject.** Act once, escalate once, close after
  two successful clear polls, and permit a new episode on recurrence.
- **Every transition is an event.** A heartbeat exposes failed inputs and
  skipped rules. Ops owns noticing a missing watch heartbeat.

## 2. Inputs and identity

**Poll on hel8 every two minutes.** `tools/records/watch --once` evaluates one
poll; the declared `fleet/units/pipeline-watch.service` and timer drive it.
The installed name is `pipeline-watch`. `--dry-run --once` previews actions and
events without changing watch state or sending mail; its records pull uses a
disposable clone. Configuration is `tools/records/watch.toml`.

**Take owners from `tools/session/start names --json`.** Resolve aliases,
explicit prefixes and supervisors from that inventory, then use `owns NAME`
to skip unowned or paused roles. Ops, s/deploy and s/multi-coord are always watched; the latter matches
`s/multi-coord/<stamp>` and `s/multi-coord-next`. An
inventory error freezes all identity-dependent episodes. Leads are expected
only for unfinished parts in active drafts, not merely because registered.
A closing with open work or handed-over outcome still means unfinished.
Codex leads use registered user-unit state rather than Claude sessions/waiters.

**Read bounded live evidence.** Local inputs include Claude sessions, post
waiters and unread headers, claims, leases and ready refs. Hosts come from the
runtime `~/src/rust/tmp/post/machines`. The watch sends its own versioned Python
probe over SSH to read run metadata, completion markers/TSV, task headers,
output modification times, live heavy state and the last two hours of the
queue, heavy, sessions, post and post-sent spools. It reads no mail bodies or
run output contents. Host probes run concurrently with timeouts and strict SSH
host-key checking. An unavailable heavy probe prevents an idle-slot inference.

**Read recent events from host spools.** Hel8 reads its local
`~/src/fabrig/events/<source>/<UTC-day>.jsonl`; every other host returns the
same bounded streams through the existing SSH probe. The probe carries its
reader code, so no separate remote reader installation is required. Rule input
names are `spool/queue`, `spool/heavy`, `spool/sessions`, `spool/post` and
`spool/post-sent`. An absent source is empty; malformed sources or failed probes
name the source/host and freeze dependent episodes.

**Read durable expectations from records.** Draft briefs/closings establish part
expectations; director questions establish deadlines. A ready tip's age is the
time continuously observed at that exact tip, not its unobservable ref creation
time. Attempts for an older tip do not count. Raw-event retention is specified
in `docs/design/records.md`, section 4.

## 3. Rules and escalation

**Thresholds live in TOML.** Conditions use strictly older-than comparisons.
The following are today's enabled defaults. Mail-health escalation waits for
two failed remedies or more than 30 minutes after a remedy; an unremedied
reader (including a Codex owner in a long turn) gets one escalation after
30 minutes. Other rules measure escalation from episode opening.

| Rule | Opens when | First action / owner | Escalate after |
|---|---|---|---|
| deaf | Live Claude session has no live waiter and unread mail older than 10 min; or inactive Codex owner has such mail | Restart idle Claude with confirmed saved full id and cwd; Codex belongs to ops | 2 failures or >30 min after remedy |
| gone | Active coordinator, director or unfinished lead is absent/inactive | Launcher dry run, then restart from role files; never Codex, paused or retired roles | 2 failures or >30 min after remedy |
| report unread | Completed run's report post is unread for 15 min and deaf does not cover it | One episode per reader, all unread count/oldest age/current turn length | >30 min, once |
| run hung | Output unchanged for 60 min AND elapsed exceeds 3× effort median (at least 5 completions), or 90 min without enough samples | Run owner | 30 min |
| idle claim | No live run/heavy and no claim/run/heavy/precheck activity for 45 min | Holder | 45 min |
| unqueued | Same ready tip seen for 30 min without its attempt, or ready refs and no batch for 20 min | Ops | 30 min |
| lease stall | Holder has waiters and no package activity for 4 h, or oldest waiter exceeds 2 h | Holder | 4 h |
| handover late | Fired handover request older than 20 min with no successor or files-current acknowledgement | Session | 20 min |
| question due | Unanswered question passes deadline | Director | No higher tool destination |
| waiter orphan | Waiter's session ended, or parent is pid 1 without a live mailbox session | Report; SIGTERM only with another live waiter or a gone mailbox session | Report only |
| waiter dead | Waiter record has no live process | Report; never edit post state | Report only |
| delivery failed | Send exit 2 without later success or completion told evidence | Sender / run owner | 20 min |

**The ladder follows the owner.** Leads escalate to their coordinator;
coordinators, ops and s/deploy escalate to the director. The director has no
supervisor. User contact belongs to the director. A gone remedy uses the launcher
from the role files. Leads escalate to their coordinator; only coordinators,
ops, s/deploy and s/multi-coord can escalate directly to the director.

**Use precise evidence.** Lease activity must name a subject/package or a lent
branch; unrelated coordinator activity is insufficient. Handover lateness uses
the first fired time, never a sampled percentage or a later repeat firing.
Handover episodes key on the fired session id. They clear when that session
or owner ends, a successor holds the mailbox, or that session posted
`files current` in the preceding 30 minutes or after firing. Old-owner context
readings cannot leave an alert on the successor. Lead `files current` metadata
and explicit successor/start evidence acknowledge handover. Send failures use sent metadata, never subject or body contents.

**Repair deaf Claude sessions in place.** Only explicit `status=idle` with
lifecycle `done` (or legacy idle activity without a lifecycle field) is eligible.
`working` and `blocked` are not proof of idleness; `waiting` requires input.
Read the job state only to confirm the full matching session id and cwd from
`~/.claude/jobs/<first-eight-id-characters>/state.json` (under
`CLAUDE_CONFIG_DIR` when set). Refuse missing, unknown or mismatched id or cwd.
Saved permission mode does not affect eligibility. Recheck activity and saved
id/cwd immediately before action. From that cwd, `claude stop FULLID`, poll `claude agents --json --all` for `stopped`
for at most 60 seconds, then and only then
`claude --bg --resume FULLID "Restart your post wait MAILBOX in the background, post read MAILBOX, and carry on."`.
The watch never adds, removes or changes a permission flag; it passes none.
Resume uses the session’s own saved options. No additional flags are passed.
A mismatching returned id is a copy: stop it,
record the failed result and leave the episode open. Orphan reconciliation
handles any waiter it leaves behind, with fresh process/session checks before
SIGTERM. Missing stop confirmation never permits resume.

**Remedies run once on success, with one retry on failure at the next interval.**
The retry also handles the original becoming stopped after a failed resume;
it must not create a fresh session through the launcher. Launch gone leads
with `session-start lead H AREA`, coordinators with `session-start coordinator H`,
and director with `session-start director`; require the identical command's
`--dry-run` to pass first. Registry absence/retirement, pause state and Codex
ownership forbid launching. Per-remedy switches, attempt limits, retry and stop
poll intervals live in TOML. Every attempted result is a `remedy` event.

**Share git connections and fetch only a changed records main.** All watch
network git calls inherit SSH `ControlMaster=auto`, `ControlPersist=600` and a
`ControlPath` under watch state (a disposable directory in dry run). Compare
records `ls-remote` with the local origin/main before calling `record pull`.
`watch.toml` supplies the records/fabrig origins; RECORDS_ORIGIN overrides the
records origin for isolated fixtures and installations. The origins can move
to Forgejo without a code change.

## 4. Episodes, spooling and heartbeat

**Persist private episodes under a lock** by sibling rename. One subject must
not throttle another. Failed post sends retry; delivered exit 0 or 3 is accepted.
A successful clear poll counts toward closure only when dependencies succeeded.
Mail send and state persistence cannot be one transaction, so death immediately
after sending can repeat an action on restart.

**Alert-open, remedy (with result), escalate, close and heartbeat append locally** to hel8's
`~/src/fabrig/events/watch/<UTC-day>.jsonl`. The shared spool writer uses the
same source lock, atomic day replacement and two-hour pruning as the collectors.
Stable event ids and a pending outbox preserve local retries. A spool failure
exits 2 with a reason and keeps pending events; success drains them. There are
no git push deferrals, origin-confirmation steps or publication counters here.
Quiet polls also prune the watch spool.

**Keep compact condition facts beyond raw-event expiry.** Private watch state
retains last claim/lease activity and batch time, attempted ready tips,
unresolved handovers and acknowledgements, and delivery dispositions. Store
needed identities, timestamps and joins rather than raw streams, mail subjects
or context samples. This keeps unresolved alerts and the four-hour lease clock
intact when source events age out. Successful delivery tombstones expire after
two hours; lease facts disappear with the live lease.

**A quiet heartbeat is due every 900 seconds,** observed at the next poll.
Alert transitions and failed-input-set changes also make it due. Heartbeats
report selected executables and failed/skipped inputs. A changing error string
alone does not force a heartbeat. Local episode state is saved on quiet polls.

**Silent mode preserves evidence.** Disabling `alerts.post` evaluates and
writes spool events without mail or remedies. `--no-post --no-remedy` also selects this mode;
combine with `--dry-run --once` for a live read without state or spool writes. Re-enabling posts catches up once per still-live
episode, with its original opening time; already-overdue unremedied episodes go directly
to the supervisor. A suppressed remedy consumes no attempt; enabling actions
performs the remedy first and starts its escalation clock. Current defaults enable posts. Dry-run is different: it
persists no watch state or spool events and never sends.

## 5. Later

- Add the planned `login held` rule with its owner, evidence and ladder.
- Add an independent missing-heartbeat alarm for ops.
