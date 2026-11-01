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
    states, which only the second plan's records reach (tested on synthetic
    records); merges and `again`, holding, rung states (a walk in flight
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

## Gaps and departures

- **The repair path is being built** by plan `docs/plan/findings-repair`
  (2, "After red-routing's tick wiring lands"; red-routing's wiring is on
  main). On main now: `fab/fix.py` factored out of `fab/tier_reds.py`
  (`RED_RUNS = fix.RUNS`), the `examine-fix`/`remedy-fix` pair (red only so
  far), `fab/fixes.py` and `fab/roles/foreman-finding.md`. Not yet: the
  tick's `finding_actions`, joining `fab.fixes.tasks` to the plan's tasks
  (the tick still keeps only red's), and the page's `finding-<n>` signal.
  Until they land a finding triaged `path` stops in state `foreman`; a
  blocking one, or one from a failed or void walk, holds its rung there.
  That plan's retire brings this line current.
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
