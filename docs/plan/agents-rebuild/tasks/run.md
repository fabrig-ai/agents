+++
id = "run"
part = "run"
kind = "feature"
needs = []
files = ["fab/run.py", "fab/tests/test_run.py"]
effort = "high"
minutes = 30
+++
# fab run: start, status, collect

Fill the bodies of `fab/run.py` as their docstrings say. Design:
`docs/design/fab.md`, section 5; the role text the brief starts with is
`fab/roles/implementer.md`. codex-run's interface is in fabrig's
`tools/codex-run/codex-run`, on the builder at
`~/src/fabrig/main/tools/codex-run/codex-run` (its header comment; `task` prints `<id> <state>`
and touches `<state>/ended` when the run ends); you need not read more of it.

## Acceptance

- `fab/tests/test_run.py` covers, with `support.FakeRunner` standing in for
  ssh: `start` issues the clone-or-fetch, worktree, brief and codex-run
  commands for each kind, sends the brief as the ssh command's input, and
  logs run.started with every field the docstring names; `status` before and
  after the ended marker; `collect` logging run.ended once (a second call
  returns None and logs nothing), and question.asked for a question.
- Pure tests for `remote_home`, `next_run`, `branch_for`, `outcome` (each
  prefix, a blank first line, an unknown first line) and `brief` (contains the
  role, the run facts and the body).
- `main`'s three subcommands are covered with the fake runner and a temporary
  FAB_HOME. For `start`, build the Task in the test or load it through
  `fab.plan` if it has landed by then; if it has not, patch a single
  `_load_spec(path)` helper of your own in `main`'s path.
- `bin/fab test` passes; `test_run.py` takes under one second.

## Options, settled up front

- One ssh command per step is fine; a combined script is not needed.
- Remote paths are absolute (codex-run refuses relative ones), from
  `remote_home`.
- Quote with `shlex`; `fab.sh.ssh` already wraps a login shell.
- `--model` is left to codex-run's default.
