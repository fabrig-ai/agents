# call-rebase

`docs/design/calls.md`, 2, "A `fab land` refusal counts as a refusal of the
chain", built as designed (`inputs/request.md`): `plan.toml`, the task specs
`tasks/`, the shared rules `notes/common.md`, the cut's decisions and
critical path `notes/decisions.md`.

Overlaps with `findings-repair` (queue): its two `fab/dispatch.py` tasks
(fix-pair, tick-findings) have landed on main, so `land-finish` changes
`fab/dispatch.py` and `fab/tests/test_dispatch.py` after them; only its
retire, which touches designs and status files, is left. `land-chain`
touches none of its files.
