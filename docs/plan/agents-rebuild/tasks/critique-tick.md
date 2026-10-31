+++
id = "critique-tick"
part = "critique"
kind = "feature"
needs = ["critic-run", "design-eligibility"]
files = ["fab/dispatch.py", "fab/tests/test_dispatch.py", "fab/tests/critiques.py"]
effort = "high"
minutes = 45
+++
# The tick critiques every task's branch before it lands or is readied

Today a done task's branch is gated and landed (this repository) or readied
(fabrig) in the same tick. From this change on, every tip a done run leaves
first passes the gates, then gets a critic run; a critique with no findings
lets it land or be readied at once, and findings go to one fix run on the
same branch, after which it lands or is readied. A repair or rebase that ends
done leaves a new tip, critiqued again; a branch whose critic keeps ending
infra parks, and never lands uncritiqued. The
stages are `fab.critique.stages` (filled by `critic-run`); this task drives
them from `decide` and the tick. Update the docstrings of every function you
change to say what it now does. Design: `docs/design/fab.md`, 13.1; the
events in section 3.

## What to change

- **`decide`, its step 2** (done tasks), by `fab.critique.stages(tasks,
  events)`, the task's stage:
  - critique: `Action("critique", task=<id>, branch=<view.branch>,
    detail=<view.branch>)`;
  - critiquing: nothing;
  - fix: nothing here; the task is a start candidate (below);
  - hold: `Action("park", task=<id>, run=<view.runs[-1]>, detail="<the
    stage's reason>; the branch waits uncritiqued, needs judgement")`, which
    the tick takes as it takes the MAX_RUNS park (a question.asked), so the
    task is parked and asks once;
  - clear: land or ready as today, the detail the branch.
  A task the fold makes runnable whose stage is critique and that has a
  reviewed run (`fab.critique.reviewed`; a hold that was answered) gets the
  critique action too, and is not a start candidate: its tip is critiqued
  again, not rebuilt.
- **`decide`, its step 3** (starts): the candidates are the rejected tasks,
  then the fix candidates, then the runnable ones that are not fix
  candidates, each group in the tasks' order. A fix candidate is a task
  whose status is done or runnable and whose stage is fix. Its start is
  `Action("start", task=<id>, host=<host>, run_kind=fab.critique.FIX,
  run=<the stage's critique>, detail="fix <host>")`, places and the target
  counted as for any start. Fix runs, like rebase runs, do not count toward
  MAX_RUNS; a fix candidate past MAX_RUNS still parks. The design step's
  count of ready tasks counts fix candidates too.
- **`decide` must not grow:** the new rules live in private functions it
  calls (the size gate holds every function to 60 lines).
- **The tick's critique action** (`_take`, a private module-level function
  of its own; `Action.kind`'s comment names `critique`):
  1. The task is gated first, as the land action gates it, through one
     private function both share: a task of a repository in
     `fab.gates.REPOS` is screened (`fab.gates.screen`); findings print
     `rejected gate:<gates>` exactly as land prints them, and no critic
     starts. A clean screen's digest is the text of
     FAB_HOME/digests/<the task's last run>.md, which screen wrote. A
     repository not gated has digest None and is not screened.
  2. The builder is `_builder(hosts, log.read(log_path))`, as vet and the
     foreman choose it (most free places, even at none; no builder at all is
     a failed action).
  3. `fab.critique.start(tasks[<id>], host, log.read(log_path),
     digest=<digest>, sh=sh, log_path=log_path)`; the printed detail is
     `<critic run> <host>`.
- **The fix start** (`_start`): for run_kind `fab.critique.FIX`, the
  rejection passed to `fab.run.start` is `fab.critique.rejection(<the
  task's stage>)`, the stage recomputed from `log.read(log_path)`; a stage
  that is no longer fix fails the action (rejection's ValueError) and starts
  nothing. Other kinds pass the decision's rejection as today.
- **`tick`'s docstring** says that done branches are critiqued before they
  land or are readied.

## Acceptance

- `fab/tests/test_dispatch.py`, in the vocabulary of
  `fab/tests/critiques.py` (`Story`, `critic`, `TASK`, `HOST`):
  - `decide` as a pure function: a done task with no critique gives a
    critique action and no land; critiquing gives neither; a done critique
    gives land (agents) and ready (a fabrig task); a failed critique gives a
    fix start with run the critic run, ahead of a runnable task and behind a
    rejected one; a fix ended done gives land and no second critique; a fix
    ended infra starts a fix again; a repair ended done after a rejection
    gives critique, not land; INFRA_LIMIT infra critiques give park with the
    reason in the detail and no land, fewer give critique; that park
    answered gives critique and no start; a task with
    MAX_RUNS - 1 implement and repair runs and one fix run that ended infra
    still starts its fix, not parks; a done task of another plan left out.
  - `tick` with `support.FakeRunner` and patched `fab.gates.screen`,
    `fab.critique.start`, `fab.run.start` and `fab.land.main` (record their
    calls):
    - a clean screen starts the critic with the digest's text on the
      builder with most free places, even at none, and lands nothing;
    - a screen with a finding prints `rejected gate:files` and starts no
      critic;
    - a fabrig task is not screened and its critic gets digest None;
    - no builder at all: a failed action, a note, nothing started;
    - a fix start passes `fab.run.start` the rejection with step
      `critique` and the findings of the critic's collected report;
    - the existing land tests, given a done critique in their logs, land
      as before.
- `bin/fab test` passes; `test_dispatch.py` stays within its budget.

## Options, settled up front

- The critique action comes in decide's step 2, where land and ready do, in
  the tasks' order.
- A critic run takes no place of its own in decide: it occupies its builder
  only while in flight, as review and foreman runs do.
- A builder for the critique is chosen when the action is taken, not in
  decide.
- Add builders to `fab/tests/critiques.py` when a test needs one; keep the
  ones there as they are.
