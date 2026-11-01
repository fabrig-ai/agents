+++
id = "fab-fetch"
part = "land-refusal-fixes"
kind = "feature"
needs = []
files = ["fab/dispatch.py", "fab/tests/test_dispatch.py", "docs/design/calls.status.md"]
effort = "medium"
minutes = 30
+++
# Only a branch absent from origin ends the chain at `fetch`

Read first: `docs/plan/call-rebase-fixes/notes/common.md`,
`docs/plan/call-rebase-fixes/notes/decisions.md` (2, 3).

The request, finding 1 (blocking): "only a branch gone from origin ends the
chain. [...] Build: failed only on exit 2 (the ref is absent); any other
non-zero code returns None, so the refusal goes on to amend as any passing
`fetch` failure does." Design: `docs/design/calls.md`, 2, "A `fab land`
refusal counts as a refusal of the chain", first sub-bullet ("a `fetch`
refusal whose branch is gone from origin logs `call.finished` failed").

## What to build

- `fab/dispatch.py`, `_finish_outcome` (~930-956): the `fetch` case returns
  `"failed"` only when the `git ls-remote --exit-code origin
  refs/heads/<branch>` result's code is 2; any other code (0, 128, ...)
  falls through to `return None`. Keep the one `ls-remote` call, in
  `checkout`, `check=False`. The docstring says "lost at fetch" means the
  ref is absent (exit 2).
- `fab/tests/test_dispatch.py`,
  `test_finish_land_refusal_steps_and_terminal_exceptions` (~2575): the
  case `("fetch", 128, False, "failed")` becomes `("fetch", 128, False,
  None)`: no `call.finished`, no `question.answered`, the note and the one
  `ls-remote` query as before.
- `docs/design/calls.status.md` (~57): "failed for a `fetch` refusal whose
  branch `git ls-remote` no longer finds" becomes "failed for a `fetch`
  refusal whose branch `git ls-remote --exit-code` reports absent (exit 2)".
  Rewrap the paragraph as it wraps; change nothing else in the file.

## Acceptance

- The test above passes with the changed case; `("fetch", 2, False,
  "failed")`, `("fetch", 2, True, "done")` and the other cases pass
  unchanged.
- `bin/fab test` green; `bin/fab status docs/plan/call-rebase-fixes` shows
  no plan problems.

## Pre-approved defaults

- You may add one more case (another non-zero code, for example 1) to the
  same test's list; no new test function is needed.

## Report

The condition as built, the test cases changed or added, and the status
line as it reads now.
