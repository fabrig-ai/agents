+++
id = "rust-gates"
part = "rust-gates"
kind = "feature"
needs = ["gates"]
files = ["fab/rust_digest.py", "fab/rust_gates.py", "fab/tests/test_rust_digest.py", "fab/tests/test_rust_gates.py"]
effort = "high"
minutes = 60
+++
# The Rust digest and the minimal Rust gates

Build `fab/rust_digest.py` and `fab/rust_gates.py` as docs/design/fab.md
13.11 says ("Rust gates, minimal" and "The Rust digest"), mirroring the
shapes of `fab/digest.py` and `fab/gates.py` (section 12) where they fit:
pure functions over texts and changed paths, one thin shell layer through
the runner seam (`fab/sh.py`) for git and `old_forms.py`.

## What to build

- `fab/rust_digest.py`: from a base and a tip (both trees, as `git
  archive`s or worktrees) and the task: public items added and removed by
  grep over changed `.rs` files; changed lines by production, tests and
  docs; functions over 60 lines added or grown (by brace matching from a
  `fn` line, comments and strings skipped well enough for rustfmt'd code);
  paths outside the task's `files`; the ratchet's per-tree counts on base
  and tip. A `render` to deterministic Markdown of at most 8,000 characters,
  and a public function returning the public items of given crates by grep,
  which the fabrig briefs will use as their inventory (13.11, "Its briefs
  speak Rust").
- `fab/rust_gates.py`: `check(digest) -> findings` for `files` and
  `ratchet` (any per-form count on the tip above the base's fails, naming
  the tree and form); `size` only as the digest's flag. A `screen(task,
  events, ...)` with the same contract as `fab.gates.screen`: build the
  digest, write it to `FAB_HOME/digests/<run>.md`, log `branch.rejected`
  with step `gate:<gate>` and `findings` on a failure, return the findings;
  a gating that cannot run raises (the branch waits, never readies
  ungated). Do not wire it into the tick here; `optimistic-start` does.
- `old_forms.py` runs as `python3 -I -B scripts/old_forms.py` from each
  touched tree's root (a top-level directory of the fabrig repository with
  that script) on base and tip. Take the counts from the form most stable
  to parse: its output or its baseline file `scripts/old-forms.txt`. A copy
  to read: `~/src/fabrig/fab/repos/fabrig/skein/scripts/old_forms.py`.

## Acceptance

- Tests on small hand-written Rust trees in temporary directories: public
  items added and removed; a 61-line function flagged, a grown old one
  flagged, an untouched long one not; test and doc lines split from
  production; a ratchet rise refused naming the form, a fall passing; a
  path outside `files` refused; the render within 8,000 characters.
- `bin/fab test` passes within the 30 s budget.
