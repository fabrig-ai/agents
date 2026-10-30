# The stuck-work watch

2026-10-30. Owner: s/multi-coord. Code: `tools/records/watch` and
`tools/records/watch.toml`. Command reference: `tools/records/watch.md`.

## 1. In one page

- **Watch detects abandoned progress.** Sessions, mail, runs, slots, leases,
  branches and questions each have an owner and a timed escalation.
- **Live state and events are different evidence.** The launcher supplies
  identity and supervision; probes supply liveness; records supply history.
  Missing evidence freezes dependent alerts instead of inventing a failure.
- **One episode per rule and subject.** Act once, escalate once, close after
  two successful clear polls, and permit a new episode on recurrence.
- **Every transition is an event.** A heartbeat exposes failed inputs and
  publication trouble. Ops owns noticing a missing watch heartbeat.

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
output modification times and live heavy state. It reads no mail bodies or
run output contents. Host probes run concurrently with timeouts and strict SSH
host-key checking. An unavailable heavy probe prevents an idle-slot inference.

**Read historical events from records today.** Queue, heavy, sessions, post and
post-sent streams join live observations. Draft briefs/closings establish part
expectations; director questions establish deadlines. A ready tip's age is the
time continuously observed at that exact tip, not its unobservable ref creation
time. Attempts for an older tip do not count. The future host-spool input is
tracked in `docs/design/watch.status.md` and `docs/design/records.md`, section 4.

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

## 4. Episodes, publication and heartbeat

**Persist private episodes under a lock** by sibling rename. One subject must
not throttle another. Failed post sends retry; delivered exit 0 or 3 is accepted.
A successful clear poll counts toward closure only when dependencies succeeded.
Mail send and state persistence cannot be one transaction, so death immediately
after sending can repeat an action on restart.

**Alert-open, escalate and close publish immediately** through the sibling
records writer's append command. Stable event ids and a pending outbox preserve
publication across retries. The first five consecutive deferred publications
remain successful polls with diagnostics; the sixth fails until recovery.
Real publication errors fail immediately. Confirm origin contains the commit
before draining pending events.

**A quiet heartbeat is due every 900 seconds,** observed at the next poll.
Alert transitions, failed-input-set changes and publication-deferral changes
also make it due. Heartbeats report selected executables, failed/skipped inputs
and preceding watch/collector publication status. A changing error string alone
does not force publication. Local episode state is still saved on quiet polls.

**Silent mode preserves evidence.** Disabling `alerts.post` evaluates and
publishes without mail or wake. Re-enabling posts catches up once per still-live
episode, with its original opening time; already-overdue episodes go directly
to the supervisor. Current defaults enable posts. Dry-run is different: it
persists nothing and never publishes or sends.

## 5. Later

- Add the planned `login held` rule with its owner, evidence and ladder.
- Read raw events from each host's spool after the records migration.
- Add an independent missing-heartbeat alarm for ops.
