+++
id = "report-code"
part = "report"
kind = "feature"
needs = ["report-base"]
files = ["fab/code_report.py", "fab/tests/test_code_report.py"]
effort = "high"
minutes = 30
+++
# The code report

Fill the bodies of `fab/code_report.py` (`spans`, `peak`, `hourly`, `gaps`,
`stops`, `figures`, `parts`, `signals`, `render`) as their docstrings say,
using `fab.report`'s helpers, `fab.state.fold` and
`fab.calls.open_questions` as they are. Design: `docs/design/fab.md`,
section 10; the metrics are `docs/design/draft/code-producing-pipeline.md`,
section 3.

## Acceptance

- `fab/tests/test_code_report.py`, with plain event dicts (ts strings in
  `fab.log.now()`'s format), a small `Plan` and tasks built in the test, and
  hosts from `fab.hosts.parse`, covers:
  - `spans` pairing starts and ends, an unended run, another draft's run
    ignored;
  - `peak` with overlapping runs, one ending as another starts, a run still
    in flight, and runs outside the range;
  - `hourly` over a three-hour window, the last hour cut;
  - `gaps`: one long enough with its cause, one too short, none once every
    task is landed, one open at the window's end;
  - `stops` of each kind, open and closed, ranked and cut at TOP_STOPS;
  - `figures`: every FIGURES key present, each computed once from a log that
    exercises it (runs per landed task counting runs before the window, a
    malformed tokens value, heavy waits on a builder and not on the gate);
  - `signals` in order, and none for a quiet day;
  - `render`: each section heading, a figure with its previous value, and
    `No run yet.` for an empty log.
- `bin/fab test` passes; `test_code_report.py` takes under half a second.

## Options, settled up front

- Times are compared as ts strings and turned into datetimes only to
  measure minutes (`fab.report.minutes`).
- Private helpers are yours; the public functions keep their signatures.
- A Stop's minutes and every figure in minutes are floats, not rounded;
  rounding is `fab.report.show`'s.
