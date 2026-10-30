# Public status pages

2026-10-30. Owner: s/multi-coord. Code: `tools/records/status-page`.
Command reference: `tools/records/status-page.md`. Release-page work is specified
in `docs/design/status-page.status.md`; it is not implemented by this renderer.

## 1. In one page

- **The index at status.fabrig.ai projects pipeline facts.** It combines records
  events, draft metadata and live capacity/subscription probes. It publishes
  counts, fixed labels and public descriptions, not private work identifiers.
- **Every source can fail separately.** Missing measurements stay unknown;
  an empty event source says no events yet. Failure does not erase good sources.
- **Write a complete page, then replace.** The declared unit writes
  `/var/www/status/index.html` every ten minutes. A browser refreshes after five.
- **A release page has separate keepers.** Its agreed records data model and
  migration are in the status file until built. The current index only links
  an existing sibling `v0.1.0.html`.

## 2. Index sections and sources

| Section | Sources and meaning |
|---|---|
| Summary tiles | Draft count; six-hour mean landings/hour; running runs; merged subscription count; open user questions |
| Drafts | Records `drafts/*/draft.toml`, ordered by `director/priorities.toml` then metadata priority/name; descriptions from the first heading in fabrig's source document; last landing only with an explicit draft join |
| Landings and the queue | Queue batch/attempt events: six one-hour landing buckets, latest 20 batches, fixed outcomes and durations, rejections by known step; ready-to-landing remains unknown |
| Work in flight | Run/session lifecycle events for running runs and live leads/coordinators; live `claim list` for held/total slots; collected claim-event count |
| Waiting on the user | Unanswered records questions: count and oldest asking time |
| Costs | Completed run, heavy and queue events in last-hour and last-24-hour windows, globally and per explicit draft |
| Machines and capacity | Concurrent local/SSH probes for machine load, CPUs, available memory, disk and public IPs |
| Subscriptions | CLI usage/limit/reset probes merged by opaque account identity across hosts; optional samples for rates and projections |
| Links | Existing sibling release page, without reading its contents |

**Records paths in this section belong to the records repository.** The page
pulls before reading unless `--no-pull` is set. Runtime roots default to
`~/src/fabrig/records` and fabrig's `~/src/fabrig/main`. Machine targets come
from runtime `~/src/rust/tmp/post/machines`; remote machines receive the probe
code over stdin. There is no import or runtime dependency on this tree's `old/`.

**Count landings from attempts, not batches.** A green attempt in a non-dry
batch contributes one branch landing. Missing batch evidence cannot establish
that it was not dry. Deduplicate events by host and id; do not count the batch
again. Session/run counts are last collected lifecycle facts, not independent
process checks, so missed stops remain a collector limitation.

## 3. Costs and uncertainty

**Measure completed work only.** Run-end events supply minutes and input,
cached-input and output tokens, with effort subtotals. Heavy completion events
supply separate run/wait minutes by build/test/other lane. Queue gate minutes
sum top-level step durations once; nested suites are included in their parent.
Batch wall time is displayed separately. Dry-run work still costs time.

**Attribute only with explicit draft joins.** No inference from private branches,
runs, sessions or coordinator names. Missing/unsafe draft ids are unattributed.
Missing measurements make the affected cells unknown. Future or out-of-window
completions are excluded; running work is not estimated or prorated.

**Do not invent timing.** Queue events currently lack ready timestamps and full
draft joins, so ready waits and some draft landing ages remain unknown. Heavy
and queue costs currently have no draft join and remain unattributed. One failed
source does not make others unknown.

## 4. Publication and privacy

**The page is a public projection.** Escape all text. Keep question bodies,
mail metadata, branches, run/session ids and private paths out of rendered text.
Draft names and source headings are explicitly public inputs; their producers
must keep private prose out. Render probe failures as fixed classifications,
never raw exceptions or upstream command output. Machine cards intentionally
show configured public machine labels; the planned release page has a stricter
public-text policy.

**Persist safely.** `--out` writes a unique sibling, flushes and fsyncs it,
sets mode 0644 and renames over the target. Without it, HTML goes to stdout.
Optional `--samples` uses the same replacement pattern with mode 0600 outside
the web root. Samples contain opaque identity and usage measurements, retain
at most one day and 5,000 rows, and are not published as raw data.

**Units are deployment-owned.** `fleet/units/status-page.service` and
`fleet/units/status-page.timer` declare output, samples and cadence. Their owner
is s/deploy. This design specifies the renderer's behavior, not live installation.

## 5. Later

- Build the records-backed release renderer and its row/page commands, with
  keeper validation and public-field validation, as detailed in the status file.
- Import the director's current release page and compare before switching.
- Consume the records host spool and summaries when that migration lands.
- Collect exact ready timestamps and explicit draft joins to fill unknowns.
