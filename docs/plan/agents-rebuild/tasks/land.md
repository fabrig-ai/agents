+++
id = "land"
part = "land"
kind = "feature"
needs = []
files = ["fab/land.py", "fab/tests/test_land.py"]
effort = "high"
minutes = 25
+++
# bin/fab land

Fill the bodies of `fab/land.py` (`outside`, `task_of`, `land`, `main`) as
their docstrings say. Design: `docs/design/fab.md`, section 6. The landing is
what every later task of this plan lands through, so keep it plain and sure.

## Acceptance

- `fab/tests/test_land.py`, with real git on `support.git_pair` (an origin and
  a clone), covers: a branch landing (main fast-forwarded, the branch deleted
  on origin, the outcome's tip equal to origin's main); a rebase conflict
  (refused, checkout clean and detached, main unchanged); a path outside
  ALLOWED (refused, naming it); a red test (refused with its output's tail);
  main moving between fetch and push (one retry, then landed), driven by a
  test command that pushes a commit to origin's main the first time it runs.
- `main` is covered with a temporary FAB_HOME: the log gets branch.landed or
  branch.rejected with the docstring's fields, and the exit code follows.
- Pure tests for `outside` and `task_of`.
- `bin/fab test` passes; `test_land.py` takes under three seconds.

## Options, settled up front

- `test` in the tests is a small argv (`["true"]`, `["false"]`, or a
  `python3 -c` one-liner), never `bin/fab test` itself.
- Use the real runner (`fab.sh.run`) for git in these tests; the fake runner
  is not needed here.
- `git rebase` with `-c user.name=fab -c user.email=fab@localhost` where the
  checkout has no identity configured is fine; do not touch global config.
- A branch that is already contained in main lands as a no-op: landed, the
  branch deleted, detail saying so.
