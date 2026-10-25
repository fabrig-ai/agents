# Cleanup

Provisional, 2026-10-25, with the user. What `~/src/rust/tmp/` may
hold, and how what work leaves behind (worktrees, branches here and on
GitHub, scratch) goes once the work is done: by the tools, with no step
of the agent's. The facts behind it are 10-25's audit of hetzner3 and
GitHub, and the sweep of the six machines' `tmp/` (section 6).

## 1. In one page

- **Why.**
  - **Nothing removed what landed.** `land` pushes `main` and leaves
    the branch, its worktree and any copy on GitHub, and a rebased
    branch is pushed under a new name, so a landing leaves one to six
    copies behind. On 10-25 GitHub held 288 branches beside the mains,
    113 of them landed, temper's 237 all from 10-22 to 10-24; hetzner3
    held 360 local branches, 293 of them landed, and 24 worktrees.
    owners.md asked only for a landed worktree's target, and
    records.md 7 said a mission's directory "may go".
  - **Cleanup grew on the side.** The director's `branch-sweep`,
    untracked in `tmp/director/`, deleted 1,040 landed branches until
    the pause of 10-24, and 10-24's cleanup freed 555 GB by hand.
  - **So did tooling.** The six machines' `tmp/` held 10,759 scripts on
    10-25: agents' watchers, launchers and probes, copied kits, a Python
    source tree, and before them the director's watcher, check and
    session scripts, all outside this repository's review and fixtures.
    "Why would agents write scripts? It sounds like extending
    agents/scripts behind the scenes" (the user, 10-25).
- **No scripts in `tmp/`** (section 2). Throwaway code lives in its
  author's worktree and goes before the branch lands. A tool the kit
  lacks is asked for, up to the director, and built here by Infra.
- **`tmp/` holds the tools' state and live work** (section 3). The rest
  is deleted.
- **`tidy` deletes what is done** (section 4): landed branches on
  GitHub and here, landed worktrees, ended missions' directories, old
  task and run directories, and any script in `tmp/`. `land` marks what
  it landed, so that `tidy` never takes new work for landed work.
- **Nobody runs it by hand** (section 5): `land` and `land-set` after
  each push, `record` after a closing note, and the director's check on
  each machine.

## 2. No scripts in tmp

- **A script** is a file run as a program: shell, Python, Perl, Ruby,
  or any file starting with `#!`. Outside a worktree, `tmp/` holds
  none but the tools' own (section 3).
- **Throwaway code** (a probe, a driver for one measurement, a parser
  of one log) lives in its author's worktree, untracked. `land` refuses
  a worktree with an untracked file, so it is deleted before the branch
  lands, and goes with the worktree if it never does. Code worth keeping
  is a change like any other: in the repository it serves, through
  `land`.
- **A tool the kit lacks** is a question, never a workaround: an
  implementer's report starts `Question:` (implementer.md 4), an owner
  escalates (owners.md 5), and the director gives it to Infra as a
  mission or declines it. A watcher, a launcher, a sweep, a pause: each
  is a tool of `scripts/`, or nothing.
- **The director's tools** are no exception: its watcher, probe, check
  report and session scripts were gone by 10-25's sweep, and each it
  still needs comes back as a tool here (director.md 12).

## 3. What tmp holds

| Path | Whose | What |
|---|---|---|
| `heavy/`, `logs/`, `gates/`, `landing-turn/`, `land-set/` | `heavy`, `land`, `land-set` | receipts, `heavy.tsv`, the gates' stamps, the landing turns, the sets' locks and state |
| `kache/`, `lab/`, `after-landing/` | their tools | the build cache's binary, the lab's store, after-landing's worktrees and locks |
| `post/`, `codex-run/` | `post`, `codex-run` | the mailboxes, the runs and `runs.tsv` |
| `machine.env` | `setup` | the machine's floor and limits |
| `owners/<m>/` | a mission's owner | its notes, handover, tasks and reports, its worktrees (`m<N>/`) and evidence, until the mission ends |
| `director/` | the director and the product owners | their notes, handovers and messages, and helper tasks (`tasks/<t>/`) |

- **Nothing else.** An entry at the top of `tmp/` outside the table is
  reported by `tidy`, and the director deletes it or gives it a place
  here.
- **No record points into `tmp/`.** A design states the surveys it
  rests on, a decision the report it answers: the files go. The survey
  paths in records.md and post.md are history.
- **A copy is evidence while its work runs:** a copied kit, a toolchain
  built for one test, a fixture's tree. It goes with its directory.

## 4. tidy

`scripts/devel/tidy [--dry-run] [REPO | --mission M]`, under a lock per
machine, safe to run at any time; `--dry-run` prints what it would do.
Every step skips what a process holds (its working directory, or a file
it has open, is inside), and keeps, and reports, anything with work on
no remote.

1. **GitHub's landed branches,** of REPO or of each repository. A
   branch goes when:
   - it has commits off `main`, each with a twin on `main` (the same
     author, author date and subject, which a rebase keeps and `land`'s
     trailers leave alone): a copy of landed work; or
   - `land` marked its name landed, and its tip is on `main`.
   A branch with no commit off `main` and no mark stays: it is new work.
2. **Local landed branches,** by the same rules, unless a worktree has
   one checked out.
3. **Landed worktrees:** a worktree whose branch carries `land`'s mark
   at its HEAD, with no change and nothing untracked, goes with its
   target and its branch.
4. **Ended missions' directories:** `owners/<m>/`, with its milestones'
   `owners/<m>-m<N>/`, whose README in the record says `ended` or
   `abandoned`, once no worktree in it holds a commit on no GitHub
   branch or an uncommitted change. One that does stays, and is
   reported.
5. **Old directories:** the director's `tasks/<t>/` and `codex-run`'s
   run directories a week after their last change, on step 4's
   condition. The `runs.tsv` row stays.
6. **Scripts** in `tmp/` outside worktrees and section 3's tools
   (section 2).
7. **Stale references:** `git fetch --prune` in each repository it
   touched.
8. **The rest** at the top of `tmp/`, outside section 3's table:
   reported, never deleted.

- **`land`'s mark.** After its push, `land` sets `branch.<name>.landed`
  to the commit it landed, in the repository's config; `land-set` does
  so for each branch of its set. A commit after the landing moves the
  tip off the mark, and the branch is work again. Deleting the branch
  drops the mark.
- **The caller's own worktree** is in use while `land` runs, its shell
  inside it, so `tidy` takes it at its next run on the machine: the
  next landing, the mission's end or the director's check. `land`
  clears its target at once.
- **Its output:** a line for each thing deleted or kept, and its exit:
  0 done, 1 something kept that needs a decision (step 4's), 2 refused.

## 5. Who runs it

- **`land` and `land-set`,** in the background after a push, for the
  repositories they pushed. As with `after-landing`, they don't wait
  for it; its lines go to `tmp/logs/tidy.log`.
- **`record commit`** of a `closing.md` whose README says `ended`.
  First it refuses (exit 2) while a worktree in the mission's directory
  on this machine holds work on no GitHub branch, naming each: push it
  and name it in the closing note's "what is left", or delete it. Then
  it commits, and runs `tidy --mission M`.
- **The director's check** (director.md 7) runs `tidy` on each machine,
  for the machines with no landing, and takes a decision on each line
  of an exit 1.
- No agent runs it, and no role holds a step of cleanup.

## 6. The sweep of 10-25

- **The scripts:** 10,759 deleted from the six machines' `tmp/` on the
  user's word, outside worktrees, section 3's tools and the files a
  process held: hel8 863, hetzner 2,941, hetzner2 1,019, hetzner3
  4,391, hetzner4 389, hetzner5 1,156. Each machine keeps them in
  `~/.cache/tmp-scripts-20261025.tar.gz`, with their list, to delete
  once nothing turns out to be missing.
- **The ended missions' directories:** 124 deleted, about 3 GB, on the
  user's word: hel8 7, hetzner 25, hetzner2 54, hetzner3 21, hetzner4
  8, hetzner5 9. A dirty worktree's diff and untracked files, and a
  commit no branch held, are in each machine's
  `~/.cache/cleanup-20261025/`.
- **The landed branches:** 112 on GitHub (agents 2, skein 4, jig 6,
  temper 100) and 2,084 on the six machines (hel8 233, hetzner 928,
  hetzner2 412, hetzner3 268, hetzner4 153, hetzner5 90), with the
  stale remote-tracking refs. A branch checked out, named in records'
  `STATUS.md`, direction, backlog or roadmaps, or on the director's
  keep list stayed. `~/.cache/cleanup-20261025/` holds each one's name
  and commit, and a bundle of the commits main lacks.
- **What stays is `tidy`'s first run:** the paused missions'
  directories, and the entries at the top of `tmp/` outside section
  3's table, which it reports.

## 7. Going live

1. **The rules of section 2** land with this design, 10-25: the
   workspace's `AGENTS.md`, implementer.md 3 and 4, owners.md 2 and 5,
   qa.md 1, director.md 6 and 12, infra.md 1, README.md 4, records.md 6
   and 7.
2. **Infra builds `tidy`** in `scripts/devel/`, with fixtures on
   scratch repositories and a scratch `tmp/` (infra.md 2), `land`'s and
   `land-set`'s mark and call, and `record`'s check and call (sections
   4 and 5).
3. **The roles' edits for the tools** land with them: owners.md 4.5
   (`land` clears the target, `tidy` the rest) and 6 (`record`'s
   check), director.md 7 (`tidy` in the check), records.md 7.
4. **`tidy`'s first run** on each machine finishes section 6's sweep.
