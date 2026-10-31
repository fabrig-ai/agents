+++
id = "lean-briefs"
part = "calls"
kind = "feature"
needs = ["accounting", "channel-tick"]
files = ["fab/calls.py", "fab/tests/test_calls.py", "fab/roles/skeleton.md", "fab/roles/call-reviewer.md"]
effort = "high"
minutes = 45
+++
# Lean briefs: what the part cites and reaches, nothing more

The model designer's review (10-31) measured the skeleton calls: about 30
turns each re-reading 100-190k of context, most of it the brief. Each
skeleton brief carries all three drafts whole, the full inventory and every
task spec of every needed part. Cut it to what the part needs.

## What to change

- The drafts: only the sections the part's design citation and the plan's
  part reach (the cited `fab.md` sections' own citations of the drafts, and
  the draft headings named in the part's title or design), not the files
  whole. The drafts check moves from the skeleton author to the cut and to the
  Codex call reviewer, which keeps the drafts whole in its brief; drop the
  check from `fab/roles/skeleton.md` and add it to `fab/roles/call-reviewer.md`.
- The inventory: the modules the part's design cites and those its needs'
  parts own, plus the shared primitives (`fab/sh.py`, `fab/log.py`,
  `fab/atomic.py`, `fab/plan.py`, `fab/state.py`), not the whole package.
- The examples: one fixed example spec (the first landed task spec of the
  part's first need, else `docs/plan/agents-rebuild/tasks/files.md`), not
  every spec of every need.
- `skeleton_brief`'s docstring says all three.

## Acceptance

- Tests in `fab/tests/test_calls.py`: a brief for a part with two needs holds
  one example spec, the inventory of the cited and needed modules plus the
  shared ones only, and the cited draft sections only; the review brief keeps
  the drafts whole.
- `bin/fab test` passes; `test_calls.py` stays within its budget.
