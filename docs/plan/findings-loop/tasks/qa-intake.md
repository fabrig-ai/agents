+++
id = "qa-intake"
part = "intake"
kind = "feature"
needs = ["findings-fold", "ladder-plan", "rungs-fold"]
files = ["fab/walks.py", "fab/cli.py", "fab/tests/test_walks.py", "fab/tests/test_package.py"]
effort = "high"
minutes = 60
+++
# fab qa: a hand walk enters fab

Read first: `docs/plan/findings-loop/notes/common.md`,
`docs/plan/findings-loop/notes/fold.md`.

The request: "`fab qa` and the intake (`fab/walks.py`, `fab/cli.py`)", on
walks a session still starts by hand. Design: `docs/design/fab.md`, 13.15,
"A walk enters fab by a command on hel8" with its three verbs and "The
result", and the merge rule in "The same finding is merged".

## What to build

In `fab/walks.py` (beside `edition` and `editions`):
- `LOCK = "qa.lock"` under FAB_HOME, held (`fcntl.flock`) by both writing
  verbs from counting ids to their last append; `WALKS = "walks"`
  (`FAB_HOME/walks/<walk>/`); limits `TITLE_LIMIT = 200`, `TEXT_LIMIT =
  4000`, `FINDINGS_LIMIT = 30`.
- `parse(text) -> Result` (pure): `result.toml` as 13.15 gives it;
  ValueError naming the field for each refusal 13.15 lists (verdict,
  pass with a blocking finding, fail with none, severity, the limits; a
  `same` naming no finding of the plan is checked by `result`, which has
  the log).
- `brief_text(texts, walk_dir, open_findings) -> str` (pure): the brief
  files' text as read, then `# Reporting to fab` (the result's form and
  where to write `report.md` and `result.toml`), then `# Open findings`
  (one line each: id, state, rung, area, title).
- `walk(plan_dir, rung, commit, *, by="session", sh=run, log_path=None) ->
  tuple[str, Path]`: fetch the plan's checkout, read the rung's brief at
  `origin/main` (through `editions`' reading), refuse a commit missing a
  landed repair of the rung's findings (`git merge-base --is-ancestor
  <landed main> <commit>` in `FAB_HOME/repos/fabrig`, naming the first
  missing), log `walk.started`, write `FAB_HOME/walks/<walk>/brief.md`;
  return the id and the brief's path.
- `result(walk_id, directory=None, *, log_path=None) -> list[dict]`: read
  and parse `result.toml`, copy it and `report.md` into the walk's
  directory, log per finding `finding.raised` (`index` its place; `again`
  set to the target when `same` names one not `fab.findings.mergeable`),
  then `finding.merged` (by the walk) for each `same` naming a mergeable
  one, then `walk.ended` last; wake the tick with `qa <walk>`
  (`fab.wake.want`, beside the log, as `fab.calls.start` does). Run again
  on a walk with no `walk.ended`, skip the indices and merges already
  logged. Refuse, logging nothing: a walk unknown or ended, and `parse`'s
  refusals.
- `main(argv)`: `fab qa walk PLAN_DIR RUNG --commit SHA [--by WHO]`
  (prints the id and the brief's path), `fab qa result WALK [DIR]`, `fab
  qa rungs [PLAN_DIR...]` (each plan's rungs, `fab.findings.line` per
  rung; plans default to `fab.channel.plan_dirs()` as the page's). A
  refusal prints its reason and exits 2.

In `fab/cli.py`: `"qa": ("fab.walks", "a ladder's QA walks: start one,
report its result, show the rungs")`.

## Acceptance

Tests in `fab/tests/test_walks.py` (13.15's "Tests", the intake cases):
- `fab qa result` on a failed walk's `result.toml` logs two
  `finding.raised`, one `finding.merged` for a `same` naming an open
  finding and `walk.ended` last, and wakes once;
- an intake cut after the first `finding.raised` and run again logs the
  rest once and nothing twice;
- two intakes at once take distinct ids (two threads or a held lock);
- a `same` naming a landed finding files it again with `again`;
- a pass with a blocking finding, or a fail with none, logs nothing;
- `fab qa walk` refuses a commit without a rung's landed repair
  (`FakeRunner` answering `merge-base` non-zero), and writes the brief
  with the open findings otherwise;
- `fab qa rungs` prints one line per rung.

## Pre-approved defaults

- `report.md` missing: `walk.ended`'s `report` is "" and the intake goes on.
- `--by` default `session`.
- If `fab/tests/test_package.py` lists the commands, add `qa` there.

## Report

The verbs built, their refusals, and the lock's scope.

## Repair (2026-11-01, step gate:size, foreman findings-loop/qa-intake/foreman-1)

shorten result() and distinguish the intake finding’s field layout.
Both gate findings belong to `fab/walks.py`; repair within that file.
- `gate:size`: `result()` at line 233 spans 61 lines, exceeding 60. Combine the adjacent `appended = []` and `identifiers = []` initializations as `appended, identifiers = [], []`, preserving behavior.
- `gate:clones`: `_Finding` lines 31–38 repeat `fab/findings.py:43`. Move intake-specific `same` before `title`, separating identity from the reported fields. Construction uses keyword arguments, so this preserves parsing and emitted record fields while breaking the repeated eight-line block.
Preserve `docs/design/fab.md`, §13.15: validation before writes, lock scope, resumable indices and merges, and `walk.ended` last.
Run `bin/fab test` and the landing structure gates to verify both findings clear.
