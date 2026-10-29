# Local records collection

`record-collect SOURCE... [--host NAME] [--dry-run] [--since ISO]` reads
`runs`, `queue`, `heavy`, `sessions`, `claims`, `leases`, and `post`. Paths
are relative to HOME: `src/rust/tmp/{codex-run,logs/heavy.tsv,heavy,post}`
and `src/fabrig/{notes/queue.jsonl,claims,leases}`. Queue area mappings come
from `src/fabrig/main/tools/queue/leads.txt`. Default host resolution uses
`post/machines` (`local` names this machine, otherwise match its hostname);
`--host` overrides it. Absent inputs print `skip SOURCE: reason`. Errors
name the source and return 2 after trying the others; success returns 0.

Each source publishes once via `record append --as collect SOURCE HOST`.
SHA-256 ids include source, host, kind and the producer's natural identity.
The private `~/.local/state/record-collect/SOURCE.json` cursor stores log
offsets, seen ids and snapshots. Source locks serialize runs; 0600 files
are flushed to siblings and renamed. A private pending outbox preserves
exact events through publication/cursor failures, including UTC midnight.
Only successful publication advances the cursor. `--dry-run` prints JSONL
without creating state or invoking `record`. Source counts go to stderr.
The first cursor uses `--since` or seven days ago; later runs retain that
bound. Complete log lines alone advance offsets; rotation safely replays ids.

Runs join through the task header, falling back to a prose `branch` followed
by a backtick-quoted name, or `ready/...`; recipient names supply area and
coordinator. Queue batches retain outcomes, selection, safe step durations
and available sizes/cleanup counts; attempts join branches through leads.txt.
Heavy's completion TSV is authoritative; release events add token/outcome.
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
