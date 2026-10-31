+++
id = "fabrig-calls-brief"
part = "fabrig-calls"
kind = "feature"
needs = ["rust-gates", "lean-briefs"]
files = ["fab/calls.py", "fab/designer.py", "fab/tests/test_calls.py", "fab/tests/test_designer.py", "fab/roles/skeleton-fabrig.md", "fab/roles/contract-fabrig.md", "fab/roles/cut-fabrig.md", "fab/roles/call-reviewer.md"]
effort = "high"
minutes = 50
+++
# A fabrig plan's calls work in fabrig and their briefs speak Rust

docs/design/fab.md 13.11 ("Its briefs speak Rust", and the calls' side of
"Its calls land through fabrig's queue").

## What to change

- A call of a plan whose repo is `fabrig` works in a worktree of the fabrig
  clone on hel8 (`FAB_HOME/repos/fabrig`, from `origin/main`) on
  `calls/<id>`, and the branch is pushed to fabrig's origin when it ends,
  as this repository's calls are.
- Role texts: the fabrig variants for the skeleton, contract and cut
  authors (`fab/roles/*-fabrig.md`): `todo!()` bodies with doc comments as
  the contract, the crate and module layout, test vocabulary as Rust test
  helpers, `cargo check -p <crate>` under `heavy` to fix its own compile
  errors, specs in the plan's `tasks/` with globs over the crate's paths.
  Read `fab/roles/fabrig.md` (the implementer's) and fabrig's own
  `AGENTS.md` for its rules; write only what differs from the Python texts.
  `fab/roles/call-reviewer.md` gains one line: a fabrig call is reviewed
  against fabrig's AGENTS.md rules too.
- The brief's inventory for a fabrig plan: the public items, by grep, of
  the crates the part's design cites and its needs' parts own
  (`fab.rust_digest`'s public-items function), not `fab.calls.inventory`.
  The example spec comes from the plan itself when it has a landed one.

## Acceptance

- Tests with a fake fabrig checkout in a temporary directory: a fabrig
  skeleton brief has the fabrig role text and a Rust inventory of only the
  cited crates; the call's worktree and push target the fabrig clone; an
  agents brief is unchanged.
- `bin/fab test` passes within the 30 s budget.
