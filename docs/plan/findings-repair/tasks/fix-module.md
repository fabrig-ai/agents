+++
id = "fix-module"
part = "fix"
kind = "feature"
needs = []
files = ["fab/fix.py", "fab/tier_reds.py", "fab/tests/test_fix.py"]
effort = "high"
minutes = 45
+++
# fab/fix.py: Fix mode's shared steps, factored out of fab/tier_reds.py

Read first: `docs/plan/findings-repair/notes/common.md`,
`docs/plan/findings-repair/notes/fix.md` ("fab/fix.py").

The request: "`fab/fix.py`, factored out of `fab/tier_reds.py` (the
foreman's launch, `parse`, `section`, `settle`, the repair task's
construction, `FIX_KINDS`, `RUNS`), red's behaviour and tests unchanged".
Design: `docs/design/fab-qa.md`, 2, "What moves out of `fab/tier_reds.py`".

## What to build

- A new `fab/fix.py` with the names and signatures `notes/fix.md` binds:
  `FIX_KINDS`, `RUNS`, `SECTION_LINES`, `launch`, `report_path`, `parse`,
  `section`, `settle`, `answers`, `sections`, `task`. `sections(events) ->
  dict[str, list[str]]` is each task's `refusal.settled` fix sections in
  log order, the other half of `tier_reds.repair_tasks`' one scan (a
  finding's repair takes them too: its refusal goes to the specless
  refusal foreman).
- `fab/tier_reds.py` calls them, its own copies gone:
  - `start` (near line 581): its tail through `fab.fix.launch` and
    `fab.fix.report_path`, keeping `red` and `tip` on run.started;
  - `remedy` (near line 608): the parse through `fab.fix.parse` with
    `skip` the `Owner:` line, its owner check reading `skipped`; its
    section through `fab.fix.section`;
  - `settle` (near line 646): through `fab.fix.settle`;
  - `repair_tasks` (near line 473): its scan through `fab.fix.answers`
    and `fab.fix.sections`, its `Task` through `fab.fix.task`;
  - `RED_RUNS = fix.RUNS` and `SECTION_LINES = fix.SECTION_LINES`, kept as
    its names for them.

## Acceptance

- `fab/tests/test_tier_reds.py` passes unchanged (do not edit it), and so
  does every red test in `fab/tests/test_dispatch.py` and
  `fab/tests/test_channel.py`.
- `fab/tests/test_fix.py` covers each function by itself: `parse` on
  fix, retry, a malformed first line, a blank report, `skip` taking the
  line after the first and returning it, and more than `SECTION_LINES`
  lines; `section` dropping trailing blanks; `settle` stamping `ts` and
  the day from one `log.now`; `answers` and `sections` in log order,
  ignoring empty answers and non-fix settlements; `task`'s fields and
  its `## Answers`; `launch` through a `FakeRunner`, numbering the run
  `<task>/foreman-<n>` and passing the caller's fields to run.started.

## Pre-approved defaults

- Every public name of `fab/tier_reds.py` and its signature stays; a
  docstring that described a moved body may shorten to say it calls
  `fab.fix`.
- `launch`'s `brief` is a callable (run id, report path) -> text, since
  the run id is numbered inside `launch` and the brief names it.
- `fab.fix` imports `fab.foreman`, `fab.log`, `fab.run` and `fab.plan`
  (for `Task`) only; it imports neither `fab.tier_reds` nor `fab.fixes`.

## Report

Each function of `fab/fix.py` and the `tier_reds` body it replaced; that
`test_tier_reds.py` is unchanged and green.
