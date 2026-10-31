+++
id = "design-eligibility"
part = "dispatch"
kind = "feature"
needs = ["tick-split"]
files = ["fab/dispatch.py", "fab/plan.py", "fab/state.py", "fab/tests/test_dispatch.py", "fab/tests/test_plan.py", "fab/tests/test_state.py"]
effort = "high"
minutes = 40
+++
# Design pulls on designed needs; the buffer follows the flow

Two drifts from the user's model, found by its designer's review (10-31):
`decide` makes a part eligible for design only when every task of each part
it needs has landed, which serialises design along the dependency chain;
and the buffer that triggers design is measured against the builders'
nominal places, while the flow target starts at 2. Bring the code to
`docs/design/fab.md` section 4 (its two new bullets) and 13.2.

## What to change

- `fab.plan.Part` gains `needs_landed: tuple[str, ...] = ()`, read from an
  optional `needs_landed` list in plan.toml; `problems` reports a name in it
  that is not also in `needs`.
- In `decide`'s design step, a need is met when its part is designed or done
  (`fab.state.part_statuses`), or `done` in plan.toml; a need listed in
  `needs_landed` is met only when done. A need on a part of mode `probe` is
  met only when done.
- The buffer: design is asked for when runnable and rejected tasks number
  fewer than `plan.low` times the flow's current target for runs in flight
  (`fab.flow`), not the builders' total places.
- `decide`'s docstring says both rules.

## Acceptance

- Tests in `fab/tests/test_dispatch.py`: a reader is eligible once its
  contract part is designed with none of its tasks landed; a `needs_landed`
  need still waits for done; a probe need waits for done; the design action
  follows the flow target (a target of 2 asks for design below 2 x low
  runnable tasks, whatever the places).
- `fab/tests/test_plan.py`: `needs_landed` parsed, defaulted, and checked by
  `problems`.
- `bin/fab test` passes; each touched test module stays within its budget.

## Options, settled up front

- `needs_landed` lives on the part in plan.toml, as a list beside `needs`.
- When the flow has no target yet for the plan, use its starting target.
