+++
id = "critic-run"
part = "critique"
kind = "feature"
needs = []
files = ["fab/critique.py", "fab/run.py", "fab/tests/critiques.py", "fab/tests/test_critique.py", "fab/tests/test_run.py"]
effort = "high"
minutes = 40
+++
# The self-critique's fold, the critic run, and the fix run's brief

Fill every body of `fab/critique.py` as its docstrings say: `task_field`,
`stages`, `reviewed`, `brief`, `start`, `findings` and `rejection`. Make `fab/run.py` do
what the amended docstrings of `branch_for`, `start` and `brief` say for the
new kind `fix` (already in `KINDS` and `EFFORTS`): a fix run continues the
task's branch as a repair does, and its brief quotes the critic's findings
under `## The self-critique found` rather than as a refusal. Nothing starts
a critic run yet; `critique-tick` drives the stages from the tick. Design:
`docs/design/fab.md`, 13.1; the role text is `fab/roles/critic.md`.

## Acceptance

- `fab/tests/test_critique.py`, in the vocabulary of
  `fab/tests/critiques.py` (`Story`, `critic`, `assert_stage`, `TASK`,
  `HOST`, `ROOT`, `DIGEST`); remove `@unittest.skip(PENDING)` and the
  `PENDING` constant from `ExemplarTest`, which must then pass unchanged:
  - `stages`: a task with no run left out; each rule of the docstring in
    turn (critique, critiquing, an infra critique below and at INFRA_LIMIT,
    hold with its reason, critique again after the hold's answer, clear on
    done, fix on failed and on question, clear after a fix ended done, fix
    again after a fix ended infra or question); a repair or a rebase that
    ends done after a rejection back at critique, its infra count its own;
    a critic run of an earlier tip not counted for the new one; two tasks
    folded apart; a record missing `run` or `outcome` skipped; equal
    timestamps kept in log order.
  - `reviewed`: None before any run ended done; the last done run that is
    not a fix; a fix ended done leaving the run it fixed.
  - `brief`: every section in order with a digest and with None, the files
    line `(none)` for a task without files, one trailing newline.
  - `start` with `support.FakeRunner` and a temporary FAB_HOME (the
    launcher answered as `test_foreman`'s `_starter` does): the worktree
    added detached at `origin/<branch>` in the builder's clone, `fab codex
    start --effort high --model <MODEL> --read-only`, run.started carrying
    task `<task>/critique`, kind critique, run `<task>/critique-1`, branch,
    base and `of` (the reviewed run); a second critique
    numbered 2; no run of the task ended done: ValueError and no command
    run.
  - `findings`: leading blank lines dropped, the FINDINGS_LINES cut,
    trailing blank lines dropped, an empty report.
  - `rejection`: a fix stage whose report file exists, one whose file is
    missing, and a clear stage (ValueError).
- `fab/tests/test_run.py`:
  - `branch_for(task, "fix", events)` is the last run.started's branch;
  - `start` of kind fix for an agents task adds the worktree from
    `origin/<branch>` as repair does, and for a fabrig task switches the
    slot to `origin/<branch>`; its effort is high;
  - `brief` with a rejection `{"step": "critique", "log": <path>,
    "findings": <text>}`: the `## The self-critique found` section with the
    paragraph and report line the docstring gives, the findings whole, and
    no `The landing refused this branch`; a gate rejection's brief is
    unchanged.
- `bin/fab test` passes; `test_critique.py` and `test_run.py` stay under a
  second each.

## Options, settled up front

- `start` reads nothing on this machine: the digest comes from its caller.
- `stages` reads outcomes as fab.run.collect logs them (`done`,
  `question`, `infra`, `failed`); any outcome but done and infra is a
  finding, as fab.call_review reads a refusal.
- In `fab.run.brief`, the critique section replaces the refusal section;
  everything else in the brief stays as it is. The literal `"critique"` in
  run.py stands for `fab.critique.STEP` (fab.critique imports fab.run, so
  not the other way).
- Add builders to `fab/tests/critiques.py` when a test needs one; keep the
  ones there as they are.
