+++
id = "queue-sweep"
part = "queue"
kind = "feature"
needs = []
files = ["fab/queue.py", "fab/tests/test_queue.py"]
effort = "medium"
minutes = 15
+++
# The queue bounds its own target

hetzner8's gate checkout held 199 GB of build output on 10-30, unbounded as
the slots were. Make `Queue.attempt` end with the sweep its amended docstring
names, using `fab.slots.sweep_plan` and `fab.slots.remove` as they are.

## Acceptance

- `fab/tests/test_queue.py` gains a test: a fake `target/debug` with an
  incremental directory and an old test executable is swept after a green
  batch and after a red one, a fresh executable is kept, and the batch
  record carries `freed`.
- `bin/fab test` passes; `test_queue.py` stays under three seconds.

## Options, settled up front

- A sweep that raises is recorded in the batch record as `sweep_error`; the
  attempt's outcome stands.
