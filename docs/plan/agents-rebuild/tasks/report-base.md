+++
id = "report-base"
part = "report"
kind = "feature"
needs = []
files = ["fab/report.py", "fab/tests/test_report.py"]
effort = "medium"
minutes = 25
+++
# What both reports share: windows, sources, figures' text

Fill the bodies of `fab/report.py` as their docstrings say, every one but
`main`: `Window`'s methods, `stamp`, `moment`, `minutes`, `day_window`,
`within`, `quantile`, `show`, `trend`, `table`, `figure_table`,
`heavy_waits`, `signal_lines`, `gather` and `report_path`. Leave `main`
raising NotImplementedError; `report-command` fills it. Design:
`docs/design/fab.md`, section 10.

## Acceptance

- `fab/tests/test_report.py` covers:
  - `day_window` for a given day and for today so far, a bad day and a day
    after now refused; `Window.holds` at both edges, `hours`, `previous`;
  - `stamp` and `moment` round-tripping `fab.log.now()`'s format;
  - `quantile` on none, one and an even count of values (0.5 and 0.9);
  - `show` for None, an int, a bool and a float; `trend`; `table` escaping a
    `|` and a newline; `figure_table` with a key missing from one side;
  - `heavy_waits` summing two hosts' records in the window and ignoring one
    outside it, another host and a non-heavy record;
  - `gather` with `fab.tests.support.FakeRunner` and hosts built with
    `fab.hosts.parse`: the ssh argv of the queue and of each heavy read, a
    torn line skipped, heavy records before `since` dropped, a failing ssh
    named in `unread` with the other sources still read, no gate host, and
    the log read from a file under a temporary FAB_HOME.
- `bin/fab test` passes; `test_report.py` takes under half a second.

## Options, settled up front

- Datetimes through `datetime` with `timezone.utc`; no new dependency.
- `gather` passes no `check=True`; it reads each result's `ok`.
- `heavy_waits` returns every key (commands, lane_wait, disk_wait,
  disk_refused) even when nothing was recorded: 0, 0.0, 0.0, 0.
