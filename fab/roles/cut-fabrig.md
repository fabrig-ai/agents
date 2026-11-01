# Cutting a fabrig plan

For this fabrig call, these rules replace the Python-specific instructions
above. Read fabrig's `AGENTS.md` and each affected tree's `AGENTS.md`.
The plan belongs beside its sources in its tree, at the plan path in this
brief, such as `skein/docs/plan/<draft>/plan.toml`.
Specs for direct parts belong in that plan's `tasks/`.

- Cut along the workspace's crate and module layout:
  `<tree>/crates/<crate>/src/` under skein, smith, jig or temper. Cite
  designs by repository-root path and section. Dependencies point toward
  skein; shared generic contracts precede their downstream readers.
- Direct specs use repository-relative globs over their crate's paths,
  including the Rust test helpers and test crates they need. Acceptance
  names Rust tests and focused nextest commands. Later skeleton and
  contract calls write full Rust signatures with `///` contracts and
  `todo!()` bodies; test vocabulary is Rust builders, fixtures and assertion
  functions.
- Validate with `fab status <the plan directory>` (`fab` is on PATH;
  fabrig has no `bin/fab`, and `bin/fab test` does not apply here). Where Rust
  code must compile, run `heavy cargo check -p <crate> --tests` and fix your
  own compile errors. Every build and test runs through `heavy`, one at a
  time; `cargo fmt` runs directly. Only `cargo check -p` of the crates you touch runs here; tests and the workspace build on the builders. Heavy exit 75
  (`heavy: Infra: disk`) ends with an `Infra: disk` report. Never run the
  whole workspace. Push your branch for fabrig's merge queue; never main.
