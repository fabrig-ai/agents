+++
id = "rust-digest"
part = "rust-gates"
kind = "feature"
needs = ["rust-scan"]
files = ["fab/rust_digest.py", "fab/tests/test_rust_digest.py", "fab/tests/rust_sources.py", "fab/gates.py", "fab/tests/test_gates.py", "fab/dispatch.py", "fab/tests/test_dispatch.py"]
effort = "high"
minutes = 50
+++
# fabrig's branches gated before they are readied

Fill every body of `fab/rust_digest.py` as its docstrings say: `classify`,
`crates`, `owner`, `sources`, `inventory`, `build` and `gather`. Then turn
the gates on for fabrig: add `"fabrig"` to `fab.gates.REPOS`, and make the
tick's ready action screen the branch first. `fab.gates.screen` already
takes the lock and the digest builder from `LOCKS` and `GATHER`; it needs
no change. Remove the skip from `ExemplarTest` in
`fab/tests/test_rust_digest.py`; it must pass as written. Design:
`docs/design/fab.md`, section 12, the bullet on fabrig's branches.

The ready action (`fab.dispatch._ready`): when the task's repository is in
`fab.gates.REPOS`, before anything else, `fab.gates.screen(task,
log.read(log_path), sh=sh, log_path=log_path)`; with findings, return
`rejected gate:<the findings' gates, unique, in order>` (the detail `_land`
prints) and fetch, untry and push nothing; without, ready as today and
return the action's detail. The ready case of `_take` prints what `_ready`
returns. Share the detail's text with `_land` through one private helper.

## Acceptance

- `fab/tests/test_rust_digest.py`, in the vocabulary of
  `fab.tests.rust_sources`:
  - `classify` for `src/lib.rs`, `tests/it.rs`, `benches/b.rs`,
    `src/foo/tests.rs`, `src/x_test.rs`, `README.md`, `docs/a.txt`,
    `Cargo.toml`, `build.rs`, `examples/e.rs`;
  - `owner` with nested crates (the longest root wins), a path under a
    crate but not under its `src/`, a `.toml` under `src/`, no roots;
  - `crates` with `support.FakeRunner` answering a `-z` ls-tree: the argv,
    the root's Cargo.toml left out, sorted; a git failure raises
    `fab.sh.Failed`;
  - `sources` and `inventory` on trees written by `tree`: a nested crate's
    files left to it, a test file left out, a crate missing from the tree;
  - `build` on two trees: an added and a removed crate (its items all
    added or all removed), a new module, a function in an existing file
    (not a new module) grown past the cap listed, an old long one untouched
    (not listed), a clone between two files, a clone added to an existing
    file, a test span's copy not a clone, a block comment repeated in two
    files not a clone, a path outside the task's files;
  - `gather` with real git (`fabrig_repo`, `commit_branch`): a branch adding
    a crate (the base side created empty, no `git archive` of it), a branch
    deleting a file, and the exemplar.
- `fab/tests/test_gates.py`: `screen` of a fabrig task, real git, the clone
  copied to FAB_HOME/repos/fabrig: a clean branch writes its digest and
  logs nothing, `gate-fabrig.lock` beside it; a changed `pub fn` signature
  logs branch.rejected with step `gate:shape`; an unclosed `{` is
  `gate:parse` with the module's path, no digest.
- `fab/tests/test_dispatch.py`, `fab.gates.screen` patched as the file
  already does: a done fabrig task with findings is not readied (no push,
  no branch.ready, no untry) and prints `rejected gate:shape`; with none it
  readies as before; a screen that raises is a failed action (a note) and
  pushes nothing; an agents task still screens before landing.
- `bin/fab test` passes; each touched test module stays under a second, and
  the whole suite within its 30 s.

## Options, settled up front

- `crates` parses NUL-separated names from the runner's `out`.
- An empty side is `(directory / side).mkdir(parents=True)`; never call
  `fab.digest.archive` with no paths (it refuses them).
- Files are read with `read_text(encoding="utf-8")`; a file that is not
  UTF-8 raises as Python does and the gating fails as an action, which the
  tick retries.
- Reuse `fab.digest.compare`, `outside`, `added_lines`, `long_functions`
  (with `find=fab.rust.functions`), `clones` and `archive`; write none of
  them again.
