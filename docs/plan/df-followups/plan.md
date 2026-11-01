# df-followups: the plan

Two direct parts, one task each, as the request asks ("item 1 by itself,
and items 2-4 together"), in its order:

- `from-main` (`docs/design/integration.md`, 3, "Retire waits for main",
  widened in the request's commit): after an integration plan's trunk
  landed, every call (all roles), foreman and refusal start begins from
  main, and `_integration` takes no git read of `origin/<trunk>`. It must
  land before the next fabrig integration plan lands its trunk.
- `small-fixes` (items 2-4): the branch probe in `fab/run.py` raises on an
  error, `answer_brief` shows a stop's empty report as none, and the two
  stale status lines in `docs/design/integration.status.md` and
  `docs/design/tick.status.md`.

`small-fixes` needs `from-main`: both change `fab/calls.py` and
`fab/tests/test_calls.py` (`main` and `answer_brief`). Specs in `tasks/`,
the standing rules in `notes/common.md`, the decisions and the critical
path in `notes/decisions.md`.

## Overlaps with drafts beside this one

These could not be avoided; each is a few lines at a named site:

- `start-commands/brief-park` changes the three `main`s (`fab/calls.py`,
  `fab/designer.py`, `fab/triage.py`) at their compile step and
  `fab/dispatch.py` (`_call`, `_parked_subjects`); `from-main` changes the
  same `main`s only at their `start(...)` call, and in `fab/dispatch.py`
  only `_start`, `_foreman`, `_examine` and `_integration`. The request lets
  them run beside each other on that ground.
- `mechanisms-out/plan-options` (`fab/designer.py` `main`, the cut's seed;
  `fab/calls.py`; `fab/dispatch.py`'s finish) and
  `mechanisms-out/land-code-first` (`fab/calls.py` `_chain_call`;
  `fab/dispatch.py` `call_actions`): `from-main` touches none of those
  functions; whichever lands second rebases.
- `small-fixes` changes `fab/run.py` and `answer_brief`, which no draft
  beside this one changes, and two status files no other task edits.
- Tests: every task puts its tests beside the tests of the function it
  changes, never at a file's end, so the rebases stay clean.
