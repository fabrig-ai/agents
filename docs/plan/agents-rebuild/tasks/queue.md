+++
id = "queue"
part = "queue"
kind = "migration"
needs = ["gate"]
files = ["fab/queue.py", "fab/tests/test_queue.py"]
effort = "high"
minutes = 30
+++
# fabrig's merge queue, ported

Fill the bodies of `fab/queue.py` as their docstrings say, using `fab.gate`
for selection and steps. Design: `docs/design/fab.md`, section 6. The source
is fabrig's `tools/queue/mq` on the builder at
`~/src/fabrig/main/tools/queue/mq` (`list_candidates`, `build_batch`,
`merge_ratchets`, `bisect`, `Queue.attempt`, `Queue.cycle_once`). Keep the
landing rules; leave out repair pins, publication intents and journals,
writer leases, train/worker/recovery, tools suites, posts and the idle full
check, as the docstrings do.

## Acceptance

- `fab/tests/test_queue.py`, with real git on `support.git_pair` and checks
  replaced (patch `fab.gate.check_steps` to return a step that is `true` or
  `false` per branch content, and pass a fake `load`), covers:
  - candidates: oldest first, tried tips left out, non-ready refs ignored;
  - a green batch of two: main advanced to the merge, both ready refs and task
    branches deleted on origin, `landed` records;
  - a conflict: rejected with step merge, the others still land;
  - a red batch of three with one bad branch: bisection lands the two good
    ones and rejects the bad one, marking its tip tried;
  - main moving under the queue: the push is refused, nothing marked tried,
    an error recorded, the next cycle lands it;
  - bisect as a pure function with a fake check;
  - `run` stopping at the stop file, and `log --since`.
- `bin/fab test` passes; `test_queue.py` takes under three seconds.

## Options, settled up front

- Ratchet conflict handling may be tested only through `build_batch` with a
  fake `old_forms.py` script in the fixture tree.
- The batch id in log names is the batch's start time, `YYYYMMDDTHHMMSSZ`.
