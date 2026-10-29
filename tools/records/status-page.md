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

The records writer currently validates the common envelope, not individual
collector payloads. These are the reader's supported payloads; collectors must
agree on them before populated events can be accepted in production. Until then,
missing `events/` directories or empty source directories render **no events
yet**. A missing records repository, malformed JSON/TOML, unreadable source or
failed probe renders **unknown**, with a fixed error classification. Sources
fail independently. Raw exceptions, command output and paths are never rendered.

All event files are `events/<source>/<host>/*.jsonl`; an event has `id`, `source`,
`host`, `kind` and UTC `time`. Identical `(host, id)` events are counted once,
then ordered by time. Unknown envelope fields are ignored. These fields are
read only for joins or converted to numbers/enums; identities never render.

- **Drafts:** `drafts/*/draft.toml` supplies `source`, `state` and `priority`.
  Ordered `[[draft]]` entries with `name` in `director/priorities.toml` come
  first; unlisted drafts follow by their numeric priority, then name. The draft
  directory's name is public. Its description is the first ATX or setext heading
  of `FABRIG_REPO/<source>`, never the body. Absolute paths outside that root,
  traversals and escaping symlinks are refused. An unreadable heading leaves
  only that description unknown. Queue landings joined by `draft` supply the
  last-landing age. No matching landing says no events yet.
- **Queue:** `kind=ready` records a branch/task's ready time. `land`, `landed` or
  `landing` is one landing; `draft` joins it to a draft. Six consecutive one-hour
  intervals cover exactly the preceding six hours, with UTC labels and counts.
  `ready_to_landing_s`, `ready_at` or `ready` gives elapsed time where present;
  otherwise a prior ready event joined by `branch` or `task` does. The median
  and sample count show the available timings only.
  `batch-start`, `batch-end` or `batch` uses `batch` as the private identity
  (otherwise `id`), `outcome`, and `duration_s` or `started`; paired starts/ends
  also yield duration. The latest 20 batches show outcome/duration, never names
  or branches. A landed batch counts as one landing if it has no explicit
  branch landing in that batch, preventing double counting. `reject`/`rejected`
  or `outcome=rejected` groups rejections by a fixed step enum; other steps say
  `other`. Outcomes outside the fixed enum say unknown. Free text logs and
  rejection messages are discarded. Unknown kinds contribute no metric.
- **Runs and sessions:** `kind=snapshot` replaces that host's state with a `runs`
  or `sessions` list. Alternatively `start`/`started`/`running`/`run-start`/
  `session-start` and `end`/`ended`/`completed`/`failed`/`stopped`/`run-end`/
  `session-stop` update private `run` or `session` join keys. Live states are
  running, active, busy, idle and waiting. Sessions use `role=lead|coordinator`,
  or infer the role from private `name`/`session` prefixes. Only counts render.
  These are last collected states, so freshness depends on the collectors.
- **Claims:** events show only their count (or no events yet); current held and
  total slots always come from live `claim list`, never reconstructed from an
  incomplete event history. Its host/slot/reservation/holder text is discarded.
- **Questions:** `director/questions/*.toml`, without `answer` or `answered`,
  contribute one question and their `asked` timestamp. Only count and oldest
  age render. Bodies, options, asking identity, recommendations and answers
  never leave the reader.
- **Links:** `v0.1.0.html` is linked only when a regular file (or symlink to one)
  exists beside `--out`. Its contents are never read. No link without `--out`.

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
- Legacy heavy-command and Codex-run cost tables: their per-mission joins no
  longer exist; the new page shows queue timing and records work counts.
- Forgejo waiting-on-user issue counts: private director question records are
  now the authoritative source of user waits; no Forgejo token is read.
- Legacy `install`/unit writer and `--json`: outside this port's interface.
  Deployment must repoint the existing timer through the fleet's unit workflow.

## Verification and deployment boundary

Fixtures cover each source, priority ordering, public descriptions, question
age, queue buckets/batch duration/wait, live slots, snapshots and transitions,
subscription sampling and rate, fake Claude/Codex probes, poisoned private fields,
malformed sources, empty events, and atomic replacement/failure cleanup.

For acceptance, clone the real records into a fresh temporary directory and
render with `RECORDS_REPO=<clone> --no-pull --out <temporary index.html>` using the
real machines/probes. Compare its h1/h2 headings to `/var/www/status/index.html`
read only, record the byte size, and inspect matches of
`grep -E 'lead/|s/[a-z]|coord-next|@|sessionId'`.

This change never writes `/var/www/status/`, changes the timer, or deploys the
page. Fleet deployment and collector payload agreement remain follow-up work.
