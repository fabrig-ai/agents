+++
id = "foreman"
part = "foreman"
kind = "feature"
needs = ["call-review", "atomic-write"]
files = ["fab/foreman.py", "fab/run.py", "fab/call_review.py", "fab/tests/test_foreman.py", "fab/tests/test_run.py", "fab/tests/test_call_review.py"]
effort = "high"
minutes = 45
+++
# The foreman: where each question stands, its run, and its answer in the spec

Fill the bodies of `fab/foreman.py` (`task_field`, `questions`, `brief`,
`start`, `answer`, `with_answer`, `commit`) and of
`fab.run.launch_detached` as their docstrings say. Design:
`docs/design/fab.md`, 13.1 (the foreman) and 3 (the events). The role text
is `fab/roles/foreman.md`, already written. `launch_detached` is built on
`fab.run.fetch_clone` and `fab.run.launch`, which `call-review` filled.
`commit` writes the spec through `fab.atomic.write`, which `atomic-write`
adds; it also touches `fab/run.py`, so it lands first.

A review run and a foreman run start the same way: a read-only run in a
worktree detached at a rev. `launch_detached` is that step, once. Make
`fab.call_review.start` use it for its steps 3 and 4 and say so in its
docstring; its arguments, its ssh commands and the run.started it logs do
not change, so the tests in `fab/tests/test_call_review.py` pass with their
expected argvs unchanged. Nothing calls `fab/foreman.py` yet:
`foreman-tick` wires it into the tick.

## Acceptance

- `fab/tests/test_foreman.py`:
  - `questions` as a pure function over hand-built events, one test per
    path: a question answered later is not open; a task outside `tasks` is
    left out; a question from the dispatcher's park, from a run of kind
    review, or with no run.started for its run is queued since its own ts;
    an implement, repair or rebase run's question is foreman; a foreman run
    in flight is deciding since its run.started; ended done is settled,
    ended failed, question or infra is queued, each since its run.ended
    with `report` from it; a foreman run with another `asked`, or started
    before the question.asked, does not count; the last of two counts; two
    questions keep their log order, also with equal timestamps; a record
    missing a field is skipped.
  - `task_field` and the run id `<task>/foreman-<n>` it gives through
    `fab.run.next_run`.
  - `brief`: every section in order, the report fenced, the spec verbatim.
  - `start` with `support.FakeRunner` and a temporary FAB_HOME holding the
    asking run's report: the worktree add `--detach` at origin/main over
    ssh, `fab codex start --effort medium --read-only`, run.started with
    task `<task>/foreman`, kind foreman, branch the task id and `asked`; the report missing gives the question's
    text in the brief; an unreadable spec starts nothing on the builder; a
    failing launch is left to `launch_detached`'s own test.
  - `answer`: the first line's text and the lines after it, cut at
    ANSWER_LINES, trailing blank lines dropped; `Failed:` and an empty
    `Done:` refused.
  - `with_answer`: a new section at the end; an entry added to an existing
    last section; an entry put before a `##` section that follows Answers;
    the same run twice gives the spec unchanged; `Question:` stripped from
    the entry's line.
  - `commit` with real git (`support.git_pair`; git's worktrees and pushes
    are the point): the branch `answers/<run>` on the origin holds the
    entry in the spec, one commit on main; once that commit is on the
    origin's main, a second commit returns None and pushes nothing; the
    worktree and the local branch are gone after both, and after a failing
    push.
- `fab/tests/test_run.py`: `launch_detached` with the fake runner (the
  worktree added at the rev after the clone's fetch, `--read-only` on the
  launcher, the extra fields in run.started; a failing launch removes the
  worktree and re-raises; a failing worktree add removes nothing).
- `bin/fab test` passes; `test_foreman.py` takes under a second, and the
  other touched modules stay within theirs.

## Options, settled up front

- `questions` walks the events once and keeps indexes, as
  `fab.call_review.chains` does; comparing ts strings would also work, but
  indexes keep equal timestamps in order.
- `fab.call_review.start` keeps its own steps 1 and 2 (the tip, base and
  diff in the plan's checkout; the run id); only the builder's side moves.
  A copy of the worktree-and-launch block left in either module is a defect
  (the `clones` gate refuses it).
- Each new function stays within 60 lines (the `size` gate).
