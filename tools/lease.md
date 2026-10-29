# Coordinator leases

`lease` enforces one coordinator writer per Cargo package or design document
for a wave. It is a standalone Python 3.13 executable using only the standard
library and local `git`; it neither runs Cargo nor accesses the network.
Owners are post names such as `s/dynamic-memory`.

```
tools/lease --fabrig ~/src/fabrig/main take s/example 'wave 2' pkg:jig-core
tools/lease want s/next 'next wave' pkg:jig-core
tools/lease lend s/example pkg:jig-core --to abc-jig/fix-x
tools/lease check s/next --repo ~/src/fabrig/main --base main --tip HEAD --branch abc-jig/fix-x
tools/lease release s/example --all
tools/lease list --json
```

`--fabrig` is a global option, before the command, defaulting to
`~/src/fabrig/main`. Mutating commands validate subjects against a single
snapshot of its HEAD. `git ls-tree` enumerates committed manifests and
`git show` supplies their TOML; uncommitted changes never affect validation.
`pkg:NAME` names a package. `doc:TREE/docs/design/NAME.md` and
`doc:TREE/docs/foundation/NAME.md` name documents in skein, smith, jig or
temper, including nested paths. The document must exist in that commit, or
have an existing Markdown sibling. Its `.status.md` companion is covered
by the same lease and cannot be leased separately.

## State and fairness

State lives in `~/src/fabrig/leases/` (0700). Each record's filename is its
subject URL-quoted with `safe=""`, with no suffix. JSON records and `.lock`
are 0600. Records contain `subject`, `owner`, `what`, UTC ISO 8601 `since`,
`lends`, and FIFO `waiters` (`owner`, `what`, `since`). Released records with
waiters retain null holder metadata; records with no holder or waiters are
removed. There are no timeouts or automatic takeovers.

Mutations hold an exclusive `flock` across reads, refusal checks, and writes.
Every file replacement uses a private sibling temporary file and `rename`.
Multi-subject operations validate and check every subject before changing any;
concurrent invocations cannot observe a partially applied operation. This is
not a journal: process or machine failure during a multi-record update may
leave a partial update. List and check use a shared lock opened read-only if
it exists; neither creates the directory, lock, or records.

`take OWNER WHAT SUBJECT...` refuses the entire request if another owner holds
any subject or a different waiter is first. Retaking one's own lease preserves
its description, timestamp and lends. The first waiter leaves the queue when
taking a free lease. `want OWNER WHAT SUBJECT...` queues each owner at most
once; a free subject without waiters is simply reported as free. A holder's
own `want` is a no-op. `unwant OWNER SUBJECT...` removes that owner's waits.

`release OWNER SUBJECT...` and `release OWNER --all` clear the holder and lends;
explicit requests containing another holder refuse as a whole. Releasing a
free subject is a no-op. After unlocking, each newly freed subject's first
waiter receives `post send --as lease OWNER@hel8 "lease free: SUBJECT"` with a
one-line body. Exit 0 or 3 is accepted; delivery failure is reported without
undoing the release. Delivery is best-effort, so always recheck state.

`lend OWNER SUBJECT... --to BRANCH` and `unlend` require the holder and change
only the named branch's permission. Git ref syntax validates branch names.
`list [--owner OWNER] [--json]` filters by holder and displays timestamps,
ages, lends, and FIFO waiter names; JSON returns the full records.

## Branch checks

`check OWNER --repo PATH --base REV --tip REV [--branch NAME]` reads the
three-dot diff, with NUL-delimited paths. It builds package mappings from the
TIP commit, choosing the longest manifest-directory prefix. Design and
foundation Markdown paths map to document subjects before package matching;
`name.status.md` maps to `name.md`. The root Cargo manifest and lockfile,
`.config/`, and `*/scripts/old-forms.txt` are exempt. Other unmapped paths print
`unowned PATH` and count as inside. Each reached subject is printed once,
as inside when held by OWNER or lent to the given branch, otherwise outside
with its holder or `unleased`. `--fabrig` does not change check's TIP catalog.

Exit status is 0 for success (including notification failure), 1 for a refusal
or any outside subject, and 2 for invalid input or operational errors.
Run the isolated tests with `python3 -I -B tools/test_lease.py`; they create a
temporary HOME, local git history, and fake post, including concurrent writers.
