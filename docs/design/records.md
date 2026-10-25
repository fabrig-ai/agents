# Records

Provisional, 2026-10-24, proposed with the user. Where the work's
record lives: `records`, a private repository of small files, one
directory per mission and per roadmap, beside one status of everything
in progress. Each fact is written once, by whoever has it, and the
metadata by the tools. The surveys behind it are
`~/src/rust/tmp/records-survey/<machine>.md` on each of seven machines
(10-24; carbon-forge was unreachable).

## 1. In one page

- **Why.** The surveys found:
  - **The record is scattered and small.** About 230 directories in
    seven machines' `tmp/owners/` hold it, beside 500 GB of worktrees,
    build trees and logs. What a reader wants is little: a closing note
    is 3 KB at the median, a plan 7 KB, a whole mission's notes 17 to
    25 KB.
  - **Each fact is written five or six times.** A milestone's end is in
    its owner's ledger and closing note, its parent's inbox file (up to
    192 KB), the product owner's log and decisions, and the director's
    log, decisions and `owners.md`.
  - **Current state goes stale beside history.** Notes, handovers and
    ledgers still say paused, pending or in flight under a closing note
    that ended the mission, on every machine.
  - **Typed metadata is wrong or missing,** while the tools already
    hold it. A ledger said high where the run was medium, durations
    disagree, ids are cut short, and no mission has a token total; but
    `heavy.tsv`, the gates, the landing turns and the Claude and Codex
    session files record it all, joined to no mission.
  - **Nothing says what is in progress,** and names don't identify
    missions: a directory reused for a second mission, two missions
    behind one inbox, an owner that names itself after its predecessor.
- **The repository,** `fabrig-ai/records`, private, checked out on
  every machine. `record` commits a role's files straight to `main` and
  pushes: no branch, gate or `land` (section 2).
- **A flat tree:** `STATUS.md`, `director/`, `roadmaps/<name>/`,
  `missions/<name>/`, each file with its writers (section 3).
- **Written once** (section 4): the brief is the mission's README; a
  report is a file its parent is pointed to, never a copy; a decision is
  written where it is taken; git's history is the timeline, so there is
  no ledger and no log.
- **The tools write the metadata** (section 5): at a milestone's end,
  `record runs` adds a table of its sessions, tokens, builds, tests and
  landings, and checks each implementer's builds and tests against
  [implementer.md](../../roles/implementer.md).
- **Caps** keep every file small (section 6), and `tmp/` keeps the
  scratch (section 7).

## 2. The repository

- **One checkout per machine,** `~/src/rust/records`, on `main`, cloned
  by `setup`. Nobody works in it on a branch.
- **`record commit [-m MESSAGE] PATH...`** is the only writer:
  - under a lock on the checkout, so the sessions of one machine take
    turns;
  - it checks each path: its place in the tree (section 3), its front
    matter, its cap (section 6), and that it holds no secret (a private
    key block or a token's known prefixes: `ghp_`, `gho_`, `ghu_`,
    `ghs_`, `ghr_`, `github_pat_`, `sk-`, `xox[abpr]-`, or `AKIA`
    plus 16 characters). `sk-` and GitHub prefixes start a token, not
    after a letter, digit,
    underscore or hyphen, and need at least 20 token characters;
  - it commits those paths only, the message starting with the
    writer's name (`POST_NAME`, [post.md](post.md) 2), or `USER`;
  - with a temporary index and plumbing it replays commits on
    `origin/main` and pushes, retrying when `main` moved, five times
    at most. Unrelated staged and unstaged edits stay in place; a
    conflict refuses without changing HEAD, index or files.
  - Exit 0: pushed. 2: refused, with the reason. 3: committed but not
    pushed; the next `record commit` pushes it. Nothing to commit is
    exit 0 with a message.
- **A file's writers** (section 3) take turns or share one machine's
  checkout, so a rebase never conflicts. A record is never moved or
  renamed once committed.
- **Reading another machine's record:** `record pull`, then the file.

## 3. The tree

| Path | Writer | Written | Holds |
|---|---|---|---|
| `STATUS.md` | the director | rewritten as missions start, change and end | one line per mission in progress, and what waits on the user |
| `director/direction.md` | the director | rewritten | the vision, the priorities, the standing rules, the drafts and what waits |
| `director/decisions/NNNN.md` | the director | appended | its numbered calls, 100 to a file (`0001.md` holds 1 to 100) |
| `director/backlog.md` | the director | entries added and removed | findings owned by no roadmap |
| `roadmaps/<r>/README.md` | its product owner | rewritten | the goal, the product owner, each feature with its draft, its missions and their state, and each feature's closing note |
| `roadmaps/<r>/decisions/NNNN.md` | its product owner | appended | its numbered calls, `R<n>-` |
| `roadmaps/<r>/backlog.md` | its product owner | entries added and removed | the findings triage keeps waiting (owners.md 4.6) |
| `missions/<m>/README.md` | its parent, then its owner | at the start; the owner keeps the front matter | the brief (section 4) |
| `missions/<m>/plan.md` | its owner | rewritten when the plan changes | the milestones (owners.md 3.1) |
| `missions/<m>/decisions.md` | its owner and sub-owners | appended | their calls, numbered, each with its reason |
| `missions/<m>/m<N>.md` | its owner (the head), then the milestone's driver | at its start, its design and its end | its goal, its design report, its end report, and the table of section 5 |
| `missions/<m>/qa.md` | its QA agents and its owner | at each pass | the passes, their findings and each one's disposition |
| `missions/<m>/closing.md` | its owner | once | the closing note (owners.md 6) |

- **Names.** A mission's name is its own for good: `record` refuses a
  new README in a directory that has one, including a lost push race
  ("name taken"). A second mission on the same work is `<name>-2`. A
  milestone has no directory of its own: its sub-owner writes `m<N>.md`
  in the mission's. A roadmap is named by its goal (`real-backends`,
  `first-release`), and its decisions keep their prefix (`R2-17`). Names
  are lowercase slugs of letters, digits, hyphens and underscores;
  numbered files use the tree's spelling. A decision is a level-2
  heading starting with its number (`1067`, `R3-12`, `12.`).
- **Front matter,** `key: value` lines between `---` lines, which
  `record` checks:
  - a mission's README: `roadmap`, `feature` (the draft's repository
    and path), `department`, `parent` and `owner` (addresses),
    `machine`, `model`, `effort`, `started`, `ended`, `state` (`active`,
    `paused`, `ended`, `abandoned`) and `end` (one line: why it ended);
  - `m<N>.md`: `driver`, `model`, `effort`, `started`, `cap`, `ended`.
  - Times are UTC, `2026-10-24T21:54Z`; what the writer doesn't know is
    `unknown`, never a guess.

## 4. Written once

- **The brief is the README.** The parent writes it before starting the
  owner: the front matter, a required first paragraph of at most 60
  words (skipping headings), then what is particular to the mission: its
  input, its end, its budgets, what the parent knows that bears on it.
  The reading order, security rules and channels are the roles', and no
  brief repeats them. The owner is started with "Read
  `~/src/rust/records/missions/<m>/README.md` and do what it says.", a
  sub-owner with its `m<N>.md`, whose head says what to read.
- **A report is a file.** The plan report is `plan.md`; a milestone's
  design report (at most 15 lines, owners.md 3.3) and end report (at
  most 10, owners.md 3.1) are sections of `m<N>.md`; the closing note
  is `closing.md`. The writer commits it with `record`, then tells its
  parent in one line, by post or today's channel, naming the file and
  the commit. The parent reads the file and copies nothing into its
  own notes; its answer, if it decides something, is a decision.
- **A decision is written where it is taken:** an owner's in its
  mission's `decisions.md`, a product owner's in its roadmap's, the
  director's in `director/`. A call that answers a report cites the
  report's path. The message that carries the answer is transport, not
  record.
- **QA:** the QA agent writes its pass in `qa.md`: what it tested,
  against which commits, and each finding with its reproduction (qa.md
  3). The owner adds each finding's disposition: fixed in a commit, sent
  to the backlog, or not a defect. A finding sent to the backlog goes to
  the roadmap's `backlog.md`, by its product owner.
- **`STATUS.md`** is the director's: one line per mission in progress,
  with its owner's address, its milestone, its state or blocker and its
  next step; then what waits on the user. A mission leaves it when its
  closing note is committed. Product owners keep their roadmap's
  README instead of a copy of the same lines.
- **No ledger and no log.** Who wrote what, and when, is git's history:
  `git log -- missions/<m>` is a mission's timeline, `git log --
  roadmaps/<r>` a roadmap's. What a ledger recorded besides is section
  5's.
- **What this removes,** per milestone: the ledger's entries, the
  reports' copies in inbox files, the product owner's and the
  director's log lines, the closing notes folded into parents' notes,
  and the director's `owners.md` rows. What an agent still writes is
  what it wrote before: its reports and its decisions.

## 5. The metadata

- **The paths name the work.** A mission's scratch is
  `tmp/owners/<m>/`, a milestone's tasks and worktrees
  `tmp/owners/<m>/m<N>/`. A session belongs to the record its first
  prompt names. No tool needs a tag. Old `owners/<m>-m<N>/` joins
  milestone N; an unsplit owner without milestone directories joins
  milestone 1. Modern mission sessions stay outside milestone paths.
- **`record runs <m> <N>`,** which the driver runs before its end
  report, rewrites the table under `m<N>.md`'s `## Runs` heading (and
  `record runs <m>` the mission's own, in its README). From what each
  tool already keeps on the machine:
  - **sessions:** each Claude and Codex session of the milestone, its
    role, the model and effort it actually ran with, its wall time and
    its tokens (input, cached, output), from the Claude transcripts, the
    Codex rollouts (whose working directory is the worktree) and
    `codex-run`'s `runs.tsv` ([post.md](post.md) 5). Codex uses its last
    cumulative token snapshot (output includes reasoning); Claude
    deduplicates message ids and takes each usage field's maximum.
    Claude inputs include cache reads and creation. Only its first
    user prompt is read for ownership. `codex-run` joins by TASK,
    deduplicates by thread; unlabelled tokens are
    `unknown`;
  - **each implementer run's builds and tests,** from `heavy.tsv`
    (whose working directory is the worktree) and `heavy`'s receipts,
    as section 5.1 counts them;
  - **landings:** worktree, gate time and result, queue wait, joined
    by heavy's working directory. Gate-cache keys and landing-turn
    events lack a worktree/token link, so cached stamps and turn wait
    are omitted.
  A source that lacks a field gives `unknown`. The table is at most 4
  KB; the long form stays where the tools keep it.
- **`record runs --all [--since DATE]`** prints implementer rows across
  missions as TSV with raw seconds, for the director and Infra.

- **Bounded tables:** always start with implementer totals: runs,
  commands, time running and waiting, kinds, repeats and counted flags.
  Implementers join Codex and heavy by worktree; absent heavy telemetry
  leaves counts unknown. Session-only directories stay in Sessions.
  Omit zero kinds and flags; show only established flags. Sessions
  group by kind, model and effort: count, wall (h:mm), input (M),
  cached (%), output (k). Implementers have one row per worktree,
  relative to the mission directory, largest running plus waiting
  first: commands, minutes running and waiting, focused, package,
  workspace, clippy, check.sh, other, repeats and flags. Kind cells are
  count or count / minutes; zero is empty. Other includes check, fmt
  and doc. Landings use m:ss. Within 4 KiB, keep totals, the largest
  rows, and one count of rows left out.

### 5.1 Builds and tests

The question is whether implementers build and test as
[implementer.md](../../roles/implementer.md) says. For each run:
- **its commands by kind:** workspace, package, focused (`nextest`
  with `--test` or `--lib`), check.sh, clippy, check, doc, fmt, other,
  in heaviest-first order. A bundle counts once under its heaviest
  kind, with all its time running and waiting;
- **repeats:** the same command on the same receipt `inputs` tree,
  including dirty tracked and untracked files, excluding ignored files.
  Heavy computes it at command start with a temporary index seeded
  from the real one, `git add -A` and `git write-tree`, without changing
  the real index or refs. Receipts also name `head`, the commit at
  command start. Both fields are optional in receipt v1: outside Git
  or on failure, omit the unavailable field and still run the command.
  Legacy receipts establish repeats only for clean gates; otherwise
  repeats remain `unknown`;
- **flags:** count commands with a filter without `--test` or `--lib`,
  no test selected (nextest exit 4), overlap with an earlier command
  from the same worktree, fmt or check.sh through heavy, or clippy
  after another clippy with the same `head`. Omit unestablished flags.

`implementer.md`'s baseline is 741 runs from 10-22 to 10-24, whose
commands ran 43 hours and waited 104. `record runs --all --since
2026-10-25` shows whether it moved.

## 6. Caps

`record` refuses a file over its cap. The writer shortens it, and
names by path what it cut, in `tmp/`. The caps sit above the surveys'
largest useful files and far below their journals.

| File | Cap |
|---|---|
| a mission's README | 8 KiB, its summary 60 words |
| `plan.md`, a mission's `decisions.md`, `qa.md` | 16 KiB each |
| `m<N>.md` | 8 KiB, and 4 KiB of table |
| `closing.md` | 8 KiB |
| a mission's files together | 128 KiB |
| `STATUS.md`, a roadmap's README | 16 KiB each |
| `director/direction.md`, a backlog | 32 KiB each |
| a decisions file | 100 decisions, 128 KiB |

## 7. What stays in tmp

- **An owner's `tmp/owners/<m>/`:** `notes.md` (its state, its open
  questions and its footprint: no decisions, no plan), `handover.md`,
  its implementers' tasks and reports, `codex/`, the worktrees and the
  evidence. None of it is record: the directory may go once
  `closing.md` is committed and its branches have landed or been
  pushed.
- **The director's and product owners' `tmp/director/`:** their
  scripts, messages, handovers and helper tasks. `direction.md`,
  `owners.md` (now `STATUS.md`), `decisions.md` and `findings.md` move
  to the record; `log.md` ends; `decisions-live.md` stays the
  director's digest, in its notes.

## 8. Going live

1. **Infra builds `record`** in `scripts/devel/` (`commit`, `pull`,
   `runs`), with fixtures on a scratch repository and fake `heavy.tsv`
   and session files, under [infra.md](../../roles/infra.md)'s rules.
   `setup` clones the checkout and links the tool. It lands unused.
2. **The backfill** (section 9) fills the repository.
3. **The roles' edits land:** owners.md 2 (the notes), 3.1 (the plan and
   the end report), 3.3 (the design report), 4.6 (QA) and 6 (the
   closing note); product.md 2 (its notes), 4 (the backlog) and 6 (a
   feature's end); director.md 3 (its notes), 4 (the brief) and 7
   (`STATUS.md` at each check); qa.md 3, qa-milestone.md and qa-lab.md
   where they name the report's file. New missions follow them; a
   running mission ends in `tmp/`, and is backfilled once it has.

Live 10-25.

## 9. The backfill and the cleanup

The user, 10-24: the small backfill, and the 500 GB freed.
- **The backfill.** For each ended mission, its README (the front
  matter, `unknown` where the notes don't say, and the summary) and its
  `closing.md` within the cap, from its brief, `milestones.md` and
  closing notes. The closing note wins over notes and ledgers. Each
  file's last line names its sources. The director's decisions 1 to
  1067, and the roadmaps' R2 and R3, split by script into section 3's
  files. One Codex run per machine writes to a staging directory; the
  stagings are merged and committed once. Nothing is read from the
  paths the surveys list as holding secrets. Done 10-24, records
  9fde4b3: 81 missions from seven machines (carbon-forge was
  unreachable), the director's decisions to 1070, R2-175 and R3-112;
  the files of decisions 401 to 500 and 601 to 700 are over the cap,
  kept whole.
- **The runs, later.** Once `record runs` works, it runs over every
  backfilled mission. Until then `tmp/logs/heavy.tsv`,
  `tmp/heavy/receipts/` and `tmp/gates/` stay on every machine.
- **The cleanup** frees what ended missions leave in `tmp/`: worktrees,
  targets, build trees, copied evidence and big logs, and the scratch
  entries the surveys list. Never a running mission's, and of a paused
  one's only its targets (the user, 10-24); never a tool's state (`heavy`, the gates, the landing turns, `kache`, the
  lab, `after-landing`'s locks), and never `~/.claude` or `~/.codex`.
  A list comes first, per machine, checked against `STATUS.md` (or the
  director's `owners.md` until it exists) and the processes running.
  What is on no remote is saved first in `tmp/cleanup-saved/`: a
  clone's commits as a bundle, a tree's changes as a diff; a worktree's
  branch stays in its repository. The missions' Markdown stays. Done
  10-24: about 555 GB freed on seven machines; six ended missions'
  directories stay, a process still in them.

## 10. Left out, on purpose

- **The implementers' tasks and reports** in the record: section 5's
  table says how each run built and tested, which is what the record
  asks of them.
- **Money:** tokens only. A price is the reader's.
- **A gate or a review of the record:** `record`'s checks are the
  whole of it.
- **Features as files:** a feature is a section of its roadmap's
  README.
