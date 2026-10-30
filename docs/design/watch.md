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
to skip unowned or paused roles. Ops and s/deploy are always watched. An
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
The following are today's enabled defaults. Escalation time is measured from
episode opening, independently of a wake's outcome.

| Rule | Opens when | First action / owner | Escalate after |
|---|---|---|---|
| deaf | Live Claude session has no live waiter and unread mail older than 10 min; or inactive Codex owner has such mail | Wake Claude once; notify Codex owner without wake | 20 min |
| gone | Active coordinator or unfinished lead is absent/inactive | Notify subject's mailbox | 30 min |
| report unread | Completed run's report post is unread for 15 min and deaf does not cover it | Run owner | 15 min |
| run hung | Output unchanged for 60 min AND elapsed exceeds 3× effort median (at least 5 completions), or 90 min without enough samples | Run owner | 30 min |
| idle claim | No live run/heavy and no claim/run/heavy/precheck activity for 45 min | Holder | 45 min |
| unqueued | Same ready tip seen for 30 min without its attempt, or ready refs and no batch for 20 min | Ops | 30 min |
| lease stall | Holder has waiters and no package activity for 4 h, or oldest waiter exceeds 2 h | Holder | 4 h |
| handover late | Fired handover request older than 20 min with no successor or files-current acknowledgement | Session | 20 min |
| question due | Unanswered question passes deadline | Director | No higher tool destination |
| delivery failed | Send exit 2 without later success or completion told evidence | Sender / run owner | 20 min |

**The ladder follows the owner.** Leads escalate to their coordinator;
coordinators, ops and s/deploy escalate to the director. The director has no
supervisor. User contact belongs to the director. A gone alert posts to the
missing role first, then its supervisor; it does not restart sessions itself.

**Use precise evidence.** Lease activity must name a subject/package or a lent
branch; unrelated coordinator activity is insufficient. Handover lateness uses
the first fired time, never a sampled percentage or a later repeat firing.
Lead `files current` metadata and explicit successor/start evidence acknowledge
handover. Send failures use sent metadata, never subject or body contents.

## 4. Episodes, spooling and heartbeat

**Persist private episodes under a lock** by sibling rename. One subject must
not throttle another. Failed post sends retry; delivered exit 0 or 3 is accepted.
A successful clear poll counts toward closure only when dependencies succeeded.
Mail send and state persistence cannot be one transaction, so death immediately
after sending can repeat an action on restart.

**Alert-open, escalate, close and heartbeat append locally** to hel8's
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
writes spool events without mail or wake. Re-enabling posts catches up once per still-live
episode, with its original opening time; already-overdue episodes go directly
to the supervisor. Current defaults enable posts. Dry-run is different: it
persists no watch state or spool events and never sends.

## 5. Later

- Add the planned `login held` rule with its owner, evidence and ladder.
- Add an independent missing-heartbeat alarm for ops.
