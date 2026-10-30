+++
id = "gate"
part = "gate"
kind = "migration"
needs = []
files = ["fab/gate.py", "fab/tests/test_gate.py"]
effort = "high"
minutes = 30
+++
# fabrig's selection and checks, ported

Fill the bodies of `fab/gate.py` as their docstrings say. Design:
`docs/design/fab.md`, section 6. The source is fabrig's
`tools/queue/mq` on the builder at `~/src/fabrig/main/tools/queue/mq`
(functions `full_inputs`, `package_owners`, `lock_changes`, `selection`,
`changed_paths`, `load_metadata`, `check_commands`, `ratchet_commands`,
`run_step`, and `Queue.choose` for `select`). Keep their rules; drop what the
docstrings drop (tools suites, observers, writer leases, disk-floor parsing).

## Acceptance

- `fab/tests/test_gate.py` covers selection with small hand-written metadata
  dicts (no cargo): full inputs, read-by-tests globs, tools paths ignored,
  Markdown in and out of source directories, an unowned non-Markdown path,
  reverse dependencies through two levels, Cargo.lock with and without
  `locked`, `always` added and a missing `always` name refused. The behaviour
  cases in fabrig's `tools/queue/test_mq.py` that test these functions are your
  checklist; port the cases, not their fixtures.
- lock_changes on two small lock texts; check_steps for full, docs, a package
  set, both lanes; ratchet_steps; config from a temporary checkout with
  `.config/gate/` and with only `tools/queue/`.
- run_steps with the fake runner: stop at the first red, NO_TESTS green for
  build/default/fuzzy only, the log holding each command and its output.
- `changed_paths` and `select` with real git on `support.git_pair` and a fake
  metadata loader (`load=`).
- `bin/fab test` passes; `test_gate.py` takes under a second.

## Options, settled up front

- Metadata and package ids in tests are minimal dicts with only the keys the
  functions read.
- `metadata` itself (it runs cargo) is covered with the fake runner only.
