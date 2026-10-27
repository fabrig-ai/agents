# The landing flow

Provisional, 2026-10-24, proposed with the user; revised 10-25 (the
user): a set proves its gates before it takes the lock, every landing
takes the set lock, and there is no keeper; and 10-26 (the user): there
is no landing queue, after landing follows each `main` (4, step 8),
and the tools settle conflicts between STATUS.md's rows and in generated
files (3); and 10-26 (the user): what each landing taught goes in the
feed (12); and 10-26 (the user): a machine without heavy lands with
plain commands (9.2); and 10-26 (the user): a tier too long for one
run splits into parts, followed apart, temper's in two (4, step 8). Built and live: `scripts/devel/land-set` and the set lock
(section 9), and since 10-26 after landing's runner (4, step 8). How
changes reach `main` across skein, smith, jig, hearth and temper:
- one set of branches per milestone;
- `land-set`, which proves a set without the lock, then lands it under
  the set lock, which orders the landings;
- a landing task, an implementer's, which runs it, and the set's owner,
  who decides when and has its failures repaired.

It has two goals. It gets the most out of the shared build cache
([build-cache.md](build-cache.md)), and it leaves owners nothing to
coordinate with each other but `main`. Today's `heavy` and `land` are
[build-infrastructure.md](build-infrastructure.md); missions
and milestones are [owners.md](../../roles/owners.md).

## 1. In one page

- **Where it stands (10-26).** `land-set` is built and live. It proves
  a set without the lock, gating every repository, then lands it under
  the lock, where an unchanged `main` makes each gate a cache hit
  (9.2). Every landing that pushes takes the same lock. Each step goes
  to a feed that `landings` shows and waits on. The owner does the rest,
  as section 9.1 lists. The landing queue and its keeper are not the
  design (the user, 10-25 and 10-26): sections 4 and 8 are retired.
- **The invariant.** Every repository's `main` pins the current `main`
  of each of its upstreams. Only a landing moves a `main`, and a landing
  keeps the invariant: it moves every repository it touches, and repins
  every repository downstream of them, all at once (section 2).
- **A set of branches per milestone.** A milestone is built on a set of
  branches, one in each repository it reaches, and the set keeps the
  same invariant inside it (section 3).
- **One landing per milestone.** At a milestone's end an implementer's
  landing task (owners.md 4) rebases the set on the current mains and
  proves it: its gates run once, without the lock. Then `land-set`
  lands it, gating again under the lock only what a moved `main`
  changed. The gates are optimistic (the user, 10-25): a failure comes
  back to the set as a repair. They run the lints and the focused and
  fuzzy suites, and nothing slower: the browser tier and the other slow
  tiers are after landing's, a runner that follows each `main` and
  sends a red back to the landing that caused it (4, step 8). Tasks
  inside a milestone merge into the set's branches, not into `main`.
- **The next milestone doesn't wait for the landing** (the user,
  10-24). It starts as soon as the landing does, on top of the set.
  - If the landing fails, the set is repaired beside the new
    milestone, as a QA pass runs today.
  - Once the earlier milestone has landed, the new one rebases on
    `main` when its owner chooses (section 3).
- **Rebases, repairs and QA fixes are implementer tasks** (the user,
  10-24). Codex (GPT Sol, high effort) does them, and escalates to the
  milestone's Claude owner or sub-owner as any implementer does. The
  owner keeps the judgement: when to rebase, which findings to fix, and
  the check of each result (section 3).
- **The set lock orders the landings** (9.1, 9.2). `land-set` holds it
  while it lands a set in skein, smith, hearth, jig and temper, and
  fails closed without it; `land` and `land --docs` take it on the machines
  the landing turn enables, and fail open (build-infrastructure.md 8).
  - If `main` moved since the set was proved, by a landing or a push
    around the tools, `land-set` rebases it again and gates from the
    most upstream repository that moved.
  - Then it lands the whole set, or stops; a stop before its pushes
    moves no `main` (9.1).
- **No queue, and no keeper** (section 5; the user, 10-25 and 10-26).
  - `land-set` does the mechanics, in the landing task the set's owner
    starts.
  - A failure goes back to the set's owner, who reads it, has its
    implementer repair the set, and escalates what it can't settle
    (owners.md 4).
  - The director takes no part in merging: it reads the feed, and
    hears of a landing only when merging goes wrong (the user, 10-24).
- **Why per milestone** (section 6):
  - **The cache:** a change is compiled once for the fleet, and two
    versions of the same crates coexist for at most a milestone.
  - **Coordination:** owners neither wait on nor relay for each other.
  - **QA:** the lab takes each milestone as soon as it lands and its
    tier is green, while the next one is being built (the user).
- **What a landing taught** goes in its commit, as `Taught:` trailers,
  which `land` and `land-set` copy into the feed and `landings taught`
  lists, so that a routine landing posts no one (section 12).
- **What goes away:**
  - repin slots, and the director's calls on repin and landing order;
  - landing hashes relayed between owners;
  - code passed from one owner to another;
  - failures routed by hand after they reach `main`.

## 2. The invariant

The repositories depend on each other in one direction: skein, then
smith, then jig, then temper; hearth depends on skein alone. Each names
its upstreams by git URL with no revision, and its `Cargo.lock` pins a
commit of each.

- **On `main`,** each lock pins every upstream's current `main` head.
  jig is then tested against the same skein that temper builds it
  with. Cargo builds one revision per git source, so temper's lock
  decides that revision.
- **A landing keeps it.** A landing that changes skein also repins
  smith, hearth, jig and temper to the new skein, and lands every one
  of them, after their gates pass. A temper-only landing touches
  temper alone.
- **It is affordable because of the patch.** Before it, every pin move
  rebuilt everything downstream with no cache hits (build-cache.md 3).
  Now a pin move compiles only what actually changed upstream and the
  crates built on it, and restores the rest.

## 3. Working in a set

Since 10-26 a milestone here is a mission's slice that lands (owners.md
4), and a sub-owner its owner.

- **The set.** A milestone's set has a branch in every repository the
  milestone edits. It also has a pin-only branch in every repository
  downstream of the most upstream one it edits.
  - A jig milestone has jig and temper.
  - A skein milestone has all five repositories.
  - Branches are named `<mission>/m<k>`, such as `accounts-move/m4`.
- **Why pin-only branches.** The invariant will make the landing repin
  them anyway, so their breakage is the milestone's to fix, and the
  sooner it shows the better.
  - Example: skein `55f46fc6` added a field to `Shutdown`, and the
    smith pinned at `d9a67aca` stopped compiling.
  - In a set, that break shows at the owner's first repin, and the
    smith fix travels in the same set as the skein change.
- **The base and the tuple.** The set records its base: the `main` of
  each repository it was cut from or last rebased on.
  - Inside the set, each branch pins the set's own branch of an upstream
    where there is one, and the base `main` otherwise.
  - One tuple of commits therefore holds across the whole set, just as
    one holds across the mains.
- **One pin mechanism.** Pins inside a set are `Cargo.lock` commits,
  like `main`'s, moved with `scripts/devel/repin`, never with `[patch]`
  overrides to local paths.
  - The kache patch normalizes Cargo's git checkouts, not arbitrary
    paths. A build from a path would key differently, and a landing's
    gates could not reuse the owner's builds. This follows from the patch's
    design; it was not measured.
- **Tasks.** Implementers branch from the set's branch in their
  repository and merge back into it, after their focused tests through
  `heavy`. An upstream task that downstream work needs merges first,
  and the owner then repins the downstream branches of its own set. No
  one outside the set is involved.
- **Rebases, repairs and QA fixes are tasks too** (the user, 10-24).
  Each goes to a Codex implementer, GPT Sol at high effort, briefed and
  launched like any other task (owners.md 3):
  - every rebase of the set, with its conflicts and the gates after it:
    during the milestone, at its end, and a stacked milestone's onto
    `main` (below);
  - the repair of a set whose proof or landing failed (9.1);
  - the fixes for the findings of the owner's QA pass that triage lets
    in (director.md 6).

  None of them needs taste once the design is settled, so they go where
  other work without taste goes (owners.md 1). The milestone's owner,
  or its sub-owner, keeps the judgement: when to rebase, which findings
  to fix, the task's brief, the check of each diff (owners.md 3) and
  the landing itself.
  - **Escalation** follows the implementers' rules (implementer.md 4,
    owners.md 5): on a doubt the implementer stops, writes the
    question as its report's first line and ends, and it never
    improvises across a boundary. A conflict that needs a call on
    whose intent wins is such a doubt.
  - Where the work gets hard, Opus advises the owner, as for any task
    (owners.md 3).
- **Rebasing during the milestone** is the owner's choice, when it needs
  something that has just landed. It follows the same steps as at the
  end.
- **At the milestone's end:**
  1. Prove the set: rebase every branch of the set on its repository's
     current `main`, which gives a new base, repin it, and run every
     gate, without the lock and pushing no `main` (9.2).
     - A `Cargo.lock` conflict is never merged by hand: take `main`'s
       lock and repin to the set's tuple.
     - **`docs/design/STATUS.md`'s rows,** which each landing changes
       (owners.md 4), are merged by the tools, `land` and `land-set`
       alike (the user, 10-26). Where `main` and the branch changed
       different rows of a table, each row, keyed by its first cell and
       unique in its table, is taken from the side that changed it, and
       a row the branch added stands after the row before it there, below
       any `main` added in the same place. The same row changed on both
       sides, a row deleted on one side and changed on the other, rows
       reordered, a malformed row, a line outside the rows, or a path no
       rule settles stops the rebase as before, for the landing task to
       resolve. A stop's paths are settled all, or none.
     - **Generated files** (the director, 10-26, decision 1201): a path
       the repository's `scripts/regenerate.sh` owns (below) takes
       `main`'s side at the stop. Once the rebase is done, and in
       `land-set` once it has repinned, since the writers read the
       upstreams, the tool runs the script on every such path through
       `heavy`, and commits what it rewrote as one commit, whose trailer, `Rebase-Resolved:
       scripts/regenerate.sh rewrote PATH, ...`, names them. When the
       script refuses or fails, or a later stop of the same rebase
       stands, the branch goes back to where it was before the rebase,
       and the landing stops as it would have at the first stop.
     - **Never silent.** Each path settled gives the replayed commit a
       trailer, `Rebase-Resolved: PATH: HOW`, and the tool's output a
       `resolved` line, where HOW names the rows each side changed, or
       `main`'s side taken for the script. The gates then run on the resolved tree as on any other. A rule that
       might drop or merge meaning is no rule: another path gets one
       only where the stops show a frequent, mechanical shape.
  2. Land it: `land-set` on the machine that proved it, under the lock
     (9.1). Where no `main` moved since the proof, its gates are the
     proof's, from the cache, so no test runs twice.
  3. Start the next milestone at once (below).

  Steps 1 and 2 are one implementer task, the landing (owners.md 4).
  The owner decides when it starts, takes step 3 meanwhile, and reads
  its outcome.
- **The gates.** A gate is its repository's `scripts/check.sh`: the
  formatting, the lints, the wasm32 ones included, and the focused and
  fuzzy suites (the user, 10-25). `land-set` runs them through `land`,
  upstream first, so a failing skein gate stops the set before four
  more run, and each downstream gate restores its upstream's builds
  from the store. With the cache, only the set's own changes and the
  crates built on them compile (section 6.1). The browser tier, with
  the bundle it serves, is `scripts/browser.sh`, and no gate runs it
  (4, step 8).
- **The generated files' writer** is each repository's own, as its gate
  is, so that agents names no product: `scripts/regenerate.sh`, where
  the repository has generated files.
  - `--owns PATH...` exits 0 when the script writes every path, and 1
    otherwise, building nothing.
  - `PATH...`, from a clean worktree, rewrites them from the tree's
    sources with their writers, and prints each path it changed. It
    owns only files that no person edits, never a declaration: exit 3,
    with the tree as it found it, when a writer would move anything it
    doesn't own, a declared limit among them (the director, 10-26).
    Exit 2 refuses before starting, and any other is a failure.
  - The tool checks it again: a path the script changed but doesn't own
    is a refusal.
- **The next milestone stacks on the set.** It doesn't wait for the
  landing, just as it doesn't wait for a QA pass.
  - **Where it starts.** Its branches start from the set's heads,
    since `main` doesn't hold the earlier milestone yet. Those heads are
    recorded as its fork point. A repository the earlier set didn't
    reach starts from `main`.
  - **Its builds start warm,** because the set's own builds published
    every unit of that tuple.
  - **Repairs.** If the set's landing fails, its owner briefs an
    implementer with the failure, and the repair loop runs beside the
    new milestone: repair, rebase, proof and landing by the
    implementer, then the owner's check of the outcome.
  - **No early landing.** The new milestone lands only after the
    earlier one, since its branches hold the earlier one's unlanded
    work.
  - **Rebasing on `main`.** Once the earlier milestone has landed, the
    new one rebases when its owner chooses. An implementer moves only
    the new milestone's commits onto `main` (`git rebase --onto main
    <fork point>` in each repository).
    - The earlier milestone may have changed on its way in, rebased by
      `land-set` or repaired. If it landed unchanged, the tuple is
      unchanged and the rebase rebuilds nothing.
    - The latest moment is the new milestone's own end, which rebases
      anyway.

## 4. The queue

Retired 2026-10-26: there is no landing queue (the user). The set lock,
which is the landing turn (build-infrastructure.md 8), orders the
landings (9.1); `land-set`, run by the set's owner, rebases, repins,
gates and pushes (9.1, 9.2); what a gate runs is section 3's. Only the
queue's last step stays, at its number, which tools and documents
cite:

8. **After landing** (the user, 10-26). The tiers too slow for a gate
   go in each repository's `scripts/after-landing.sh`: the browser tier
   (`scripts/browser.sh`), the process and QA tiers, the exhaustive
   profile. The script runs them and exits nonzero with the failed
   tests' names, and reports to no one. The rest is the runner's,
   `scripts/devel/after-landing`, live on hetzner3 since 10-26; its
   contract is build-infrastructure.md 11.
   - **It follows the mains, not the landings.** A user service polls
     each repository's `main` on origin, so it sees every writer, a
     plain `land` and a push around the tools included. When a `main`
     moves, it runs that repository's tier on it, one run per
     repository at a time; when a run ends, the next takes the newest
     `main`. Its cost is then one machine's, whatever the rate of
     landings: from 10-23 to 10-25, a run after each landing on every
     machine held the exclusive lane for 21.5 hours, with 49.2 hours of
     builds behind it (build-efficiency.md 3).
   - **Its machines, warm.** Build machines the director names, one
     by default, where `setup` installs a service per follower. A tier's
     script that lacks a tool there, Chromium or temper's pinned
     Forgejo, says so, and the runner takes it as a fault, not a red:
     agents names no product, so `setup` can't check for them. Each
     follower keeps one clone and target on its machine and nowhere
     else, the target bounded by a cap past which the follower removes
     it between runs (build-infrastructure.md 11), and runs its tier at
     `HEAVY_CLASS=background`, not `--gate`
     (build-efficiency.md 8, change 5). A tier that fails only under
     load has a test to fix, not a claim on an exclusive lane. The
     runner's machines carry little else (the user, 10-26;
     director-operations.md 8): its slow tests run one at a time at
     background weight, and a loaded machine doubles them, which
     heavy's waits don't show.
   - **Parts** (the user, 10-26). A tier too long for one run is split
     into parts, so that a verdict comes sooner and each run passes
     over fewer landings. The repository's script owns the split
     (`--part K/N`), by phase and by measured time: what a part runs
     is the script's, never the runner's. Each part is a follower of
     its own, on any of the runner's machines: it runs, reruns and
     bisects as a whole tier does, over its own runs, and a red in one
     part delays no other. Over a commit, a red from any part decides
     at once, and it clears once every part has cleared it. A split
     changes nothing else: the rerun, the bisect and their attribution,
     the posts, and the range rule below hold per part.
     - temper's tier is in two (10-26): the process tier with the
       lab's tests, and the QA and browser tiers, about 7 and 9
       minutes on a quiet machine. Whole, a run took 25 minutes at the
       median and a verdict 46, over five landings a run (hetzner3's
       feed, 10-26 16:31-22:15Z). A follower always busy gives a
       verdict in about one and a half runs: about 15 minutes, over one
       or two landings.
     - skein's, smith's, hearth's and jig's tiers stay whole: each
       takes 1 to 4 minutes.
   - **A red.** The runner reruns the failed tests alone, once, at the
     same commit.
     - If they pass, it was a flake: the verdict names it, and the
       landing's owner files it as a finding (director.md 6).
     - A starved pass, a real-loop run that waited for a CPU it wasn't
       given (skein's `testing-strategy.md` 2.8), is green; the verdict
       names it as it names a flake, so that a story starved often
       shows (the director, 10-26).
     - If not, and the run passed over landings, it bisects over their
       tips, the commits their gates passed, from the last green: only
       there does the invariant hold. The first red landing goes back
       to its owner with the log, and an implementer repairs it
       (section 3).
     - A test already red on `main` counts against the landing that
       first failed it, and against no later one. A commit's first
       landing is the landing whose pushed range holds it: the main
       rebased onto, exclusive, through the pushed tip, inclusive.
     - heavy refusing the run, a full disk, a missing tool or origin
       out of reach is a fault of the infrastructure, not a red. The
       runner retries, and posts the director if it lasts 15 minutes.
   - **It holds nothing up.** A red stops no landing: the gates are
     optimistic (section 1), and a flaky tier would stop everyone. The
     red landing's owner has it repaired first.
   - **The feed** holds each repository's tier, a part's apart: its
     last green commit, and its first red one with the landing and the
     failed tests. `landings` shows it. `landings wait --cleared`, on a
     set or a plain landing's commit, exits with its verdict: cleared,
     once a run on a `main` that holds it has no red of its own, in
     every part, or red. A landing's
     verdict is the worst over every commit in its pushed range and
     every part of its repository's tier,
     including repins and a resolver's regenerate commits: any red is
     the landing's red, even when its tip's own verdict is cleared or
     the red commit's `landing_set` is null. Every pushed commit must
     be decided before the landing clears. Older events without a
     range keep the single-commit judgement below. "Holds" is
     ancestry, not an exact match, so that every landing gets a
     verdict, and the wait says which of these gave it:
     - its own, where the runner judged the landing's commit;
     - else, in a repository with no tier script, cleared once its
       `main` holds the commit: agents, which the runner doesn't
       follow, and smith and hearth, whose runs have nothing to run;
     - else, that of the run whose range holds it. A baseline clears
       it, since its reds stand on no landing: a landing older than its
       repository's first run is judged by that run. Any other run
       gives it the verdict of the run's first landing that holds it.

     A commit that no `main` holds is no landing: the wait ends at
     once, and says so.
   - **The owner waits for the verdict** (the user, 10-26). On the
     landing task's report, it starts the wait in a user unit that
     posts it the exit. During the mission the owner is on anyway, and
     a red comes back like a failed landing. A mission closes only once
     its last landing has cleared, about one tier run after it lands. A
     new owner would read less than the landing's own, and add a session
     and a hop, as a keeper would (section 5).
     - With no verdict in 2 hours, the runner is at fault: the wait
       exits, the director hears of it, and the owner closes with the
       landing uncleared in `closing.md`.
     - A red on a landing whose owner is gone goes to the director.
   - **QA takes a cleared `main`** ([qa-flow.md](qa-flow.md) 4), so
     that no QA agent spends its tokens finding again what the tier
     showed.
   - **Since it runs** (10-26), a mission closes once its last landing
     has cleared (owners.md 4 and 5), and the director's after-landing
     inbox is gone.

## 5. Who does what

Mechanics go to the tools, and reading a set's failure to its owner. All
code goes to the owners' implementers, and decisions about the work
stay with owners and directors (the user, 10-24). No one decides
whether a set lands: the gates do.

- **The tools,** `land-set`, `land` and `landings`, are hand-rolled
  scripts in `scripts/devel/`, deterministic and tested in fixtures
  (build-infrastructure.md 8 and 10). The set lock's holder and the
  feed are on hetzner3, the landing turn's coordinator, which clients
  reach over the landing turn's ssh.
- **The runner,** `after-landing`, follows the mains on one machine, as
  a user service the director runs (4, step 8). It writes the feed, and
  pushes nothing.
- **The owner** decides when a set lands, starts the landing task that
  proves and lands it, and reads its outcome (owners.md 4, 9.1). An
  implementer repairs a set that fails, while the mission's next
  milestone goes on (section 3).
- **No queue** (the user, 10-26). Once a set proves its gates before it
  takes the lock (9.2), the gates run side by side on the owners'
  machines, and the lock is held for seconds per repository where no
  `main` moved (landing-proof.md 5). A service that ordered and gated
  the sets would add a journal and a request protocol to what the lock
  and the landing task already do.
- **No keeper** (the user, 10-25). A Codex session woken for each
  failure would read less than the set's owner, who knows the set and
  whose implementers can build and run, and would add a session and a
  hop to each failure. 10-25's stops were the tool's own faults, fixed
  in the tool, and the sets' own reds and conflicts, which their owners
  repair anyway. What the keeper would have escalated, the owner
  escalates (owners.md 4).
- **The director** reads the feed, and hears of landings only in
  owners.md 4's escalations. It doesn't order landings, and relays one
  only to an owner that can't reach the feed (director.md 5).

## 6. Why this shape

### 6.1 For the cache

- **Pin moves are cheap now.** With the patch, a repin compiles what
  changed upstream and the crates built on it, and restores the rest.
  The trial's pin move reached 5 changed units and 17 built on them out
  of about 700 (build-cache.md 6).
  - Before the patch, a pin move rebuilt everything downstream. That
    cost is what made repins something to batch and schedule.
  - The invariant, which repins on every upstream landing, is only
    affordable because of the patch.
- **Each tree is built once for the fleet.**
  - The implementers' builds publish to the shared store as they work,
    so the set's proof is mostly hits.
  - Once a set lands, every other owner's next rebase restores the
    proof's builds of the new `main` instead of compiling them.
- **A stacked milestone starts warm.** The next milestone builds on the
  set's tuple, which that set's own builds have published. If
  that set lands unchanged, the rebase onto `main` leaves the tuple as
  it was and rebuilds nothing.
- **Divergence stays short.** While a set is unlanded, every crate
  downstream of its upstream changes exists in two versions: the set's
  and `main`'s.
  - Each version is built, and rebuilt at each rebase, by its own users,
    and neither can reuse the other.
  - Landing per milestone bounds that window by a milestone, which is
    capped at 4 hours. Landing per mission would stretch it to the
    mission, about 16 hours.
- **The cost of a change follows its ripple** (build-cache.md 2). A
  change deep in skein is the most expensive kind. Landed, its ripple is
  built once by its proof and then shared; held on a set, it is built by
  that set's machines alone. No rule needs to know this; it follows
  from landing early.

### 6.2 For coordination

On 10-23 most of the director's traffic was ordering and relaying:
- about 49 log entries on repin slots and landing order since the
  sub-director pilot began;
- 156 messages from the director, and 301 from one sub-director.

Their kinds were landing hashes, code passed between owners, failures
routed after they reached `main`, and interface facts. Their causes:
- repins were done by whichever owner needed a newer upstream;
- order mattered, and only the director could decide it;
- failures surfaced after landing, on someone else's work.

In this flow:
- **An owner's only interface to other owners is `main`.**
  - It never waits on another owner's landing: it rebases on whatever
    `main` holds at its milestone's end.
  - It repins for no one.
  - It carries no one else's code: an upstream break lands with its
    downstream fix, in one set.
- **Failures are caught before `main`,** and go back to the set that
  caused them.
- **Conflicts belong to the later set,** which resolves them at its
  rebase or when it comes back.
- **The only order is the set lock's:** one landing at a time.
- **What's left for the directors:** dispatching work, policy, machines
  and escalations.

Some things stay shared, and no landing order fixes them, which is why
grouping missions by coupling still matters:
- version counters, frozen until the first release (codec.md 5);
- shared test-time budgets;
- hot files. The temper memory figures are being split into one file
  per term.

### 6.3 For QA and pipelining

Each milestone works on its own (owners.md 4), and three things now
run side by side:
- **The next milestone,** which starts when the landing does, not when
  it ends, so a landing never idles an owner.
- **The owner's QA pass, its fixes and any repair loop,** all on the
  ended milestone: implementer tasks under its sub-owner.
- **The QA lab,** which takes the milestone from `main` as soon as it
  lands and its tier is green (4, step 8).

Landing per mission would leave the lab idle for the length of a
mission, then flood it with four milestones at once.

### 6.4 Why not per task, or per mission

- **Per task**, today's roughly 400 landings a day. Under the invariant
  that came to about 38 hours a day of gate work (the 10-23 estimate,
  with warm caches), serial under the lock as it was then.
- **Per mission:**
  - conflicts between missions surface at the end;
  - a set sent back carries up to four milestones of work;
  - an upstream change stays hidden from other missions for most of a
    day;
  - QA is idle, then flooded;
  - divergence lasts longest (6.1).
- **Per milestone:** about 8 to 12 hours a day of gate work, by the
  same estimate, before the cache's savings, and since the proofs
  (9.2) no longer serial. It fits, with room to spare.

## 7. Costs and risks

- **Throughput.** Landings are serial under the lock, their gates not:
  each set proves on its owner's machine, and holds the lock for its
  pushes where no `main` moved (landing-proof.md 5). A skein set still
  runs five gates in its proof. The levers left are section 11's.
- **What no gate runs.** A break that only a slow tier shows, the
  browser tier's among them, reaches `main`, and later sets build on
  it until the runner's verdict, about one tier run later, and longer
  when the runner is behind.
- **The runner's machine.** While it is down, no `main` is checked
  after landing, and an owner at its mission's end waits out its 2
  hours.
- **Flakes are everyone's problem.** One flaky temper test stops a
  skein set. A failure the set's changes don't reach runs once alone
  (implementer.md 3): passing alone, it is a flake that the report
  names.
- **Wide sets.** A milestone that reaches all five repositories runs
  five gates. Plans should keep sets narrow; the footprint in the
  owner's notes shows when they can't.
- **Later visibility.** Other missions see a milestone's work only when
  it lands, at most a milestone later.
- **Building on a set that fails.** If the earlier milestone needs a
  large repair, the next one has built on code that is about to change,
  and its rebase absorbs the change. It is the mission's own code, so
  no one else is involved.
- **Conflicts resolved by Codex.** A rebase's resolution may keep the
  code compiling but lose one side's intent. The gates catch most of
  it; the owner's check of the diff and the implementer's escalation on
  a doubt catch the rest.
- **One point of failure.** While the set lock's holder on hetzner3 is
  out of reach no set lands: `land-set` fails closed
  (build-infrastructure.md 10), while a plain `land` goes on without its
  turn (build-infrastructure.md 8). Owners keep working on their sets.

## 8. What changes when it goes live

Retired 2026-10-26: there is no go-live. The roles of 10-26 say how a
set lands (owners.md 4), with section 9.1, and gate evidence stays in
`land`'s trailers (gate-policy.md 3).

## 9. Building it

Built and live: `land-set`, its proof and the set lock (9.1, 9.2,
build-infrastructure.md 8 and 10), the feed and `landings`, the metrics
(section 10), and since 10-26 after landing's runner (4, step 8;
build-infrastructure.md 11), on hetzner3.

What is open is section 11's.

### 9.1 Where it stands

Live as soon as possible, perfected over time (the user, 10-24). The
first sets, 10-24 from 14:00 to 21:36Z, showed what hurt (a survey of
every machine):
- four of five sets left the mains disagreeing, for 11 minutes to over
  an hour: an upstream had pushed, then a downstream stopped on a full
  disk, a conflict, or a pin-only repository that no longer built;
- the mains pinned four different skeins, so a skein set first paid for
  its pin-only repositories' drift: hearth was 734 commits behind;
- owners and directors relayed hashes, asked for go's and polled to
  learn that a set had landed;
- the set lock's waits were short, 7 minutes over 10 sets: order isn't
  what hurt.

`scripts/devel/land-set` (build-infrastructure.md 10), run from an
agents checkout like `repin`, answers the first three:
- **One set at a time.** It takes one set lock on hetzner3, through the
  landing turn's holder.
- **Every gate before any push.** In each repository of the set,
  upstream first, it rebases the branch on `main`, keeping `main`'s side
  of a `Cargo.lock` conflict and settling STATUS.md's rows (section 3),
  repins it, and gates it with `land
  --no-push`. An upstream's gated commit goes to a staging branch, so
  that its downstreams can pin it. Only once every gate has passed does
  it push the mains, upstream first, each the very commit its
  downstreams pinned. A failure before then pushes nothing.
- **The invariant, set by set.** Each repository it lands pins every
  upstream to this run's commit where the set has one, and to that
  upstream's current `main` otherwise (section 2).
  It validates every selected source, then replaces their package records
  together in `Cargo.lock` with package identities from those commits' own
  locks. Incoming lock edges to those sources are removed, so an old
  version cannot survive a pin move; retained edges are qualified before
  seed names can collide with them. One `cargo metadata` resolve reads
  their dependency edges and drops unused seed records, then the tool
  checks the whole tuple again. Candidate locks come from the supplied
  worktrees; an uncached external commit is fetched into disposable
  storage, without changing the primary's refs. Cargo accepts only one
  `--precise` value: separate updates can unlock an
  upstream and search its `main` for a crate first added in this set.
  Manifests and source identities stay as they are; absent or ambiguous
  sources, revision constraints and split revisions still refuse.
- **Pin-only repositories.** It refuses a set without them, and makes
  their branches itself when the set file says `pin-only`.
- **The feed.** Each run's steps go into a feed on hetzner3: waiting,
  started, each repository gated and landed, and how it ended.
  `landings` shows the feed and the sets in flight, the lock's holder
  among them. `landings wait <set>`, with `--cleared` too, exits 1 when
  the set's newest run, a proof or a landing, has stopped, printing a
  line with its repository, status and reason. A newer run, started by
  `proving`, `waiting` or `started`, supersedes that stop; a successful
  proof still waits for landing. Runs are ordered by their first feed
  record, so an older run's late stop cannot end the newer run's wait.
  Landing and tier-verdict outcomes keep their existing exits.

Beside the tool, the owner and its implementers do the rest:
- **The catch-up.** The first set after the release brings every
  `main` to the invariant: a set whose downstream repositories are all
  pin-only. What fails in it is drift, which implementers repair before
  the owners resume.
- **Sets and repins.** The owner keeps the set's branches. Repins inside
  the set are `cargo update --precise SHA -p <package>`, run directly
  since it builds nothing, of a commit pushed to its branch.
- **The milestone's end** follows section 3, as one implementer task,
  the landing (owners.md 4). It proves the set, `land-set --prove
  SETFILE` (9.2): it rebases, repins and gates every repository without
  the lock, and pushes no `main`. A conflict the tools don't settle
  (section 3) stops it, and the task resolves it and proves again; a red it repairs. Then
  it lands the set, `land-set --prove SETFILE && land-set SETFILE` on
  the same machine (9.2), and its report, posted to the owner when the
  run ends, says how. The owner starts the next milestone on the set's
  branches without waiting for it. A proof after a repair takes its
  unchanged repositories' gates from the cache, on the same machine.
- **Stacking.** Once the earlier set has landed, an implementer moves
  the new milestone with `git rebase --onto main <fork point>` in each
  repository, then repins.
- **A failure in the gates** pushes nothing to any `main`. The
  summary and the feed say where the run stopped and why. The owner
  reads the failure (owners.md 4), and an implementer repairs the set,
  proves it and lands it again.
- **One writer.** Every landing that pushes to skein, smith, hearth,
  jig or temper takes the set lock, plain and docs landings too (9.2),
  on the machines the landing turn enables (build-infrastructure.md 8),
  so no `main` moves under a set's run. A push around the tools still
  could: `land-set` checks every `main` again before its pushes and
  gates again what moved, so only a failure once the pushes have begun
  can leave a set half-landed: a gate run again that fails, a signal.
  Its rerun then resumes: the landings it recorded are checked against
  `origin/main`, and reused to pin downstream repositories without
  landing them again.
- **Order and escalation.** The set lock is the only order. An owner
  escalates a landing as owners.md 4 says.
- **Landing news.** Whoever waits on a set runs `landings wait`, and
  directors read `landings`: no hashes are relayed.
- **What `land` still does.** A docs change still lands with `land
  --docs`. Code that moves skein, smith or jig goes through `land-set`,
  with its pin-only repositories; a lone temper or hearth change may use
  either. Either way it takes the set lock, and `land` proves a code
  change first, without it (9.2).

### 9.2 Proving, and one writer

The user, 10-25; the design is [landing-proof.md](landing-proof.md).
On 10-25 a set held the lock through all its gates, 17.5 and 24.8
minutes for two clean skein sets, and plain landings moved `main`s
under it: the set upgrades-4-m1 gated temper five times to land it
once.

- **Prove.** `land-set --prove SETFILE` is phase 1 without the lock: in
  each repository, upstream first, it rebases, repins and runs `land
  --no-push`. Each gate's result goes to the machine's gate cache, and
  `DEV_TMP/land-set/proofs/<set>.json` records each repository's base
  and commit. It pushes no `main`, and its feed events say `mode:
  prove`.
- **Land.** `land-set SETFILE`, on the machine that proved it. Under
  the lock, where no `main` moved, each rebase is a no-op and each gate
  a cache hit, and a pin-only repository's repin is reset to the
  proof's commit when its parent and tree are the proof's, so that
  downstream pins stay the proof's. From the most upstream repository
  whose `main` moved, it gates again.
- **One writer.** A plain `land` in a set's repository proves its tree
  with `land --no-push`, then takes the set lock for its rebase, its
  cached gate and its push. If `main` moved meanwhile, it gives the lock
  back and proves again, and only its third pass gates under the lock;
  `land --docs` takes the lock with no proof (build-infrastructure.md
  8).
- **The receipt is the gate cache,** per machine, so a set proves and
  lands on one machine, in one environment: the cache's key, the gate
  policy, names the worktree's path and `PATH` (gate-policy.md). A
  stale or foreign proof costs a gate run again, never a wrong landing.
  So the landing proves again before it lands, `land-set --prove
  SETFILE && land-set SETFILE`: where the task's proof holds there, that
  prove is all cache hits; where it doesn't, it gates without the lock.
- **Check space before the prebuild.** Where heavy is installed, its
  40 GB floor (or the machine's `PLAN_MIN_DISK_GB`) applies at submission
  and again just before each payload starts, including after a queue wait.
  Below it at submission a landing's task waits for its floor, up to 20
  minutes (build-infrastructure.md 2, "A landing's room"); below it after
  that, or just before its payload, `land` exits 9 with heavy's usual
  disk diagnostic and runs no prebuild. The gate checks again because the prebuild may use the room.
  `land-set` gets the same checks through `land`; plain machines keep
  plain execution (build-infrastructure.md 2, 12).
- **Without heavy, a plain gate** (the user, 10-26). On a machine where
  heavy isn't installed, a person's laptop, `land` runs its prebuild and
  gate itself, with plain commands, and the rest of the flow, set lock,
  proof, cache and push included, is unchanged (build-infrastructure.md
  12). Its evidence says so, `Gate-Runner: plain`, and serves only that
  machine's plain gates (gate-policy.md 3.2). Where heavy is installed,
  `land` never falls back to plain: a refusal is exit 9.

## 10. Metrics

The user, 2026-10-25: collect what the landing flow costs, so that
reports can be written on top of it. Each fact is written once, by the
tool that sees it; the reports only read.

- **The gate's steps.** Each project's `scripts/check.sh` wraps its
  main commands in a `step NAME command...` helper, which prints one
  line to stderr:
  ```
  gate-step NAME SECONDS EXIT
  ```
  `SECONDS` has three decimals. The names are the same in every
  repository: `fmt`, `clippy`, `wasm` (lints and checks on the browser
  target), `build` (the test binaries, `cargo nextest run --workspace
  --no-run`), `focused`, `fuzzy`; and, in results from before the
  browser tier left the gates, `bundle` (what that tier serves) and
  `browser`. A name may come twice, and its times add. What
  no step covers is `other`: the gate's time less its steps'. agents'
  own gate is the exception: its steps are its suites (`test-land-set`,
  `shellcheck` and the rest), they run side by side, and their times
  add up to more than the gate's, so its `other` means nothing.
  agents alone adds a fifth field, `gate-step NAME SECONDS EXIT CPU`:
  `CPU` is the suite's user plus system CPU seconds, including its
  children, with three decimals. Other repositories keep four fields;
  readers accept both. At the end agents prints `gate-share NAME CPU
  PERCENT%` for every suite, largest CPU share first. The total is the
  sum of the suites' CPU seconds, rather than the gate's elapsed time.
  An unadmitted share above 10% and at most 12.5% passes with one line:
  `check.sh: NAME CPU share N%: past 10%, add a line to scripts/gate-shares before it passes 12.5%`.
  Above 12.5% it fails unless `scripts/gate-shares` admits it with
  `NAME MAX_PERCENT REASON`, one suite per line and the reason in words.
  An admitted share above that line's maximum fails, with no headroom added.
  The failure names the suite, its share and the file, so a budget increase carries its reason
  at landing. Initial admissions use three runs of main through
  `heavy --gate`: each suite's median CPU seconds divided by their sum,
  and for each share above 10%, its share times 1.25 rounded up to a
  whole percent. Blank lines and comments beginning with `#` are allowed;
  duplicate names, invalid percentages and missing reasons fail the gate.
- **Starved passes** (the director, 10-26; skein's
  `testing-strategy.md` 2.8). A repository whose tests may pass starved
  keeps passing tests' output in its gate's nextest JUnit, and its
  `scripts/check.sh` prints one line per test that passed starved:
  ```
  gate-starved NAME
  ```
  NAME is `PROFILE BINARY_ID TEST_NAME`, as after landing's
  (build-infrastructure.md 11). The repository finds them; the tools
  only read the lines.
- **`land`'s result.** Once `land` has rebased, it ends by printing one
  line, `land: result JSON`, and writes the same object to the file
  `LAND_RESULT` names, when it is set:
  ```
  {"schema": "land-result-v1", "repo": "skein", "machine": "debian-16gb-hel1-1",
   "runner": "heavy", "base": SHA, "commit": SHA, "tree": SHA, "tries": 1,
   "prebuild": {"wait_s": 3, "run_s": 61, "exit": 0},
   "gate": {"kind": "ran", "receipt": TOKEN, "wait_s": 5, "run_s": 164,
            "exit": 0, "steps": {"fmt": 4.213, "clippy": 25.3}, "cpu": {}, "failed_step": null},
   "pushed": true, "exit": 0}
  ```
  - `repo` is the primary checkout's directory name (the parent of
    `git rev-parse --git-common-dir`), or a bare clone's name less
    `.git`; `machine` is the host name, `commit` the tip `land` gated
    or took from the cache.
  - `runner` is `heavy` or `plain` (9.2), `null` for `--docs`.
  - `prebuild` and `gate` are `null` when `land` didn't reach them.
    Their times are `heavy`'s `waited` and `ran`; a plain gate's are 0
    and `land`'s own measure, and its `receipt` is `null`.
  - `gate.kind` is `ran`, `cached` (the gate cache's result: no
    receipt, zero times, no steps) or `none` (`--docs`).
  - `steps` sums the gate log's `gate-step` lines by name, in their
    order, accepting both four and five fields. `gate.cpu` sums the fifth
    field by name and is `{}` when no line has it, also for cached and
    skipped gates. `failed_step` is the first step that exited nonzero, else
    `other` when the gate failed, else `null`.
  - `starved` lists the gate log's `gate-starved` names, at most 50,
    `starved_more` counting the rest; `[]` for a gate that printed none,
    was cached or didn't run.
  - `exit` is `land`'s own status.
- **The feed.** `land-set` runs each `land` with `LAND_RESULT` set, and
  adds the object it wrote as `result` to the event it then writes:
  `gated`, `landed`, or the `stopped` of a failed `land`. A prove's
  events carry `mode: prove`, from `proving` to `proved`; a landing
  started from a proof carries its token as `proof` in `started`.
- **The report.** `landings report [--since DATE] [--repo NAME]
  [--tsv]` reads the feed:
  - per repository: gates run, cached and failed; the gate's median
    and 90th percentile; the median queue wait and prebuild; the median
    of each step, and of `other`; failures by step;
  - per set: how many ended `done` and `stopped`, and how many started
    from a proof; the wait for the lock (`waiting` to `started`) and the
    run (`started` to its end), median and longest;
  - per set's proves: how many ended `proved` and `stopped`, and their
    run, median and longest;
  - `--tsv`: one row per result, with raw seconds, for other scripts.
  - **Starved passes,** per repository and per test, most first: from
    the gates' results (a set's events, and a plain `land`'s record,
    which carries `starved` beside `taught`, section 12) and the
    runner's runs, each counted once per gate or run.
  - **After landing's verdicts** (10-26), per repository with a tier,
    and per part: the time to a landing's verdict, median and 90th
    percentile, from its record in the feed (a set's `landed`, a plain
    `land`'s, section 12) to the runner's record that decided it (the
    first red, else the last part's clearing); the landings per run,
    median; the runs' `ran_s`, median and 90th percentile. A landing
    with no record of its own, a push around the tools, counts in the
    runs but not in the times.

Not collected yet: the results of plain `land`s outside a set (their
record in the feed, section 12, carries none; the result line is in their
output only), and each test's time (nextest's JUnit output).

## 11. Open

- **The gates' levers,** each measured before it is added (section 10):
  tests selected by the crates a set changed (nextest's `rdeps()`), and
  test results reused for byte-identical test binaries.
- **A docs landing upstream of a set** changes the commit that every
  downstream's lock pins, and the downstreams then gate again for
  Markdown alone (landing-proof.md 7).
- **Proving on one machine and landing on another** needs a receipt
  that the lander can read and check (landing-proof.md 7).
- **A part past its run's share** (4, step 8): when one profile alone
  outgrows a part, the script may split that profile's tests by
  nextest's `--partition`, at the cost of building its binaries in each
  part. temper's process and QA tiers run one test at a time; tests
  that could run side by side would shorten a part more than another
  part would.
- **The runner's machine and class.** On a machine of the runner's
  own, its `background` weight yields to nothing; beside CPU-heavy
  work it yields to all of it. Which of the two, and whether the class
  stays `background` there, is the director's to bring to the user,
  from the verdicts' report (section 10).

## 12. What a landing taught

The user, 10-26: "re landing notices: can't we include in the feed the
'what each landing post says the code taught' bit of info?". Owners
posted their parent at every landing (owners.md 4): of the 127 posts to
the director from 01:40Z to 10:50Z that day, about half were landing
notices, each a wake (decision 1252). What a landing taught now goes in
its commit, the tools copy it into the feed, and `landings` shows it, so
that a routine landing needs no post. Built 10-26 (o/landing-taught).

- **The trailer.** What the code taught that the design doesn't say (a
  boundary that moved, a behaviour settled) is a trailer in the landing's
  commit message, `Taught: <one line>`, of at most 200 characters; a
  landing that taught several things carries a few, one each. It stands
  in the message's last paragraph with the others: `QA:`
  ([qa-flow.md](qa-flow.md) 2), `Co-Authored-By:`, the gate's. The
  landing task writes it from its owner's words, as it writes `QA:`. A
  landing with nothing to teach carries none.
- **Written once, in git, and copied.** The feed holds a copy, at the
  landing's time, so that a reader catching up needs neither a checkout
  nor a commit's date: a set proved at 10:00 and landed at 10:30 keeps its
  10:00 commits.
- **Whose lines.** A landing's lines are the `Taught:` values of every
  commit it brings to that repository's `main`, oldest first, unfolded and
  stripped, an empty one dropped.
  - `land`: from the `main` its last pass rebased on to the commit it
    pushed.
  - `land-set`: in each repository, the set's own commits, from the base
    its candidate was gated on to that candidate, read before its push.
    A repin's commit carries none. Where `main` moved under the lock and
    `land` rebased again (9.2), the lines stay the candidate's: a commit
    that rebase dropped as already upstream keeps its line.
- **Bounded, never refused.** The tools keep a landing's first 10 lines in
  each repository, each cut to 200 characters (`…` marks a cut), and count
  the rest as `taught_more`. A trailer never stops a landing: a read of
  the trailers that fails, or takes over 2 seconds, teaches nothing, since
  `land-set` makes it between its lock's pulses. A feed that can't be
  written warns, as `land-set`'s does (build-infrastructure.md 10).
- **A set's landing record.** Each `landed` event of `land-set`
  (build-infrastructure.md 10) carries `taught`, the list of lines, and
  `taught_more` when it left some out; neither when that repository's
  commits taught nothing. A set teaches per repository. It also carries
  `base`, the main the successful push rebased onto, and `commit`, its
  actual pushed tip: its range is (base, commit], per repository. This
  is the push's range even if main moved after the candidate was gated.
  The same pair in a matching pushed `result` also supplies a range.
  If publication is recovered without that result, `base` is null:
  the new range is unknown and stays pending, never judged by its tip
  alone as an old record without a range would be.
- **`land`'s own record.** Before this, a plain `land` reached the feed
  only inside a set. Now a `land` that pushes, `--docs` included, appends
  one line once its push has succeeded, whether or not its local `main`
  follows:
  ```
  {"time": ISO, "kind": "land", "event": "landed", "host": NAME,
   "token": HEX32, "repo": "agents", "branch": "landing-taught/m1",
   "base": SHA, "commit": SHA, "taught": ["..."]}
  ```
  - `repo` is `land`'s own (section 10); `taught` and
    `taught_more` are as above, absent when there is nothing to show;
    `starved` and `starved_more` as in `land`'s result (section 10),
    absent when it has none.
  - **No `set`,** so every reader of a set's runs passes over it:
    `landings`' set views, `wait` and `report`, the status page, and after
    landing's `landing_set`.
  - **Inside a set, none:** `land-set` sets `LAND_FEED` empty for the
    `land`s it runs, as it sets `LAND_TIDY`, and records each landing
    itself. `--local` and `--no-push` push nothing, and write none.
  - **Fixtures.** `LAND_FEED`, a local path, replaces hetzner3's feed, and
    set empty writes none. Without it, only a push to a remote with a host
    (`git@host:path`, `ssh://`, `https://`) reaches hetzner3's feed, over
    `land-set`'s ssh: never a path or `file://` origin, and never a fixture
    run's (`HEAVY_RECOVERY_FIXTURE=1`). A remote helper's address decides
    (`https::https://host/...` has a host), and `ext::` never has one.
  - Its result stays out of it: plain `land`s' costs are still not
    collected (section 10).
- **Verdicts cover the push.** For a set or a plain landing, the
  landing's verdict is the worst over every commit in (base, commit],
  whoever made it: its own commits, repins and the resolver's
  regenerate commits. A red charged to any one is this landing's red;
  a cleared tip cannot override it. All must clear before the landing
  clears. The first landing of a failing commit is the one whose range
  holds it; later landings inherit no blame for an existing failure.
  `landings` shows this judgement and `wait --cleared` uses it, on a
  set or its tip. No past feed record is rewritten; an older record
  without a range keeps its former single-commit judgement.
- **`landings` shows it.**
  - Its event list holds `land`'s records beside the sets' events, a
    record's branch where a set's name stands, and prints a landing's
    lines under it, indented, then `(N more)` for `taught_more`. A control
    character in a line, or in a `land` record's branch or repository,
    prints as `?`, so that no record splits a line or reaches the terminal
    as an escape.
  - `landings taught [--since TIME]`, TIME a date or an ISO time, UTC by
    default, as `report`'s: every landing in the feed since then, oldest
    first, both kinds. One line for each, its date and time, set or branch,
    repository, commit and machine, then its lines indented under it; a
    landing that taught nothing is its line alone.
- **Who reads it.**
  - **The director,** at its check, `landings taught --since` its last
    one (director.md 7): an owner under the director posts nothing at a
    landing, and its trailer is the notice (owners.md 4).
  - **A designer** still hears from its owners at each landing, since it
    adjusts the design from them (designer.md 4); their landings may carry
    the trailer too.
  - Questions, escalations, a red verdict's repair and a mission's closing
    still post (owners.md 4, 5).
- **Not public.** The status page shows no taught text (status-page.md
  1): it renders no `taught` field of a set's events, and counts
  `land`'s records, which have no `set`, without showing them
  (status-page.md 3).
- **The tests.** On scratch feeds, with no ssh:
  - `test-land-set`: a set whose commits carry trailers in two
    repositories, each `landed` event with its own lines, none on the
    pin-only one, and the `land`s it runs given `LAND_FEED` empty;
  - `test-landings`: a set's `landed` and a `land` record shown with their
    lines and `taught_more`, a landing without them shown alone,
    `taught --since`, and records with a malformed `taught` shown without
    it;
  - `test-land-resolve`, whose lab runs the real `land`: a push to a
    `file://` origin with `LAND_FEED`, its record with its lines, one
    without trailers with none, and one without `LAND_FEED`, which writes
    nothing.
