# Local records collection

`record-collect SOURCE... [--host NAME] [--dry-run] [--since ISO]` reads
`runs`, `queue`, `heavy`, `sessions`, `claims`, `leases`, `post`, and `post-sent`. Paths
are relative to HOME: `src/rust/tmp/{codex-run,logs/heavy.tsv,heavy,post}`
and `src/fabrig/{notes/queue.jsonl,claims,leases}`. Queue area mappings come
from `src/fabrig/main/tools/queue/leads.txt`. Default host resolution uses
`post/machines` (`local` names this machine, otherwise match its hostname);
`--host` overrides it. Absent inputs print `skip SOURCE: reason`. Errors
name the source after trying the others. Exit policy: 0 when every selected
source succeeds, skips or defers publication; 2 when any source fails, including
publication or cursor errors, or publication defers for six consecutive runs.
An optional-part skip is also successful. A deferred run prints
`record-collect: deferred (k/6): <record's reason>`; errors also include record's
stderr. A confirmed publication prints `record-collect: published N events`,
including `published 0 events` for an empty run; exit 0 alone is not a publication
receipt.

All successfully read sources in a run publish together via the sibling
`record append --as collect --batch HOST`: one commit and at most one successful
push for the run. Record retries races up to five attempts, with a random 1–5
second pause between tries; retries cost only rejected attempts. Empty or wholly
duplicate batches make no commit or push.
A failed source does not prevent the others from publishing.
SHA-256 ids include source, host, kind and the producer's natural identity.
The private `~/.local/state/record-collect/SOURCE.json` cursor stores log
offsets, seen ids and snapshots. Source locks serialize runs; 0600 files
are flushed to siblings and renamed. A private pending outbox preserves
exact events through publication/cursor failures, including UTC midnight.
All selected source locks are acquired in a fixed order and held through
publication and cursor updates. A deferred batch preserves every staged event and cursor, updating only its
deferral counters. A failed batch preserves the events and cursors too. After a successful push, a cursor-write failure leaves the
remaining outboxes for idempotent replay without another commit for those ids.
After record exhausts its retries or encounters a rebase conflict, publication
is deferred to the next poll. Each pending transaction stores a `deferrals`
counter outside its cursor state; the sixth consecutive deferral exits 2.
`SOURCE.publication.json` also exposes `deferrals`, `status` and the last reason
for local inspection and watch heartbeats, under the same source lock.
A real publication error resets the counter and exits 2 immediately. Successful
publication removes the outbox and its counter.
Only a publication confirmed by fetching origin and checking commit containment
advances the cursor or drains its pending outbox. A lost acknowledgement can
therefore complete safely without publishing duplicate ids. The saved batch is
unchanged even if a producer appends new input while record is retrying; that
input is collected on the following run. `--dry-run` prints JSONL
without creating state or invoking `record`. Source counts go to stderr.
The first cursor uses `--since` or seven days ago; later runs retain that
bound. Complete log lines alone advance offsets; rotation safely replays ids.

Runs join through the task header, falling back to a prose `branch` followed
by a backtick-quoted name, or `ready/...`; recipient names supply area and
coordinator. Queue batches retain outcomes, selection, safe step durations
and available sizes/cleanup counts; attempts join branches through leads.txt.
Heavy's completion TSV is authoritative; release events add token/outcome.
Multi-line commands are joined into logical rows at task/lane/timestamp row
starts. Malformed rows are skipped with a count on stderr; unfinished trailing
rows keep their starting offset so a later append can complete them.
Slot claims naming a run supply its join. Command arguments are not collected.
Sessions diff the pipeline names returned by `claude agents --json`; a missing
session produces an observed end, a rename produces `session-name`. Every
live pipeline session also gets a fresh `session-context --name` reading
on each collection, so that source intentionally is nonempty on repeat runs.

Claims and leases diff snapshots. Missing claims/holders produce observed
releases; waiter/lend removals use `want`/`lend` with `active = false`.
Snapshot collectors cannot reconstruct changes between polls. Post reads
only unbuffered headers in each mailbox's `new/` and `cur/`, never bodies
or `sent/`. Mail ids include the destination mailbox. Delivery uses inode
mtime; read time uses ctime after the move to `cur/` (marked
`read_time_basis = "inode-ctime"`). Post stores neither timestamp explicitly:
copies, chmod or restores can change this evidence. Subjects are collected
as requested metadata; acceptance reports must redact their values.

Run `python3 -I -B tools/records/test_record_collect.py`. Fixtures use synthetic
identities and headers only, a temporary HOME, a bare local origin, and fake
Claude/context commands. Tests cover every source, joins, cursor advance,
partial lines, rotation, publication retries, read boundaries, and isolation.

The sessions source checks `session-context --capabilities` once per
collection. If the check fails or omits `fired-markers`, it prints
`skip sessions/fired: <why>` to stderr and still collects session lifecycle,
name, context and files-current events. Otherwise it reads
`session-context --fired --json`; failures or invalid markers are real errors.
Each resolved marker yields a `handover-needed` event for its first firing and an append-only update for each later observed last firing.
Ids join session id, first firing and the observed firing timestamp; replay
keeps the same ids. Fields include `session`, `name`, `role`, `reason`,
`first_fired` and `last_fired`. Unresolved names are skipped. Polling cannot
recover intermediate firings overwritten between observations. Context
readings alone are never hook-fired evidence.

Sessions also projects lead end posts into `files-current` events: the
sender must be a lead and the subject must start with `files current`
(case-insensitive). Only the post header is read. The event carries the
sender as `name`, message id and delivery time, and replays idempotently.

`post-sent` reads `src/rust/tmp/post/sent.jsonl`, skipping the source while
absent. Its agreed rows are `{time, from, to, subject_sha256, message_id, exit}`;
the subject hash is 64 lowercase hex characters. It emits `send` events,
with sender joins, stable ids, and only those metadata fields. Complete-line
cursors, rotation replay and pending publication recovery work as for other
logs. Exit 2 is delivery failure; a later row for the same message id can
record success. This source reads neither subjects nor bodies.

The sessions source also reads `session-start names --json` (PATH, with sibling
`../session/start` fallback). Codex leads bypass Claude lookup: user-unit active
transitions emit `session-start`/`session-end`, tagged `session_kind="codex-owner"`
(`kind` remains the event type). Each owner gets a `session-context --owner NAME`
reading, without Claude's calls field. Exit 3 emits `handover-needed` once per
threshold crossing; a below-threshold reading or a new thread permits the next
crossing. Cursor counters keep crossing ids stable on retries. Owners without
a measurement print a metadata-only skip while unit transitions still collect.
Unit query failures are errors; missing/inactive units are valid observations.
