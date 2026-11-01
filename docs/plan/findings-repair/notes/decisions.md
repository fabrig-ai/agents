# The cut's decisions

What the request and `docs/design/qa.md` 2 left to the cut, each
settled with its reason. The specs bind them.

1. **Six tasks in five parts, all direct.** `fix` (fix-module), `kinds`
   (fix-kinds, fix-pair), `foreman` (finding-repair), `tick`
   (tick-findings), `signal` (finding-signal). The request's four bullets
   are the parts; its third bullet (the tick) splits by what each half
   builds on: the renamed pair and the `FIX_KINDS` readings need only
   `fab/fix.py`, the finding's steps need `fab/fixes.py` too.
2. **`fab.fix.launch` takes its brief as a callable** (run id, report
   path) -> text: the design has `launch` number the run, and the brief
   names the run and its report, so the brief is made inside.
3. **`fab.fix.sections(events)`** beside `answers`: a finding's repair
   goes to the specless refusal foreman as a red's does (qa.md 2), and
   its refusal sections reach its body by the same scan red's
   `repair_tasks` does today; one copy for both kinds.
4. **`fab.fixes.foremen(events)`** folds each finding's foreman run, tip,
   outcome and report: `fab.findings` folds the state but keeps no run
   id, and the tick (remedy-fix) and the page (the read paths) both need
   them. `fab/findings.py` is not changed.
5. **The `_red_steps` step becomes `_fix_steps`** in fix-pair and gains
   kind `finding` in tick-findings: the design's "`_take` sends each to its
   kind's start or settle" is met by the step that already takes red's
   actions outside `_take`, against one log snapshot.
6. **`finding.settled` joins `fab.wake.AGAIN`,** as `red.settled` is:
   the repair it makes should start on the next round, not the backstop.
7. **The finding's foreman's tip** is `git rev-parse origin/main` in the
   plan's checkout, read once per round by the tick (qa.md 2: "main's
   tip in the plan's checkout this tick").
8. **The walk's report is cut at 15 KiB** (`fab.fixes.WALK_REPORT_BYTES`,
   the kit's cap) and marked, so one oversized report cannot swell a brief.
9. **finding-signal waits for finding-repair** though it could start at
   once: it reads the foreman's report path through `fab.fixes.foremen`
   (one copy), and waiting keeps it off `fab/channel.py` while
   `findings-loop/ladder-page` is still changing that file.
10. **No user questions.** The request settles what is built and where
    (hel8, the existing builders and calls); nothing in it is a budget, a
    machine or hard to reverse.
11. **Status and design:** `docs/design/qa.status.md` is the
    designer's (the retire call brings it current); a task edits qa.md
    2 and its status line only for a departure it must make.

## The critical path

`fix-module` (45) -> `finding-repair` (60) -> `tick-findings` (50): 155
implementer-minutes, about 2.6 hours, the longest task plus its contract
and the one task that wires both. Beside it: `fix-pair` (40, after
fix-module) is merged by minute 85, before finding-repair ends at 105;
`fix-kinds` (25) by 70; `finding-signal` (35) by 140.

## Overlaps with findings-loop

- `fab/dispatch.py` and `fab/tests/test_dispatch.py`: fix-pair and
  tick-findings, beside `findings-loop/backlog-branch`. Unavoidable: the
  pair and the joined tasks live in the tick. fix-pair starts after
  fix-module, so backlog-branch has about 45 minutes' start; each spec
  says to rebase and keep both.
- `fab/channel.py` and `fab/tests/test_channel.py`: finding-signal,
  beside `findings-loop/ladder-page`. Delayed to minute 105 (9 above).
- fix-module, fix-kinds and finding-repair touch no file another draft is
  changing.
