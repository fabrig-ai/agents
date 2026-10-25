# The landing flow

Provisional, 2026-10-24, proposed with the user; revised 10-25 (the
user): a set proves its gates before it takes the lock, every landing
takes the set lock, and there is no keeper. Live in part since 10-24:
`scripts/devel/land-set` is its starting primitive, and agents do the
rest by hand until it is built (section 9.1). How changes reach `main`
across skein, smith, jig, hearth and temper:
- one set of branches per milestone;
- a landing queue that is the only writer to `main`;
- a tool that runs the queue, and the set's owner for its failures.

It has two goals. It gets the most out of the shared build cache
([build-cache.md](build-cache.md)), and it leaves owners nothing to
coordinate with each other but `main`. Today's `heavy` and `land` are
[build-infrastructure.md](build-infrastructure.md); missions
and milestones are [owners.md](../../roles/owners.md).

## 1. In one page

- **Where it stands (10-25).** Only `land-set` is built. It proves a
  set without the lock, gating every repository, then lands it under
  the lock, where an unchanged `main` makes each gate a cache hit
  (9.2). Every landing that pushes takes the same lock. Each step goes
  to a feed that `landings` shows and waits on. Agents do by hand what
  the rest of this flow will do, as section 9.1 lists, and the tools
  come over time.
- **The invariant.** Every repository's `main` pins the current `main`
  of each of its upstreams. Only a landing moves a `main`, and a landing
  keeps the invariant: it moves every repository it touches, and repins
  every repository downstream of them, all at once (section 2).
- **A set of branches per milestone.** A milestone is built on a set of
  branches, one in each repository it reaches, and the set keeps the
  same invariant inside it (section 3).
- **One landing per milestone.** At a milestone's end the set is
  rebased on the current mains and proved: its gates run once, without
  the lock. The owner then asks the queue to land it, which gates again
  only what a moved `main` changed. The gates are optimistic (the user,
  10-25): a failure comes back to the set as a repair. They run
  the lints and the focused and fuzzy suites, and nothing slower: the
  browser tier and the other slow tiers are after landing's, which
  nothing runs until the user designs how (section 4). Tasks inside a
  milestone merge into the set's branches, not into `main`.
- **The next milestone doesn't wait for the landing** (the user,
  10-24). It starts as soon as the set is in the queue, on top of it.
  - If the landing fails, the set is repaired beside the new
    milestone, as a QA pass runs today.
  - Once the earlier milestone has landed, the new one rebases on
    `main` when its owner chooses (section 3).
- **Rebases, repairs and QA fixes are implementer tasks** (the user,
  10-24). Codex (GPT Sol, high effort) does them, and escalates to the
  milestone's Claude owner or sub-owner as any implementer does. The
  owner keeps the judgement: when to rebase, which findings to fix, and
  the check of each result (section 3).
- **The queue is `main`'s only writer** (section 4).
  - If `main` moved since the set was rebased, the queue rebases it
    again and runs the gate of every repository the set reaches.
  - Then it lands the whole set, or sends it back to its owner.
  - Sets that need no gate go first, then returned sets, then the rest
    as they came.
- **A tool runs the queue, and no keeper watches it** (section 5; the
  user, 10-25).
  - The tool does the mechanics, the order's fixed rules included.
  - A failure goes back to the set's owner, who reads it, has its
    implementer repair the set, and escalates what it can't settle
    (owners.md 4.4).
  - Directors and product owners take no part in merging: they get news
    of what landed, and escalations when merging goes wrong (the user,
    10-24).
- **Why per milestone** (section 6):
  - **The cache:** a change is compiled once for the fleet, and two
    versions of the same crates coexist for at most a milestone.
  - **Coordination:** owners neither wait on nor relay for each other.
  - **QA:** the lab takes each milestone as soon as it lands, while the
    next one is being built (the user).
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
    paths. A build from a path would key differently, and the queue
    could not reuse the owner's builds. This follows from the patch's
    design; it was not measured.
- **Tasks.** Implementers branch from the set's branch in their
  repository and merge back into it, after their focused tests through
  `heavy`. An upstream task that downstream work needs merges first,
  and the owner then repins the downstream branches of its own set. No
  one outside the set is involved.
- **Rebases, repairs and QA fixes are tasks too** (the user, 10-24).
  Each goes to a Codex implementer, GPT Sol at high effort, briefed and
  launched like any other task (owners.md 4.2, 4.3):
  - every rebase of the set, with its conflicts and the gates after it:
    during the milestone, at its end, and a stacked milestone's onto
    `main` (below);
  - the repair of a set the queue sent back (section 4);
  - the fixes for the findings of the owner's QA pass that triage lets
    in (owners.md 4.6).

  None of them needs taste once the design is settled, so they go where
  other work without taste goes (owners.md 1). The milestone's owner,
  or its sub-owner, keeps the judgement: when to rebase, which findings
  to fix, the task's brief, the check of each diff (owners.md 4.4) and
  the request to the queue.
  - **Escalation** follows the implementers' rules (implementer.md 4,
    owners.md 5): on a doubt the implementer stops, writes the
    question as its report's first line and ends, and it never
    improvises across a boundary. A conflict that needs a call on
    whose intent wins is such a doubt.
  - Where the work gets hard, Opus advises the owner, as for any task
    (owners.md 4.2).
- **Rebasing during the milestone** is the owner's choice, when it needs
  something that has just landed. It follows the same steps as at the
  end.
- **At the milestone's end:**
  1. Prove the set: rebase every branch of the set on its repository's
     current `main`, which gives a new base, repin it, and run every
     gate, without the lock and pushing no `main` (9.2).
     - A `Cargo.lock` conflict is never merged by hand: take `main`'s
       lock and repin to the set's tuple.
  2. Push the set's branches and ask the queue to land it. Where no
     `main` moved since the proof, the queue's gates are the proof's,
     from the cache, so no test runs twice.
  3. Start the next milestone at once (below).

  Step 1 is one implementer task (above). The owner checks its result,
  then takes steps 2 and 3.
- **The next milestone stacks on the queued set.** It doesn't wait for
  the landing, just as it doesn't wait for a QA pass (owners.md 3.1).
  - **Where it starts.** Its branches start from the queued set's heads,
    since `main` doesn't hold the earlier milestone yet. Those heads are
    recorded as its fork point. A repository the earlier set didn't
    reach starts from `main`.
  - **Its builds start warm,** because the queued set's gates published
    every unit of that tuple.
  - **Repairs.** The ended milestone's sub-owner stays on for its
    landing, as it stays on for QA. If the queue sends the set back, the
    sub-owner briefs an implementer with the failure, and the repair
    loop runs beside the new milestone: repair, rebase and gates by the
    implementer, then the sub-owner's check and a new request. A
    returned set goes first (section 4).
  - **No early queueing.** The new milestone can't enter the queue
    before the earlier one has landed, since its base would hold
    unlanded work.
  - **Rebasing on `main`.** Once the earlier milestone has landed, the
    new one rebases when its owner chooses. An implementer moves only
    the new milestone's commits onto `main` (`git rebase --onto main
    <fork point>` in each repository).
    - The earlier milestone may have changed on its way in, rebased by
      the queue or repaired. If it landed as queued, the tuple is
      unchanged and the rebase rebuilds nothing.
    - The latest moment is the new milestone's own end, which rebases
      anyway.

## 4. The queue

The queue is the only writer to every repository's `main`. Its tool,
`queue`, runs on hetzner3 (section 5) and takes one set at a time.

1. **The request.** The owner pushes the set's branches and runs `queue
   request` with a set file: the set's name, each repository's branch,
   head and base, and its gate receipts. The tool refuses at once, with
   the reason, a request with any of these:
   - a head that isn't pushed;
   - a base that isn't on its repository's `main`, which also refuses a
     stacked milestone queued before the earlier one has landed;
   - a missing pin-only branch, or a lock that doesn't pin the set's
     tuple;
   - a receipt that doesn't check out (step 3).
2. **The order.** It follows fixed rules:
   1. sets that need no gate: docs sets, and sets whose base is still
      current and whose receipts check out. Each takes seconds, and
      landing them early saves their gates;
   2. returned sets;
   3. the rest, first come, first served.
3. **Unchanged base.** If each repository's `main` is still the set's
   base, and each candidate tree has a receipt that checks out, the set
   lands without a new gate.
   - Today the receipt is the gate cache of the machine that proved the
     set, and the set lands from that machine (9.2).
   - A queue that lands for everyone will read heavy's receipt on the
     machine that ran the gate. It checks it as `land` does
     (gate-policy.md 3.1): the tree, the policy, the outcome and the
     log's digest.
   - The tree includes the lock, and with it the tuple.
   - Receipts are checked, never taken on an owner's word.
4. **Moved base.** Otherwise the tool rebases each branch on its
   current `main`, repins the set and runs every gate.
   - It pushes the rebased branches under new names, and never forces a
     push.
   - It resolves only mechanical conflicts: a `Cargo.lock` conflict
     (take `main`'s lock, repin to the tuple), or a generated file that
     has a generator. Any other conflict sends the set back, for the
     owner's implementer to resolve (section 3).
   - A gate is its repository's `scripts/check.sh`: the formatting, the
     lints, the wasm32 ones included, and the focused and fuzzy suites
     (the user, 10-25). The browser tier, with the bundle it serves, is
     `scripts/browser.sh`, and no gate runs it (step 8).
   - Gates run through `heavy --land` on a free build machine, upstream
     first. A failing skein gate stops the set before four more run, and
     each downstream gate restores its upstream's builds from the store.
   - With the cache, only the set's own changes and the crates built on
     them compile here (section 6.1).
5. **Green.** The tool pushes the mains upstream first: skein, then
   smith and hearth, then jig, then temper.
   - Each push is a fast-forward and is journaled, so a crash between
     pushes resumes where it stopped.
   - No push can be refused, because nothing else writes to `main`.
   - The gate evidence goes in a git note on each landed commit, not in
     a trailer. Amending skein's head after temper's lock pinned it
     would leave temper pinning a commit that `main` never holds.
   - The landing goes into the landings feed.
6. **Red.** The tool reruns the tests that failed, alone, once.
   - If they pass, it was a flake. The set lands, and its owner files
     the flake as a finding (owners.md 4.4).
   - If not, the set goes back to its owner, with the failure's log, and
     the next set starts. The owner reads the failure (owners.md 4.4),
     and its implementer repairs the set.
   - A fault of the infrastructure is not a red: heavy refusing the
     run, or a machine or GitHub out of reach. The tool retries it, and
     tells the set's owner if it lasts.
7. **Docs sets.** Markdown-only changes go through the queue too, with
   no gate, so the queue stays `main`'s only writer.
8. **After landing.** The tiers too slow for a gate go in each
   repository's `scripts/after-landing.sh`: the browser tier
   (`scripts/browser.sh`), the process and QA tiers, the exhaustive
   profile. Nothing runs it, on the user's word, while they design how
   it should (owners.md 4.5): `land` and `land-set` start no tier after
   landing. Once something does, a failure goes to the owner of the
   first landing it fails on.

The set lock is already the advisory landing turn
(build-infrastructure.md 8). Speculative runs come later, when the
queue backs up: testing set B on top of set A while A's gates run, and
batching several sets.

## 5. Who does what

Mechanics go to the tool, and reading a set's failure to its owner. All
code goes to the owners' implementers, and decisions about the work
stay with owners and directors (the user, 10-24). No one decides
whether a set lands: the gates do.

- **The tool,** `queue`, is a hand-rolled script like `land` and
  `repin`. It is deterministic and journaled, and runs as a user
  systemd service on hetzner3.
  - hetzner3 is already the landing turn's coordinator and hosts the
    store. Clients reach it over the landing turn's ssh
    (build-infrastructure.md 8).
  - It does section 4's mechanics: checking requests and receipts, the
    order, rebases, repins, mechanical conflicts, gates, the rerun,
    pushes, the journal and the feed.
  - It is tested in fixtures, like `heavy` and `land`.
- **No keeper** (the user, 10-25). A Codex session woken for each
  failure would read less than the set's owner, who knows the set and
  whose implementers can build and run, and would add a session and a
  hop to each failure. 10-25's stops were the tool's own faults, fixed
  in the tool, and the sets' own reds and conflicts, which their owners
  repair anyway. What the keeper would have escalated, the owner
  escalates (owners.md 4.4).
- **Owners** reach the queue through two commands, and need no
  messages:
  - `queue request <set file>` (section 4);
  - `queue wait <id>`, in a user unit (9.1). It exits when the
    set lands or comes back with its failure, and its exit wakes the
    owner, on any machine. A sub-owner that stays on for the landing
    then runs `queue wait --after <id>` for the after-landing tiers.

  A returned set goes to the sub-owner of the milestone that made it,
  who has an implementer repair it (section 3) while the mission's next
  milestone goes on.
- **`land` stays, as a front end.** A one-repository landing becomes a
  one-branch request, and the tool adds the downstream pin-only branches
  the invariant needs. `land --docs` becomes a docs request. Habits and
  scripts keep working.
- **Directors and product owners** read the landings feed, and hear
  of landings only in owners.md 4.4's escalations. They don't order
  landings, and they don't relay them.
- **Building and running it.** The build-infra mission, with a Codex
  owner, builds the tool. The director runs the service.

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
    so the queue's gate of the set is mostly hits.
  - Once a set lands, every other owner's next rebase restores the
    queue's builds of the new `main` instead of compiling them.
- **A stacked milestone starts warm.** The next milestone builds on the
  queued set's tuple, which that set's own builds have published. If
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
  built once by the queue and then shared; held on a set, it is built by
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
- **The only order is the queue's,** set by fixed rules.
- **What's left for the directors:** dispatching work, policy, machines
  and escalations.

Some things stay shared, and the queue can't fix them, which is why
grouping missions by coupling still matters:
- version counters, frozen until the first release (codec.md 5);
- shared test-time budgets;
- hot files. The temper memory figures are being split into one file
  per term.

### 6.3 For QA and pipelining

Each milestone works on its own (owners.md 3.1), and three things now
run side by side:
- **The next milestone,** which starts when the set is queued, not when
  it lands, so time in the queue never idles an owner.
- **The owner's QA pass, its fixes and any repair loop,** all on the
  ended milestone: implementer tasks under its sub-owner.
- **The QA lab,** which takes the milestone from `main` as soon as it
  lands.

Landing per mission would leave the lab idle for the length of a
mission, then flood it with four milestones at once.

### 6.4 Why not per task, or per mission

- **Per task**, today's roughly 400 landings a day. Under the invariant
  that came to about 38 hours a day of serial queue work (the 10-23
  estimate, with warm caches): more than one queue can do.
- **Per mission:**
  - conflicts between missions surface at the end;
  - a set sent back carries up to four milestones of work;
  - an upstream change stays hidden from other missions for most of a
    day;
  - QA is idle, then flooded;
  - divergence lasts longest (6.1).
- **Per milestone:** about 8 to 12 hours a day of queue work, by the
  same estimate, before the cache's savings and before reused receipts.
  It fits, with room to spare.

## 7. Costs and risks

- **Throughput.** The queue is serial, and a skein set runs five gates.
  The levers, in order:
  1. reused receipts;
  2. speculative runs;
  3. batching docs sets;
  4. tests selected by the crates a set changed (nextest's `rdeps()`).

  Measure before adding any of them (section 9).
- **What no gate runs.** A break that only a slow tier shows, the
  browser tier's among them, reaches `main`, and later sets build on
  it. Until after landing has its design (section 4, step 8), only a
  QA pass or a task that names the tier finds it.
- **Flakes are everyone's problem.** One flaky temper test sends a
  skein set back. Hence the single rerun, and the finding it files.
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
- **One point of failure.** While the queue is down nothing lands, but
  owners keep working on their sets.

## 8. What changes when it goes live

- **owners.md 3.1:**
  - A milestone hands over when its set is queued, and the next
    milestone starts then.
  - It ends when the set has landed. Its 4-hour cap runs to the
    request. The repair loop after it doesn't count against the cap
    (the user, 10-24); owners.md 4.4's escalations bound it.
  - Its sub-owner stays on for the landing as well as for QA, and
    briefs and checks the implementers that repair the set and fix the
    pass's findings.
- **owners.md 4.2:** rebases, repairs and QA fixes are implementer
  tasks at high effort, which the launcher doesn't lower.
- **owners.md 4.4:** tasks merge into the set's branches. The owner
  checks the end-of-milestone rebase as it checks any task's diff,
  requests the milestone's landing with `queue request`, and waits on
  it with `queue wait`. The queue lands it.
- **owners.md 4.5:**
  - Repins happen inside the set, by its owner, with `scripts/devel/repin`.
  - "Breaking upstream" waits for no one's word: the break and its
    downstream fix land together.
  - The footprint stays, to plan narrow sets and to group missions, but
    no longer orders landings.
- **owners.md 4.6:** a QA pass may start on the queued set. Its fixes
  are implementer tasks, and land as their own small set once the
  milestone has landed.
- **director.md:**
  - The ordering of landings and repins, and the relaying of hashes,
    leave the director and the product owners.
  - The landings feed replaces landing news.
  - The director runs the queue's service.
- **gate-policy.md 3:** gate evidence moves from trailers to git notes.

## 9. Building it

1. **The shared store on every build machine** (build-cache.md 7),
   under way.
2. **The queue's tool,** as a build-infra mission (section 5). The
   first version:
   - serial, with sets across repositories;
   - request and receipt checks, the order's rules, automatic rebases,
     and mechanical lock and generated-file resolution;
   - the rerun, journaled pushes, git-note evidence and the landings
     feed;
   - `queue wait`, and `land` as a front end.

   Fixtures cover it as they cover `heavy`.
3. **`scripts/devel/repin` learns sets:** one command moves every branch of
   a set to its tuple. It also learns a stacked set's rebase: onto
   `main` from the recorded fork point, in each repository.
4. **A trial** with two or three missions, then everyone. owners.md and
   director.md change then.
5. **Later:** speculative runs, tests selected by affected crates, and
   reuse of test results for byte-identical test binaries.

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

The starting primitive, `scripts/devel/land-set`
(build-infrastructure.md 10), run from an agents checkout like `repin`,
answers the first three:
- **One set at a time.** It takes one set lock on hetzner3, through the
  landing turn's holder.
- **Every gate before any push.** In each repository of the set,
  upstream first, it rebases the branch on `main`, keeping `main`'s side
  of a `Cargo.lock` conflict, repins it, and gates it with `land
  --no-push`. An upstream's gated commit goes to a staging branch, so
  that its downstreams can pin it. Only once every gate has passed does
  it push the mains, upstream first, each the very commit its
  downstreams pinned. A failure before then pushes nothing.
- **The invariant, set by set.** Each repository it lands pins every
  upstream to this run's commit where the set has one, and to that
  upstream's current `main` otherwise (section 2).
- **Pin-only repositories.** It refuses a set without them, and makes
  their branches itself when the set file says `pin-only`.
- **The feed.** Each run's steps go into a feed on hetzner3: waiting,
  started, each repository gated and landed, and how it ended.
  `landings` shows the feed and the sets in flight, the lock's holder
  among them; `landings wait <set>` exits when the set has landed or
  stopped.

Until the rest is built, agents do by hand what the tools don't:
- **The catch-up.** The first set after the release brings every
  `main` to the invariant: a set whose downstream repositories are all
  pin-only. What fails in it is drift, which implementers repair before
  the owners resume.
- **Sets and repins.** The owner keeps the set's branches. Repins inside
  the set are `cargo update --precise SHA -p <package>`, run directly
  since it builds nothing, of a commit pushed to its branch.
- **The milestone's end** follows section 3. One implementer task
  proves the set, `land-set --prove SETFILE` (9.2): it rebases, repins
  and gates every repository without the lock, and pushes no `main`. A
  conflict outside `Cargo.lock` stops it, and the task resolves it and
  proves again; a red comes back as a repair. Then the owner runs
  `land-set --prove SETFILE && land-set SETFILE` on the same machine
  (9.2), detached, as a user unit (`systemd-run --user --collect`,
  through a login shell) that posts the owner its exit (`post send
  --as`) when it ends. It starts the next milestone on the set's
  branches without waiting for it. A proof after a repair takes its
  unchanged repositories' gates from the cache, on the same machine.
- **Stacking.** Once the earlier set has landed, an implementer moves
  the new milestone with `git rebase --onto main <fork point>` in each
  repository, then repins.
- **A failure in the gates** pushes nothing to any `main`. The
  summary and the feed say where the run stopped and why. The owner
  reads the failure (owners.md 4.4); its implementer repairs the set
  and proves it again, and the owner runs `land-set` again.
- **One writer.** Every landing that pushes to skein, smith, hearth,
  jig or temper takes the set lock, plain and docs landings too (9.2),
  so no `main` moves under a set's run. A push around the tools still
  could: `land-set` checks every `main` again before its pushes and
  gates again what moved, so only a failure once the pushes have begun
  can leave a set half-landed: a gate run again that fails, a signal.
  Its rerun then resumes: the landings it recorded are checked against
  `origin/main`, and reused to pin downstream repositories without
  landing them again.
- **Order and escalation.** The set lock is the only order. An owner
  escalates a landing as owners.md 4.4 says.
- **Landing news.** Whoever waits on a set runs `landings wait`, and
  directors read `landings`: no hashes are relayed.
- **What `land` still does.** A docs change still lands with `land
  --docs`. Code that moves skein, smith or jig goes through `land-set`,
  with its pin-only repositories; a lone temper or hearth change may use
  either. Either way it takes the set lock, and `land` proves a code
  change first, without it (9.2).

Not built yet:
- the queue's service and order;
- receipts shared between machines, and git-note evidence (land's
  trailers stay);
- the rerun of failed tests;
- `land` as a front end;
- `repin` for sets and stacked rebases.

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
  So the owner's unit proves again before it lands, `land-set --prove
  SETFILE && land-set SETFILE`: where the task's proof holds there, that
  prove is all cache hits; where it doesn't, it gates without the lock.

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
- **`land`'s result.** Once `land` has rebased, it ends by printing one
  line, `land: result JSON`, and writes the same object to the file
  `LAND_RESULT` names, when it is set:
  ```
  {"schema": "land-result-v1", "repo": "skein", "machine": "debian-16gb-hel1-1",
   "base": SHA, "commit": SHA, "tree": SHA, "tries": 1,
   "prebuild": {"wait_s": 3, "run_s": 61, "exit": 0},
   "gate": {"kind": "ran", "receipt": TOKEN, "wait_s": 5, "run_s": 164,
            "exit": 0, "steps": {"fmt": 4.213, "clippy": 25.3}, "failed_step": null},
   "pushed": true, "exit": 0}
  ```
  - `repo` is the primary checkout's directory name (the parent of
    `git rev-parse --git-common-dir`), or a bare clone's name less
    `.git`; `machine` is the host name, `commit` the tip `land` gated
    or took from the cache.
  - `prebuild` and `gate` are `null` when `land` didn't reach them.
    Their times are `heavy`'s `waited` and `ran`.
  - `gate.kind` is `ran`, `cached` (the gate cache's result: no
    receipt, zero times, no steps) or `none` (`--docs`).
  - `steps` sums the gate log's `gate-step` lines by name, in their
    order. `failed_step` is the first step that exited nonzero, else
    `other` when the gate failed, else `null`.
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

Not collected yet: plain `land`s outside a set (their result line is in
their output only), and each test's time (nextest's JUnit output).

## 11. Open

- **The queue's throughput,** measured: replay 10-23's milestones
  through it with the cache.
- **Where the queue's gates run.** A gate pauses the other builds on
  its machine (build-infrastructure.md 1). The queue's gates could
  keep to one or two machines, or take whichever is free.
- **A docs landing upstream of a set** changes the commit that every
  downstream's lock pins, and the downstreams then gate again for
  Markdown alone (landing-proof.md 7).
- **Proving on one machine and landing on another** needs a receipt
  that the lander can read and check (landing-proof.md 7).
