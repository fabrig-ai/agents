+++
id = "queue-depth"
part = "queue-depth"
kind = "feature"
needs = []
files = ["fab/queue.py", "fab/tests/test_queue.py"]
effort = "medium"
minutes = 35
+++
# The queue takes ready refs of any depth

Read first: `docs/plan/dogfood-faults/notes/common.md`,
`docs/plan/dogfood-faults/notes/decisions.md` (4).

The request, item 2. Design: `docs/design/landing.md`, 2 (the ready refs,
"fixed 11-01").

## What to build

- `fab/queue.py`, `candidates` (~36-51): take every
  `refs/remotes/origin/ready/<name>` whose name has two segments or more
  (`ladder/<draft>/backlog-<n>`, `answers/<run>`, `repairs/<run>` with
  slashes in the run id). `Branch.name`'s comment and the docstrings say so.
- Check the rest of `fab/queue.py` (the batch, the landing and its ref
  cleanup, the rejection and collateral records, untry) and
  `fab/dispatch.py` `_import_queue` and `_queue_record` for the same
  two-segment assumption. Today `_queue_record` reads deep branches through
  `owners` (backlog, answers, repairs), so no dispatch change is expected.

## Acceptance

- `candidates` returns `ladder/v0.1.0-ladder/backlog-1`,
  `answers/<draft>/<task>/foreman-1` and a two-segment name, oldest first,
  and still leaves out a tried tip; a one-segment `ready/x` is left out.
- A batch with a deep name lands: its `ready/<name>` and `<name>` refs are
  deleted with their leases and the `landed` record names the full branch.
- `bin/fab test` green.

## Pre-approved defaults

- An assumption found outside `fab/queue.py` is reported, not fixed: say
  where in the report (a `Question:` only if it stops a deep ref landing).

## Report

The rule as built; each place checked and what it does with a deep name.
