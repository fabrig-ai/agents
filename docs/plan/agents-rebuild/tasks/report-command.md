+++
id = "report-command"
part = "report"
kind = "feature"
needs = ["report-code", "report-landing"]
files = ["fab/report.py", "fab/cli.py", "fab/tests/test_report.py", "fab/tests/test_package.py"]
effort = "medium"
minutes = 20
+++
# fab report

Fill `fab.report.main` as its docstring says, and add `report` to
`fab/cli.py`'s COMMANDS ("the standing reports of a plan and of the
landing"). Design: `docs/design/fab.md`, section 10.

## Acceptance

- `fab/tests/test_report.py` gains tests, under a temporary HOME and
  FAB_HOME, with `fab.report.gather` patched to return fixed Sources (no
  ssh) and `fab.hosts.load` patched:
  - `code` on a plan directory written in the test prints a report starting
    `# Code report:`; with `--write` the file is at
    `FAB_HOME/reports/<draft>/<day>.md` and its path is printed last;
  - `landing --day` writes under `reports/landing/`;
  - `daily` writes yesterday's reports, and a second run prints `kept` for
    each and rewrites none; a plan that does not load is reported
    on stderr with exit 1 and the landing report still written;
  - a bad day exits 2.
- `fab/tests/test_package.py`: `fab --help` lists `report`.
- `bin/fab test` passes; `test_report.py` stays under a second.

## Options, settled up front

- argparse subcommands, as `fab/queue.py` parses its own; no new dependency.
- `daily` gathers once with `since` from yesterday's window, for every
  report it writes.
