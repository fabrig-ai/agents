# The triage family

For `triage-shell`, `triage-decisions`, `triage-brief`, and what
`tick-triage`, `backlog-branch` and `ladder-page` read of `fab.triage`.

## The call

- Role `triage`, effort medium, subject `<draft>/triage`, role text
  `fab/roles/triager.md`, started by the tick as `fab call triage --plan
  PLAN_DIR` (`fab.triage.main(argv)`, handed over from `fab.calls.main`).
- Report-only: `fab.calls.start(..., report_only=True)` makes no branch,
  pushes nothing, and its `call.started` has no `branch` field. Not in
  `fab.call_review.REVIEWED`: no chain, review, finish or landing.

## The report (bound: the role text says it, the parser reads it)

- First line `Done: <n> decisions`, or `Question: <what>` (only the user's,
  for the whole batch), or `Failed: <why>`.
- Then one line per decision, each starting at column 0 with a finding id:
  - `finding-<n>: path <owner>: <why>` optionally ending `; user: <what the
    user must do>`;
  - `finding-<n>: backlog: <why>`;
  - `finding-<n>: user: <the question>`;
  - `finding-<n>: brief <rung>: <what is wrong>`;
  - `finding-<n>: merge finding-<m>: <why>`;
  - `finding-<n>: drop: <why>`.
  `<owner>` and `<rung>` are one token each (no spaces, no colon). Any other
  line is prose and ignored.

## Bound names in fab/triage.py

- `ROLE = "triage"`; `AT = 4` and `AFTER = 30` (minutes): the answerer's
  thresholds, equal to `fab.dispatch.ANSWER_AT` and `ANSWER_AFTER` (a test
  pins it; fab.dispatch imports fab.triage, so not the reverse).
- `subject(draft) -> str`: `<draft>/triage`.
- `due(plan, events, now) -> bool` (13.15 "When").
- `decisions(plan, events, reports) -> list[tuple[str, dict]]`: the records
  to log, `(ev, fields)`, for each triage call ended done not yet recorded;
  reports maps a call id to its report text (the tick reads
  `FAB_HOME/calls/<call>/report.md`; a missing one is not in the map and
  the call is skipped until it is).
- `backlog_text(plan, events) -> str`; `render_key(text) -> str` (sha256 hex
  of the UTF-8 text: `branch.ready`'s `render`).
- `backlog_held(plan, events, render) -> dict | None`: the latest
  `branch.rejected` of a `ladder/<draft>/backlog-<n>` branch when two such
  rejections of branches readied with this render come after the latest
  `signal.cleared` of `backlog:<draft>` and after the latest backlog
  `branch.landed` of the draft; else None. The tick readies nothing while it
  holds; the page shows `backlog:<draft>` while it holds.
- `brief(...)`, `main(argv)` (triage-brief).
