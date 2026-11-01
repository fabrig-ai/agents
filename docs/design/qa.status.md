# qa status

2026-11-01. Contract: `docs/design/qa.md`. Split from `docs/design/fab.status.md`.

## Present

- **QA findings' first build** (2, "Now, independent"; plan
  `docs/plan/findings-loop`, retired 11-01), on walks a session starts by
  hand. Tested with temporary homes, fake runners and synthetic records; no
  real ladder has been ticked by it yet.
  - **The ladder plan** (`fab/plan.py`): `[ladder]` and `[[rung]]` read into
    `Plan.ladder` and `Plan.rungs` (`fab.plan.Ladder`, `fab.plan.Rung`),
    `[[part]]` optional, `triage` in `fab.plan.RESERVED`, and 2's problems
    (no parts nor rungs, a rung id twice, `after` unknown or a cycle, a
    backend not in `fab.findings.BACKENDS`, rungs off `queue` landing, a
    brief file missing, checked only when `load` passes the plan directory).
  - **Editions** (`fab.walks.edition`, `fab.walks.editions`): each brief's
    path as plan.toml writes it and its text at `origin/main`.
  - **The intake** (`fab qa walk|result|rungs`, `fab/walks.py`): `qa.lock`
    around ids and appends, the landed-repair ancestry check, the brief with
    `# Reporting to fab` and `# Open findings`, `result.toml`'s refusals and
    limits, `walk.ended` last, a cut intake retried whole.
  - **The fold** (`fab/findings.py`): every state of 2 including the repair
    states, which the repair path's records reach; merges and `again`, holding, rung states (a walk in flight
    for under `WALK_HOURS`), `passes` and the shared rung line.
  - **The triage call** (`fab/triage.py`, `fab/roles/triager.md`): report-only
    through `fab.calls.start(report_only=True)`, effort medium, no chain; its
    due rule (`AT` and `AFTER`, constants equal to the answerer's, a test
    pinning it), brief and decisions, and the backlog's render,
    `render_key` and `backlog_held`.
  - **The tick's ladder steps** (`fab.dispatch._tick_loaded`, a plan with
    rungs): decisions recorded, then `rung.passed`, then the backlog readied
    as `ladder/<draft>/backlog-<n>` through `fab.spec_edit.commit_path`,
    before `decide`; `call_actions` starts the triage call when due;
    `_import_queue` brings a backlog branch's landing and rejection home, and
    `ladder/` is kept out of `queue.*`.
  - **The page** (`fab/channel.py`): `finding` asks and their answers,
    `backlog:<draft>`, `## The ladder` with each rung's line and the
    backlog's count.
  - **The landing report's QA figures** (reports.md 2).
- **The repair path** (2, "After red-routing's tick wiring lands"; plan
  `docs/plan/findings-repair`, retired 11-01), on findings-loop's fold and
  triage. Tested with temporary homes, fake runners and synthetic logs.
  - **Fix mode's shared steps** (`fab/fix.py`): `launch`, `report_path`,
    `parse`, `section`, `settle`, `answers`, `sections`, `task`,
    `FIX_KINDS` and `RUNS`, factored out of `fab/tier_reds.py`
    (`RED_RUNS = fix.RUNS`), red's records and tests unchanged.
  - **The finding's foreman** (`fab/fixes.py`,
    `fab/roles/foreman-finding.md`): `repair_id`, the `foremen` fold, the
    brief (the walk's report cut at `WALK_REPORT_BYTES`, 15 KiB, and
    marked), `start`, `settle` (`finding.settled` fix, left or none) and
    `tasks`, the `<draft>/finding-<n>` repair with 2's body and
    acceptance, from a fix, a none or a foreman ending otherwise.
  - **The tick** (`fab/dispatch.py`): `red_actions` and `finding_actions`
    make the `examine-fix`/`remedy-fix` pair, `_fix_steps` sends each to
    its kind, main's tip read once a round for finding foremen (a failed
    read noted and the foremen deferred); finding repairs joined to the
    plan's tasks, the queue import (their landing marked `into` main) and
    after-landing's owners; `FIX_KINDS` wherever the red wiring read kind
    `red` (`fab/buffer.py`, `fab/integration.py`, the run limit, the trunk
    a repair starts from); `finding.settled` in `fab.wake.AGAIN`.
  - **The page's `finding-<n>`** (`fab/channel.py`, channel.md 2): open from
    `finding.settled` left until its rung's next `rung.passed`, or a hand
    clear, which drops the finding.

## Gaps and departures

- **Neither build has met a real ladder:** both plans' code is tested on
  fake runners and synthetic logs only; the first walk by hand on hel8
  will be the first finding to reach a foreman and a repair.
- **Walks run by fab: not built** (2's last part; 3): a session still walks
  by hand with `fab qa walk` and `fab qa result`.
- **Stale citations:** `fab/spec_edit.py` (`commit_path`) and
  `fab/dispatch.py` (`_queue_record`, `_backlog_branches`, `_ready_backlog`)
  cite `docs/design/fab.md, 13.15`, the section before the split; it is
  this design's 2.
- **Departures,** each with its reason in 2:
  - from temper's `domain/findings.md`: the record lives in fab's log,
    not a labelled forge issue; no signature (QA findings have no test
    ids), so duplicates are merged by the walker naming them or by
    triage, never by a key; `area` is the component the walker names,
    free text; severity is the walker's (its open question 10); states add
    `asked`, `merged` and a repair's states; a finding closes on its
    rung's rerun, not on `Fixes #n` once its landing clears;
  - from `execution-modes.md`'s Fix mode ("Claude designs nothing by
    default"): every finding meets one Claude call, the triage, in
    batches, since v0.1.0.md 4 has the director triage every finding; the
    repair is Codex's (foreman and implementer), Claude only after two
    failed tries; the public-item wake waits for the api gate, as for
    reds;
  - from v0.1.0.md 4, which puts a rung's own walk's findings on the path
    by definition: the triage call decides each, at the user's request,
    with the path its default for a finding that failed an acceptance;
  - from qa-ladder's practice: repairs readied one by one from main and
    batched by the queue, not merged into hand batches; a kit change gives
    every rung reading it a new edition, where qa-ladder judged per rung.
