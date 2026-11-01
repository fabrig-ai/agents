# Request: `bin/fab test`'s budget is CPU time

From agents/loop, 2026-11-01. `fab/testrun.py` fails the suite past 30 s of wall time, so a busy
machine fails a fast suite:
- `mechanisms-out/land-code-first-1` ended `Infra:` at 18:20Z on hetzner6 with every test passing;
- two hand runs on hel8 failed the same way at load 7.

`fab land` runs the same check, so a loaded hel8 can refuse a good branch at `test`.

Build (`docs/design/fab.md` 1 and 4, changed in this request's commit):
- `fab/testrun.py`: measure CPU time, user and system, children included (`os.times()`: `user +
  system + children_user + children_system`, delta from the start). The over-budget check uses
  that. `BUDGET_SECONDS` stays 30.0. The summary prints both, e.g. `2135 tests in 19.5 s wall,
  17.8 s CPU (budget 30 s CPU)`.
- Keep `TimedResult`'s per-test wall times, which name the slow tests.
- Check for readers of the summary line's format (`fab/roles/*.md`, the tests) and update them.
- A test with a fake clock or patched `os.times`: over budget by CPU fails, over 30 s wall but
  under by CPU passes.

The user's rule: dogfood. Built by fab's loop (landed through `bin/fab land`); the plan's landing
is `queue` (the cut is started with `--set 'landing="queue"'`). One direct part, one task.
