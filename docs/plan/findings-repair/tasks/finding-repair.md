+++
id = "finding-repair"
part = "foreman"
kind = "feature"
needs = ["fix-module"]
files = ["fab/fixes.py", "fab/roles/foreman-finding.md", "fab/tests/test_fixes.py"]
effort = "high"
minutes = 60
+++
# fab/fixes.py: a routed finding's foreman, its settlement and its repair task

Read first: `docs/plan/findings-repair/notes/common.md`,
`docs/plan/findings-repair/notes/fix.md`.

The request: "`fab/fixes.py` and `fab/roles/foreman-finding.md`: a routed
finding's foreman, its brief, its settlement (`finding.settled`) and the
`<draft>/finding-<n>` repair task folded from the log, with the Fix-mode
acceptance (a test in the lowest world, red before and green after)".
Design: `docs/design/fab-qa.md`, 2, "Its foreman", "Its report keeps the
form", "The repair is `<draft>/finding-<n>`" and "One repair per
finding". Model every function on its red twin in `fab/tier_reds.py`.

## What to build

`fab/roles/foreman-finding.md`: the role text, on the pattern of
`fab/roles/foreman-red.md`: a read-only Codex run on fabrig at main's
tip, qa-ladder's cause survey; it decides the code's (`Done: fix:
<line>`, then at most thirty lines: the cause, where on main, what to
change, and the lowest world that reproduces it: a unit or world test on
the fake backends, a fake model's script from the walk's transcript where
the model's turn matters) or not the code's (`Done: retry: <line>`: the
walk's setup or machine, a backend's outage; at most ten lines; it leaves
a signal, nothing reruns), or `Failed: <why>`. When unsure, it is the
code's. It changes nothing, builds nothing, pushes nothing.

`fab/fixes.py`, the names binding:
- `KIND = "finding"`, `PART = "qa"`, `ROLE` (the role file's path),
  `SETTLED = "finding.settled"`, `WALK_REPORT_BYTES = 15 * 1024` (the
  kit's cap on a walk's report).
- `repair_id(finding) -> str`: `<draft>/<finding id>`.
- `@dataclass(frozen=True) class Foreman`: finding, run, tip, outcome
  ("" while in flight), report ("" until collected); `foremen(events) ->
  dict[str, Foreman]`, pure: each finding's first foreman run.started
  (task `<draft>/finding-<n>/foreman`, kind `foreman`, with `finding`) and
  that run's run.ended.
- `brief(finding, plan, *, run_id, report, tip, briefs, merged,
  walk_report, role) -> str`, pure: the role text; `# The finding`: run,
  finding, rung, backend, walk, commit walked, area, the triager's owner
  and reason, the rung's brief paths (`briefs`, repository paths), the
  report path, `Your checkout is fabrig at <tip>, read-only.`; `# The
  record`: title, reproduction, expected, seen, and each finding of
  `merged` (its id, walk and reproduction); `# The walk's report`:
  `walk_report` whole.
- `start(finding, plan, plan_path, host, tip, events, *, sh=run,
  log_path=None) -> str`: reads the role and `FAB_HOME/walks/<walk>/
  report.md` (unreadable: `(walk report unreadable: <why>)`; over
  `WALK_REPORT_BYTES`: cut there and marked), the merged findings from
  `fab.findings.findings(events)` (`finding.sightings`), the briefs as
  `plan_path/<brief>` for each of the rung's `brief` files, then
  `fab.fix.launch(repair_id(finding), host, tip, ..., finding=finding.id,
  tip=tip)`; returns the run id.
- `settle(finding, foreman, report, *, log_path=None) -> dict`:
  `fab.fix.parse(report)`, for fix `fab.fix.section("## Repair (<day>,
  finding <n>, foreman <run>)", reason, lines)`, logged through
  `fab.fix.settle` as `finding.settled` (finding, run, verdict, reason,
  section; section "" for left and none).
- `tasks(plan, events) -> dict[str, Task]`, pure, in raise order: one
  task per finding of the plan's draft from its `finding.settled` fix or
  none, or its foreman's run.ended other than done (the fallback), made
  through `fab.fix.task(repair_id, KIND, PART, body, answers)` with
  `fab.fix.answers` and `fab.fix.sections` (refusal sections appended
  after the foreman's, as red's are). Its body: `# Repair a QA finding
  (finding-<n>)`; the rung, backend, walk, commit and edition; the area,
  owner and the triager's reason; `## The finding` (title, reproduction,
  expected, seen, and each merged finding's walk and reproduction); the
  foreman's section; then `## Acceptance` as fab-qa.md 2 words it
  (reproduce first in the lowest world, a test red on main before the
  change and green after, naming the world and why it is the lowest; then
  fix; design text the change makes untrue changes in the same branch:
  the tree's `docs/design/` and status file, `temper/docs/help/` with its
  help tests; then the task's own checks as any fabrig task, precheck
  `--onto origin/main`).

## Acceptance

Tests in `fab/tests/test_fixes.py`, with records from
`fab/tests/qa_records.py`:
- `brief` has its sections in order with every fact named, the merged
  findings' reproductions, and the walk's report; `start` through a
  `FakeRunner` launches one run `<draft>/finding-<n>/foreman-1` on fabrig
  at the tip, its run.started carrying `finding` and `tip`, and marks an
  unreadable or overlong walk report;
- `settle` logs `finding.settled` fix with its section, left and none
  with none, and `fab.findings.findings` then folds the finding
  `repairing` or `left`;
- `tasks` makes `<draft>/finding-<n>` (kind `finding`, part `qa`, files
  `**`, no path) from fix, from none and from the fallback, none from
  left or before settlement, none for another draft's finding; the body
  holds the foreman's section, a merged finding's reproduction, a
  refusal's section and the user's answers; one task per finding, also
  after a merge into it.

## Pre-approved defaults

- A finding whose repair task exists keeps it whatever its later state
  (landed, fixed, unfixed), as a started red task does.
- `fab.fixes` imports `fab.fix`, `fab.findings`, `fab.foreman`, `fab.log`,
  `fab.run` and `fab.plan`; never `fab.dispatch`, `fab.channel` or
  `fab.tier_reds`.

## Report

Each function and what it reads; the role text's verdicts.
