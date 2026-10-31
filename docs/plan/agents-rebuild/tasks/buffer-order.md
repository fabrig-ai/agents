+++
id = "buffer-order"
part = "buffer-order"
kind = "feature"
needs = ["receipts-ready", "plans-tick"]
files = ["fab/buffer.py", "fab/plan.py", "fab/dispatch.py", "fab/tests/test_buffer.py", "fab/tests/buffer_order.py", "fab/tests/test_plan.py", "fab/tests/test_dispatch.py"]
effort = "high"
minutes = 30
+++
# Runnable tasks start in the timeline's order

Today `decide` starts rejected tasks first, then runnable ones in the order
of their spec files. The user's timeline puts a structure review's
consolidations at the head of the buffer, then repairs and rebases, then
the tasks of contract parts, then the rest by their part's slice. Fill
`fab/buffer.py` and make `decide` start runs in its order. Design:
`docs/design/fab.md`, 13.10, and section 4 for the spec's header.

## What to fill

- **`fab/buffer.py`:** `group` and `order`, as their docstrings say. Pure;
  no other module's code is copied into it.
- **`fab.plan.parse_task`:** reads an optional `consolidation` boolean
  from the header into `Task.consolidation` (the field is there, default
  false). A value that is not a boolean is a PlanError naming the path, as
  for the other keys. Its docstring lists the new default.
- **`fab.dispatch.decide`, step 3:** the candidates (rejected and runnable
  tasks) are put in `fab.buffer.order(plan, tasks, candidates, refused)`
  before the starts are chosen, `refused` being the candidates whose start
  carries a refusal (`_start_kind`'s rejection is not None). The design
  step still counts every candidate. In step 3 of the docstring, replace
  "for rejected tasks first, then runnable ones in the tasks' order" with
  "for rejected and runnable tasks in fab.buffer.order's order, refused
  being those whose start carries a refusal". Whatever `repairs-tick`,
  `receipts-ready` and `plans-tick` left in step 3 (a refused task held at
  its foreman, the draft's own runs) stays as it is.

## Acceptance

- `fab/tests/test_buffer.py`, in the vocabulary of
  `fab/tests/buffer_order.py` (`sliced`, `spec`, `specs`, `ids`,
  `BufferTestCase.assertOrder`):
  - the exemplar test runs: remove its skip;
  - `group`: each of the four groups, a consolidation that is also refused
    and of a contract part, a task whose part is not in the plan;
  - `order`: a part in two slices ranks by the first; within a slice, parts
    in plan order; equal group, slice and part go in the specs' order
    (`tasks`' order) whatever the candidates' order; a part in no slice and
    a part not in the plan after every slice; candidates and tasks
    unchanged; a candidate missing from tasks is a KeyError.
- `fab/tests/test_plan.py`: `consolidation` parsed, defaulted to false, and
  a string value a PlanError.
- `fab/tests/test_dispatch.py`, with plans from `sliced` and specs from
  `spec`: with room for one start, a consolidation starts before a rejected
  task; a rejected task of slice 2 before a runnable task of slice 1; a
  runnable task whose last run ended infra keeps its slice's place; a
  contract part's task before a slice 1 task; of two refused tasks of one
  part, a rejected task whose spec comes later starts after a runnable
  task whose spec comes earlier and whose next run carries a refusal (a
  `branch.rejected` since its last run); a park at MAX_RUNS is still
  given whatever the order. Every existing test passes unchanged.
- `bin/fab test` passes; `test_buffer.py` takes well under a second and
  `test_dispatch.py` stays within its budget.

## Options, settled up front

- A task's next run being a repair only because its last run ended infra
  is not a refusal: it keeps its part's group.
- `order` sorts every group by slice and part alike; there is no oldest
  refusal first.
- A consolidation is marked only by its header; the review call's role text
  (`fab/roles/reviewer.md`) already asks for `consolidation = true`.
- Each plan orders its own tasks; plans keep their order in the tick
  (13.4).
