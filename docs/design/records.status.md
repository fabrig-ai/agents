# Records status

2026-10-30. Owner: s/multi-coord. Contract: `docs/design/records.md`, sections 2–5.
Baseline: agents origin/main `1335337`. This is the new contract, ahead of code.

## Present

- **The locked writer exists.** `tools/records/record` validates paths, formats,
  sizes and secrets, commits, and retries publication against confirmed origin.
  Its commands are `pull`, `write`, `append`, `check`, `show`, `draft`, `priority`,
  `ask`, `answer`, `questions`, `decide` and `status`. Director writes and reads
  require `--as`; see `tools/records/record.md`, "Director commands".
- **Collectors exist** for runs, queue, heavy, sessions, claims, leases, post and
  post-sent. Stable ids, source locks, pending outboxes and confirmed publication
  protect retries. See `tools/records/record-collect.md`.
- **After-landing verdicts have a declared writer** in `tools/records/writers.toml`.

## Gaps and departures

- **Raw events still enter git.** Both collectors and watch invoke the sibling
  writer's `append`. The schema accepts `events/<source>/<host>/<date>.jsonl`,
  not just after-landing. No per-host event spool or two-hour pruning exists.
  Sessions still emit context samples on every poll. Private retry outboxes are
  publication recovery state, not the designed live event spool.
- **No summarizer exists.** `record-collect` accepts only its eight sources;
  there is no `summarize` command, open-task carry state or task-summary schema.
  Queue and heavy events do not yet carry full draft joins.
- **Role memory is not implemented.** `record state`, `record log`,
  `record incident` and `record close part` do not exist. State, journal and
  incident paths in sections 2–3 are not accepted. `status --as NAME` currently
  shows drafts, open questions, recent decisions and last-hour event counts,
  without role state, incidents or task summaries.
- **Lifecycle writes are absent.** `tools/session/start` reads the scratch brief
  and starts the lead; it never invokes the writer to commit that brief.
  It does not commit handovers at `--next` or closings when a part ends.
- **R1 snapshot paths remain accepted.** The current schema is
  `sessions/<role>/<mailbox-with-slashes-as-plus>/<YYYYMMDDTHHMMZ>-{handover,state,common}.md`,
  for coordinator, lead, director and ops. These are still snapshots, not
  `state.toml` and journals. They must survive until the replacement is usable.
- **Release paths and commands are absent.** See `docs/design/status-page.status.md`.
- **Installed name differs.** `tools/installed` exposes this writer as
  `fabrig-record`; the contract calls it `record`. Direct repository invocation
  is `tools/records/record`. Status-page still resolves `record pull` on PATH;
  collectors and watch use the sibling writer explicitly.
- **Rights are coarser than the new contract.** Declared producer writers are
  restricted to their sources and append-only operations. General post-name
  writers are syntactically validated, without full role-to-path authorization.

## Verification

`tools/records/test_record.py` and `tools/records/test_record_collect.py` exercise
local fixture origins and temporary HOME. `bash tools/check.sh` is the gate.
No live records were read or changed for this backfill.
