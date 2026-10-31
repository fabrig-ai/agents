+++
id = "integration-check"
part = "replay"
kind = "feature"
needs = ["integration-merge"]
files = ["fab/integration.py", "fab/dispatch.py", "fab/run.py", "fab/designer.py", "fab/cli.py", "fab/tests/test_integration.py", "fab/tests/test_dispatch.py", "fab/tests/test_designer.py", "fab/tests/test_run.py"]
effort = "high"
minutes = 60
+++
# The end check of an integration plan, its repairs, and its ready

docs/design/fab.md 13.12 ("The end check", "Retire waits for main"). The
merge path exists (`integration-merge`: `_merge_branch`, `branch.landed`
with `into`); `fab precheck SLOT TIP --onto REF --full` runs the queue's
full checks (`replay-trunk`).

## What to change

- **`fab/integration.py`**, new, pure except `main`:
  - `trunk_tip(plan, events) -> str | None`: `main` of the last
    `branch.landed` whose `into` is the plan's trunk.
  - `repair_tasks(plan, events, reports: Mapping[str, str]) -> dict[str,
    Task]`: one Task per check run of the plan that ended failed, in log
    order: id `<draft>/repair-<n>` (n from 1), part `integration`, kind
    `repair`, repo the plan's, files `("**",)`, effort high, minutes 20,
    path `""`, body: what failed (the check's tip, its run id, then
    reports[run], the collected report, at most 120 lines) and the
    acceptance (that step green on the trunk with the change, the
    narrowest checks first, then the failing step itself).
  - `next_step(plan, tasks, events) -> Step | None`, `Step(kind, tip,
    detail)` a frozen dataclass, for a plan whose landing is integration
    (None otherwise): nothing while any task of `tasks` (the plan's and
    its repair tasks) is not landed, or no merge has happened, or a check
    run (`run.started` kind `check`, task `<draft>/integration`) is in
    flight. Else, for the trunk tip: no check of it yet: `check`; its
    check ended done: `ready` when `plan.ready` and no `branch.ready` names
    task `<draft>/integration`, else None; its check ended failed: None
    (its repair task, now in tasks, runs), unless three checks have failed:
    `stop`, detail `red 3 times; needs judgement`.
  - `fab check start --tip TIP --onto REF BRIEF WORKDIR REPORT`: the
    builder's side, as `fab codex start` (state under FAB_HOME/check/<id>,
    `fab.codex.new_id`, a user unit `fab-check-<id>` with UMask 0077 and the
    same ExecStopPost wake, printing `<id> <state>`). `fab check _exec ID`
    runs `fab.precheck.precheck(WORKDIR, TIP, onto=REF, full=True)`, writes
    REPORT (`Done: green <tip>`, or `Failed: <first red step> red`, then one
    line per step and the receipt's log path), `result.json` (exit, ended)
    and touches `ended` last.
- **The recount** (13.12, "Merging, not landing"), in `fab/integration.py`
  and `fab.dispatch._merge_branch`: `baselines(paths) -> list[str]` (pure)
  returns the trees whose `<tree>/scripts/old-forms.txt` are all of the
  unmerged paths (tree in `fab.gate.TREES`; empty when any other path is
  unmerged); `recount(checkout, trees, *, sh)`: for each tree, `git checkout
  --ours -- <tree>/scripts/old-forms.txt`, then `python3 -I -B
  scripts/old_forms.py --write` with cwd the tree (check=True: a non-zero
  exit, a raise, is a Failed), then `git add` the file. `_merge_branch`,
  on a failed merge, lists the unmerged paths (`git diff --name-only
  --diff-filter=U`); when `baselines` names trees, it recounts and commits
  the merge (`git -c user.name=fab -c user.email=fab@localhost commit
  --no-edit`) and goes on as a clean merge; a recount that fails, or any
  other conflict, aborts and rejects as before (the findings say which).
- **`fab/run.py`**: `launch(..., command: Sequence[str] | None = None)`:
  when given, it is run with BRIEF, WORKDIR and REPORT appended instead of
  the Codex launcher; the rest (brief written, `<id> <state>` read,
  run.started) is unchanged.
- **`fab/dispatch.py`** (`_tick_plan` and decide's callers):
  - the plan's tasks include `integration.repair_tasks` (reports read from
    the collected `FAB_HOME/runs/<run>/report.md`, unreadable as empty), so
    fold, buffer order, starts and merges treat them as any task;
  - after the plan's other actions, `integration.next_step`: `check`
    claims an idle slot on the builder with most free places (as
    `_call_tests` does), fetches in it and launches run
    `fab.run.next_run("<draft>/integration", events)` with kind `check`,
    task `<draft>/integration`, branch the trunk, base the tip, `slot`, and
    `command` `["fab", "check", "start", "--tip", <tip>, "--onto",
    "origin/<trunk>"]`; a failed launch releases the slot. `ready` pushes
    `<tip>:refs/heads/ready/<trunk>` from the plan's checkout and logs
    `branch.ready` (task `<draft>/integration`, branch the trunk, tip).
    `stop` prints its detail and logs one note per tip. Each prints one
    line, `integration <draft> <kind> <detail>`.
  - check runs are collected as any run (they are the draft's).
- **`fab/designer.py`**: `retire_due` is false for an integration plan
  until a `branch.landed` without `into` names task `<draft>/integration`.
- **`fab/cli.py`**: register `check`.

## Acceptance

- test_integration: `trunk_tip`, `repair_tasks` (ids, body, files) and each
  branch of `next_step`, over plain events; `fab check _exec` with a fake
  precheck writes the report, result.json and `ended` in that order.
- test_dispatch: a plan with every task merged starts one check run in a
  claimed slot with the `fab check start` command; a failed check adds
  `<draft>/repair-1`, which starts from the trunk and is merged, after
  which the new tip is checked; a green check with `ready = false` starts
  nothing more; with `ready = true` it readies the trunk once.
- test_dispatch, real git: two branches lowering different counts on the same
  old-forms.txt line merge after a recount (a fake old_forms.py that writes
  the counts); a recount that exits 1, or a conflict in any other file,
  rejects with step `merge`.
- test_run: `launch` with `command`.
- test_designer: retire waits for the trunk to land.
- `bin/fab test` passes within its budget.
