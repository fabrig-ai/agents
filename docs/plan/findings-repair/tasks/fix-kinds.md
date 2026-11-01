+++
id = "fix-kinds"
part = "kinds"
kind = "feature"
needs = ["fix-module"]
files = ["fab/buffer.py", "fab/integration.py", "fab/tests/test_buffer.py", "fab/tests/test_integration.py"]
effort = "medium"
minutes = 25
+++
# FIX_KINDS in the buffer and the integration trunk

Read first: `docs/plan/findings-repair/notes/common.md`,
`docs/plan/findings-repair/notes/fix.md`.

The request: "`FIX_KINDS` wherever the red wiring reads kind `red`".
Design: `docs/design/fab-qa.md`, 2, "Everything fab-after-landing.md 2
gives kind `red` holds for each of `fab.fix.FIX_KINDS`".

## What to build

Where these modules read kind `red`, read `kind in fab.fix.FIX_KINDS`:
- `fab/buffer.py`, `group` (near line 30): a finding repair sorts as a
  repair, as a red does; its docstring says so;
- `fab/integration.py`, near line 169 (`task.kind not in ("repair",
  "red")`, the pending tasks of a check along the way) and near line 216
  (`next_step` leaving red tasks out of the trunk's): a finding repair is
  left out as a red is.

`fab/dispatch.py`'s readings are `fix-pair`'s; touch none here.

## Acceptance

- `fab/tests/test_buffer.py`: a task of kind `finding` groups as
  `repair` and orders with the red tasks, ahead of contracts and slices.
- `fab/tests/test_integration.py`: a finding task is not among a mid
  check's pending tasks, and does not count toward the trunk's next step,
  as the red cases there show.
- Every existing test passes unchanged.

## Report

The sites changed, by function and line.
