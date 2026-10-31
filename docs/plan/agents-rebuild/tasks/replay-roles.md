+++
id = "replay-roles"
part = "replay"
kind = "feature"
needs = ["replay-options", "replay-trunk"]
files = ["fab/run.py", "fab/designer.py", "fab/tests/test_run.py", "fab/tests/test_designer.py"]
effort = "high"
minutes = 25
+++
# Replay-mode role texts reach the cut and the runs

docs/design/fab.md 13.12 ("Replay-mode texts"). The texts are written:
`fab/roles/cut-direct.md` and `fab/roles/fabrig-integration.md`.

## What to change

- `fab/run.py`: `role_text(repo, trunk: str = "main")`: when trunk is not
  main and `fab/roles/<repo>-integration.md` exists, it takes the place of
  `fab/roles/<repo>.md`; otherwise unchanged. `start` (and the rebase
  brief) pass their trunk.
- `fab/designer.py`: `cut_brief` appends `fab/roles/cut-direct.md` to the
  role text (after the fabrig variant, when there is one) when the parsed
  options set `direct = true`.

Only these two; `fab/dispatch.py` is another task's.

## Acceptance

- test_run: role_text with a non-main trunk for fabrig uses the integration
  text, for agents (no such file) the usual one; `start` with a trunk
  compiles it into the brief.
- test_designer: a cut with `--set direct=true` carries cut-direct.md's
  text; without, not.
- `bin/fab test` passes within its budget.
