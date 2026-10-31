+++
id = "receipts-ready"
part = "landing-checks"
kind = "feature"
needs = ["receipts", "designer-tick", "channel-tick", "repairs-tick"]
files = ["fab/dispatch.py", "fab/tests/test_dispatch.py"]
effort = "medium"
minutes = 15
+++
# The dispatcher carries a tip's receipt to the gate when it readies it

`fab.receipts.deliver` (filled by `receipts`) reads a tip's precheck
receipt on the builder of the task's last run and hands it to the queue.
Nothing calls it yet. Make the dispatcher's ready step call it, so the
queue finds the receipt when it takes the ready ref. Design:
`docs/design/fab.md`, 13.8.

## What to build

- **`fab.dispatch._ready`:** once the tip is known, and after the untry of
  a same-tip rejection, call `fab.receipts.deliver(action.task, tip,
  log.read(log_path), hosts, sh=sh, log_path=log_path)`, then push the
  ready ref as today. Its result changes nothing: a tip without a
  receipt is readied all the same, and the queue checks it in full. Say so
  in the docstring.

## Acceptance

- `fab/tests/test_dispatch.py`, beside the existing ready tests and with
  their fake runner and hosts:
  - a ready with a builder run in the log: the `cat` over ssh to that
    builder, then `fab queue receipt <tip>` over ssh to the gate with the
    receipt as input, both before the ready push;
  - a builder whose `cat` fails: no receipt command, the ready push and
    branch.ready as today;
  - the same-tip untry still comes first;
  - the existing ready tests pass unchanged, adding rules to their fake
    runner where they need one.
- `bin/fab test` passes; `test_dispatch.py` stays within its time.

## Options, settled up front

- `_ready` reads the log once more for `deliver`, as it already does for
  the rejection; no new argument is threaded through `_take`.
