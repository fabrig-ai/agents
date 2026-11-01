+++
id = "fix-pair"
part = "kinds"
kind = "feature"
needs = ["fix-module"]
files = ["fab/dispatch.py", "fab/tests/test_dispatch.py"]
effort = "high"
minutes = 40
+++
# The examine-fix/remedy-fix pair and FIX_KINDS in the tick

Read first: `docs/plan/findings-repair/notes/common.md`,
`docs/plan/findings-repair/notes/fix.md` ("The action pair").

The request: "one examine/remedy action pair for reds and findings
(`examine-fix`, `remedy-fix`, the rename after-landing.md 2 names)",
and "`FIX_KINDS` wherever the red wiring reads kind `red`". Design:
`docs/design/qa.md`, 2, "One action pair for both kinds";
`docs/design/after-landing.md`, 2 (near line 308).

## What to build

In `fab/dispatch.py`, for reds only (findings are `tick-findings`'):
- `red_actions` (near line 207): `Action("examine-fix", task=red.task,
  detail=red.id, run_kind="red")` and `Action("remedy-fix", task=red.task,
  run=red.foreman, detail=red.id, run_kind="red")`; the `Action` kind
  comment (near line 160) names the pair.
- `_red_steps` and `_remedy_red` (near lines 236-265) become one step,
  `_fix_steps`, taking the round's fix actions and sending each by
  `run_kind` to its kind's start or settle (for `red`, `tier_reds.start`
  and `tier_reds.settle`, as now), logging a failure as a `note` and
  printing one line per action as now. Shape it so `tick-findings` adds
  kind `finding` as one more branch.
- Every `tier_reds.KIND` reading becomes `kind in fix.FIX_KINDS`: the
  stop step's startable tasks and `MAX_RUNS` (near lines 346-352, `RUNS`
  for each), the filter before red tasks are joined (near line 1066), the
  run's and the refusal foreman's trunk `main` (near lines 1247 and 1372),
  and the `merge` exception for integration plans (near line 1652).

## Acceptance

- The red tick tests in `fab/tests/test_dispatch.py` pass with
  `examine-red`/`remedy-red` renamed to `examine-fix`/`remedy-fix` in
  their expectations and nothing else changed; the actions carry
  `run_kind="red"`.
- New tests: a task of kind `finding` in a plan's tasks starts from
  `origin/main` (trunk `main`) in an integration plan, is readied rather
  than merged, starts while the trunk's step is `stop`, and parks after
  `fix.RUNS` runs, as a red task does.

## Pre-approved defaults

- `fab/tests/test_dispatch.py` is shared with `findings-loop/
  backlog-branch` and `tick-findings`; if either lands while you work,
  rebase and keep both.

## Report

The renamed pair, the step's shape, and each `FIX_KINDS` site by line.
