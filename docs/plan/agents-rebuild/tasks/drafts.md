+++
id = "drafts"
part = "plans"
kind = "feature"
needs = []
files = ["fab/drafts.py", "fab/tests/test_drafts.py"]
effort = "high"
minutes = 30
+++
# What each draft owns, and what plans share in one tick

Fill the bodies of `fab/drafts.py` as their docstrings say. Design:
`docs/design/fab.md`, 13.4, with 13.2 and 13.3. The functions are pure.
`plans-tick` makes the tick use them. It waits for the tasks that change
`fab/dispatch.py` now, so this module comes first, apart from them.

It uses `fab.flow.target` and `fab.plan.Plan`, both on main. Its tests
speak in `fab/tests/support.py`'s vocabulary for several plans:
`write_plan`, `run_started`, `run_ended`, `call_started`, `call_ended` and
`units`. `fab.dispatch.in_flight` gives the `flight` the functions take.

## What to fill

- `under`, `owned` and `strays`: which runs in flight are a draft's.
- `design_calls`: a plan's design calls to start, up to its flow target.
- `spend`: the calm map after a plan has used builders.
- `unit`: a call's unit name, keyed by its subject.

## Acceptance

- `fab/tests/test_drafts.py`:
  - Remove the skip from the exemplar test. It passes unchanged.
  - `under`: the draft itself, a name under it, a draft that only shares
    a prefix (`one` and `one-more/x`), and a non-string.
  - `owned`:
    - task runs and foreman runs;
    - a review run of the draft's call, and one of another draft's call;
    - a review run whose call has no call.started;
    - records with no task, or a task that is not a string.
  - `strays`: none when every run is owned; a run of a draft not listed.
  - `design_calls`:
    - START calls from nothing in flight;
    - more once `fab.flow.target` has grown (use landings with full
      windows, as `fab/tests/test_dispatch.py`'s `growth` does);
    - none when the calls in flight reach the target;
    - an ended call no longer counts;
    - another draft's calls and an answer or review call do not count;
    - a fresh part whose subject has a call in flight is skipped, and the
      next part is chosen;
    - an unknown part is skipped;
    - contract against skeleton roles.
  - `spend`: None, a builder started on, a builder not in calm.
  - `unit`: a subject with `/`, a root call's id, a key with other
    characters, and a ValueError for an empty role or key.
- `bin/fab test` passes; `test_drafts.py` takes under a second.

## Options, settled up front

- `owned` looks up a review run's call by the run's `task`, the root
  call's id, not by its `call` field (which may be an amend's).
- `design_calls` counts only skeleton and contract calls (DESIGN_ROLES).
  An amend call is not part of the limit.
- `unit` replaces each character by itself: no escape sequences, no
  hashing.
