# Watch status

2026-10-30. Owner: s/multi-coord. Watch-health work stacks on `mc/gate-cut`.
Contract: `docs/design/watch.md`, sections 2–4.

## Present

- Decision 0025 mail health repairs are implemented: fixed s/multi-coord
  inventory, idle/saved-bypass gated stop-confirm-resume, exact id/copy checks,
  launcher dry-run-before-start, one retry, remedy result events, safe orphan
  cleanup, and report-only dead waiter records.
- Mail reports open one episode per reader, with unread count/oldest age and
  current turn length. Escalation waits for two remedy failures or more than
  30 minutes after remedy; readers without a remedy escalate once after 30
  minutes. Only coordinator/infrastructure subjects route to director.
- Handovers key on session id and clear on owner exit, successor or a matching
  files-current acknowledgement (including the preceding 30 minutes).
- Network git uses configured origins and a shared SSH control socket; records
  fetch occurs only when main changed. This branch changes no installed service.

- All original ten rules plus orphan/dead waiter reconciliation, enabled posts, episodes, clear confirmation, silent catch-up,
  SSH probes, fired-marker events and Codex-owner liveness are implemented.
- Raw rule inputs come from the local and SSH-probed host spools, bounded to
  two hours. Failed inputs name their source and host. Alerts and heartbeats
  append to hel8's watch spool with atomic pruning; git publication/deferral
  paths are gone. Compact condition facts retain long-lived rule behavior across
  spool expiry, and saved episode dependencies migrate to spool input names.
- Replay reads a single-host spool directory.
- The hel8 two-minute service/timer is declared in `fleet/units/`; heartbeat
  interval is 900 seconds in `tools/records/watch.toml`. No deployment was
  performed or live service state checked by this rebase/docs task.

## Plan differences and remaining gaps

- **Run hung follows code and tuned TOML.** The old director-records plan used
  unchanged output for 30 minutes OR elapsed above 3× median. Today's code
  requires unchanged output for 60 minutes AND elapsed above the median limit,
  using at least five completions or a 90-minute fallback. The design reflects
  this implemented rule; the early proposed rule is not an operational promise.
- **Escalation follows inventory.** The early plan hard-coded ops for idle
  claims, director for lease stalls, and ops for delivery failures. Code uses
  the actual owner's supervisor. The design follows code.
- **Part expectations need lifecycle records.** Gone uses committed briefs
  and closings, while the launcher does not yet write them. It deliberately
  does not infer unfinished work from scratch files or registry presence.
- **Heartbeat is emitted, not independently supervised here.** The plan assigns
  missing-heartbeat detection to ops. This checkout has no separate watchdog
  that implements that alarm.
- **No login-held rule exists.** It remains Later, with no invented threshold.
- **Replay has limits.** `tools/records/replay_watch.py` reconstructs retained
  spooled lifecycle evidence with synthetic quiet-output assumptions; it cannot prove
  actual historical hangs or true-positive rates. Fixture tests are evidence
  of behavior, not a fleet acceptance run.

## Verification

`tools/records/test_watch.py`, `tools/records/test_watch_periodic.py` and
`tools/records/test_watch_replay.py` use
synthetic producers and temporary HOME. `bash tools/check.sh` runs both.
