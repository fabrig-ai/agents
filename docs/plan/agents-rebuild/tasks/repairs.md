+++
id = "repairs"
part = "foreman-repairs"
kind = "feature"
needs = ["foreman", "accounting"]
files = ["fab/repairs.py", "fab/spec_edit.py", "fab/foreman.py", "fab/run.py", "fab/tests/test_repairs.py", "fab/tests/test_spec_edit.py", "fab/tests/test_foreman.py", "fab/tests/test_run.py"]
effort = "high"
minutes = 50
+++
# The foreman on a refusal: where each refusal stands, its run, its verdict and section

Fill the bodies of `fab/repairs.py` (`refusals`, `brief`, `start`, `remedy`,
`section`, `with_section`, `commit`), `fab/spec_edit.py` (`commit`) and the
new `fab.run.excerpt` and `fab.run.refusal_text`, as their docstrings say.
Design: `docs/design/fab.md`, 13.1 (the foreman writes the rebase and repair
tasks) and 3 (`refusal.settled`). The role text is
`fab/roles/foreman-repair.md`, already written. Nothing calls
`fab/repairs.py` yet: `repairs-tick` wires it into the tick.

Two moves, so the package keeps one copy of each:

- **`fab.spec_edit.commit` is `fab.foreman.commit`'s body,** with the edit,
  branch, message and worktree as arguments. Make `fab.foreman.commit` one
  call to it (edit: `with_answer` with its day, question, answer and run;
  branch `answers/<run_id>`; message `Answer <task.id>'s question from its
  options`; worktree FAB_HOME/runs/<run_id>/wt) and say so in its
  docstring. Its argvs and outcomes do not change: the tests in
  `fab/tests/test_foreman.py` pass unchanged.
- **`fab.run.excerpt` is the cut `fab.run.brief` makes today** for a
  rejection without findings. Move it there and make `brief` call it; the
  brief's tests in `fab/tests/test_run.py` pass unchanged.

## Acceptance

- `fab/tests/test_repairs.py`, in the vocabulary its head defines (`event`,
  `task_run`, `rejected`, `foreman_run`, `settled`, `report`, `refusal`,
  `RepairsTestCase.only` and `assertStands`); add builders there rather than
  beside a test:
  - the exemplar test runs: remove its skip;
  - `refusals` as a pure function over hand-built events, one test per path:
    each state with its since; closed by a later run.started, branch.ready
    or branch.landed of the task, never by a foreman run's records; replaced
    by a later branch.rejected (the new one's tip, step and kind); a task
    outside `tasks` left out; a foreman run with `asked` instead of
    `refused`, or started before the branch.rejected, does not count; the
    last of two counts; fallback for each of failed, question and infra; a
    settlement naming another run does not count; kind rebase for steps
    rebase and merge; `retried` after a retry settlement since the last
    run, not after one before it; findings and log carried, "" when
    missing; two refusals keep their log order, also with equal
    timestamps; each record missing a field is skipped;
  - `brief`: every section in order, the role text it is given first, the
    log fenced, the spec verbatim, `-` for an empty tip, yes and no for
    retried;
  - `start` with `support.FakeRunner` and a temporary FAB_HOME: the
    worktree added `--detach` at `origin/<branch>` over ssh, `fab codex
    start --effort medium --read-only`, run.started with task
    `<task>/foreman`, kind foreman, branch, `refused` and `step`; the run
    numbered after a question foreman of the same task; an unreadable spec
    starts nothing on the builder; the gates' findings in the brief without
    reading a gate;
  - `remedy`: fix with its body cut at SECTION_LINES and trailing blank
    lines dropped; retry; retry refused when retried and for `paths` and a
    `gate:` step; `Failed:`, an empty line, another verdict word and an
    empty report give none, never an exception;
  - `section` for a repair and a rebase; `with_section` appended after one
    blank line, unchanged when the run's section is already there;
  - `commit` with real git (`support.git_pair`): the branch `repairs/<run>`
    on the origin holds the section, one commit on main; once that commit
    is on the origin's main, a second commit returns None and pushes
    nothing.
- `fab/tests/test_spec_edit.py`: with real git, an edit committed and
  pushed to the branch; an edit returning the spec unchanged gives None
  and pushes nothing; the worktree and the local branch gone after both
  and after a failing push; with `support.FakeRunner`, a spec outside the
  checkout is a ValueError before any command.
- `fab/tests/test_run.py`: `excerpt` (the brief's cut cases, now on the
  function); `refusal_text` for findings (no host loaded), a repository in
  LANDED (its log verbatim, and the diagnostic without one), a queue log
  read on the first gate by name and cut by `excerpt`, no gate host, and
  hosts that fail to load.
- `bin/fab test` passes; `test_repairs.py` and `test_spec_edit.py` take
  under a second each, and the other touched modules stay within theirs.

## Options, settled up front

- `refusals` walks the events once and keeps indexes, as
  `fab.foreman.questions` does.
- A foreman's run id comes from `fab.run.next_run` over
  `fab.foreman.task_field`: refusal and question foremen of a task share
  one numbering.
- `remedy` matches `Done:`, the verdict word and its colon case-sensitively,
  with any spaces around the colons; `Done: Fix:` is not a verdict.
- `commit` builds its edit with `functools.partial` or a lambda; either is
  fine.
- A copy of `fab.foreman.commit`'s worktree-and-push block, or of brief's
  cut, left anywhere is a defect (the `clones` gate refuses it). Each new
  function stays within 60 lines (the `size` gate).
