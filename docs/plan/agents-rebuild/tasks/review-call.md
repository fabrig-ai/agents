+++
id = "review-call"
part = "gates"
kind = "feature"
needs = []
files = ["fab/calls.py", "fab/dispatch.py", "fab/tests/test_calls.py", "fab/tests/test_dispatch.py"]
effort = "high"
minutes = 30
+++
# The structure review call, and when the dispatcher starts it

Fill `review_brief`, `last_review` and `landed_after` in `fab/calls.py` as
their docstrings say, add `"review": <roles>/reviewer.md` to `ROLES`, and
make `main` take `fab call review --plan PLAN_DIR` (subject
`<draft>/review`, `--brief-only` as for the others). Make
`fab.dispatch.call_actions` start review calls as its amended docstring
says (REVIEW_AT, REVIEW_AFTER). The tick already starts any role's call
(`fab call <role> --plan`) and finishes it by landing its branch; it needs
no change. Design: `docs/design/fab.md`, section 12; the role text is
`fab/roles/reviewer.md`.

## Acceptance

- `fab/tests/test_calls.py`:
  - `last_review` with none, a failed and a done review (with and without
    `done`); `landed_after` with None, a ts, and a task of another plan
    left out;
  - `review_brief` on a small hand-built plan with two landed tasks, one
    with a digest under FAB_HOME/digests and one without: every section the
    docstring names, the digest text, `(no digest)`, the design once though
    both cite it; nothing landed gives `(none)`; the BRIEF_LIMIT refusal;
  - `main review --brief-only`.
- `fab/tests/test_dispatch.py` (`CallActionsTest`): a review at REVIEW_AT
  landings and not one before; at REVIEW_AFTER minutes with one landing and
  not with none; counting from the last review's call.started, a failed
  one included; none while a review is in flight; none while
  `<draft>/review` is parked by a question, and one after
  question.answered names it.
- `bin/fab test` passes; the touched test modules stay under a second each.

## Options, settled up front

- The parts table of `skeleton_brief` moves into one private function both
  briefs call; `skeleton_brief`'s output does not change.
- The review action comes after the skeleton action in call_actions' list.
