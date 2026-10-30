# Public pipeline status page

`tools/records/status-page` is Python 3.13 with the standard library only. It
copies the legacy page's light/dark styling, summary tiles, tables, machine
cards, capacity probes, Claude/Codex subscription probes and usage sampling.
It has no runtime dependency on `old/`.

```
tools/records/status-page --out /tmp/status.html --no-pull
tools/records/status-page --out /tmp/status.html --samples /tmp/status-usage.jsonl
python3.13 -I -B tools/records/test_status_page.py
```

Without `--no-pull`, it runs `record pull` through PATH before reading
`RECORDS_REPO` (default `~/src/fabrig/records`). `record` must be the new records
writer. A failed pull is reported; available local records still render.
`FABRIG_REPO` defaults to `~/src/fabrig/main`. `--machines` defaults to
`~/src/rust/tmp/post/machines`; its two-column format is unchanged. A `local`
target probes this host; SSH targets receive this script over stdin, so remote
machines need no installed copy. `DEV_TMP`, `STATUS_NOW`, and
`STATUS_PROBE_TIMEOUT` retain the legacy probe/fixture overrides.

HTML is written to a unique sibling, flushed, fsynced, chmodded 0644, then
renamed over `--out`. Without `--out`, HTML goes to stdout. The optional samples
file uses the same replacement procedure and mode 0600. Put samples outside the
public web root. No samples file is created without `--samples`. Samples retain
only CLI, an eight-digit opaque account hash, limit, use, reset and sample time;
expired samples and those older than a day are pruned, with a 5,000 sample cap.
Subscriptions shared across hosts merge as before, with rate and projected use.
The page reloads after five minutes and carries `noindex`.

## Records and event payloads

The collector in [record-collect](record-collect) is the source of truth, with
its usage and limits in [record-collect.md](record-collect.md). The page consumes
that output directly: locally and through its existing SSH probe, which returns
the last 2 hours of queue, runs, heavy, claims and sessions alongside capacity
and subscription data. A failed source/probe names the unavailable host; other
sections still render. Durable drafts and questions continue to come from records. No alternative snapshot or invented ready/landing event
format is supported. Missing spool directories or empty source directories
render **no events yet**. A missing repository, malformed JSON/TOML, unreadable
source or failed probe renders **unknown** with a fixed error classification.
Sources fail independently. Raw exceptions, command output and paths never
render.

Events live at `~/src/fabrig/events/<source>/*.jsonl` on each host and have `id`, `source`, `host`,
`kind` and UTC `time`. Identical `(host, id)` events count once and are ordered
by time. Joins and other private fields are never displayed as text.

- **Drafts:** `drafts/*/draft.toml` supplies `source`, `state` and `priority`.
  Ordered `[[draft]]` entries with `name` in `director/priorities.toml` come first;
  unlisted drafts follow by numeric priority and name. Directory names are
  public. Descriptions use the first ATX or setext heading in
  `FABRIG_REPO/<source>`, never the body. Escaping paths/symlinks are refused.
  An unreadable heading leaves only that description unknown. A queue attempt's
  `draft`, if present, joins its landing to a draft. The current collector
  does not supply this join: landings without it leave draft ages unknown,
  rather than inferring a draft from a branch, coordinator or run.
- **Queue:** `kind=batch` gives `start`, `end`, `outcome`, `dry`, `branches` and
  top-level `steps` (which can contain nested `suites`). Duration is end minus
  start. The latest 20 batches display their fixed outcome (green, red, conflict,
  failed, cancelled, skipped; other values unknown) and duration.
  `kind=attempt` joins its batch by `(host, batch_start)`. A green attempt
  in a non-dry batch is one branch landing. Batch rows themselves never add
  landings. Two consecutive one-hour intervals cover exactly the preceding
  2 hours. Red/conflict attempts count rejections by `rejected_step`;
  unknown/private step names render as `other`. No branch, suite name or log
  is rendered. Missing batch records cannot establish dry status and contribute
  no landing. Ready-to-landing time is **unknown: ready timestamps not
  collected**. Neither batch start nor branch history is substituted for ready.
- **Runs:** `run-start` and `run-end` update private `(host, run)` identities.
  A start without a later end counts as running, with no guessed expiry.
- **Sessions:** `session-start` and `session-name` supply the latest
  name/role for a private `(host, session)` identity; `session-end` removes it.
 Recognized roles match the collector: `lead/...`,
  `coordinator/...`, `s/...`, coordinator, coord-next and coordinator-next.
  Only lead/coordinator counts render. These are last collected lifecycle facts,
  not independent process probes; missed stops remain a collector limitation.
- **Claims:** claim/release events show only their count; held/total slots
  always come from live `claim list`. Its host/slot/holder text is discarded.
- **Questions:** unanswered `director/questions/*.toml` contribute one question
  and their `asked` time. Only count and oldest age render. Bodies, options,
  asking identities, recommendations and answers never leave the reader.
- **Links:** a sibling regular file (or symlink to one) `v0.1.0.html` is linked
  beside `--out` if present. Its contents are never read. No link without --out.
- **Post/leases:** the page does not read their private metadata at all.

Landings and the queue, work in flight and costs are labeled **last 2 hours**.
Lifecycle counts reflect only transitions retained in that window; a start before
the window cannot establish current membership on its own.

### Costs

Costs show **Last 2 hours** and **Last hour**, using event completion times.
A completed event contributes its full measurements to each applicable window;
running work is not estimated or prorated. Future and older events are excluded.
Tables contain only global totals and per-draft aggregates. The event's own
`draft` is the sole attribution source; missing or unsafe draft ids become
`unattributed`. Joins via run, branch, coordinator or session never infer a draft.

- **Codex runs:** `run-end.minutes`, `tokens_in`, `tokens_cached`, `tokens_out`,
  grouped by fixed `effort` (minimal/low/medium/high/xhigh/max/ultra, else other).
  Both all-effort totals and effort subtotals appear globally and per draft.
  A missing measurement makes that aggregate cell unknown, not zero.
- **Heavy:** `command.run_s` and `wait_s` become minutes. `lane=build` and
  `lane=test` have separate run/wait columns; other lanes have other/run-wait
  columns. Labels and commands are never used to guess classification. The
  collector currently supplies no draft join, so current costs are unattributed.
- **Queue gates:** sum only top-level `batch.steps[].duration` in seconds,
  converted to minutes. Nested suites are already included in their parent
  gate and are not counted again. Batch wall time is displayed separately and
  is not substituted for gate time. Missing/invalid durations give unknown.
  Attempts never add gate minutes. Dry-run gate work, if recorded, still costs
  time. The collector currently supplies no draft join, so these are unattributed.

Empty source directories say no events yet; a source with no completions in the
window says so. Failed cost sources show unknown while the others still render.

Draft names and source headings are explicitly public fields. Their producers
must keep people's names and private prose out of them. As additional protection,
the reader rejects obvious email, session, token and path syntax even there;
it does not attempt to identify arbitrary people's names in prose. Other inputs
are projected to numbers, fixed labels, known plan/limit patterns or opaque
subscription hashes. Raw machine error strings and upstream subscription display
names cannot reach the HTML.

## Removed legacy sources

- Landing turns: the new pipeline has no landing-turn source; queue events now
  carry the landing timeline.
- Landing sets and their feed: replaced by mq batches, outcomes and step results.
- `landings` feeds and plain `land` records: replaced by records queue events;
  no collector reads the legacy feed location.
- Mission READMEs, their history and blocked/ended mission tables: missions moved
  into frozen `old/`; current work comes from drafts, priorities and questions.
- Legacy heavy TSV and Codex-run file readers: costs now come from collected
  heavy/run/queue events, with no legacy per-mission joins.
- Forgejo waiting-on-user issue counts: private director question records are
  now the authoritative source of user waits; no Forgejo token is read.
- Legacy `install`/unit writer and `--json`: outside this port's interface.
  Deployment must repoint the existing timer through the fleet's unit workflow.

## Verification and deployment boundary

Fixtures cover each source, public descriptions/order, question age, queue
buckets/batches/rejections/dry runs, live slots, real session transitions,
cost windows/attribution/missing measurements, subscription sampling and rate,
fake Claude/Codex probes, poisoned fields, partial failures, empty events and
atomic replacement. The contract test reuses test_record_collect.py's producer
fixture builders and actually executes record-collect into a temporary spool with a local
bare records origin left untouched before rendering, including session renames/stops and green attempts.

For acceptance, isolate HOME, cursors and spool; expose real producer files read
only. Run available collector sources, then render with a scratch durable records
clone and `--no-pull`. Never write `/var/www/status/`. Fleet deployment remains
separate; existing collector command lines and units are compatible.
