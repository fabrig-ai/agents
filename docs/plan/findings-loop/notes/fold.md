# The fold and its readers

For `findings-fold`, `rungs-fold`, `ladder-plan` and every task that reads
`fab.findings` (`qa-intake`, `triage-decisions`, `triage-brief`,
`tick-triage`, `ladder-page`).

## Records (fab.md section 3; 13.15)

- `walk.started`: walk, draft, rung, backend, edition, commit, by.
- `walk.ended`: walk, verdict (`pass`, `fail`, `void`), reason, report,
  findings (the ids, a list).
- `finding.raised`: finding, draft, walk, index, rung, backend, commit,
  edition, kind (`qa`), title, severity, area, blocking, reproduction,
  expected, seen, evidence (a list of strings), again (an id or "").
- `finding.merged`: finding, into, by (the walk id or the call id), reason.
- `finding.triaged`: finding, call, decision (`path`, `backlog`, `user`,
  `brief`, `drop`, `again`), owner, reason, question, into. Every field is
  present, "" when unused: path: owner the tree, question the `; user:`
  action or ""; user: question; brief: owner the rung, question what is
  wrong; again: into the target.
- `rung.passed`: draft, rung, walk, edition, commit.
- `call.answered` (13.6) with subject `<draft>/triage/<finding>` answers a
  finding's question; `signal.cleared` with signal `finding-<n>` drops it.
- The repair path's records, which this plan never writes but the fold
  reads (the second plan adds the writers): a foreman's `run.started` and
  `run.ended` with task `<draft>/finding-<n>/foreman`
  (`fab.foreman.task_field`); `finding.settled` (finding, run, verdict `fix`,
  `none` or `left`, reason, section); the repair's `run.started` and
  `branch.landed` with task `<draft>/finding-<n>`.
- Ids are global: `walk-<n>` and `finding-<n>`, n one more than the
  `walk.started` (`finding.raised`) records in the whole log.

## Bound names in fab/findings.py

- `BACKENDS: dict[str, tuple[str, ...]]`: `{"chatgpt-forgejo": ("chatgpt",),
  "claude-forgejo": ("claude-box",), "chatgpt-github": ("chatgpt",
  "github")}`, the login kinds each backend's walk borrows.
- `VERDICTS = ("pass", "fail", "void")`, `SEVERITIES = ("low", "medium",
  "high")`, `DECISIONS = ("path", "backlog", "user", "brief", "drop",
  "again")`, `WALK_HOURS = 4`.
- `STATES`: `new`, `asked`, `foreman`, `deciding`, `decided`,
  `repairing`, `landed`, `fixed`, `unfixed`, `left`, `backlog`, `dropped`,
  `merged`.
- `Finding` (frozen dataclass): `id`, `draft`, `walk`, `index`, `rung`,
  `backend`, `commit`, `edition`, `title`, `severity`, `area`, `blocking`,
  `reproduction`, `expected`, `seen`, `evidence` (tuple), `again`, `raised`
  (its ts), `verdict` (its walk's), `state`, `into` (merged: the direct
  target), `owner`, `reason`, `question` (the open question, or ""), `action`
  (an open `; user:` action, or ""), `answers` (tuple of the user's answer
  texts, oldest first), `sightings` (tuple: ids merged into it), `landed`
  (the `main` of its repair's `branch.landed`, or ""); and the property
  `holds`: blocking or its walk's verdict is fail or void, and the state is
  one of new, asked, foreman, deciding, decided, repairing, or `action` is
  open.
- `findings(events) -> dict[str, Finding]`, `target(found, identifier) ->
  str`, `mergeable(finding) -> bool` (findings-fold); `RungState`,
  `holders(found, rung) -> tuple[Finding, ...]`, `rungs(plan, events,
  editions, now) -> list[RungState]`, `passes(plan, events, editions) ->
  list[dict]`, `line(state) -> str` (rungs-fold).

## Defaults for what the fold meets

- A record with a missing or wrongly typed field is skipped, never an
  exception (as `fab.tier_reds.reds` does).
- A finding of a walk with no `walk.ended` is not in the fold.
- Folds are pure and read the log in its order; "later" means later in the
  log, not a later ts.
