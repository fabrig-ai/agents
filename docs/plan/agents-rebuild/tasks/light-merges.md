+++
id = "light-merges"
part = "replay"
kind = "migration"
needs = []
files = ["fab/dispatch.py", "fab/integration.py", "fab/rust_gates.py", "fab/gates.py", "fab/tests/test_dispatch.py", "fab/tests/test_integration.py", "fab/tests/test_rust_gates.py", "fab/tests/test_gates.py"]
effort = "high"
minutes = 25
+++
# Light merges into a trunk; the files gate goes

docs/design/fab.md 13.12 ("Merging, not landing, and light"; "The run's
own texts": the `files` gate is gone) and sections 12 and 13.11.

## What to change

- `fab/dispatch.py`: an integration plan's `merge` action runs no gates:
  drop the `rust_gates.screen` before `_merge_branch`. `_merge_branch`
  keeps fetch, reset to `origin/<trunk>`, merge, the old-forms recount of a
  conflict confined to baselines (`fab.integration.baselines` and
  `recount`), push and the `branch.landed` record, and drops the trunk
  ratchet check after the merge (the `old_forms.py` run without `--write`
  and its `gate:ratchet` rejection).
- `fab/rust_gates.py` and `fab/gates.py`: no `files` gate: `GATES` and
  `check` lose it. The digests still list the paths outside the task's
  files, as information. Queue plans keep their other gates.
- Tests: the existing tests of the removed behaviour go or change to assert
  its absence (a merge with an outside path or a raised count merges; no
  `files` finding); nothing else changes meaning.

## Acceptance

- An integration merge issues no gate or old_forms command except the
  recount of a baseline-only conflict (fake runner argv), and merges a
  branch whose path lies outside its task's files.
- `bin/fab test` passes within its budget.
