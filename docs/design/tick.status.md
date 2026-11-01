# tick status

2026-11-01. Contract: `docs/design/tick.md`. Split from `docs/design/fab.status.md`.

## Present

- **Runs:** `fab run start|status|collect` with worktrees for this repository
  and slots for fabrig (claim, switch, release with the sweep at collect);
  `fab codex` launches Codex as user units (live on hetzner6 since 20:30Z;
  codex-run is no longer called). A failed start gives back what it took.
  Before a start's builder work, its fab install follows the running
  dispatcher's commit under `install.lock`, only forward; a sync failure
  notes stderr and the start continues. `FAB_HOME/install.pinned`, owned
  by a person or replay setup, skips sync before the fetch under the same
  lock and notes `install pinned`. Dispatcher hosts are skipped.
  Services still move and restart only with `bin/install.sh`.
- **Reruns start from the right place** (3; plan `docs/plan/dogfood-faults`,
  retired 11-01; 53dfbf6): `fab.run._prepare_and_launch` probes
  `refs/remotes/origin/<branch>` once after the fetch (in the slot, or the
  repository's clone for worktrees). In a slot or a worktree, an implement
  or repair start uses `origin/<branch>` when it exists and the task's base
  when it does not; an implement continuation merges the base in and aborts
  a conflicting merge for the run to resolve; review and rebase start from
  the base. Before it, an `Infra:` rerun that had pushed nothing failed its
  start every tick, and a worktree implement rerun dropped its pushed work.
  Tested with fake runners (`test_run.py`, `test_dispatch.py`'s
  `OptimisticStartTest`).
- **A failed task run parks for the answerer** (11-01, findings-loop; 44f2a0a):
  `fab.run.collect` logs a failed implement, repair or rebase run's report as a
  `question.asked` with `park` (calls.md 2), so it queues at once; it parked
  unheard before.
- **The dispatcher:** `fab tick PLAN_DIR` collects, lands, starts and parks;
  run by hand, live since 20:27Z.
- **A ladder plan in the tick** (qa.md 2; plan findings-loop, retired
  11-01): `[ladder]` and `[[rung]]` in plan.toml and `triage` reserved (1);
  each round a plan with rungs records ended triage calls' decisions, then
  `rung.passed`, then readies its backlog branch, before `decide`, and
  starts the triage call when due; `fab qa result` wakes the tick
  (`qa <walk>`). Tested with fake runners and fixture logs.
- **A ladder plan's repairs in the tick** (qa.md 2, 6; plan findings-repair,
  retired 11-01): after the refusal settlements, `red_actions` and
  `finding_actions` give one `examine-fix`/`remedy-fix` pair, which
  `_fix_steps` sends to each kind's start or settle; the plan's tasks are
  joined with its finding repairs; `finding.settled` wakes the tick again.
  Tested with fake runners and fixture logs.
- **The flow grows** (`docs/design/tick.md`, 4; since 10-30):
  `fab.flow.target` folds first-attempt landings from full windows, rejections
  and infra outcomes; `calm` and `measure` check builders' load and waits.
  `fab.dispatch._round` measures once per builder; `decide` caps queue-plan
  starts at the target and prints it, and `places` allows one extra run on
  a calm builder below its slot limit. Since 10-31, `decide` starts the
  target at builders' places; integration plans use that capacity directly.
- **Several plans share a tick** (`docs/design/tick.md`, 5; since 10-31):
  `fab.dispatch._round` takes `fab.channel.plan_dirs`' listed then named
  plans under `tick`'s lock; `_checkout` shares fetches, `_load_plans` skips
  retired plans and reports failed loads, and `_import_queue` reads from
  the oldest loaded draft's cursor. Each `_tick_loaded` sees fresh events;
  `fab.drafts.owned` scopes collection, `strays` leaves unowned runs until
  last, and `spend` spends a builder's calm extra once per round.
  `fab.dispatch.call_actions` scopes call limits and review times by draft;
  `_part_calls` uses `fab.drafts.design_calls` to share the flow target
  between parallel skeleton and contract calls. `_call` uses
  `fab.drafts.unit` to name units by role and subject, and since 11-01
  (dogfood-faults; a074df1) passes `--setenv=FAB_HOME=<fab.log.home()>`,
  so a tick with another home (a replay's) starts calls that write to it.
- **The buffer's order** (`docs/design/tick.md`, 7; since 10-31):
  `fab.buffer.group` and `order` put consolidations before refusals' repairs
  and rebases, then contracts, then slice tasks, breaking ties by slice,
  part and spec order. `fab.plan.parse_task` reads `consolidation` and
  `fab.dispatch.decide` applies the sort before `_run_starts`; an infra
  rerun alone keeps its part's place. Red tasks and finding repairs also
  enter the repair group through `fab.buffer.group` (11-01).
- **Events drive the tick** (`docs/design/tick.md`, 6; since 10-31):
  `fab.wake.want`, `wake` and `take` append reasons locally or over ssh and
  coalesce them by renaming the want before reading it.
  `fab.dispatch.tick` takes it under its lock, waits for the lock on event
  ticks, and closes every round with `fab.wake.settle`: lost-event notes
  on backstop ticks and self-wakes bounded to five rounds. `fab.wake.main`
  supplies `fab wake`; `units` and `install` supply the four event and
  10-minute backstop units, enable them and stop the old 2-minute timer.
  Wakers are wired in `fab.codex.start` (ExecStopPost), `fab.calls.start`,
  `fab.land.main`, `fab.channel.answer` and `clear`, `fab.queue.Queue.cycle`
  (with the callback supplied by `main`), `fab.after_landing.AfterLanding.check`
  and `fab.walks.result`.
- **Design follows designed needs** (`docs/design/tick.md`, 2; since
  10-31): `fab.dispatch.decide` measures the ready buffer against the
  current flow target; `_design_action` accepts designed or done needs,
  requires done for `needs_landed` and probes, and excludes parts held by
  unanswered plan questions. Tasks still wait for their own needs to land.

## Gaps and departures

- **`fab draft start` is not built** (`docs/design/tick.md`, 7):
  `fab.cli.main` dispatches through `COMMANDS`, which has no `draft`
  command. Intake still starts the cut by hand through `fab.calls.main`.
