# fab-qa status

2026-11-01. Contract: `docs/design/fab-qa.md`. Split from `docs/design/fab.status.md`.

## Present

- (nothing yet)

## Gaps and departures

- **QA findings: designed, not built** (2; the user, 11-01, after
  qa-ladder ran v0.1.0's ladder by hand and left 48 off-path findings in
  `coord/qa-ladder/findings.md` with no owner). Nothing of it is in the
  code. Until it lands, ladder sessions triage, survey, repair, land and
  rerun by hand, as qa-ladder did.
  - **Runs before red-routing's tick wiring lands:** the ladder plan's
    rungs (`fab/plan.py`); the intake (`fab qa walk|result|rungs`,
    `qa.lock`, `walk.ended` last; `fab/walks.py`); the findings' and rungs'
    fold, rung states and `rung.passed` (`fab/findings.py`); the triage
    call, report-only, its due rule and recorded decisions, and the
    backlog rendered from the log and readied as `ladder/<draft>/backlog-<n>`,
    its queue records imported as `branch.*` and its `backlog:<draft>`
    signal (`fab/triage.py`, `fab.calls.start`'s `report_only`,
    `fab.spec_edit.commit_path`, `_import_queue`'s owners, the tick's
    triage steps, rebased on red-routing's `_tick_plan` wiring if that
    lands first); the page's `finding` asks, `finding-<n>` and
    `backlog:<draft>` signals and `## The ladder`
    (`fab/channel.py`); the landing report's QA figures. Built alone, an
    on-path finding stops at its foreman and holds its rung.
  - **Runs after it:** the repair path: `fab/fix.py` factored out of
    `fab/tier_reds.py` (launch, parse, section, settle, answers, task,
    `FIX_KINDS`, `RUNS`; red's behaviour and tests unchanged), fab-after-landing.md 2's
    `examine-red` and `remedy-red` renamed `examine-fix` and `remedy-fix`
    with it, `fab/fixes.py`, `fab/roles/foreman-finding.md` and
    `finding_actions`.
  - **Last, separable:** walks run by fab (the `walk` role, the `build`
    run, `boxes`, logins per walk, `fab.calls.TIMEOUTS`).
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
