+++
id = "run-place"
part = "run"
kind = "feature"
needs = []
files = ["fab/run.py", "fab/tests/test_run.py"]
effort = "medium"
minutes = 30
+++
# A run's place is taken and given back in one readable step

`fab.run.start` takes a place for the run (a slot of a SLOTTED repository,
else a worktree), launches, and gives the place back when the launch fails.
It does this through two private functions that are hard to follow:

- `_prepare_and_launch(task, host, kind, remote, *, run_id, branch, base,
  root, repo, worktree, brief_path, report_path, text, log_path)` takes
  fourteen arguments. Its fourth, named `remote`, is the runner: the body
  does `sh = remote`, then defines its own `remote` closure over ssh.
  `brief_path` and `report_path` are passed and never read: `launch`
  computes both again.
- `fab slot list` is read twice, in `_prepare_and_launch` (the idle slot)
  and `_undo_start` (the slot this run claimed). Both run `json.loads` on
  each line of a builder's output with no guard, which the taste pair "A
  line from another machine may not parse" rules out. A torn line in the
  first raises a JSONDecodeError out of `start`; in the second it is
  swallowed with the release it was meant to do.

Design: `docs/design/fab.md`, sections 5 and 7.

## What changes

- `start` keeps its signature, docstring and behaviour. Its body reads as
  its steps: the ids, paths and brief; `fetch_clone`; `_take_place` (claim
  a slot and switch it to the branch, or add the worktree) returning the
  workdir and run.started's extra fields (`{"slot": n}` or `{}`); `launch`;
  and on any failure `_give_back`, today's `_undo_start`.
- The private functions take the runner as `sh: Runner` and build their
  own `remote` from it, as `start` does. No parameter is passed and unused.
- One private `_slot_entries(output: str) -> list[dict]` reads `fab slot
  list`: the JSON objects of its lines with an int `slot`, skipping blank
  and malformed lines. Both readers use it. With no idle slot left after
  skipping, the ValueError naming the host is unchanged.
- `fab.digest.functions` over `fab/run.py` finds no function over 60
  lines, as today.

## Acceptance

- `fab/tests/test_run.py`: a `fab slot list` output with a torn line still
  claims the idle slot the good lines name; a failed launch of a slot run
  releases the claimed slot even with a torn line in the listing.
- Every existing test in `test_run.py` passes unchanged: the argv over ssh
  and their order are the same. A test may be added, none weakened.
- `bin/fab test` passes; skipping a torn slot line is the one change in
  behaviour.

## Options, settled up front

- The split functions stay private; `fab.run`'s public surface does not
  change.
- `_give_back` still ignores its own errors: the launch's error is the one
  `start` raises.
