# The records writer

`record` is a Python 3.13, standard-library command. It owns a dedicated clone
at `~/src/fabrig/records`; `RECORDS_REPO` and `RECORDS_ORIGIN` override that path
and `git@github.com:fabrig-ai/records.git`. Missing clones are created atomically.
Each operation holds `.git/record.lock` with `flock`. A sibling initialization
lock also serializes clone creation. Dirty clones (including ignored files),
symlink paths, linked worktrees, foreign fetch or push origins, unfinished Git
operations and unpublished commits refuse. Nothing imports the frozen `old/` kit.

```
record pull
record write --as s/multi drafts/example/draft.toml --from /tmp/draft.toml
record write --as director director/decisions/next.md < /tmp/decision.md
record append --as ops queue hel8 < /tmp/events.jsonl
record check [PATH ...]
record show director/priorities.toml
```

Writers are post names: `s/NAME`, `lead/[HANDLE/]NAME`, `director`, or `ops`;
`collect` and `watch` are permitted for `append` only.
`write` accepts one judgement file and `append` accepts JSON objects, one per
line. Both read stdin unless `--from FILE` is supplied. `--message TEXT` sets
the complete commit message; otherwise subjects name the writer and operation.
All commands fetch and fast-forward before acting. `show` validates its file
before printing it. Exit codes are 0 for success, 1 for refusal (validation,
clone safety or conflict), and 2 for usage or operational errors.

## Data and validation

The allowlist covers event JSONL; draft metadata; part briefs and closings;
draft and director decisions; director priorities and questions; session
handover/state/common snapshots; README files and root AGENTS.md. Unknown paths,
traversal, symlinks, invalid UTF-8, CR characters, credentials and private keys
refuse. Formats, required fields, UTC times, enum values and the specified byte
caps are checked before writing. Priorities must reference existing draft
directories. Decision Markdown requires a title and Context, Options, Decision
and Why sections. TOML dates can be quoted UTC strings or native UTC datetimes.

`check` validates the whole tracked tree or explicit file paths and prints a
count of files and refusals. Whole-tree checks omit the frozen `old/` archive:
it contains historical formats and is outside the new schema. Explicit paths
under `old/` always refuse, including `old/README.md`. The clone safety checks
still reject symlinks anywhere in the tracked tree. No generated state is stored.
`RECORDS_BRANCH` selects a branch for `check` only; every other command uses main.

Events are grouped by source, hostname and each event's UTC date. Existing ids
in that file, including duplicates within one input, are skipped. Every new line
and resulting file is validated; existing bytes remain intact. All changed files
are written to a temporary sibling, flushed and renamed over their destinations,
then committed together and pushed once. An idempotent call creates no commit.

Every event has string `id`, UTC `time`, `source`, `host`, and `kind` fields.
Optional string joins are `coordinator`, `draft`, `area`, `part`, `task`,
`branch`, `run`, `session`; other fields hold each producer's facts.
Leads and coordinators should begin task files with this TOML join header:

```toml
+++
task = "example"
branch = "mc/example"
coordinator = "s/example"
draft = "wave"
area = "tools"
part = "collect"
+++
```

`record-collect runs sessions claims post --dry-run --since 2026-10-29T11:00Z`
previews local facts. See [collector usage and limits](record-collect.md) for all
eight sources, cursors, joins and snapshot/timestamp semantics.

## Races and recovery

Every publish starts from origin/main. A rejected push triggers a fetch; only
an advanced remote branch warrants a retry. The unpublished commit is rebased,
the resulting files are validated again, and push is attempted at most five
times, with exponential jittered backoff. A conflict aborts the rebase, resets
the clone to the fetched origin, reports the original input on stderr, and exits
1. Other publication failures also undo the local write and report its input;
operational failures exit 2. Inputs rejected during validation are not echoed.

`next.md` in decision directories and `next.toml` in director questions allocate
the first free number from 0001 to 9999 while locked. If another clone claims
that number during a push race, the losing writer resets to the new origin and
allocates again using its original input. Distinct judgements never merge into
one numbered file. Ordinary concurrent writes use Git's rebase conflict rules.

## Director commands

Every command below requires `--as NAME`, including reads, using the post names
above. Writes build the files, validate them, and commit and push through the
same locked writer as `write`. Reads pull first and never commit generated data.
Text is quoted by the tool; no hand-written TOML is needed.

```
record draft dynamic-memory --as director --coordinator dm \
  --mailbox s/dynamic-memory --source skein/docs/design/draft/dynamic-memory.md \
  --state active --priority 1
record priority set dynamic-memory upgrades --as director --reason "Green first"
record priority show --as director
record ask --as director --question "Which scope?" --option small --option full \
  --recommendation small --deadline +24
record answer 0001 --as director --answer small
record answer 0001 --as director --applied commit:abc123
record questions --as director --open
record decide --director --as director --title "Resume QA" --context @context.txt \
  --options "QA or upgrades" --decision QA --why "Restore the checks first"
record decide --draft dynamic-memory --as s/dynamic-memory --title "Scope" \
  --context "First release" --options "small or full" --decision small --why "Time"
record status --as director
record status --as director --json
```

- `draft NAME --coordinator H --mailbox s/NAME --source PATH [--state S]
  [--priority N]` creates or updates `drafts/NAME/draft.toml` and sets `updated`
  to now in UTC. Coordinator, mailbox and source are required on updates too.
  New drafts default to `queued` and priority 1; an omitted state or priority
  on an existing draft preserves its value. Creation accepts any schema state.
  Changes allow `queued → active`, `active → paused`, `paused → active`, and
  `active → done`; the same state is allowed, and `done` is terminal.
- `priority set NAME... --reason TEXT` replaces `director/priorities.toml` with
  the supplied order. Names must be unique existing drafts with valid metadata.
  Each entry receives the reason. Its `since` stays the same at the same
  position; new or moved entries receive now in UTC. `priority show` prints the
  validated TOML, or reports that no priorities exist yet.
- `ask --question TEXT --option TEXT... --recommendation TEXT --deadline ISO|+HOURS`
  creates the next `director/questions/NNNN.toml`. Repeat `--option` for each
  option. The writer becomes `by`, and `asked` is now in UTC. Deadlines take an
  ISO UTC time (`Z` or `+00:00`) or positive hours from now, including fractions
  such as `+0.5`. The final output line is the allocated four-digit number,
  including after a concurrent numbering retry.
- `answer NNNN --answer TEXT [--applied TEXT]` records `answer` and `answered`.
  `answer NNNN --applied TEXT` requires an already answered question and preserves
  its answer and timestamp. A new `--answer` replaces the answer and timestamp.
  Question numbers may omit leading zeroes. `applied` can name a commit, event,
  or explain what was done.
- `questions [--open]` prints number, age since asking, UTC deadline, asking post,
  and the first 80 characters of the question on one line. Unanswered questions
  past their deadline are marked `OVERDUE`. `--open` hides answered questions.
- `decide (--draft NAME | --director) --title T --context T --options T
  --decision T --why T` writes the next decision in that draft or the director's
  decisions directory. A draft must already exist. Each text argument accepts
  `@FILE` for UTF-8 input. The title must be one line. The Markdown contains
  `# title`, writer and UTC date, then Context, Options, Decision and Why sections.
  The entire generated file, including headings and attribution, is capped at
  4096 UTF-8 bytes.
- `status [--json]` computes drafts in priority-list order (unlisted drafts follow
  by metadata priority, then name), with state, coordinator and age of `updated`;
  open questions ordered overdue first, then by deadline; the last five director
  and draft decisions in Git history order; and event counts by source in the
  last hour. Future events are excluded. The text view omits event counts when
  there are none. JSON always includes `drafts`, `questions`, `decisions`, and
  `events_last_hour` (empty arrays/object when absent). Drafts and questions
  retain their metadata, with `name`/`number` and numeric `age_seconds`; questions
  also have `overdue`. Decisions have `path`, `title` and Unix commit `timestamp`.
  UTC datetimes are JSON strings. No status file is written.

## Verification

Run `python3 -I -B tools/records/test_record.py`. Tests use temporary HOME
and Git configuration, local bare origins, real concurrent processes and
pre-push barriers to exercise push retries, conflict recovery and number
allocation. They never access the real records origin. A separate acceptance
check can inspect real main or a proposed records branch in a fresh clone;
`check` never commits or pushes.
