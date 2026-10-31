+++
id = "receipts"
part = "landing-checks"
kind = "feature"
needs = []
files = ["fab/receipts.py", "fab/queue.py", "fab/tests/test_receipts.py", "fab/tests/test_queue.py", "fab/tests/landing_checks.py"]
effort = "high"
minutes = 45
+++
# The queue lands a batch of one on its precheck receipt

Precheck already checks a fabrig tip merged with main in the implementer's
slot and writes a receipt there. The queue checks the same tree again in the
gate lane. Fill `fab/receipts.py` as its docstrings say, and make the queue
take the receipt instead when it names the batch's tip and main. Design:
`docs/design/fab.md`, 13.8 (and 6 for the queue). Nothing delivers receipts
to the gate yet: `receipts-ready` wires `fab.receipts.deliver` into the
dispatcher's ready step.

## What to build

- **`fab/receipts.py`:** every body (`path`, `parse`, `store`, `load`,
  `reusable`, `covers`, `builder`, `deliver`). `covers` uses
  `fab.landing_report.steps` to split the steps; `deliver` uses
  `fab.run.remote_home` and `fab.sh.ssh`.
- **`fab queue receipt TIP`** in `fab.queue.main`, as its docstring says:
  the receipt is read from stdin and kept with `fab.receipts.store` under
  FAB_HOME. TIP takes the positional `branch` already parsed; `untry` and
  `receipt` require it, the other commands refuse it.
- **The reuse in `Queue.attempt`,** the docstring's "A receipt" paragraph:
  when exactly one branch merged, the batch is not a full one and the
  receipt is reusable, the checks are the ratchet steps with `--write` and
  their baseline commit as always, then only the steps named `fmt` of
  `fab.gate.check_steps` for the queue's own selection (metadata loaded as
  today when the selection is a set). The batch record gains `receipt`; the
  batch counts toward the next full one whatever the selection. A red `fmt`
  or ratchet on a reused batch rejects the branch with that step, as today.

## Acceptance

- `fab/tests/test_receipts.py`, in the vocabulary of
  `fab/tests/landing_checks.py` (`receipt`, `receipt_text`, `kept`, `TIP`,
  `MAIN`); add builders there rather than beside a test:
  - `path`: under `receipts/`; a short id, an uppercase id and `../x` are
    ValueErrors;
  - `parse`: a receipt as `receipt()` gives it round-trips with its other
    keys; one ValueError per field (tip differing, main not a SHA, outcome
    unknown, selection a number, steps not a list) and for text that is not
    JSON or not an object;
  - `store` then `load` with a temporary FAB_HOME; a refused receipt writes
    nothing; `load` gives None for a missing file, bad JSON, another tip's
    receipt and a non-SHA tip;
  - `reusable`: green, same tip and main; False for None, red, conflict,
    another main and another tip;
  - `covers`: full selection; the package listed for `pkg` and
    `pkg::wire`; a package not listed; a step the receipt did not run (a
    docs receipt); a red receipt; None;
  - `builder`: the latest implement, repair or rebase run's host; a foreman
    or review run of the task does not count; a host missing from hosts or
    without role builder gives None;
  - `deliver` with `support.FakeRunner`: the `cat` over ssh to the builder
    with `remote_home`, then `fab queue receipt <tip>` over ssh to the
    first gate by name with the text as input, True; nothing run without a
    builder; False and no note when `cat` fails or the receipt is red; a
    note and False for a receipt that does not parse, no gate host and a
    refusing gate (its last err line in the note).
- `fab/tests/test_queue.py`, in `GitTest` with real git and `kept` putting
  the receipt into the queue's FAB_HOME (`self.data`), `check_steps`
  patched to return a `fmt` step and a `check` step:
  - a batch of one with a green receipt naming its tip and main runs `fmt`
    and not `check`, lands, and its batch record carries `receipt`;
  - no receipt, a receipt naming another main, a red receipt, a batch of
    two each with its receipt, and the full_every-th batch all run `check`;
  - a reused batch raises batches_since_full by one, also when its
    selection is full;
  - `fab queue receipt TIP` keeps a receipt from stdin; a bad one exits 1
    with `fab queue: ` and its error; `receipt` without TIP is a usage
    error.
- `bin/fab test` passes; `test_receipts.py` takes under a second and
  `test_queue.py` stays under three seconds.

## Options, settled up front

- `parse` checks only the fields named; it does not check the steps'
  `name:code:seconds` form (`covers` splits them as the landing report
  does).
- Receipts on the gate are never removed for now; a tip's receipt is
  replaced when another arrives.
- `Queue._checks` may take the merged branches as an argument and split
  into private methods; each function stays within 60 lines (the `size`
  gate). The test-step JUnit and the classing of reds are `red-classes`',
  not this task's.
- `deliver`'s `cat` is one argv, `["cat", <path>]`, through `fab.sh.ssh`.
