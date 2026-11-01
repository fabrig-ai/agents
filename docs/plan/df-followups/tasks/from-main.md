+++
id = "from-main"
part = "from-main"
kind = "feature"
needs = []
files = ["fab/integration.py", "fab/tests/test_integration.py", "fab/designer.py", "fab/tests/test_designer.py", "fab/calls.py", "fab/tests/test_calls.py", "fab/triage.py", "fab/tests/test_triage.py", "fab/dispatch.py", "fab/tests/test_dispatch.py"]
effort = "medium"
minutes = 60
+++
# Calls after a trunk lands start from main

Read first: `docs/plan/df-followups/notes/common.md`,
`docs/plan/df-followups/notes/decisions.md` (3-6), then
`docs/design/integration.md` 3, "Retire waits for main".

The request's item 1. Today only the retire moves to main once the trunk
has landed; the queue deletes `<draft>/integration` and the clone prunes
`refs/remotes/origin/<trunk>`, so between the trunk's landing and the
retire's an answer, review, triage or amend call fails at `worktree add`
every round, and `_integration` logs a "failed:" note every tick from its
`_contains`/`rev-parse` of `origin/<trunk>`.

## What to build

- **`fab/integration.py`:** `call_base(plan, events) -> str` beside
  `trunk_landed` (~38), with a docstring (decision 3).
- **`fab/designer.py` `main`** (~509): `base = integration.call_base(plan,
  events)` for every role, replacing the retire-only expression; the
  docstring (~490) says every role uses main after the trunk lands.
- **`fab/calls.py` `main`** (~775): `start(..., base=integration.call_base(plan,
  events), ...)`; `events` is already read there.
- **`fab/triage.py` `main`** (~332): the same at its `calls.start` call
  (decision 4), reading the log once for both the brief and the base.
- **`fab/dispatch.py`:** `_start` (~1498), `_foreman` (~1545) and
  `_examine` (~1623) pass the helper's base as `trunk`, fix kinds keeping
  `"main"` (decision 5); `_integration` (~1979) returns before its git
  reads once the trunk landed (decision 6).

Change these lines only: the three `main`s at their `start(...)` call, the
four dispatch functions at the lines named.

## Acceptance

- `test_integration.py`, beside `test_trunk_landed_requires_its_queue_landing`:
  `call_base` is `plan.trunk` for an integration plan before its
  `branch.landed` (with `queue_ts`) for `<draft>/integration`, `"main"`
  after, and `plan.trunk` for a queue plan whatever the log holds.
- `test_designer.py`: `test_other_designer_roles_keep_trunk_after_queue_landing`
  flipped (renamed to say so): contract and decision start from `main`
  once their plan's trunk landed; the cut of another draft (`new`) keeps
  its own trunk unless its own trunk landed.
  `test_retire_base_requires_own_queue_landing` still passes.
- `test_calls.py`, beside the test at ~1422: answer, review and amend
  start from `main` after the landing and from the trunk before it.
- `test_triage.py`: the triage start's base is `main` after an
  integration plan's trunk landed.
- `test_dispatch.py`, beside the existing tests of each function: after
  the landing, a foreman start and a refusal (`_examine`) start pass
  `trunk="main"`, and a task start too; before it, `plan.trunk` as today.
  An integration tick with `ready = true` after the landing runs no
  `merge-base`/`rev-parse` of `origin/<trunk>` and logs no `failed:`
  note (beside `test_main_ancestry_error_is_not_treated_as_main_moving`,
  ~5700).
- `bin/fab test` green.

## Pre-approved defaults

- A test that pins `plan.trunk` for a start after a trunk landed (other
  than the one the request flips) is updated to `main`, named in your
  report.
- Rebase over `start-commands/brief-park` or `mechanisms-out` changes in
  the same `main`s or in `fab/dispatch.py`; yours are at the lines above.

## Report

The sites changed, by function; the tests added or flipped.
