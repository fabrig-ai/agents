# Skeletons in fabrig

For this fabrig call, these rules replace the Python-specific instructions
above. Read fabrig's `AGENTS.md`, the affected tree's `AGENTS.md`, and the
cited designs first. Follow skein's `docs/foundation/programming-model.md`
and `testing-strategy.md`, section 1.

- Write Rust crates and modules in the existing workspace: `skein/`,
  `smith/`, `jig/`, `temper/`, with crates under `<tree>/crates/<crate>/`
  and modules under `src/`. Keep dependencies pointing from temper to jig
  to smith to skein; a generic mechanism belongs in skein before its consumer.
- Public items have full Rust signatures and `///` doc comments stating
  their contract. Unfilled function bodies contain only `todo!()`; types
  and constants are written out. A story that does not reach a body leaves
  it `todo!()`.
- Write the test vocabulary as Rust builders, fixtures and assertion
  functions in the tree's test helpers, with an exemplar that compiles and
  adds no failing test. Test crates are ordinary Rust, following their
  tree's `tests/clippy.toml`.
- Task specs live in this plan's `tasks/`, wherever the plan sits in its
  tree. Use repository-relative globs over the crate's paths for `files`,
  including its test helpers and test crates where needed. Use Rust test
  acceptance and its focused nextest command, not Python test names.
- Run `heavy cargo check -p <crate> --tests` one command at a time and fix
  your own compile errors before committing; `cargo fmt` runs directly.
  Every build and test goes through `heavy`; Only `cargo check -p` of the crates you touch runs here; tests and the workspace build on the builders. If heavy
  exits 75 (`heavy: Infra: disk`), stop with `Infra: disk` in the report.
  Never run the whole workspace. Push your branch; main moves only through
  fabrig's merge queue.
