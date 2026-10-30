+++
id = "queue-checks"
part = "queue"
kind = "feature"
needs = ["atomic-write"]
files = ["fab/gate.py", "fab/queue.py", "fab/precheck.py", "fab/tests/test_gate.py", "fab/tests/test_queue.py", "fab/tests/test_precheck.py"]
effort = "high"
minutes = 35
+++
# The queue and precheck share one check sequence

Section 6 says the selection and the steps are shared through `fab/gate.py`.
They are shared only in part. `fab.queue.Queue.attempt` (117 lines) and
`fab.precheck.precheck` (69 lines) each repeat three things:

- a closure that loads cargo metadata once (`load` and `load_metadata`,
  both with `nonlocal meta`);
- the selection as a record field (`sorted(selected) if isinstance(selected,
  set) else selected`);
- the steps as `name:code:seconds` strings, the form
  `fab.landing_report.steps` parses back.

`attempt` also holds the whole batch inline: preparing, merging, selecting,
ratcheting and committing baselines, checking, pushing, retiring, rejecting,
recording and sweeping. Both functions are over the size gate's 60 lines, so
the next change to either fails `size`. Design: `docs/design/fab.md`, sections
6 and 12.

## What changes

- `fab/gate.py` gains three functions, each with its docstring, and both
  modules use them:
  - `loader(load: Callable[[Path], dict] | None = None, *, sh: Runner = run)
    -> Callable[[Path], dict]`: the metadata loader for one candidate. It
    calls load (default `metadata(repo, sh=sh)`) on the first call and
    returns the same dict after that.
  - `shown(selected: str | set[str]) -> str | list[str]`: the selection as
    records carry it.
  - `step_texts(results: Sequence[StepResult]) -> list[str]`: the
    `name:code:seconds` (3 decimals) strings.
- `Queue.attempt` keeps its signature, docstring and records. Its body is
  split into private methods of `Queue`, each under 60 lines. Default
  split: `_checks(parent, paths, detail, record) -> tuple[bool, list[StepResult],
  str | set[str]]` (selection, ratchet with `--write`, the baseline commit,
  the gate-lane checks, and `batches_since_full`); `_publish(parent)` (the
  clean check, the push with its lease, and moving `origin/main`); and
  `_finish(started_ns, started, record, prepared, clean)` (the reset, the
  sweep and the `batch` record of the `finally`).
- `fab.precheck.precheck` keeps its signature, docstring and receipt. It is
  under 60 lines, with the slot's restore in a private `_restore(git,
  original, branch)`.
- The queue's extra `load(self.repo)` before `check_steps` goes:
  `gate.select` has always loaded metadata when it returns a set. Both
  callers pass `check_steps` the loader's dict when the selection is a set,
  and None otherwise.

## Acceptance

- `fab/tests/test_gate.py`: `loader` calls its load once over two calls
  and passes the repo through; `shown` and `step_texts` give the forms the
  existing queue and precheck tests expect.
- `fab.digest.functions` over `fab/queue.py` and `fab/precheck.py` finds
  no function over 60 lines.
- `test_queue.py` and `test_precheck.py` pass unchanged. A test may be
  added, none weakened.
- `bin/fab test` passes, with no change in behaviour.

## Options, settled up front

- The split methods stay private; `Queue`'s public surface does not change.
- If the default split leaves one method over 60 lines, split it again at
  the next step boundary. Do not compress lines to fit.
