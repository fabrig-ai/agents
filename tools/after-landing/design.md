# After-landing checks

Provisional, 2026-10-29 (green, s/dynamic-memory). Runs fabrig's slow tiers on what the merge queue landed, confirms each new red, and tells the coordinator whose branches it suspects.

## 1. In one page

- **What landed is read from git, not a feed:** every first-parent merge commit on fabrig's `main` is one landed branch (`Merge ready/<key>/<task>`); the queue publishes only gated batches, so each `main` it published is a tested tip. The queue's `queue.jsonl` stays the queue's journal; this tool needs no transport from the gate machine.
- **One run per new main, serial:** when `origin/main` moves past the last checked commit, the tool checks the newest `main` with every tier of its set; the merges since the last checked commit are that run's **suspects**. Every landed merge is covered by exactly one run. Runs never overlap.
- **The tier set is explicit** (section 3): the slow tiers no gate runs, minus the live tiers and temper's process tier; each through fabrig's `tools/tiers/run TREE TIER` at the checked commit, with its own budget.
- **A red is confirmed before anyone hears of it:** each failed test is run once more alone at the same commit; the same test failing again is a **confirmed** red, passing is a **flake**. A failure to run (prerequisite, disk wait past its bound, heavy refusal, no test selected) is a **fault**, never a red.
- **New is told, standing is not:** a confirmed red already red at the previous run is **standing** and is not blamed on the new suspects; a red with no passing run before it is **unattributed** (the first run's reds).
- **Told to the suspects' coordinators:** each new confirmed red goes by `post` to the coordinator of each suspect branch (section 5), with the commit, the test, both logs, the suspects and whether the culprit is known (one suspect) or not; faults go to ops.
- **Every verdict is a records event** (section 6), written before the post is sent; state survives a restart.
- **Ops runs it,** in one pool slot it claims, on one builder, at heavy's background class; s/deploy declares its unit on that one host.

## 2. The loop

1. Every 60 s: `git fetch` in its slot; if `origin/main` equals the last checked commit, sleep.
2. Else the suspects are `git rev-list --first-parent --merges LAST..origin/main`, each with its branch name from the merge subject and its second parent (the branch tip). A merge whose subject does not name a `ready/` branch is a suspect named by its commit.
3. Switch the slot's checkout to the new `main` (detached, clean), run every pair of the tier set in order, recording per pair: selected, passed, failed test ids, nextest exit, heavy logs, wall time.
4. For each failed test id: `tools/tiers/run TREE TIER -- -E 'binary_id(=BIN) & test(=NAME)'` once; record pass or fail and its log.
5. Classify (section 4), write the events, send the posts, move the last checked commit to this `main`, and record per test id its last state (passing, red since COMMIT).
6. Restart-safe: the state file (last checked commit, per-test states, the run in progress, posts not yet delivered) is written by sibling-and-rename after each step; a run interrupted mid-way is redone whole at the same commit on start.

A test's identity is `(profile, binary id, test name)`, from nextest's own output.

## 3. The tier set

The pairs, run in this order: `exhaustive-skein`, `qa-skein`, `qa-smith`, `qa-jig`, `process-jig`, `browser-skein`, `browser-jig`, `browser-temper`, `qa-temper`. The list lives in the tool's configuration, not discovered: a new profile in fabrig's config is not enrolled until added here. Not in the set: `live-*` (real providers and the user's sign-ins), `process-temper` (its owner's). Each pair is validated against `tools/tiers/run`'s pairs at each run; a missing pair is a fault.

Expected cost per run: about 20 minutes serial on a warm slot (baseline 1, 10-29: qa-temper 7.3 min, browser tiers with bundles about 13 min including their builds). When runs are slower than landings, suspects simply grow: still one run per new `main`.

## 4. Verdicts

Per run, one of:
- **green:** every pair ran and every selected test passed (flakes allowed and listed);
- **red:** at least one confirmed red; each listed as `new` (passing at the previous run), `standing` (red at the previous run) or `unattributed` (no earlier passing run);
- **fault:** a pair could not run (exit 2 of `tools/tiers/run`, nextest exit 4, a disk wait over 30 minutes, heavy refusal); the run is retried at the next poll at the same or newer `main`, and the suspects carry over.

A test confirmed red at one run and passing at a later one is **recovered**.

## 5. Who is told

- A suspect branch `ready/<key>/<task>`: `<key>` names its owner. The coordinator is found from fabrig's registry (`tools/session/start names --json`: a lead's `branch_key` gives its `coordinator_mailbox`; a coordinator's own key, as `coord` for `s/dynamic-memory`), else `tools/queue/leads.txt`'s address for `<key>`. No route is a fault to ops, never a guess.
- One post per coordinator per run, under 15 lines: the commit, the new reds (test, profile, first error line, both log paths, builder), the suspects with their tips, `culprit: <branch>` for one suspect or `culprit: unknown` for several. Sent as `after-landing`; exit 0 or 3 is delivered, else retried at the next poll.
- Faults: to ops, once per episode (the first fault after a green or red run).
- Standing, unattributed, flakes and recoveries: events only, no post.

## 6. Records

Events (agents `tools/records/record.md`), source `after-landing`, one per run (`kind: after-landing-run`: commit, suspects, verdict, per pair counts and logs) and one per new, standing, recovered or flaky test (`kind: after-landing-test`), each with a durable id `<commit>:<profile>:<binary>:<test>`, written before any post so a retry never changes identity.

## 7. Where it runs

- Ops claims one pool slot for it (`claim claim HOST N ops after-landing`) and keeps it; the slot's target stays warm; the slot guard's rules apply.
- Every cargo command goes through heavy (via `tools/tiers/run`) with `HEAVY_CLASS=background`; the 80 GB disk rule is `tools/tiers/run`'s.
- s/deploy declares one unit on that one host (`fleet/units/`), restart on failure after 60 s, not on exit 2; ops starts and stops it.

## 8. Later

- Bisection over a red run's suspects (each first-parent merge is a buildable `main`-like commit), to name a culprit among several.
- A slower cadence or parts across two slots when runs fall behind landings, from measured numbers.
- Process-temper and live tiers, when their owners agree.
- Verdicts read by the queue (holding a batch on a standing red) and the status page.
