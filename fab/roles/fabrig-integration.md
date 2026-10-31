# Working in fabrig, on an integration trunk

Your checkout is a builder slot: a fabrig checkout whose `target/` stays warm
across tasks. It is yours for this run; never touch another slot. Your task's
facts name its trunk: your branch is merged into it when you are done, and
the trunk gets the queue's full checks once, at the end.

- **Read fabrig's `AGENTS.md` first,** then the tree's `AGENTS.md`, the
  notes and designs your task names. The code's rules are skein's
  `docs/foundation/programming-model.md` and `testing-strategy.md`, section 1.
- **Every build and test goes through `heavy`**, one command at a time;
  `cargo fmt` runs directly. If heavy exits 75 (`heavy: Infra: disk`), stop
  and report `Infra: disk` as your first line.
- **The checks before you report,** in this order:
  1. `cargo fmt --all`, then `cargo fmt --all --check`;
  2. `python3 -I -B scripts/old_forms.py` from the root of each tree you
     touched (skein, smith, jig, temper): a raised count is red; lower the
     baseline with `--write` when your change lowers a count;
  3. `heavy cargo clippy -p PKG ... --all-targets -- -D warnings` for every
     package you changed;
  4. `heavy cargo nextest run -p ...` for the packages you changed and their
     direct dependents in every tree (`cargo tree -i PKG --workspace -e
     normal,dev --depth 1`), then the same with `--profile fuzzy`;
  5. after a public API change, `heavy cargo check -p DEPENDENT --tests` for
     each dependent package in every tree.
  Never the whole workspace and no precheck: the trunk's end check runs the
  queue's checks.
- **Report** each check's command, outcome and test counts, and your
  implementation and check minutes apart.
