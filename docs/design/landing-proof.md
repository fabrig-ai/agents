# Proving a set before its lock

Provisional, 2026-10-25, decided by the user the same day. A
change to `land-set` ([landing-flow.md](landing-flow.md) 9.2,
[build-infrastructure.md](build-infrastructure.md) 8 and 10): a set's gates
run before it takes the set lock, and under the lock `land-set` lands
what they proved, if no `main` has moved. Every write to a `main` takes
the set lock. Written first for the build-efficiency session, whose
landing scenario models this flow beside today's (section 6).

## 1. In one page

- **What hurts today** (the feed, 10-25):
  - A set holds the lock through all its gates. A clean skein set held
    it 17.5 minutes (forgejo-elsewhere-3/m4) and 24.8 minutes
    (fake-backends/m3-oauth), two thirds of that in the prebuild.
  - Plain `land`s and docs landings move a `main` under a held lock.
    upgrades-4-m1 gated temper five times to land it once, and stopped
    on the three-round bound.
- **Prove:** `land-set --prove SETFILE` is phase 1 without the lock. It
  rebases, repins and runs `land --no-push` in each repository, upstream
  first, and pushes no `main`. Each gate's result goes to the machine's
  gate cache, keyed by tree, gate command and policy (gate-policy.md 3).
- **Land:** `land-set SETFILE`, as today, on the same machine. Under the
  lock its phase 1 runs again, and where no `main` moved, every step is
  a no-op or a cache hit: seconds per repository, no build. Where one
  moved, it gates again from the most upstream repository that moved, as
  today.
- **The receipt is the gate cache,** so a set proves and lands on one
  machine. That is per machine for now, not a principle: kache shares
  compiled units across machines, and only the gate's result stays
  local (section 7).
- **One writer:** a plain `land` and `land --docs` take the set lock
  for their rebase and push. Nothing then moves a `main` under a held
  lock, and phase 2's rounds for a moved `main` stop happening.
- **Unchanged:** the gates and what they run, one gate per landing in
  the common case (optimistic, the user, 10-25), and the next milestone
  stacked on the set.

## 2. Prove

- **Who runs it.** The implementer task at the milestone's end, in
  place of 9.1's "rebase and repin the set, and run no gate". A
  conflict outside `Cargo.lock` stops it, as `land-set` stops today,
  and the implementer resolves it. A red comes back as a repair, with
  no lock held and nothing pushed.
- **What it builds, and where.** In each of the set's worktrees, on the
  owner's machine, upstream first:
  1. fetch, rebase on `origin/main`, repin;
  2. the build lane's prebuild: `cargo fmt --check`, `cargo clippy
     --workspace --all-targets`, `cargo nextest run --workspace
     --no-run`;
  3. the gate, `scripts/check.sh`, alone in the gate lane, which pauses
     the machine's other builds.

  Other owners prove at the same time, on their own machines.
- **The tuple.** A set's own upstreams are pinned to this run's
  candidates, the others to their `main` as read once at the start, as
  phase 1 does today.
- **No repins by hand.** Prove repins. The task neither repins first nor
  orders `cargo update` itself: forgejo-elsewhere-3's repair spent two
  implementer rounds on that order (a1b-r1, a1b-r2).
- **The proof.** It writes `DEV_TMP/land-set/proofs/<set>.json`: the
  set, the machine, a token, the time, and each repository's base,
  commit and tree, and whether it is pin-only. The gate cache stays the
  evidence. The proof lets land keep a pin-only repository's proved
  commit (section 3), say what it reused, and lets the report count it
  (section 5).
- **After a repair** it runs again. Repositories whose trees didn't
  change take their gates from the cache.

## 3. Land

- **When and where.** On the machine that proved, once prove has
  passed: `land-set --prove SETFILE && land-set SETFILE`, run detached as
  today (9.1). The cache's key names the worktree's path and `PATH`
  (gate-policy.md), so a proof made in the task's environment may not
  hold in the unit's; that second prove then gates without the lock,
  and is all cache hits where it does hold. Pin-only worktrees keep one
  path per set for the same reason.
- **An unchanged `main`.** Under the lock it fetches every repository.
  Where `main` is still the proof's base, and every upstream's
  candidate is unchanged:
  - the rebase is a no-op and the repin finds the same tuple;
  - a pin-only repository's repin makes a new commit, with new dates;
    when its parent and tree are the proof's commit's, the branch is
    reset to that commit, so that its downstreams pin the proof's;
  - `land --no-push` finds the tree in the cache, runs no prebuild and
    no gate, and amends nothing, so the candidate is the proof's commit;
  - phase 2 pushes it, as today: about 8 seconds per repository on
    10-25.
- **A moved `main`.** From the most upstream repository whose `main`
  moved to the end of the set, phase 1 rebases, repins and gates again,
  under the lock: today's cost, for those repositories only. The ones
  upstream of it keep their proof.
- **A docs-only move** (Markdown under `docs/`) keeps that repository's
  gate through `land`'s existing rule. Its downstreams then pin a new
  commit and gate again (section 7).
- **Another machine, or a new policy** (a kit landing between prove and
  land) finds nothing in the cache, and every gate runs again under the
  lock. That is correct, only slower.
- **The lock's hold,** for a set whose mains didn't move: a fetch, a
  no-op rebase, the repin's `cargo update` and `cargo metadata`, a
  cached `land --no-push`, then a push, per repository. That should be
  about two minutes for five repositories; to be measured.

## 4. One writer

- **A lone temper or hearth landing** proves with `land --no-push`,
  without the lock, then takes the set lock for `land`: a no-op rebase,
  a cached gate, a push. If `main` moved during the prove, it gives the
  lock back and proves again, and only its third landing pass gates
  under the lock (build-infrastructure.md 8). Code in skein, smith or
  jig goes through `land-set` already (9.1).
- **`land --docs`** takes the set lock for its rebase and push: seconds.
- **The temper turn** is gone: the set lock is the landing turn now
  (build-infrastructure.md 8), and orders every landing.
- **agents** isn't in any set, and takes no set lock: its landings keep
  only `land`'s per-repository turn on their machine.
- With every writer under the lock, a `main` moves under a held lock
  only when someone pushes around the tools. Phase 2's moved-main rounds
  and exit 6 stay, for that case.

## 5. What it costs and saves

- **Saves:**
  - the lock's hold for a set whose mains didn't move: 10 to 25 minutes
    down to about two;
  - serial gates: sets' gates run side by side on their owners'
    machines, not one set at a time;
  - regates from plain landings during a set's run.
- **Costs:** when a `main` moves between prove and land, that
  repository and its downstreams gate twice, once in prove and once
  under the lock. The second build is warm: kache restores what the
  prove compiled, and only the ripple of what landed compiles.
- **Measures,** from the feed and the proofs: the lock's hold per set;
  request to landed; gates per landed set and why each ran (first, a
  moved `main`, a repair); how often a `main` moved during a prove.

## 6. For the landing scenario

What to model, in build terms, for both flows. Neither uses `land` or
`land-set`: rebase by hand, then each repository's `scripts/check.sh`
through `heavy --gate`, after the prebuild's three commands in the
build lane.

- **Today:**
  - one lock for the fleet;
  - per set, under it, per repository upstream first: rebase, repin,
    prebuild, gate, then the pushes;
  - plain temper landings, about 4 an hour on 10-25, under their own
    turn, moving temper's `main` meanwhile.
- **This flow:**
  - per set, without a lock, on the owner's machine: the same work per
    repository;
  - then the lock: per repository, nothing builds where `main` is the
    base; from the most upstream moved repository on, the same work
    again;
  - every landing, plain and docs, under the lock.
- **The mix** in 10-25's feed: sets reaching all five repositories
  (skein), sets of jig and temper, temper alone; six sets from 03:29 to
  12:54Z, plus the plain landings.
- **What it decides:**
  - how much the second, warm gate costs after a moved `main`, against
    the prove's;
  - the lock's hold, and how often a `main` moves during a prove, at
    10-25's rate and at a busier one.

## 7. Open

- **A docs landing upstream of a set.** A docs landing in skein during a
  set's prove changes skein's commit, which every downstream's lock
  pins. They then gate again, for Markdown alone. A possible rule: a
  downstream tree that differs from its gated tree only in its lock's
  pins, where each upstream's old and new commits differ only in
  Markdown under `docs/`, keeps its gate. It is `land`'s docs rule,
  carried through the lock.
- **Proving on one machine and landing on another,** or a queue on
  hetzner3 that lands for everyone, needs a receipt and its log that
  the lander can read and check, as gate-policy.md 3.1 checks them
  locally. Nothing needs that while the owner's machine does both.
- **Starvation.** A set whose `main` moved during its prove gates
  again under the lock. Nothing moves a `main` while it holds the lock,
  so that second run always ends.
