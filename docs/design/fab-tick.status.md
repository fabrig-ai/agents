# fab-tick status

2026-11-01. Contract: `docs/design/fab-tick.md`. Split from `docs/design/fab.status.md`.

## Present

- **Runs:** `fab run start|status|collect` with worktrees for this repository
  and slots for fabrig (claim, switch, release with the sweep at collect);
  `fab codex` launches Codex as user units (live on hetzner6 since 20:30Z;
  codex-run is no longer called). A failed start gives back what it took.
- **The dispatcher:** `fab tick PLAN_DIR` collects, lands, starts and parks;
  run by hand, live since 20:27Z.

## Gaps and departures

- **A failed task run parks for the answerer** (11-01, findings-loop): `fab.run.collect`
  logs a failed implement, repair or rebase run's report as a `question.asked` with `park`
  (fab-calls.md 2), so it queues at once; it parked unheard before.
- **The flow is a skeleton:** `fab/flow.py` holds 4's target, calm and
  measure, and `fab.dispatch.places` and `decide` take a `calm` argument they
  do not use yet. The task `flow` fills them after `gates-tick`; until then
  the tick fills every builder's `places` and never passes them.
- **Several plans are a skeleton:** `fab/drafts.py` holds 5's rules:
  which runs in flight a draft owns, the strays no plan owns, a plan's
  design calls up to its flow target, the calm a plan leaves the next, and
  a call's unit named by its subject. The task `drafts` fills it.
  `plans-tick` makes one tick take every plan in `FAB_HOME/plans`, after
  `designer-tick`, `channel-tick` and `accounting`. Until it lands, `fab
  tick PLAN_DIR` ticks one plan and collects every run in flight. It
  starts one skeleton call at a time (one contract call beside it once
  `designer-tick` lands), in units numbered by role. Its answer and review
  limits, and the review's last-review time, count every draft's calls,
  and its queue import reads from the log's newest record of any draft.
- **The buffer's order is a skeleton:** `fab/buffer.py` holds 7's
  groups and the sort, `fab.plan.Task` its `consolidation` field, and
  `fab/roles/reviewer.md` asks the review call to mark its specs with it.
  The task `buffer-order` fills the sort, reads the header and makes
  `decide` start runs in the sort's order, after `receipts-ready` and
  `plans-tick`. Until then `decide` starts rejected tasks first, then
  runnable ones in their specs' order, and a spec's `consolidation` key is
  ignored.
- **Events are a skeleton:** `fab/wake.py` holds 6's want file, the
  wake from any machine, the round's close (the lost-event note, the tick
  waking itself) and the tick's four units; `fab.hosts.this` names this
  machine's entry. The task `wake` fills the module, registers `fab wake`
  and makes the wakers wake: a Codex unit's ExecStopPost, a call's end, `fab
  land`, `fab page answer` and the queue's cycle. `wake-tick` makes the tick
  take the want, wait for its lock as an event tick, close each round, and
  fills `fab wake --install`, after `buffer-order` since it changes
  `fab/dispatch.py`. Until both land the transient `fab-tick.timer` ticks
  every 2 minutes and wants pile up unread in `FAB_HOME/tick.want`. Once
  they land, `fab wake --install` on hel8 starts the units, and each
  builder needs ssh to hel8 for its runs' wakes.
- **Design waits for implementation:** `fab.dispatch.decide` makes a part
  eligible only when every task of its needs has landed, and sizes the
  buffer against nominal places; section 2 now says otherwise, and the task
  `design-eligibility` brings the code to it.
