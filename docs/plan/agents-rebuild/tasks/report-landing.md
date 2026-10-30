+++
id = "report-landing"
part = "report"
kind = "feature"
needs = ["report-base"]
files = ["fab/landing_report.py", "fab/tests/test_landing_report.py"]
effort = "high"
minutes = 30
+++
# The landing report

Fill the bodies of `fab/landing_report.py` (`steps`, `busy_seconds`,
`latencies`, `waiting`, `bisections`, `step_rows`, `figures`, `signals`,
`render`) as their docstrings say, using `fab.report`'s helpers and
`fab.gate.NO_TESTS`. The records are those `fab.queue.Queue.attempt`
writes (`batch`, `landed`, `rejected`) and the log's `branch.ready`. Design:
`docs/design/fab.md`, section 10; the metrics are
`docs/design/draft/landing-pipeline.md`, section 3.

## Acceptance

- `fab/tests/test_landing_report.py`, with plain record dicts shaped as
  `fab/queue.py` writes them and a `fab.report.Sources` built in the test,
  covers:
  - `steps` parsing a name holding a colon, a malformed entry skipped, and
    green for build with NO_TESTS but not for clippy with it;
  - `latencies` joining on branch and tip, a re-readied branch using its
    latest ready, a branch never marked ready left out;
  - `waiting`: a landed and a rejected tip not waiting, a newer ready tip of
    a rejected branch waiting;
  - `bisections`: a red batch of four split into halves and quarters, then an
    unrelated batch ending it;
  - `step_rows` with failures and a timeout;
  - `figures`: every FIGURES key present and each computed once, including a
    collateral rejection landed after the window and repair rounds counting
    rejections before it;
  - `signals` in order, and none for a quiet day;
  - `render`: each section heading and an error's first line.
- `bin/fab test` passes; `test_landing_report.py` takes under half a second.

## Options, settled up front

- An `error` batch with no branches (a failed cycle) counts in `error` but
  not in `batches`.
- Percentages are 0-100 floats; `show` rounds them.
- Private helpers are yours; the public functions keep their signatures.
