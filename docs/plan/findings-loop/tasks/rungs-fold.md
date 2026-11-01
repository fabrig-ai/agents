+++
id = "rungs-fold"
part = "findings"
kind = "feature"
needs = ["findings-fold", "ladder-plan"]
files = ["fab/findings.py", "fab/plan.py", "fab/tests/test_findings.py", "fab/tests/test_plan.py", "fab/tests/qa_records.py"]
effort = "high"
minutes = 45
+++
# Where each rung stands, and when a pass counts

Read first: `docs/plan/findings-loop/notes/common.md`,
`docs/plan/findings-loop/notes/fold.md`.

The request, item 4: "Acceptance by itself: when a rung's repairs have
landed, its brief is rerun unchanged, and the pass, or a new finding, is
recorded." Design: `docs/design/fab.md`, 13.15, "Acceptance by itself", "A
pass is recorded by the tick", "fab says a rerun is due" and the holding
rule in "Where each finding stands".

## What to build

In `fab/findings.py` (pure):
- `RungState` (frozen dataclass): `rung`, `backend`, `edition`, `state`
  (`passed`, `walking`, `waiting`, `holding`, `due`), and its detail:
  `walk` and `since` (walking; passed: the passing walk), `waits` (rung
  ids), `holders` (tuple of (finding id, state)), `due` (`first walk` or
  `rerun`), `at` (the main a rerun must contain, or ""), `commit` (passed
  at).
- `holders(found, rung) -> tuple[Finding, ...]`: the targets holding the
  rung, in raise order: each finding of the rung that holds itself, and
  each merged finding of the rung (by `rung`) whose target is in a holding
  state and that would hold were it in that state (13.15: "a merged one
  holds through its target"), given as its target, each once.
- `rungs(plan, events, editions, now) -> list[RungState]`: plan order, the
  first state that holds as 13.15 lists them; walking is a `walk.started`
  of the rung with no `walk.ended` and younger than `WALK_HOURS` at now;
  due's `at` is the newest `landed` main among the rung's findings'
  repairs (merged ones' through their targets); "" when none.
- `passes(plan, events, editions) -> list[dict]`: the `rung.passed`
  fields (draft, rung, walk, edition, commit) not yet logged, at most one
  per walk, by 13.15's rule: a walk ended pass at the rung's current
  edition, after another walk of it at that edition ended pass or fail,
  with no holder at its end and no failed walk of the rung since, and each
  rung in `after` passed when it ended or passed by a walk at the same
  commit. A pass whose lower rung passed later at another commit counts no
  more.
- `line(state) -> str`: `<rung> (<backend>), edition <e>: ` then `due:
  first walk` or `due: rerun at a main containing <at[:12]>` (`due:
  rerun` when at is ""), `walking: <walk> since <ts>`, `waiting for <r1>,
  <r2>`, `holding: finding-3 repairing, finding-7 new`, `passed at
  <commit[:12]> (<walk>)`.

In `fab/plan.py`, `problems` adds a rung whose backend is not in
`fab.findings.BACKENDS` (decision 4 of
`docs/plan/findings-loop/notes/decisions.md`; `fab.plan` imports
`fab.findings` at module level).

## Acceptance

Tests in `fab/tests/test_findings.py` (13.15's "Tests" list, the rung
cases):
- the rung holds while its blocking finding is new or repairing, then is
  due for a rerun at the repair's main once it lands, and the rung above
  waits meanwhile;
- a non-blocking finding of a passing walk holds nothing; one of a void
  walk holds; a merged one holds through its target;
- a rerun's pass gives one `rung.passed` and not twice once logged; a
  first walk's pass gives none;
- a pass whose lower rung has not passed gives nothing until the lower
  passes at the same commit;
- a failed walk after a pass reopens the rung (due, not passed);
- a new edition makes earlier walks count no more (first walk again);
- walking until `WALK_HOURS`, then due;
- `line` for each state.
In `fab/tests/test_plan.py`: an unknown backend is a problem.

## Pre-approved defaults

- A rung missing from editions (its edition unreadable): left out of
  `rungs` and `passes`.
- A walk at another rung's id or another draft: ignored.

## Report

The functions built and any ordering case the design's rule left open.
