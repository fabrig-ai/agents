+++
id = "ladder-plan"
part = "ladder"
kind = "interface"
needs = []
files = ["fab/plan.py", "fab/walks.py", "fab/tests/test_plan.py", "fab/tests/test_walks.py", "fab/tests/ladder_plans.py", "fab/designer.py", "fab/state.py", "fab/tests/test_designer.py", "fab/tests/test_state.py", "fab/tests/test_dispatch.py"]
effort = "medium"
minutes = 40
+++
# The ladder is a plan; a rung's edition is its brief's bytes

Read first: `docs/plan/findings-loop/notes/common.md`,
`docs/plan/findings-loop/notes/fold.md`.

Design: `docs/design/fab.md`, 4 (a ladder plan names `[ladder]` and its
`[[rung]]`s instead of parts) and 13.15, "The ladder is a plan" and "A
rung's edition is its brief's bytes".

## What to build

In `fab/plan.py` (sites: `RESERVED` near line 17, `Plan` near 55,
`load_plan` near 116, `_plan_tables` near 189, `problems` near 301, `load`
near 105):
- `Rung` (frozen dataclass: `id`, `backend`, `brief: tuple[str, ...]`,
  `after: tuple[str, ...] = ()`) and `Ladder` (`happy_path`, `backlog`);
- `Plan.rungs: dict[str, Rung]` (plan order, default empty) and
  `Plan.ladder: Ladder | None` (default None), as keyword fields after the
  existing ones;
- `load_plan`: `[[part]]` optional (default none); `[ladder]` with both
  keys strings; each `[[rung]]` with `id`, `backend`, `brief` (strings),
  `after` (default none); wrong types a PlanError as for parts;
- `problems(plan, tasks, plan_dir: Path | None = None)` adds: a plan with
  neither parts nor rungs; a rung id not matching `[a-z0-9-]+` or used
  twice; `after` naming no rung, or a cycle among rungs; rungs without
  `[ladder]`, or `[ladder]` without rungs; rungs in a plan whose landing is
  not `queue`; with plan_dir, a brief file missing under it. `load` passes
  its plan_dir;
- `"triage"` joins `RESERVED`.

New module `fab/walks.py`, its first two functions (qa-intake adds the
rest):
- `edition(files: Sequence[tuple[str, str]]) -> str`: the first 12 hex of
  sha256 over each (path, text) in order (path as plan.toml writes it,
  UTF-8; separate path and text unambiguously, e.g. each followed by a NUL).
  Pure.
- `editions(plan, plan_dir, *, sh=run) -> dict[str, str]`: each rung's
  edition from its brief files at `origin/main` of the checkout holding
  plan_dir (`git rev-parse --show-toplevel`, then `git show
  origin/main:<path from the checkout's root>`), in plan order; a file
  `git show` cannot read is a ValueError naming the rung and the file.

Check that a plan with rungs and no parts is never designed or retired
(`fab.designer.retire_due` already needs a part; `fab.state` and the
design calls must not fail on no parts); fix there only if they do.

Test vocabulary `fab/tests/ladder_plans.py`: `write_ladder(directory,
draft="ladder", rungs=None, *, briefs=None) -> Path`: a sound ladder plan
(landing queue, `[ladder]`, rungs `{id: (backend, after)}`, default two
rungs `b0` and `b1` after `b0` on `claude-forgejo`, and the brief files
`briefs/kit.md` and `briefs/<rung>.md` written), through
`fab.atomic.write`.

## Acceptance

Tests in `fab/tests/test_plan.py` and `fab/tests/test_walks.py`:
- a ladder plan loads with its rungs in order and its ladder; a plan with
  parts loads as before (existing tests unchanged);
- each new problem is reported, one line each, in the sorted order
  `problems` keeps; a part named `triage` is refused;
- `edition` changes when a file's text or path changes and not otherwise;
  `editions` reads `origin/main` through the runner (a `FakeRunner`
  answering `git show`) and raises naming a missing file.

## Pre-approved defaults

- The backend check against `fab.findings.BACKENDS` is not yours (it
  comes with rungs-fold); do not import `fab.findings`.
- `fab status` of a ladder plan prints no task lines: fine.

## Report

The new fields and problems, and whether designer or state needed a change.

## Answers

2026-11-01. May `fab/tests/test_dispatch.py` join this task's files to
replace its empty registered-plan fixture? Yes: the rejection of a plan with
neither parts nor rungs is this task's acceptance, and the suite cannot be
green without that fixture changing, so it is added to `files`. Change only
the fixture of
`TickTest.test_tick_writes_page_after_actions_using_explicit_log_and_registered_plans`:
write the registered plan with `write_ladder` and keep its `[[question]]`
`budget` (append it, or pass it through, without widening `write_ladder`'s
signature beyond what the test needs), so the test still asserts actions
`["start"]` and both questions on the page. Touch no other dispatcher test.

## Repair (2026-11-01, step gate:shape, foreman findings-loop/ladder-plan/foreman-2)

extract rung validation from problems; resolve the task kind conflict with its required signature.
Both findings belong to this branch; retrying unchanged will fail.
`fab/plan.py:340`: `problems` is 71 lines, exceeding the 60-line cap.
Extract ladder/rung checks into a private function accepting `plan` and `plan_dir`.
Keep `problems`’ final sorting and all existing diagnostics; keep both functions within 60 lines.
The shape finding is a task metadata conflict: the spec requires the added `plan_dir` parameter, but declares `kind = "feature"`.
`docs/design/fab.md`, section 12, permits signature changes only for `interface` or `migration`; `fab/gates.py:EXEMPT` implements that rule.
The task is now `interface` (the plan owner, 11-01): the signature change may land.
Preserve the specified signature and `load` passing `plan_dir`; do not bypass the gate or change its exemptions.

## Rebase (2026-11-01, step rebase, foreman findings-loop/ladder-plan/foreman-3)

resolve duplicate ladder implementations during rebase, preserving the refused tip’s combined behavior.
The rebase fails applying `5ea8416` after replaying overlapping ladder work from `17c6e44`.
These are branch-history conflicts; `origin/main` contains no `fab/walks.py`.
Resolve content conflicts in `fab/tests/test_designer.py`, `fab/tests/test_dispatch.py`, `fab/tests/test_plan.py`, and `fab/tests/test_state.py`.
Resolve add/add conflicts in `fab/walks.py` and `fab/tests/test_walks.py` into one implementation and test suite.
Use refused tip `0b83bbee` as the reference for the intended combined contents of these six files, preserving any intervening main changes.
Keep `edition` hashing ordered paths and texts and `editions` reading `origin/main`, naming unreadable briefs, and returning `{}` without git calls when there are no rungs.
Keep the designer lifecycle coverage and state coverage for empty-plan rejection and ladder status.
In the dispatcher test, change only the approved registered-plan fixture to `write_ladder`, retaining its `budget` question and existing assertions.
When replaying the remaining changes, preserve `fab/plan.py`’s `_ladder_problems` extraction, sorted diagnostics, and required `plan_dir` signature.
Do not restore the earlier oversized `problems` implementation or duplicate rung definitions and tests.
Keep the final diff within the task’s allowed files and validate with `bin/fab test` and the landing gates.
