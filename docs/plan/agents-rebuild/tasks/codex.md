+++
id = "codex"
part = "codex"
kind = "migration"
needs = []
files = ["fab/codex.py", "fab/tests/test_codex.py"]
effort = "high"
minutes = 30
+++
# fab codex: the Codex launcher

Fill the bodies of `fab/codex.py` as their docstrings say. Design:
`docs/design/fab.md`, section 5. It replaces fabrig's `codex-run task`
(on the builder at `~/src/fabrig/main/tools/codex-run/codex-run`: read its
`turn` and `finish_task` functions for the codex flags and the capacity retry
it keeps). Leave out what the docstrings leave out: owners, posts, stale
scans, final notes, slot holds and trims, reaper hooks.

## Acceptance

- `fab/tests/test_codex.py` covers `new_id`, `command` (fresh, resume,
  read-only, model), `tokens`, `at_capacity`, and `start`'s refusals and its
  systemd-run argv with the fake runner, under a temporary FAB_HOME.
- `execute` is covered with a fake `codex`: a small executable script put
  first on PATH in the test, printing JSON events (thread.started,
  turn.completed with usage) and optionally writing the report, or failing
  once at capacity then succeeding on resume. Cover: report written by the
  run; report missing (the fallback with last.md); a capacity retry (sleep
  patched); `ended` written after result.json.
- `bin/fab test` passes; `test_codex.py` takes under a second.

## Options, settled up front

- `execute` may use `subprocess` directly for the codex process (it streams
  to files); the runner seam is for the short commands.
- The python3 in `start` is `sys.executable`.
