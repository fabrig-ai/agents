# start-commands: the plan

Four direct parts, one task each, in the request's order:

- `trunk-make` (`docs/design/integration.md`, 3, "The plan lives on its
  trunk"): `fab trunk make`, in `fab/trunk.py`.
- `plan-inputs` (same section): `fab plan inputs`, in `fab/inputs.py`.
- `brief-park` (`docs/design/calls.md`, 2): a `--tick` call whose brief
  cannot be compiled parks its subject.
- `retired-import` (`docs/design/tick.md`, 5, "A plan that cannot load"):
  a retired plan's last landing is imported and its retire finished.

The first two start at once; `retired-import` needs `brief-park` (both
change `fab/dispatch.py`). Specs in `tasks/`, the standing rules in
`notes/common.md`, the decisions and the critical path in
`notes/decisions.md`. No task edits `docs/design/`: the designs are
written, and the status lines are the retire call's.

## Overlaps with drafts beside this one

- `hel8-units/logins-report` (`fab/units.py`, `fab/logins.py`,
  `fab/report.py` and their tests): no shared file.
- `mechanisms-out` is not cut yet. Its request changes `fab/dispatch.py`
  (`call_actions`, `_chain_actions`, `_take`'s finish), `fab/calls.py`
  (`_chain_call`'s amend), `fab/designer.py` (`main`, the cut's facts) and
  their tests, which `brief-park` also changes (`_call`,
  `_parked_subjects`, `call_actions`' triage line; the three `main`s). It
  could not be avoided: the park is in those mains. The request lets
  `brief-park` run beside `mechanisms-out` while that one has not reached
  `fab/calls.py` `main`'s amend path; it has not, so `brief-park` starts
  at once and `mechanisms-out` rebases over it.
- `dogfood-faults` has landed and retired: nothing to wait for.
