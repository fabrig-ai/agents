# Records status

2026-10-30. Owner: s/multi-coord. Contract: `docs/design/records.md`, sections 2–5.
Baseline: agents origin/main `580a456` plus `mc/events-1-r`. The spool portion of
the contract is implemented; the remaining durable-memory work is listed below.
This describes repository code, not verified fleet deployment.

## Present

- **The locked writer exists.** `tools/records/record` validates paths, formats,
  sizes and secrets, commits, and retries publication against confirmed origin.
  Its commands are `pull`, `write`, `append`, `check`, `show`, `draft`, `priority`,
  `ask`, `answer`, `questions`, `decide` and `status`. Director writes and reads
  require `--as`; see `tools/records/record.md`, "Director commands".
- **Collectors exist** for runs, queue, heavy, sessions, claims, leases, post and
  post-sent. They write `~/src/fabrig/events/<source>/<UTC-day>.jsonl` on each
  host, never records git. Stable ids, source locks and pending outboxes protect
  spool/cursor recovery. Each poll atomically rewrites retained day files under
  the source lock, drops events older than two hours and removes empty days.
  See `tools/records/record-collect.md`.
- **Sessions emit no context samples.** Lifecycle, handover-needed and
  files-current facts remain. The Codex threshold probe supplies handover facts
  without storing context measurements.
- **Malformed task headers do not stall runs.** Unclosed/invalid TOML headers,
  invalid join values and unreadable task files leave joins empty and add a
  short, content-free `header_error`. Other events continue and the source
  succeeds when everything else succeeds. The runs summary counts annotated
  events, including both start and end when affected.
- **Readers use host spools.** Watch and status-page combine local events with
  each host's bounded SSH probe. Watch stores its alerts and heartbeat in hel8's
  watch spool; replay accepts a host spool directory. See `docs/design/watch.md`,
  sections 2–4, and `docs/design/status-page.md`, sections 2–3.
- **Raw-event writes are refused by every records writer.** Only
  `events/after-landing/` remains accepted; automatic declarations contain only
  after-landing. Director and agent judgement commands remain available.
- **After-landing verdicts have a declared writer** in `tools/records/writers.toml`.

## Gaps and departures

- **Fleet rollout and the historical rewrite are separate actions.** This
  branch does not deploy tools or rewrite the records repository. Once every
  host uses the spool collectors/readers, remove historical raw events while
  retaining durable after-landing verdicts.
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
  is `tools/records/record`. Watch and status-page use the sibling writer for
  durable reads; collectors do not invoke the records writer.
- **Rights are coarser than the new contract.** Declared producer writers are
  restricted to their sources and append-only operations. General post-name
  writers are syntactically validated, without full role-to-path authorization.

## Verification

`tools/records/test_record.py`, `tools/records/test_record_collect.py` and
`tools/records/test_event_spool.py` exercise local fixture origins, atomic retention,
nonfatal header errors and temporary HOME. `bash tools/check.sh` is the gate.
Deployment and records-history migration are not established by these fixtures.
