+++
id = "precheck-collector"
part = "precheck-collector"
kind = "interface"
needs = []
files = ["fab/precheck.py", "fab/queue_cpu.py", "fab/tests/test_precheck.py", "fab/tests/test_queue_cpu.py", "fab/tests/landing_checks.py"]
effort = "medium"
minutes = 60
+++
# Precheck's test steps through the queue's collector

Read first: `docs/plan/precheck-starved/notes/common.md`,
`docs/plan/precheck-starved/notes/decisions.md`, then
`docs/design/landing.md` 2, "Starvation stays green in the gate" and "The
selection and the steps are shared".

The request: `v0.1.0-ladder/finding-5-2`'s precheck went red only on the
default suite's 120 s global timeout (23,338 passed, 7 SIGTERMed, 938 never
ran, nothing asserted). The queue calls that green; `fab precheck` runs
its steps through `gate.run_steps`, which checks exit codes only, so a
run's own check refuses what the queue would land.

## What to build

- **`fab/queue_cpu.py` `run_steps`** (~118): a `lane: str = "gate"`
  keyword passed to `cpu.build_wrapper` (decision 2). Docstring says so.
- **`fab/precheck.py` `precheck`** (~65): replace `gate.run_steps(steps,
  log_path, sh=sh)` with `queue_cpu.run_steps(steps, log_path, record,
  lane="build", sh=sh)` (decision 3); its non-test steps keep
  `gate.run_steps` inside it. Before the steps, remove
  `FAB_HOME/precheck/<tip>/` (decision 6). From the returned reports, the
  receipt's `starved` (decision 4) and one log line per starved case
  (decision 5). `outcome` from the steps' `green` as today. Move the
  check section into a private helper if `precheck` would pass the 60-line
  cap. Docstring: the receipt's `starved`, the collector.

## Acceptance

In `fab/tests/test_precheck.py`, beside the existing green and red tests,
with real git as there and `FakeNextest` (in the style of
`fab/tests/test_queue_cpu.py`) for the checks:

- A default run cancelled by the global timeout (starved cases, passes,
  no failure, nextest exit 100): receipt `outcome` green, `starved` > 0
  equal to the starved cases, the log naming each starved test; the slot
  restored.
- The same with an assertion failure beside the starved: red, the
  `default` step's code 100, no fuzzy after it.
- A docs-only and a conflict receipt carry `starved` 0;
  `assert_receipt`'s key set gains `starved`.
- Checking the same tip twice works (the collector directory replaced).
- The build lane: no `heavy --gate` in precheck's commands.

In `fab/tests/test_queue_cpu.py`: `lane="build"` builds the wrapper with
`heavy cc` (no `--gate`); the default stays `--gate`.

`bin/fab test` green.

## Pre-approved defaults

- `FakeNextest` fakes only `heavy --gate cc`; a build-lane `heavy cc`
  already falls through to `Result(0)`. Change `fab/tests/landing_checks.py`
  only if a fallback runner swallows it, and then only to fake `heavy cc`
  the same way.
- Precheck tests whose checks use `FakeRunner` and never reach a test step
  stay as they are, apart from the receipt's new key.
- `fab/receipts.py` needs no change: `parse` keeps other keys.

## Report

The functions changed, the receipt's new field with an example, a starved
precheck's log lines, and the tests added.
