# Login custody

`logins` coordinates exclusive custody of refreshing credentials and programs'
signed-in configuration directories. It is a standalone Python 3.13 tool using
only the standard library, with no product dependency or network access. It
never reads, prints, copies or hashes login contents. A grant prints a path;
the caller imports and exports a file through its product, or uses a program's
configuration directory in place. Custody alone never moves a login.

```
logins add NAME PATH
logins replace NAME PATH
logins take NAME --as HOLDER [--note TEXT] [--run ID] [--wait SECONDS | --now]
logins take POOL --any --as HOLDER [--note TEXT] [--run ID] [--wait SECONDS | --now]
logins drop NAME --as HOLDER
logins drop POOL --any --as HOLDER
logins give NAME --as HOLDER
logins list [NAME] [--json]
```

Names match `[a-z][a-z0-9-]*`; `lock` and `waiting.json` belong to the tool.
Holders match `[a-z][a-z0-9-]*(/[a-z0-9][a-z0-9-]*)*`. Notes contain at most
120 characters and no control characters or Unicode line separators. Waits
are finite nonnegative seconds. `--wait` and `--now` are mutually exclusive.

## State and privacy

Custody state is kept on hetzner6, where the logins rest, in `~/src/rust/tmp/logins/`.

`DEV_ROOT` defaults to `~/src/rust`; `DEV_TMP` defaults to `$DEV_ROOT/tmp`.
Both expand `~` and become absolute paths. State lives in
`$DEV_TMP/logins/` (0700), with a global `lock` and `waiting.json` (0600).
Each `NAME/` is 0700 and contains `login`, `lock`, optional `holder.json`,
and `log.tsv`. Metadata files and locks are 0600. The process sets umask 077.

A resting login is an owned, nonempty regular file of mode exactly 0600 or
an owned directory of mode exactly 0700 with at least one entry. Links and
other file types are refused. Files are checked by `lstat`, never opened.
A directory is checked through one descriptor opened with `O_NOFOLLOW`;
`fstat` checks it and `scandir` asks for just its first entry. Entry contents,
permissions and descendants are never inspected. A directory swapped for a
link during checking is refused. These checks do not inspect account validity.

The tool refuses symlinked tmp, state root, login directories and known state
paths, and incorrect state-directory or metadata modes. Global lock and queue
files must also have exactly one hard link. It checks the entire discovered
registry even for an operation on one name. It does not repair unsafe state.

`holder.json` has `holder`, `note`, `since`, and an optional `run` (an ID
string or null). Older state without `run` remains readable and reports null.
A granted take with `--run ID` records that ID; without it the field is omitted.
IDs have 1–256 ASCII characters, start with a letter, digit or underscore,
and contain only letters, digits, underscores, dots, colons, @ or hyphens.
Retaking by the current holder preserves the original run, note and timestamp.
A queued request does not store a run: supply `--run` on the invocation that
obtains the grant, including retries. `--wait` retains the option while polling.
The global queue is a JSON array of rows with exactly `holder`, `request`,
`pool` (boolean), `note`, `since`, `seen`. Times are UTC
`YYYY-MM-DDTHH:MM:SSZ`. Requests are unique by holder, request and pool flag.
`log.tsv` has five tab-separated fields per line: UTC time, event (`add`,
`replace`, `take`, `give`), holder, nonnegative integer seconds, note.
`add` and `replace` use an empty holder and note and zero seconds; `take`
records waiting time, `give` records held time.

All metadata replacements write a private sibling temporary file then rename
over the destination. Locks keep their inode; holder removal and queue-file
migration use unlink. Updates across files are ordered, not transactional or
fsynced: a crash can leave saved custody without its event or printed grant.
An interrupted global queue replacement can leave `.waiting.json-*` siblings;
these are ignored during discovery.

## Commands and fairness

`add` renames PATH to the resting path on the same filesystem, refusing a name
that already has a login or holder. It prints `added: NAME at PATH`.
`replace` renames a private replacement over an existing resting file,
unlinking the previous file unread. It refuses held logins, missing or unsafe
resting logins, the resting file itself (including a hard-link alias), and a
login reserved by a waiter. It prints `replaced: NAME at PATH`. Replacement
refuses directories as either source or destination: a nonempty directory
cannot be overwritten with the required single atomic rename. Cross-filesystem
moves refuse with `move it on the same filesystem`; nothing is copied.

`take NAME` grants only an at-rest, unheld login with no earlier reservation,
saves custody, removes its queue row, records the event, then prints PATH.
Retaking by its holder is idempotent while the login remains at rest; the
holder's original note and timestamp remain. An absent resting login refuses
even its current holder. A refusal reports the holder and time, that the login
is not at rest and held by nobody, or which waiter goes first.

A pool is a base name without a trailing `-<digits>` plus its numbered
siblings. Nested numeric suffixes such as `chatgpt-2-3` are not members of
`chatgpt` and cannot be pool requests. Members are tried base first, then by
numeric suffix, then name. `take POOL --any` prints `NAME PATH`; each grant
requires a free login, including for a holder already holding another member.
An exhausted pool reports `POOL has no free login available; waiting`.

There is one queue for named and pooled requests, sorted by first request
time, then holder name. Each waiter reserves its first matching free, resting
login. A waiter for a stuck login reserves none; a pool waiter reserves only
one. Later requests can use other free logins. Retrying refreshes `seen`,
keeping the first time and original note. Rows older than 900 seconds since
last seen expire on mutation; a row exactly 900 seconds old retains its turn.
A named request already granted to its holder is also removed on mutation.

An ordinary take without `--wait` refuses with exit 1 while retaining its row.
`--wait SECONDS` polls until granted or its deadline; timeout removes the row
before refusing. `LOGINS_POLL_SECONDS` defaults to 5 and must be finite and
positive. `drop` removes just the holder's matching named or pool request,
printing `dropped: NAME` or `not waiting: NAME`. It does not release custody.

`--now` requires a free, unclaimed login even for a named login's current
holder. It considers itself after all live queue reservations, never joins or
refreshes the queue, and never writes, removes or migrates queue files. Stale
and already-served rows are ignored in memory. An exhausted pool's message
omits `; waiting`.

`give` checks the caller against the holder and frees custody only after the
login is back at rest. It prints `given: NAME by HOLDER after H:MM`.
A missing, empty, unsafe or linked login stays held; a failed export is for
its holder to recover. Giving a free, resting login is idempotent and prints
`already free: NAME`; a free login that is not at rest still refuses.

`list` prints each login's holder, note, timestamp, elapsed H:MM and whether
it is at rest, or `at rest`/`missing` when unheld. Matching waiters follow,
with pool requests under every member as `(any of POOL)`. It reports the last
24 hours' takes and longest waiting time, and sums held seconds on give events
in that window plus the current holding's entire elapsed time. Minutes are
truncated. It does not prune queue rows, so stale waiters remain visible.
It leaves existing metadata untouched, but can create the state directory and
missing locks; listing is not a filesystem-read-only operation.

## JSON contract

`logins list --json` writes one JSON document followed by a newline: an array
with one object per registered login, in the same lexicographic name order as
plain `list`. `list NAME --json` returns an array containing that login only;
an empty registry produces `[]`. Exit codes and state validation are the same
as plain `list`. On failure, JSON mode writes diagnostics to stderr and no
partial document to stdout. Plain output is unchanged.

| Field | Type | Meaning |
|---|---|---|
| `name` | string | Login's registered name |
| `pool` | string | Its pool name; an unpooled nested numeric name such as `chatgpt-2-3` uses its own name |
| `holder` | string or null | Current custody holder, or null when unheld |
| `since` | string or null | Current take's UTC RFC 3339 timestamp, exactly `YYYY-MM-DDTHH:MM:SSZ`; null when unheld |
| `note` | string or null | Current take's note; null when absent or empty |
| `use` | string | `walk`, `pass` or `other`, derived from the holder as below |
| `run` | string or null | Recorded codex-run, unit or session ID; null if unknown or unheld |
| `waiters` | array of objects | Matching waiters, each with string `holder`, UTC RFC 3339 string `since`, and string `use` |

`walk/...` holders have use `walk`. `pass/...`, legacy `qa-watch/...` and
`qa-watch` holders have use `pass`. All other holders, including null, have
use `other`. Custody remains held when its login is away from the resting
path; it still reports its holder, since, note and run. An unheld missing
login has null holder, since, note and run just like an unheld resting login.
This contract does not report file location or rest status.

Waiters are ordered by their first request time, then holder name, exactly
as in plain output. Named waiters appear under that login; pool waiters
appear under every member. Legacy per-login queues are merged in memory.
Stale and already-served rows remain visible, as with plain `list`; listing
does not prune or migrate queues. There are no waiters when the array is `[]`.

The contract is additive: fields are only added, never renamed or removed,
and existing field types and meanings remain stable. Consumers must ignore
unknown fields, including in waiter objects. JSON contains custody metadata
only, never login contents or paths inside a login. The offline consumer
fixture is `tools/qa/fixtures/logins-list.json`; the custody tests check its
schema and reproduce it through real commands against fake state.

## Locks, compatibility and callers

Every operation takes the global flock first, then every login's exclusive
flock in sorted name order. `list` takes a shared global lock; other commands
take it exclusively. Locks are held through validation and state changes.
A caller's explicitly inherited admission-lock descriptor remains open in the
child: callers must pass it when a take is decided under an admission cap.
Login custody does not itself implement QA's admission caps or reserve sizes.

Per-login `waiting.json` arrays with `holder`, `note`, `since`, `seen` are
merged into named global requests. A duplicate retains the earliest `since`
and latest `seen`. Mutations save the merged queue before unlinking the old
queues; listing merges only in memory, and `--now` leaves both forms intact.
The new tool reads older holder and queue state without moving any login,
changing its contents or signing in again. Older executables with strict
holder schemas cannot read holder state containing `run`; upgrade all custody
callers before using `--run`. For rollback, stop custody mutators and remove
only the optional `run` field through a private sibling metadata replacement
before restoring an older executable. No login contents need to be accessed.

Live passes and walks use the QA caller's admission controls. QA's takes use
`--any --now`, so they hold no queue reservation ahead of walks. A managed
walk take passes its current run ID with `--run` when known. Current starts
and resumes acquire logins before launching the new run, so their take-time
run is normally unknown and JSON reports null; it is not inferred from the
holder, note or an earlier attempt's run. Manual live
runs use `qa take` and `qa give`. Custody alone gives no permission to exceed
those caps. The operator checks saturation and stuck holders through `list`.
Before switching the installed tool, stop outstanding old `logins take --wait`
processes and restart their requests after the switch. Keep the state tree in
place; no `add`, `replace` or credential migration is part of installation.

Exit status is 0 for success, 1 for unavailable custody, invalid resting login
or refused replacement/move, 2 for invalid input, unknown names/pools or giving
another holder's login, and 4 for unsafe/invalid state or operational errors.
Diagnostics keep the `logins: ` prefix on stderr; grants and success messages
are on stdout. Argparse supplies usage diagnostics for malformed options.

## Port departures and tests

The executable uses `python3 -I -B` instead of `python3 -S`: isolated Python
ignores Python environment and user import paths, and disables bytecode writes.
The state-root default is always `~/src/rust`, independent of checkout location;
the checkout-relative fallback used when the old script's ancestor was named
`agents` is removed because this executable lives under `tools/qa/` and is
installed through a deployment link. `DEV_ROOT` and `DEV_TMP` still override it.
There are no other production departures; atomic metadata writes, layout,
modes, messages, status codes and lock order are preserved.

Run `python3 -I -B tools/qa/test_logins.py`. All 57 original cases are separate
unittest cases in temporary HOME/DEV_ROOT directories, using dummy files and
instrumented offline drivers. Three additional cases exercise inline compatible
state, the default HOME-based root, and an inherited admission lock. Eleven
JSON/run cases cover empty/resting/missing logins, moved holdings, legacy
holders, use classification, waiter ordering and preservation, take modes,
idempotency, invalid IDs/state, exit codes, privacy, the consumer fixture,
and QA forwarding known run IDs. The existing exact plain-output assertion
also exercises a holder with run metadata. Each case
has its own Linux subreaper process and session with signal cleanup, tracked
child reaping, a 300-second tool hang bound and a 900-second case hang bound.
The unittest wrapper runs cases sequentially; these bounds detect hangs rather
than assert individual command speed. Tests never read login contents, including
the dummy directory move test, which compares entry names, inodes and sizes.
