# Fix mode's names and records

For every findings-repair task: what the tasks bind for one another
(`docs/design/fab-qa.md`, 2).

## fab/fix.py (task fix-module)

- `FIX_KINDS = ("red", "finding")` and `RUNS = 2`. `fab.tier_reds.RED_RUNS`
  stays, equal to `fab.fix.RUNS`; `fab.tier_reds.KIND` stays `"red"`.
  `fab.fixes.KIND = "finding"`.
- `launch(task_id, host, tip, brief, events, *, sh=run, log_path=None,
  **fields) -> str`: the run id `fab.run.next_run(fab.foreman.task_field(
  task_id), events)`, then `fab.run.launch_detached(host, run, "fabrig",
  tip, ...)` with task `foreman.task_field(task_id)`, kind
  `foreman.KIND`, effort `foreman.EFFORT`, branch task_id, base tip,
  brief, and `fields` on run.started. `brief` is a callable from
  (run id, report path) to the brief's text, since the brief names both.
- `report_path(host, run) -> str`: `fab.run.remote_home(host)/runs/<run>/
  report.md`.
- `parse(report, *, skip=None) -> tuple[str, str, list[str], list[str]]`:
  (verdict `fix`, `left` or `none`, reason, lines, skipped). The first
  non-blank line is `Done: fix: <line>` or `Done: retry: <line>`; retry is
  `left`; anything else is `none` with reason `no verdict: <the first line,
  at most 120 characters>`. For fix, lines are the next `SECTION_LINES`
  (30) lines right-stripped; `skip` is a predicate on the line straight
  after the first: when it holds, that line is taken out and returned in
  `skipped` (red's `Owner:` line).
- `section(heading, reason, lines) -> str`: `<heading>`, a blank line, the
  reason and lines with trailing blank lines dropped, ending with a newline.
- `settle(ev, fields, *, log_path=None) -> dict`: one `fab.log.now()`
  stamp; appends `ev` with `ts` the stamp and `fields(stamp[:10])`'s
  fields; returns the record.
- `answers(events) -> dict[str, list[str]]`: each task's `question.answered`
  answers in log order (non-empty `answer`), as `tier_reds.repair_tasks`
  scans them.
- `task(task_id, kind, part, body, answers) -> fab.plan.Task`: repo
  `fabrig`, no needs, files `("**",)`, effort `high`, 20 minutes, no path,
  body with `\n## Answers\n\n- <answer>` lines appended when answers is
  not empty.

## Records the finding's path writes

- The foreman's `run.started`: task `<draft>/finding-<n>/foreman`, run
  `<draft>/finding-<n>/foreman-1`, kind `foreman`, `finding` (its id) and
  `tip` (main's tip in the plan's checkout this tick). Its `run.ended`
  comes from the usual collect, `report` the local report path.
- `finding.settled`: finding, run (the foreman run), verdict (`fix`,
  `left` or `none`), reason, section (`## Repair (<day>, finding <n>,
  foreman <run>)` and the foreman's lines for fix; "" otherwise).
- The repair's runs and landing: task `<draft>/finding-<n>`, kind
  `finding`, part `qa`, as a red task's are.

## The action pair (task fix-pair, then tick-findings)

- `Action("examine-fix", task=<repair id>, detail=<red or finding id>,
  run_kind=<kind>)` and `Action("remedy-fix", task=<repair id>, run=<the
  foreman run>, detail=<red or finding id>, run_kind=<kind>)`, kind one of
  `FIX_KINDS`. `red_actions` and `finding_actions` make them; one step in
  `fab/dispatch.py` sends each to its kind's start or settle.
