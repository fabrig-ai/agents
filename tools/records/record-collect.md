# Local records collection

`record-collect SOURCE... [--host NAME] [--dry-run] [--since ISO]` reads
`runs`, `queue`, `heavy`, `sessions`, `claims`, `leases`, `post`, and `post-sent`. Paths
are relative to HOME: `src/rust/tmp/{codex-run,logs/heavy.tsv,heavy,post}`
and `src/fabrig/{notes/queue.jsonl,claims,leases}`. Queue area mappings come
from `src/fabrig/main/tools/queue/leads.txt`. Default host resolution uses
`post/machines` (`local` names this machine, otherwise match its hostname);
`--host` overrides it. Absent inputs print `skip SOURCE: reason`. Errors
name the source after trying the others. Exit policy: 0 when every selected
source succeeds or skips; 2 when any source fails, including spool or cursor
errors. Each source is attempted even when another fails. No git command or
records writer is invoked, and RECORDS_REPO/RECORDS_ORIGIN are ignored.

Events go to `~/src/fabrig/events/SOURCE/YYYY-MM-DD.jsonl`, on this host.
`event_spool.py` sets retention to **2 hours**. Every successful source collection,
including an empty one, merges stable ids, drops events with `time` older than
that cutoff, atomically replaces day files and removes days left empty. The exact
cutoff is retained. A source lock serializes cursor/collection/spooling; a spool
source lock also protects the files. Files are mode 0600, flushed and fsynced to
siblings before rename. Readers see complete files. Producer files are read only.

SHA-256 ids still include source, host, kind and the producer's natural identity.
The private `~/.local/state/record-collect/SOURCE.json` cursor stores log offsets,
seen ids and snapshots. A pending outbox preserves exact events and cursor state
through a spool or cursor-write failure, including UTC midnight. Replaying it
skips ids already in the spool; only a successful spool write advances the cursor
and removes the outbox. Retained seen ids prevent re-collection even after expiry.
Old pending outboxes are drained into the spool, with expired events and context
samples discarded. Old git publication counters are removed on success.

`--dry-run` prints JSONL without creating state or changing the spool. Source
counts go to stderr. Normal runs print `record-collect: spooled N events` (the
number collected before retention). The first cursor uses `--since` or seven
days ago; later runs retain that bound. Complete log lines alone advance offsets;
rotation safely replays ids. Retention applies independently of that lower bound.

Runs join through the task header, falling back to a prose `branch` followed
by a backtick-quoted name, or `ready/...`; recipient names supply area and
coordinator. Unclosed or invalid TOML headers, invalid join values, and unreadable
or undecodable task files never fail the runs source. Their events retain their
run identity and facts, omit every task/recipient join key, and carry a fixed,
content-free `header_error`. The summary is `runs: N events, M header errors`;
M counts emitted events carrying that annotation (a start and end count twice).
Other runs and sources still collect normally. Queue batches retain outcomes, selection, safe step durations
and available sizes/cleanup counts; attempts join branches through leads.txt.
Heavy's completion TSV is authoritative; release events add token/outcome.
Multi-line commands are joined into logical rows at task/lane/timestamp row
starts. Malformed rows are skipped with a count on stderr; unfinished trailing
rows keep their starting offset so a later append can complete them.
Slot claims naming a run supply its join. Command arguments are not collected.
Sessions diff the pipeline names returned by `claude agents --json`; a missing
session produces an observed end, a rename produces `session-name`. No context samples are emitted or requested for Claude sessions. Repeated
unchanged sessions produce no new events.

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
partial lines, rotation, spool failure recovery, read boundaries, and isolation.

The sessions source checks `session-context --capabilities` once per
collection. If the check fails or omits `fired-markers`, it prints
`skip sessions/fired: <why>` to stderr and still collects session lifecycle,
name and files-current events. Otherwise it reads
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
cursors, rotation replay and pending spool recovery work as for other
logs. Exit 2 is delivery failure; a later row for the same message id can
record success. This source reads neither subjects nor bodies.

The sessions source also reads `session-start names --json` (PATH, with sibling
`../session/start` fallback). Codex leads bypass Claude lookup: user-unit active
transitions emit `session-start`/`session-end`, tagged `session_kind="codex-owner"`
(`kind` remains the event type). The owner threshold probe is retained solely to produce handover firings;
no `context` event or token measurement is stored. Exit 3 emits `handover-needed` once per
threshold crossing; a below-threshold reading or a new thread permits the next
crossing. Cursor counters keep crossing ids stable on retries. Owners without
a measurement print a metadata-only skip while unit transitions still collect.
Unit query failures are errors; missing/inactive units are valid observations.
