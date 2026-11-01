+++
id = "status-current"
part = "status-current"
kind = "feature"
needs = []
files = ["docs/design/tick.status.md", "docs/design/gates.status.md"]
effort = "medium"
minutes = 45
+++
# fab's tick and gates status files current

Read first: `docs/plan/dogfood-faults/notes/common.md`,
`docs/plan/dogfood-faults/notes/decisions.md` (11).

The request, item 6. Designs: `docs/design/tick.md` and
`docs/design/gates.md`; their status files are what change.

## What to build

- `docs/design/tick.status.md`: check each of "The flow is a skeleton",
  "Several plans are a skeleton", "The buffer's order is a skeleton",
  "Events are a skeleton" and "Design waits for implementation" against the
  code on main (`fab/flow.py`, `fab/drafts.py`, `fab/buffer.py`,
  `fab/wake.py`, `fab.dispatch.decide`). Move what is built and wired into
  the tick to Present, in the file's style (what is there, where, since
  when if `git log` says); leave under Gaps only what is not. Add under
  Gaps: `fab draft start` is not built (`docs/design/tick.md` 7).
- `docs/design/gates.status.md`: the same for "Gates and the structure
  review are a skeleton" and "Present: (nothing yet)" against
  `fab/gates.py`, `fab/digest.py` and `fab.dispatch._check_calls`. Record
  the gates on skeleton and contract tips (`docs/design/gates.md` 2, now
  designed): Present if the code runs them, Gaps otherwise.

## Acceptance

- Each line moved or kept says why by naming the code (module and
  function) it rests on; nothing in the design files changes.
- `bin/fab test` green; `bin/fab status docs/plan/dogfood-faults` shows no
  plan problems.

## Pre-approved defaults

- A claim you cannot settle by reading the code stays under Gaps with
  what you found; it is not a `Question:`.
- The faults this plan fixes are not recorded here: the retire call does.

## Report

Each heading named above and where it went (Present or Gaps), with the
code it rests on.
