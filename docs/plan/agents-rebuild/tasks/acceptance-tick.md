+++
id = "acceptance-tick"
part = "acceptance"
kind = "feature"
needs = ["acceptance-tasks", "accounting"]
files = ["fab/run.py", "fab/dispatch.py", "fab/state.py", "fab/tests/test_run.py", "fab/tests/test_dispatch.py", "fab/tests/test_state.py"]
effort = "high"
minutes = 40
+++
# Test-writer and accept runs start, land and show

Make runs, the tick and `fab status` carry `fab.acceptance`'s tasks, as the
amended docstrings say: `fab.run.branch_for`, `role_text`, `brief` and
`start`; `fab.dispatch.decide` (step 3's run kind, step 4's spec tasks),
`call_actions` (no answer call for an owned task's question) and `tick`
(the merged tasks, slice.done); `fab.state.main`. Design:
`docs/design/fab.md`, section 13.1. This task waits for `accounting`,
the last of the open tasks that change `fab/run.py`, `fab/dispatch.py` and
`fab/state.py` (it needs `channel-tick`, which needs `designer-tick`,
`foreman-tick` and so `tick-split` and `designer`). Read those files as they
are on main when you start: the tick is split into functions by then, and
`fab.state.part_statuses` is filled.

## What changes

- `fab/run.py`: KINDS gains `"tests"` and `"accept"` (fab.acceptance.KINDS);
  EFFORTS gains `"tests": "high"` and `"accept": "medium"`.
  `role_text(repo, kind="implement")` reads `fab.acceptance.ROLES[kind]` for
  those kinds. `branch_for` gives a tests or accept run
  `fab.acceptance.BRANCH` of its own run id, `accept/<run id>`, never a
  branch under a spec task's `<draft>/<task>`.
  `brief` leaves out `(spec ...)` when the task's path is empty. `start`
  passes its kind to `role_text`.
- `fab/dispatch.py`: as the docstrings of `decide`, `call_actions` and
  `tick` say. The merge is one private function,
  `{**specs, **acceptance.tasks(plan, specs, events)}`, which the tick calls
  after the queue import for decide and again over the re-read events for
  call_actions.
- `fab/state.py`: `main` prints the specs' tasks, then the owned ones.

## Acceptance

- `fab/tests/test_run.py`: `role_text("agents", "tests")` and `"accept"`
  start with their role files, then the taste file; `branch_for` for both
  kinds gives `accept/` and the next run id; `brief` of a task with an empty
  path has the line `- Task: <id>` and no `spec`; `start` of a tests task
  adds the worktree with `-b accept/<run id>` from origin/main, writes the test-writer's role
  in the brief and starts Codex at effort high (accept: medium). The
  existing loops over KINDS take the new kinds' branch and effort.
  A regression test: a draft `d` whose part `core` has a spec task `core`
  (its branch `d/core`): the branches of `d/core/tests` and
  `d/core/accept-1` runs neither equal `d/core` nor start with `d/core/`
  (git cannot hold a ref and one under it at once).
- `fab/tests/test_dispatch.py`, with `fab.tests.support`'s builders:
  - decide: an owned tests task starts with run_kind `tests`; a rejected
    accept task starts with run_kind `accept` and its rejection; a part whose
    spec tasks all landed is a need met for the design step while its accept
    task is not landed;
  - call_actions: an open question of an owned task starts no answer call,
    with ANSWER_AT of them queued;
  - tick (the fake runner, a temporary FAB_HOME and a plan written there):
    a designed feature part's tests task is started; a slice whose accept
    task landed green logs one slice.done and prints `slice <n> done`, and a
    second tick logs none; an accept task landed this tick with a `Done: red`
    report reaches call_actions as a red round: patch
    `fab.dispatch.call_actions` and check that its tasks hold the next
    round's accept task, not the landed one.
- `fab/tests/test_state.py`: `fab status` on a plan with a designed feature
  part lists `<draft>/<part>/tests` and `<draft>/<part>/accept-1` after the
  specs.
- `bin/fab test` passes; the touched test modules stay as fast as they are.

## Options, settled up front

- `fab.state.main` imports `fab.acceptance` inside the function (the
  module imports `fab.state`).
- No new constant in `fab/dispatch.py`; the kinds come from
  `fab.acceptance.KINDS`.
- When this lands, a feature part designed with a task not yet landed gets
  its test-writer run on the next tick; parts whose tasks have all landed by
  then (this part among them) owe none. That is intended: acceptance begins
  with this change, for the parts designed after it.
