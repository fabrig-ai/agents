+++
id = "cut-direct-text"
part = "paper-cuts"
kind = "feature"
needs = []
files = ["fab/roles/cut-direct.md"]
effort = "medium"
minutes = 15
+++
# cut-direct.md worded for a queue plan

Read first: `docs/plan/dogfood-faults/notes/common.md`,
`docs/plan/dogfood-faults/notes/decisions.md` (12).

The request, item 7's third paper cut. `fab/roles/cut-direct.md` is read
only by direct queue plans (`fab/designer.py`, `_cut_role_options`; a
direct integration plan gets `cut-run.md`).

## What to build

- `fab/roles/cut-direct.md` (~54-56): "Its base is the trunk's tip when its
  needs have merged" becomes: a spec's base is main's tip once its needs
  have landed. "Your branch is merged into the plan's trunk, not readied
  for the queue" becomes: the cut's branch lands on main once reviewed
  (this repository through `bin/fab land`, fabrig through its queue).
  Nothing else in the file changes.

## Acceptance

- The two sentences read as above, wrapped as the file wraps; no other
  line changes.
- `bin/fab test` green (`fab/tests/test_designer.py` reads the file
  whole; no test pins these sentences).

## Report

The two sentences as they read now.
