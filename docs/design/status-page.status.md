# Status-page status

2026-10-30. Owner: s/multi-coord. Baseline: origin/main `580a456` plus `mc/events-1-r`.
Contract: `docs/design/status-page.md`, sections 2–4.

## Present and limits

- The index renderer, fixture-backed sources, public projection, cost tables,
  samples and atomic publication exist. Service/timer declarations are present;
  this rebase/docs task neither deploys nor checks the live website.
- Queue ready timestamps and queue/heavy draft joins are not collected. Costs
  remain unattributed and waits unknown rather than inferred. Run/session
  liveness is the collected history, with the collector's snapshot limits.
- The index consumes the last two hours of local and SSH-probed queue, runs,
  heavy, claims and sessions spools. Event sections state that window; queue
  charts have two hourly buckets, and costs show the last two hours and last
  hour. Events deduplicate by host/id, failed probes name unavailable hosts,
  and other sections still render. See `docs/design/records.md`, section 4.
- Durable drafts/questions still come from records, pulled through the sibling
  `tools/records/record`. The installed writer name `fabrig-record` does not
  affect this explicit reader path.
- Task summaries remain unimplemented; the index does not consume them.

## Release page: agreed design, not built

**Source of intent:** external `director-records.md`, section 5, agreed with
  the director on 10-30 at 09:13Z. The paths below are records data paths,
  and the commands below are planned interfaces, not available commands.

**Store layout:**

| Records path | Keeper | Data |
|---|---|---|
| `releases/<release>/page.toml` | Director | Title, intro, badge line, ordered sections; table columns, groups and rows/tiles rendering |
| `releases/<release>/rows/<table>/<row>.toml` | Row draft's coordinator, or director | Group, order, optional draft, text cells, updated time and writer |

**Sections are prose or tables.** Tiles, resumption steps, the ladder, work
items, known work and QA passes are separate tables. Tiles have label/value/note
columns. A row's draft determines its keeper; no draft means director. Green
keeps the outside-gate checks tile; QA keeps ladder and QA tiles/tables; upgrades
keeps its tile; the director keeps the overall release tile, steps and known
work. Each work item's draft keeps its row.

**The writer remains the only records writer.** Planned interfaces:

```text
record item RELEASE TABLE ROW [--group G] [--order N] [--draft D] --set KEY=TEXT ... --as WRITER
record item RELEASE TABLE ROW --delete --as director
record page RELEASE FILE --as director
status-page --release v0.1.0
```

**Updates preserve unspecified row fields.** A new row needs a group and draft
unless kept by the director. Only the row's draft coordinator mailbox or director
may update it; deletion and replacing page.toml are director-only. Validate page
columns and groups against existing rows before accepting a replacement.

**Cells are plain text, at most 400 characters.** Percent columns accept
`n/a`, `-`, `0%` through three-digit percentages, or ranges such as `66-73%`,
with the agreed pattern `^(n/a|-|[0-9]{1,3}%|[0-9]{1,3}-[0-9]{1,3}%)$`.
A bare `100` is refused with a `100%` hint. The renderer escapes text.
Reject secrets, private home paths, private machine names, mailbox/session
names, and run/session ids in every public page field and cell. Unlike the
index's machine cards, the release page carries no private machine labels.

**Render to a sibling and rename** over `/var/www/status/v0.1.0.html`, retaining
the current page's style and structure. Stamp it with the newest row update.
List rows unchanged for 24 hours while their draft is active. Extend the existing
status-page unit tick; no new unit is planned.

**Migration needs comparison before switch.** Import the hand-written page once
into page/row data. The director compares the first render with its current page
before ending the two-hour manual rewrite. Coordinators then update rows at
part starts/ends and value changes, replacing reply-on-request status gathering.

**Nothing above is implemented yet.** `record` rejects release paths and has
no `item` or `page` command. `status-page` has no `--release`; its only release
behavior is linking an existing sibling. There was no import or switch here.
The old director-role plan's manual rewrite stays a transitional duty, not an
implemented rendering feature. A future implementation updates this status
and `docs/design/status-page.md` together.

## Verification

`tools/records/test_status_page.py` uses temporary HOME, fake probes and a local
records origin, including actual collector-to-spool-to-renderer contract fixtures. The
gate is `bash tools/check.sh`; no live probes were used for this rebase/docs update.
