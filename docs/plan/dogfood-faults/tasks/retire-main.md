+++
id = "retire-main"
part = "retire-main"
kind = "feature"
needs = []
files = ["fab/designer.py", "fab/tests/test_designer.py", "fab/dispatch.py", "fab/tests/test_dispatch.py"]
effort = "high"
minutes = 50
+++
# An integration plan's retire works from main

Read first: `docs/plan/dogfood-faults/notes/common.md`,
`docs/plan/dogfood-faults/notes/decisions.md` (2, 3).

The request, item 1. Design: `docs/design/integration.md`, 3, "Retire waits
for main" ("It then works from main, not the trunk ...").

## What to build

- `fab/designer.py`, `main` (~509, `calls.start(..., base=plan.trunk)`):
  the retire call starts from `main` once `fab.integration.trunk_landed(plan,
  events)`; every other role, and retire before the trunk landed, keeps
  `plan.trunk`.
- `fab/dispatch.py`, `_deliver` (~803): an integration plan whose trunk has
  landed (`integration.trunk_landed(plan, log.read(log_path))`) delivers as
  a queue plan does: `_queue_branch` for fabrig, `_land_branch` otherwise;
  never `_merge_branch`. This covers the retire and any other call of the
  plan delivered after the landing. Before the landing, nothing changes.
- `fab/dispatch.py`, `_checkout` (~1158), given the log: `_load_plans`
  passes its `events`. After the fetch, when the plan's trunk has landed
  (a `branch.landed` with `queue_ts` for task `<draft>/integration`, the
  draft being the plan directory's name, as `trunk_landed` reads it), the
  checkout moves detached to `origin/main` (`git checkout -q --detach
  origin/main`) instead of following its upstream, at every fetch. The
  queue deleted the trunk branch, so its upstream is gone.

## Acceptance

- designer: the retire call of an integration plan whose trunk landed (a
  fixture log) starts with base `main`; before the landing, with
  `plan.trunk`; a cut or answer call keeps `plan.trunk`.
- dispatch: a finish of a call of a landed-trunk integration plan of repo
  fabrig readies `ready/calls/<id>` and logs `branch.ready`, with no merge
  into the trunk; before the landing it merges into the trunk as today.
- dispatch: `_checkout` of a plan directory whose trunk landed runs the
  detach after the fetch and no `merge --ff-only`; any other plan follows
  its upstream as today; a fetch failure is shared as today.
- `bin/fab test` green.

## Pre-approved defaults

- `_finish_outcome` and `_record_finish` stay as they are: a fabrig plan's
  call is finished when `_queue_branch` sees the queue's landing.
- A checkout already fetched this round (`fetched`) is not detached again.

## Report

Each changed function and the condition it reads; the tests added.
