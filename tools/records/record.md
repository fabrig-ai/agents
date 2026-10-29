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

Writers are post names: `s/NAME`, `lead/NAME`, `director`, or `ops`;
`collect` is permitted for `append` only.
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
seven sources, cursors, joins and snapshot/timestamp semantics.

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

## Verification

Run `python3 -I -B tools/records/test_record.py`. Tests use temporary HOME
and Git configuration, local bare origins, real concurrent processes and
pre-push barriers to exercise push retries, conflict recovery and number
allocation. They never access the real records origin. A separate acceptance
check can inspect real main or a proposed records branch in a fresh clone;
`check` never commits or pushes.
