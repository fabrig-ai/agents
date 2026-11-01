# fab-gates status

2026-11-01. Contract: `docs/design/fab-gates.md`. Split from `docs/design/fab.status.md`.

## Present

- (nothing yet)

## Gaps and departures

- **Gates and the structure review are a skeleton:** `fab/digest.py` and
  `fab/gates.py` hold section 2's signatures and contracts, and
  `fab.calls.review_brief`, `last_review` and `landed_after` the review
  call's; `fab/taste.md` and `fab/roles/reviewer.md` are written. The tasks
  `digest`, `digest-render`, `gates`, `taste-brief` and `review-call` fill
  them; `gates-tick` turns the gates on in the tick. Until it lands every
  branch lands ungated and no review call starts. Once it does, a change to a
  function already over 60 lines (`fab.dispatch.tick` among them) fails
  `size` and must split it.
