+++
id = "after-landing-verdicts"
part = "after-landing"
kind = "feature"
needs = []
files = ["fab/after_landing.py", "fab/tests/test_after_landing.py"]
effort = "medium"
minutes = 20
+++
# after-landing: suspects, test states, verdicts

Fill `suspects`, `state` and `verdict` in `fab/after_landing.py` as their
docstrings say. Leave `AfterLanding` and `main` raising
NotImplementedError; `after-landing-runner` fills them. Design:
`docs/design/fab.md`, section 11.

## Acceptance

- `fab/tests/test_after_landing.py` covers:
  - suspects with real git on `support.git_pair`: a plain commit, a merge
    `Merge drafty/task-a` and an old-style `Merge ready/drafty/task-b`
    (both named, oldest first), a merge with another subject (no branch),
    a commit on a merged branch not listed (first parent only), and
    previous None giving none;
  - state for every row of its docstring, and each ValueError;
  - verdict: red over a fault, partial, green, and green for no states.
- `bin/fab test` passes; `test_after_landing.py` takes under a second.

## Options, settled up front

- suspects asks git once per commit for parents and subject, as the old
  tool did; batching is not needed.
