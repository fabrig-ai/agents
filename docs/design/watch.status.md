# Watch status

2026-10-30. Owner: s/multi-coord. Baseline: origin/main `95d8351`.
Contract: `docs/design/watch.md`, sections 2–4.

## Present

- All ten rules, enabled posts, episodes, clear confirmation, silent catch-up,
  SSH probes, fired-marker events and Codex-owner liveness are implemented.
- The hel8 two-minute service/timer is declared in `fleet/units/`; heartbeat
  interval is 900 seconds in `tools/records/watch.toml`. No deployment was
  performed or live service state checked by this docs task.

## Plan differences and remaining gaps

- **Run hung follows code and tuned TOML.** The old director-records plan used
  unchanged output for 30 minutes OR elapsed above 3× median. Today's code
  requires unchanged output for 60 minutes AND elapsed above the median limit,
  using at least five completions or a 90-minute fallback. The design reflects
  this implemented rule; the early proposed rule is not an operational promise.
- **Gone notifies before escalation.** The old plan sent straight to the
  supervisor and described restarting. Code first posts the subject's mailbox,
  then the inventory supervisor after 30 minutes. It launches nothing.
- **Escalation follows inventory.** The early plan hard-coded ops for idle
  claims, director for lease stalls, and ops for delivery failures. Code uses
  the actual owner's supervisor. The design follows code.
- **Events remain in records git.** SSH probes provide live run/heavy state;
  they do not yet fetch host-spool events. Records' migration to a two-hour
  spool is `docs/design/records.status.md`.
- **Part expectations need lifecycle records.** Gone uses committed briefs
  and closings, while the launcher does not yet write them. It deliberately
  does not infer unfinished work from scratch files or registry presence.
- **Heartbeat is emitted, not independently supervised here.** The plan assigns
  missing-heartbeat detection to ops. This checkout has no separate watchdog
  that implements that alarm.
- **No login-held rule exists.** It remains Later, with no invented threshold.
- **Replay has limits.** `tools/records/replay_watch.py` reconstructs retained
  lifecycle evidence with synthetic quiet-output assumptions; it cannot prove
  actual historical hangs or true-positive rates. Fixture tests are evidence
  of behavior, not a fleet acceptance run.

## Verification

`tools/records/test_watch.py` and `tools/records/test_watch_replay.py` use
synthetic producers and temporary HOME. `bash tools/check.sh` runs both.
