# Working in fabrig

Your checkout is a builder slot: a fabrig checkout whose `target/` stays warm
across tasks. It is yours for this run; never touch another slot.

- **Read fabrig's `AGENTS.md` first,** then the tree's `AGENTS.md` and the
  designs your task cites. The code's rules are skein's
  `docs/foundation/programming-model.md` and `testing-strategy.md`, section 1.
- **Every build and test goes through `heavy`**, one command at a time:
  `heavy cargo check -p PKG --tests` while errors last, then the narrowest
  test (`heavy cargo nextest run -p PKG --test BIN -E 'test(=NAME)'`).
  `cargo fmt` runs directly.
- **heavy waits for disk by itself.** If it exits 75 (`heavy: Infra: disk`),
  stop and report `Infra: disk` as your first line; never work around it.
- **At the end, once:** `cargo fmt`; `heavy cargo clippy -p PKG ...
  --all-targets -- -D warnings` for every package you changed; their tests and
  their direct dependents' (`heavy cargo nextest run -p ...`). Never the whole
  workspace: precheck selects what the queue will run.
- **Then precheck your pushed tip:** `fab precheck <your slot> <tip> --onto <trunk>`. It must
  print outcome green. Use the trunk your task's facts name (`origin/main`
  when they name none). Put its receipt path in your report. A red is yours to
  repair within the task; a conflict with the trunk is a `Question:`.
