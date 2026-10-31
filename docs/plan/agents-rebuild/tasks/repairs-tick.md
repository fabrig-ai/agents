+++
id = "repairs-tick"
part = "foreman-repairs"
kind = "feature"
needs = ["repairs", "foreman-tick"]
files = ["fab/dispatch.py", "fab/state.py", "fab/run.py", "fab/tests/test_dispatch.py", "fab/tests/test_state.py", "fab/tests/test_run.py"]
effort = "high"
minutes = 45
+++
# The tick sends each refusal to the foreman before a repair or rebase run

Today a refused task gets a repair or rebase run at once, its brief quoting
the refusal. From this change on, the refusal first gets a foreman run
(`fab.repairs`, filled by `repairs`). Its verdict decides what follows: a
fix lands as a section of the spec and goes into the next run's brief; a
retry sends the tip back to the landing unchanged, with no run; a foreman
that cannot say leaves the run to start as today. Update the docstrings of
every function you change to say what it now does. Design:
`docs/design/fab.md`, 13.1; the events in section 3.

## What to build

- **`fab.dispatch.repair_actions(tasks, events)`,** pure, as its docstring
  says: examine for a refusal at the foreman, remedy for a decided one.
- **`fab.dispatch.decide`, step 3:** a task with an open refusal
  (`fab.repairs.refusals(tasks, events)`) takes a start or a park only when
  the refusal is settled with verdict fix or none, or is a fallback; at the
  foreman, deciding or decided it takes neither, whatever the target and
  the places. A settled retry folds as done (below), so step 2 lands or
  readies it. A task with no open refusal starts as today. A start whose
  task's open refusal is settled fix carries `rejection={**<the
  branch.rejected record>, "section": <the refusal's section>}`; the kind
  still comes from `_start_kind`, rebase for a step in
  `fab.repairs.REBASE_STEPS`.
- **`fab.dispatch.tick`:** after decide's actions, the foreman's and the
  refusals' actions are computed from one read of the log, foreman_actions
  first, then repair_actions, and taken in that order before call_actions,
  which reads the log as it stands after them. Each body is a private
  module-level function, as the others are:
  - examine: the refusal is recomputed from the log, the task's open one in
    state foreman, else a ValueError. The builder is `_builder`'s (most free
    places, even at none, ties by name). Start it with
    `fab.repairs.start(refusal, tasks[<task>], host, log.read(log_path),
    sh=sh, log_path=log_path)`; the printed detail is `<step> <host>`.
  - remedy: the refusal is recomputed the same way, in state decided with
    foreman equal to the action's run. The report is
    FAB_HOME/runs/<foreman run>/report.md (fab.run.collect's copy; an
    unreadable one is the empty report). `fab.repairs.remedy(refusal,
    report)` gives the verdict, reason and body.
    - fix: the section is `fab.repairs.section(refusal, day=<today, UTC,
      YYYY-MM-DD>, run_id=<foreman run>, body=body)`; the branch is
      `fab.repairs.commit(refusal, task, section, <the plan's checkout
      root>, run_id=<foreman run>, sh=sh)`, landed through `_land_branch`
      when not None.
    - retry and none: nothing is committed.
    Then log `refusal.settled` (task, run: the foreman run, verdict,
    reason, branch: the landed branch or "", section: the fix's section or
    ""). Any failure logs no `refusal.settled`: the refusal stays decided
    and the next tick tries again. The printed detail is `<verdict>
    <reason>`. The plan's checkout root is found as `_settle` finds it;
    make one private function of it for both.
  - `Action.kind`'s comment already lists examine and remedy.
- **`fab.state.fold`:** a `refusal.settled` with verdict retry makes its
  task done (branch and tip unchanged), so decide lands it again (this
  repository) or readies it again, which runs `fab queue untry` for the
  same tip (`_ready`, unchanged). Other verdicts change no status.
- **`fab.run.brief`:** a rejection with a non-empty `section` puts that
  text, verbatim and followed by one blank line, after the run facts and
  before `## The landing refused this branch`. Its checkout is the branch,
  whose spec does not hold the section.

## Acceptance

- `fab/tests/test_dispatch.py`, building refusals with the builders of
  `fab/tests/test_repairs.py` (import them):
  - `repair_actions` as a pure function: each state's action, their order,
    tasks of another plan left out;
  - `decide`: no start and no park for a refused task at the foreman,
    deciding or decided, even with MAX_RUNS runs; a start after a settled
    fix, carrying the section in its rejection; after none and a fallback,
    a start with the record alone; rebase for a conflict; a settled retry
    lands (repo agents) or readies (fabrig) the branch.
  - `tick` with `support.FakeRunner` and patched `fab.repairs.start`,
    `fab.repairs.commit` and `fab.land.main` (record their calls):
    - a gate refusal starts its foreman in the same tick, on the builder
      with most free places, even at none, and no repair run;
    - a decided fix lands the spec branch and logs refusal.settled with the
      section, and the next tick starts the repair run with the section in
      its brief;
    - commit returning None logs refusal.settled without a landing;
    - a refused landing logs a note and no refusal.settled, and the next
      tick remedies again;
    - a retry logs refusal.settled, and the next tick lands the branch again;
    - none and an unreadable report log refusal.settled, and the next tick
      starts the repair run with the refusal alone;
    - foreman actions before refusal actions, both before call actions.
- `fab/tests/test_state.py`: a retry settlement makes a rejected task done
  with its branch; fix and none leave it rejected.
- `fab/tests/test_run.py`: `brief` with a section (its place, verbatim) and
  without one (unchanged).
- `bin/fab test` passes; the touched test modules stay under a second each.

## Options, settled up front

- `repairs-tick` follows `foreman-tick` in `fab/dispatch.py`: reuse
  `_builder`, `_land_branch` and the way `_question` recomputes a question
  for the refusal; keep each new or changed function, `tick` among them,
  within 60 lines.
- Pass the open refusals into `_starts` as a mapping by task, computed once
  in `decide`.
- A refusal's foreman is never retried: an infra foreman is a fallback
  (`fab.repairs.refusals`).
- The dispatcher's literal `("rebase", "merge")` in `_start_kind` becomes
  `fab.repairs.REBASE_STEPS`.
