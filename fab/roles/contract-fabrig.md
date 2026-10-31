# Shared contracts in fabrig

For this fabrig call, these rules replace the Python-specific instructions
above. Read fabrig's `AGENTS.md`, the affected tree's `AGENTS.md`, and the
readers' cited designs. Follow skein's `docs/foundation/programming-model.md`
and `testing-strategy.md`, section 1.

- Write the contract as Rust types, constants and public items in the
  workspace's existing crate and module layout: `<tree>/crates/<crate>/src/`
  under skein, smith, jig or temper. Dependencies point toward skein;
  a generic contract goes there before a downstream reader.
- Use full Rust signatures and `///` doc comments as the contract;
  unfilled bodies contain only `todo!()`. Write out types and constants.
  Express test vocabulary as Rust builders, fixtures and assertion functions
  in the tree's test helpers.
- Write specs in this plan's `tasks/`, using repository-relative globs over
  the crate's source paths, test helpers and test crates. Their acceptance
  names Rust tests and focused nextest commands.
- Run `heavy cargo check -p <crate> --tests` and fix your own compile errors
  before committing. Run one build or test at a time through `heavy`;
  `cargo fmt` runs directly. hel8 builds nothing. Heavy exit 75
  (`heavy: Infra: disk`) ends with an `Infra: disk` report. Never check the
  whole workspace. Push your branch for fabrig's merge queue; never main.
