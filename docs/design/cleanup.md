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
  task and run directories, and any script in `tmp/` but a fixture's
  marked evidence. `land` marks what it landed, and a copy must match
  `main` in content as well as in names, so that `tidy` never takes new
  work for landed work.
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
| `heavy/`, `logs/`, `gates/`, `landing-turn/`, `land-set/` | `heavy`, `land`, `land-set`, `tidy` | receipts, `heavy.tsv`, `tidy.log` and its lock, `tidy-trash/` (step 9), the gates' stamps, the landing turns, the sets' locks and state |
| `fleet/` | `fleet` | the last tend's record, and on the watch's machine its state and rounds ([fleet-watch.md](fleet-watch.md) 3.3, 4) |
| `kache/`, `lab/`, `after-landing/` | their tools | the build cache's binary, the lab's store, the runner's clones, state, logs and locks |
| `post/`, `codex-run/` | `post`, `codex-run` | the mailboxes, the runs and `runs.tsv` |
| `git-fabrig/` | the director, `issue` | the forge's tokens, which the director copies, 0600 in a 0700 directory; on hel8 the router's webhook secret ([user-issues.md](user-issues.md) 3.2, 4) |
| `qa/` | `qa` | its clones of the repositories (`repos/`), the QA passes' scratch directories, which `qa watch` deletes 7 days after their end, and the service's lock ([qa-flow.md](qa-flow.md) 4) |
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
- **A fixture marks its evidence.** A fixture that keeps its run in a
  directory its caller names (`--evidence DIR`,
  `GATE_POLICY_FIXTURE_EVIDENCE`) writes `EVIDENCE.TAG` in each
  directory it creates there, as it creates it and before anything else
  goes in: its first line `agents fixture evidence`, its second the
  fixture's name. Its fakes, payloads and copied kits are scripts, and
  stay with it until its directory goes (section 4, steps 4 and 5).
  Only a fixture writes the mark, as only Cargo writes a target's
  `CACHEDIR.TAG`: written by hand, it is a script in `tmp/` by another
  name (section 2). A mark on a directory of this table (`owners/`, a
  mission's `owners/<m>/`, `director/`, `director/tasks/`, a task's
  `tasks/<t>/`) is no fixture's, since none creates those.

## 4. tidy

`scripts/devel/tidy [--dry-run] [REPO... | --mission M | --targets [--room GB] | --checkouts]`,
Python, under a lock per machine (`tmp/logs/tidy.lock`; a second run
waits for it), safe to run at any time. `--dry-run` takes no lock,
deletes nothing and prints what it would do. With REPO, it runs steps 1
to 3 and 7 for those repositories; with `--mission M`, step 4 for M;
with `--targets`, step 9 alone, with no fetch and no pull; with
`--checkouts`, step 10 alone, likewise; with none of them, every step.

- **The repositories** are the workspace's seven (`agents`, `skein`,
  `smith`, `jig`, `hearth`, `qa`, `temper`), at their primary checkouts in
  `~/src/rust/<repo>`; `records` has no branches. `main` itself, a
  primary checkout and a locked worktree are never touched.
- **First, fresh references:** `git fetch --prune origin` in each
  repository a step reads, and `record pull` before step 4. A step
  whose fetch or pull fails is skipped, and reported.
- **Held by a process:** a path is held when a process of the user's has
  its working directory, or a file open, inside it (`/proc/*/cwd` and
  `/proc/*/fd`). Every step skips what is held, and reports it.
- **Work on no remote:** a commit on no branch of origin, a change to a
  tracked file, or an untracked file (ignored files, such as `target/`,
  are no work). What holds it is kept and reported.

**Landed.** A branch, local or on GitHub, is landed when either holds:
- **A copy:** it has commits off `origin/main`, each with a twin on
  `origin/main` (the same author, author date and subject, which a
  rebase keeps and `land`'s trailers leave alone), and it adds nothing
  to `main`: merging it into `origin/main` (`git merge-tree
  --write-tree`) leaves `origin/main`'s tree, or each commit's patch-id
  equals its twin's. Both leave out `Cargo.lock`, which a rebase takes
  from `main` and regenerates (landing-flow.md 3, 9.1): on 10-26 it alone
  made 49 of hel8's copies look different. Names alone are not enough: an
  amend keeps the author date and the subject, so a fix amended after
  its landing has a twin and differs. A branch whose commits all have twins but whose
  content differs is kept, and reported.
- **Marked:** `land` marked it landed, and its tip is on `origin/main`.

A branch with no commit off `main` and no mark stays, unreported: it is
new work. There is no keep list: a landed branch's commits are on
`main`, and a record names a commit, never a branch.

1. **GitHub's landed branches,** of REPO or of each repository:
   deleted with `git push origin :NAME`. One already gone is done.
2. **Local landed branches,** unless a worktree has one checked out.
3. **Landed worktrees:** a worktree under `tmp/`, outside section 3's
   tools' directories, whose branch is landed, or whose detached HEAD is on
   `origin/main`, with no work on no remote: removed (`git worktree
   remove`, its `target/` inside it with it), then its branch. A
   worktree elsewhere is a session's or the user's (`~/.claude/jobs/`,
   a repository's `.claude/worktrees/`), and stays, unreported.
4. **Ended missions' directories:** `owners/<m>/`, with its milestones'
   `owners/<m>-m<N>/`, whose README in the record says `ended` or
   `abandoned`, once no worktree in it holds work on no remote: its
   worktrees removed, then the directory. One that holds some stays,
   and is reported, naming each worktree. A directory in `owners/`
   with no README in the record is kept, and reported.
5. **Old directories:** the director's `tasks/<t>/` and `codex-run`'s
   run directories a week after their last change (the newest mtime
   inside), on step 4's condition. The `runs.tsv` row stays.
6. **Scripts** in `tmp/owners/` and `tmp/director/` (section 2: a
   name ending `.sh`, `.bash`, `.py`, `.pl` or `.rb`, or a file
   starting with `#!`), outside any Git working tree or repository (a
   worktree, a clone, a bare repository), a Cargo target (a directory
   holding `CACHEDIR.TAG`) and a Cargo home's `registry/` and `git/`.
   An entry outside section 3's table is step 8's, whole: on 10-26 a
   Cargo registry copy in one held 2,995 such files. A copied kit kept as
   evidence is a clone, so its scripts stay with it.
   - **A fixture's evidence,** a directory holding section 3's mark (a
     regular file whose first line is the mark's), is skipped whole, as a
     Cargo target is. A mark that is not one (another first line, a
     symlink, a directory) leaves its tree swept. A mark on a directory
     of section 3's table is ignored and reported; one tidy cannot read
     keeps its tree, and is reported.
7. **Stale worktree entries:** `git worktree prune` in each repository
   it touched.
8. **The rest** at the top of `tmp/`, outside section 3's table:
   reported, never deleted.
9. **Build targets past their use** (the user, 10-27: "finished tasks'
   build targets, each owner's two-target limit"): a `target/` holding
   `CACHEDIR.TAG` at the top of a worktree under `tmp/owners/` or
   `tmp/director/`, as step 3 finds them. Nothing else: not a primary
   checkout's, a session's or the user's worktree, after landing's
   runner (which caps its own, build-infrastructure.md 11), `qa/` or
   `land-set/`, but for a pin-only worktree a set's proof kept
   (build-infrastructure.md 10): `tidy` removes it whole, its target
   with it, once its set has landed or its proof is over 24 hours old,
   while no run of the set holds the set's file lock and it is not in
   use (section 4's sense); under that lock it checks again that the
   worktree is still on the proof's branch and commit. Before then its target counts for room
   alone: `--room` may clear it, never the worktree, as any idle
   target, so that the qa run starts warm where there is room and from
   the cache where there isn't.
   - **Its owner** is the mission whose directory holds it, with its
     milestones' `owners/<m>-m<N>/` as one, or `director`.
   - **In use** while held by a process (section 4's sense, for its
     worktree: a build, a test binary, an implementer's Codex), or while
     a build holds Cargo's lock, a `.cargo-lock` in `target/` or one of
     its profile directories (`flock`, tried without waiting): never
     touched, nor counted idle.
   - **Its last build** is the newest modification time of `target/` and of
     each profile directory's `deps/`, `.fingerprint/` and `build/` in
     it: a few `stat`s, never a walk.
   - **Cleared** when not in use and either idle, its last build 2
     hours old or more, or beyond its owner's two: an owner keeps at
     most two targets on a machine, those in use first, then the latest
     built. Age and count decide alone: no task, run or record is read,
     so a finished task's target goes once idle, whatever its task.
   - **Clearing** takes every `.cargo-lock` of the target, then checks
     again that no process holds its worktree, then renames the target
     into `tmp/logs/tidy-trash/` and lets the locks go: a build that
     started before holds a lock, and one that starts after finds no
     target and starts afresh. The rename done, it deletes the target
     there. Each run first deletes what an interrupted one left in the
     trash.
   - **Room for a landing,** with `--room GB`: after the rules above,
     while less than GB is free on the workspace's filesystem, where
     heavy reads its floor (build-infrastructure.md 2), it clears the
     least recently built target that is not in use and was last built
     15 minutes ago or more, one at a time, reading the free space
     after each, and stops when none is left. Its line's reason is
     `(room for a landing)`. A machine's tend passes it while a landing
     waits for its floor in heavy's ledger
     ([build-infrastructure.md](build-infrastructure.md) 2, "A
     landing's room").
   - **Held beyond two:** an owner with more than two targets in use
     keeps them all, each one past its two reported, without exit 1:
     nothing waits on a decision, and the fleet watch shows it.
   - On XFS a target shares its blocks with kache's store (reflinks),
     so clearing one frees what the store no longer holds; kache's own
     collection frees the rest ([build-cache.md](build-cache.md) 7).
10. **Cargo's git checkouts no lock pins** (the director, 10-27: one
    checkout per pinned revision of jig, skein and smith, never pruned;
    hetzner held 28 GB, 494 revisions of which 95 were pinned, and
    went under its floor): each `git/checkouts/<repo>-<hash>/<rev>/` in
    Cargo's home (`CARGO_HOME`, else `~/.cargo`), only on a machine
    where heavy is installed: a person's laptop keeps its own Cargo
    home (build-infrastructure.md 12).
    - **Pinned:** `<rev>` begins a commit that a `Cargo.lock` under the
      workspace names in a `source = "git+…#<commit>"` line: the
      primary checkouts', and every worktree's under `tmp/` and a
      repository's `.claude/worktrees/`, never looking inside a
      `target/`, a `.git` or a Cargo home. A `Cargo.lock` it cannot read
      fails the step (exit 3) and deletes nothing: a pin it might hold
      can't be ruled out.
    - **Kept:** a pinned checkout; one changed in the last 6 hours (a
      repin under way, before its lock names it); one held by a
      process (section 4's sense).
    - **Deleted:** the rest, each whole. Cargo checks a missing
      checkout out again from its git database (`git/db/`, never
      touched) when a build next pins it, so a deletion costs that
      build a few seconds at most.
    - **What it freed:** after the step, `tidy: checkouts: N deleted,
      M pinned, K recent, X GB freed`, X the free space it gained on
      the Cargo home's filesystem.

- **`land`'s mark.** After a landing that pushed, or landed on the
  local `main` (`--local`), `land` sets `branch.<name>.landed` to the
  commit it landed, in the repository's config, which its worktrees
  share; `--no-push` sets none. `land-set` sets it for each branch of
  its set after that branch's push; a pin-only repository has no branch
  of the set. A commit after the landing moves the tip off `main`, and
  the branch is work again. Deleting the branch drops the mark.
- **The caller's own worktree** is in use while `land` runs, its shell
  inside it, so `tidy` takes it at its next run on the machine: the
  next landing, the mission's end or the director's check. After the
  landing, `land` clears its target at once: the worktree's `target/`,
  when it is a directory inside the worktree and the worktree is not a
  primary checkout. A target elsewhere (`CARGO_TARGET_DIR`) may be
  shared, and stays. `land-set` does the same for each worktree of its
  set it landed.
- **Undoing a deletion.** Each line names the commit, and the deleting
  machine keeps the objects until Git prunes them (two weeks):
  `git branch NAME COMMIT`, and a push for a GitHub branch, restore
  it.
- **Its output:** a line for each thing deleted or kept, `tidy: deleted
  KIND WHAT COMMIT (REASON)` or `tidy: kept KIND WHAT: REASON`, and
  `tidy: would delete` under `--dry-run`. KIND is `github-branch`,
  `branch`, `worktree`, `mission`, `directory`, `script`, `entry`,
  `target` or `checkout`; WHAT is `REPO:NAME` for a branch, else the
  path. A target
  has no commit: `tidy: deleted target PATH (idle 3 h)`, or `(beyond
  two of OWNER)`. New work prints nothing.
- **Its exit:** 0 done; 1 something kept that needs a decision (step
  4's work on no remote, an `owners/` directory with no README, a
  branch landed in name only, an entry outside section 3, an evidence
  mark on a directory of section 3's table); 2 refused (usage, no
  workspace); 3 a step failed (a fetch, a push, an evidence mark it
  cannot read), the rest done.

## 5. Who runs it

- **`land` and `land-set`,** after the push, for the repositories they
  pushed: started detached (`setsid`, stdin from `/dev/null`), its
  lines appended to `tmp/logs/tidy.log`. They don't wait for it, and
  its exit changes theirs in nothing. `LAND_TIDY` names the command,
  by default the kit's `tidy`; empty, none runs, as the fixtures set it.
- **`record commit`** of a `missions/<m>/closing.md` whose README, as
  committed with it or before, says `ended` or `abandoned`. First it
  refuses (exit 2) while a worktree under `tmp/owners/<m>/` or
  `tmp/owners/<m>-m<N>/` on this machine holds work on no remote,
  naming each: push it and name it in the closing note's "what is
  left", or delete it. Then it commits, and starts `tidy --mission M`
  as `land` starts `tidy` (`RECORD_TIDY`, as `LAND_TIDY`).
- **The director's check** (director.md 7) runs `tidy` on each machine,
  for the machines with no landing, and takes a decision on each line
  of an exit 1.
- **Each machine's tend,** every 5 minutes, runs `tidy --targets`, and
  once an hour `tidy --checkouts` ([fleet-watch.md](fleet-watch.md) 4).
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
2. **`tidy` is built,** 10-26, in `scripts/devel/`, with its fixtures,
   `test-tidy`, on scratch repositories and a scratch `tmp/` (infra.md
   2), `land`'s and `land-set`'s mark, target and call, and `record`'s
   check and call (sections 4 and 5). Two tasks, side by side: `tidy`
   and `test-tidy`; the mark, the calls and `record`'s check, with
   their fixtures. Sections 4 and 5 were completed for them on 10-25:
   the copy's content check, the worktree rule without the mark, the
   output and exits; and on 10-26 after a dry run on hel8: `Cargo.lock`
   out of the content check, worktrees and scripts only where agents
   write.
3. **The roles' edits for the tools** landed with them: owners.md 4.5
   (`land` clears the target, `tidy` the rest) and 6 (`record`'s
   check), director.md 7 (`tidy` in the check), records.md 7.
4. **`tidy`'s first run** on each machine finishes section 6's sweep:
   done 10-26 on the seven machines, each kit moved to `main` first. It
   deleted 83 GitHub branches, 12 local ones, 26 worktrees, 63 ended
   missions' directories and 203 scripts. The 37 GitHub branches and 18
   local ones it kept as differing were earlier rounds that later ones
   replaced, and went on the user's word, each machine's in a bundle
   in its `~/.cache/cleanup-20261026/`. What it still reports goes to
   the director's check: `owners/` directories with no README, ended
   missions whose evidence repositories have no remote, and the
   entries outside section 3's table.
5. **The evidence mark,** 10-26 (sections 3 and 4, step 6): the
   director's `tidy` on hetzner2 took 106 files `test-heavy-recovery`
   had written into an active mission's `--evidence` directories, its
   `fixture-bin/` fakes and payloads, as scripts outside Git. A
   directory's name could not tell them from an agent's scratch, and the
   lab's layout belongs to the fixture, so the fixtures mark their
   directories, and `tidy` reads the mark. Directories made before the
   mark carry none, and their scripts go at the next run.
