+++
id = "files"
part = "files"
kind = "feature"
needs = []
files = ["fab/plan.py", "fab/state.py", "fab/tests/test_plan.py", "fab/tests/test_state.py"]
effort = "high"
minutes = 25
+++
# Plans, task specs and the status fold

Fill the bodies of `fab/plan.py` (`load_plan`, `parse_task`, `load_tasks`,
`problems`) and `fab/state.py` (`fold`, `runnable`, `main`) as their
docstrings say. Design: `docs/design/fab.md`, sections 3 and 4.

## Acceptance

- `bin/fab status docs/plan/agents-rebuild` lists this plan's tasks (the spec
  files under `docs/plan/agents-rebuild/tasks/`) with their status from an
  empty log, and exits 0. The real `plan.toml` and specs load without
  problems.
- `fab/tests/test_plan.py` covers: a minimal and a full plan; each PlanError
  case the docstrings name; a spec with and without optional keys; the body
  kept verbatim; short ids made full; each kind of `problems` line,
  including a cycle among tasks.
- `fab/tests/test_state.py` covers each event rule in `fold`'s docstring,
  needs turning waiting into runnable once landed, unknown tasks and event
  types ignored, and `main` printing the rows (log under a temporary
  FAB_HOME).
- `bin/fab test` passes; the two new modules' tests together take under one
  second.

## Options, settled up front

- TOML through `tomllib`; no new dependency.
- `problems` lines read like `part queue needs unknown part heavy-x`; their
  exact wording is yours, but each names the file or id at fault.
- A cycle is reported once, naming its members in sorted order.
- `main` prints aligned columns with plain spaces; no colours.
