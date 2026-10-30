# After-landing checks

Provisional, 2026-10-29 (green, s/dynamic-memory). Runs fabrig's slow tiers on each `main` the merge queue publishes, confirms each new red, and tells the coordinators of the branches it suspects.

## 1. In one page

- **What landed is read from git:** the tool polls fabrig's `origin/main` every 60 s and queues each new tip it sees, in order. A batch takes the queue several minutes, so each published batch tip is seen; the commits between two tips are that tip's **suspects**. The queue's `queue.jsonl` stays the queue's journal on the gate machine; this tool needs no transport from it.
- **Every published tip, in order, one at a time:** each queued tip gets one run of the whole tier set (section 3), serially. When more than two tips wait, the tool runs the newest and records the skipped ones as **coalesced** into it (their suspects join its suspects): coverage of a tip broken and repaired between two runs is then lost, and the run's event says so. Each hour it posts ops and the coordinator the published tips seen, runs completed, tips coalesced and the lag of the oldest waiting tip, so coverage loss is visible and a cadence change is made on numbers (one slot finishes at most about three runs an hour).
- **A red is confirmed before anyone hears of it:** each failed test is run once more alone at the same commit; the same identity failing again is **confirmed**, passing is a **flake**. A pair that cannot run is a **fault**, never a red.
- **New is told, standing is not:** a confirmed red whose test last executed and passed is **new**; one whose test was last confirmed red is **standing**; one with no executed result before is **unattributed**.
- **Attribution is suspicion, not proof:** a new red names its suspects; one suspect is reported as `single suspect`, several as `several suspects`. A new red with several commits since its last pass is then **bisected** to an observed transition: a commit failing on top of a passing first parent (section 9). It is not proven the earliest failure: commits not probed may break and repair.
- **Told to the suspects' coordinators** by `post` (section 5); faults to ops. **Every verdict is a records event** (section 6), written before its post.
- **Ops runs it** in one pool slot on one builder, at heavy's background class; s/deploy declares its unit on that host (section 7).

## 2. The loop

1. **Poll:** `git fetch` in the slot every 60 s. A new `origin/main` that descends from the last seen tip is appended to the tip queue; one that does not (rewritten history) is a fault to ops, and the tool stops polling until ops resets its cursor.
2. **Suspects of a tip:** `git rev-list --first-parent PREV..TIP`, each commit classed by its parents and subject: a merge `Merge ready/<key>/<task>` is a **branch suspect** (key, task, second parent = branch tip); any other merge (e.g. `Merge commit '…'`) and any single-parent commit is an **other suspect**, named by commit and subject (the queue's own baseline commits are other suspects and are never routed). The queue does not squash or fast-forward branches onto `main`; a branch tip reachable by first parent is an other suspect too.
3. **Run:** switch the slot to the tip (detached, clean), then each pair of the tier set in order through fabrig's `tools/tiers/run TREE TIER`, under the tool's supervision: a pair's run (prerequisites included) has a wall bound of its profile's global timeout plus 30 minutes; past it, the tool cancels the heavy command in flight through heavy's own interface (`heavy --cancel TOKEN` from the submitting directory, the token from heavy's output), waits until heavy reports that command finished, and only then ends the child and records a fault for that pair. While a cancelled command's end is unknown, the slot's checkout, inputs and claim stay as they are, no next pair or tip starts, and ops is told.
4. **Failure identity** is `(profile, binary id, test name)`, read from a machine-readable nextest output (JUnit XML or libtest JSON, the implementer's choice, pinned by a fixture test of the parser), never from the human summary.
5. **Rerun:** each failed identity once, alone: `tools/tiers/run TREE TIER -- -E '<exact filter>'` with exact matchers (`binary_id(=…)`, `test(=…)`) built from the identity with nextest's quoting; the rerun counts only if exactly one test was selected and its identity is the same.
6. **Classify** (section 4), write events (section 6), send posts (section 5), and update per-identity state. The cursor (last checked tip) moves only past a run with no faulted pair; a run with faulted pairs keeps its tip queued and its suspects, and retries only the faulted pairs at the next attempt.
7. **State** (tip queue, cursor, per-identity last executed result with its commit, the run in progress, undelivered posts) lives in one file under the tool's state directory, replaced by sibling-and-rename after each step; a run interrupted mid-way is redone at the same tip on start, without new event ids for parts already written. Every identity outcome, including passing and skipped, is saved individually. Replay compares the selected identities and each saved outcome; a change faults the pair and retains its prior evidence and history until a later attempt resolves it. Run completion, its fault episode and its pending fault post are saved in one replacement.

## 3. The tier set

`exhaustive-skein`, `qa-skein`, `qa-smith`, `qa-jig`, `process-jig`, `browser-skein`, `browser-jig`, `browser-temper`, `qa-temper`, in that order, from the tool's configuration file: a new profile in fabrig's config is not enrolled until added here. Not in the set: `live-*` (real providers, the user's sign-ins), `process-temper` (its owner's). A pair `tools/tiers/run` refuses is a fault.

Expected cost: about 20 minutes per run on a warm slot (baseline 1, 10-29: qa-temper 7.3 min, browser tiers with their bundle builds about 13 min).

## 4. Verdicts

- Per pair: **ran** (counts, failed identities) or **faulted** (tiers/run exit 2, nextest exit 4, wall bound passed, heavy refused).
- Per identity, from executed results only: **passing**, **confirmed red** (`new`, `standing`, `unattributed`), **flake**; a confirmed red later executed and passing is **recovered**. An identity not selected or skipped is **unobserved**: its last state stands, and it never recovers without executing.
- Per run: **green** (every pair ran, no confirmed red), **red** (any confirmed red, whatever else), **partial** (no confirmed red, some pair faulted); a red run with faulted pairs reports both. A confirmed identity is retained if a later confirmation in the same pair faults.

## 5. Who is told

- **Resolver,** one function: a branch suspect's `<key>` → agents' launcher registry (`session-start names --json`, today `~/src/fabrig/current/tools/session/start names --json`): a lead's `branch_key` gives that lead's `coordinator_mailbox`; a coordinator's own prefix (`coord` → `s/dynamic-memory`, `q`, `u`) gives its mailbox; keys the registry lacks (`ops`, `mc`) → fabrig's `tools/queue/leads.txt` address. A registry mailbox without a host is resolved by an exact mailbox match in `leads.txt`, so a builder does not accidentally post to a local mailbox; missing or ambiguous addresses are faults. Conflicting duplicate keys are faults, and every final address must include a host. No route, or the registry unreadable, is a fault to ops, never a guess.
- **One post per coordinator per run** with a new red, under 15 lines, as `after-landing`: the tip, each new red (identity, first error line, both log paths, builder), the branch and other suspects, and `single suspect` or `several suspects`. Exit 0 or 3 is delivered; otherwise it stays undelivered and is retried at the next poll. The durable event id inside a post body stays unchanged across retries; post transport ids may differ, and exit 0 or 3 marks delivery in state. A resolver failure leaves the new-red notification unresolved in the durable outbox; resolution retries independently of later per-test history, until a route and delivery succeed.
- **Faults** to ops, once per episode (an episode ends at the next run with no faulted pair).
- Standing, unattributed, flakes, recoveries and coalescing: events only.

## 6. Records

Agreed with s/multi-coord (10-29): source `after-landing`, written with `record append --as after-landing --batch HOST` (one push per run; `~/src/fabrig/current/tools/records/record` until `fabrig-record` is on PATH). Kinds:
- `after-landing-run`: tip, attempt, suspects, coalesced tips, verdict, per pair counts, wall time and log paths; id `<tip>:<attempt>`;
- `after-landing-test`: identity, state (`new`, `standing`, `unattributed`, `flake`, `recovered`), both log paths; id `<tip>:<attempt>:<profile>:<binary>:<test>`.
Large event lists are kept in referenced private JSON detail files; the wire event stays below 16 KiB with counts and explicitly named previews. When an event needs this compaction and its full id exceeds 1024 bytes, its wire id is `sha256:` plus its deterministic digest, with the original id and complete identity retained in the detail file. Ids are deterministic (re-collection safe); events carry log paths, never contents (lines capped at 16 KB), and the join keys `commit` and, for routed reds, `branch`. An event is written before its post; a publication failure keeps the run's state undelivered and is retried with the same ids.

## 7. Where it runs

- **Slot:** ops claims one pool slot (`claim claim HOST N ops after-landing`; the slot ops names, proposed hetzner7 slot 4) in the activation window after fresh idle and space checks, and keeps it; its target stays warm; the slot guard's rules apply, and the tool frees disk only in that slot's target.
  After each verdict and its events/outbox are durably saved, before the next checkout and only with all heavy completions known, it runs `python3 -I <slot>/tools/slots/trim --older 0 <slot>` (`--trim` overrides the script); trim failures are saved and posted to ops once until a successful trim, never block the next run, and hourly coverage includes the reported bytes freed (rounded to one MB).
- **Builds:** every cargo command through heavy (via `tools/tiers/run`) with `HEAVY_CLASS=background`; the 80 GB rule is `tools/tiers/run`'s, bounded by section 2's wall bound.
- **Unit** (s/deploy's conventions, 10-29): a single-host role `after-landing` in `fleet/units/roles.toml`, given in `fleet/hosts.toml` to ops's host; first line `# fleet-sync: start-once`, so fleet-sync starts it once when it first appears and ops starts and stops it afterwards; `Type=exec`, `ExecStart=/bin/bash -lc 'exec "$$HOME/src/fabrig/current/tools/after-landing/after-landing" follow'`, `Restart=on-failure`, `RestartSec=60`, `RestartPreventExitStatus=2`, `WorkingDirectory=%h`. Shipped as an agents branch for s/deploy's review, landed in a window agreed with ops.

## 8. Later

- Parts across two slots, or a slower cadence, from the coalescing numbers.
- `process-temper` and the live tiers, when their owners agree.
- Verdicts read by the queue (holding a batch on a standing red) and by the status page.

## 9. Bisection

Added 2026-10-30 (green), reviewed the same day. A confirmed new red with several commits since its last pass is narrowed to a commit observed failing on top of a passing first parent. A bisection is evidence for the coordinators, not a verdict: it changes no run's verdict and no per-identity history (section 2, step 7).
- **Which reds:** a run's `new` identities (section 4) whose interval holds more than one commit. An identity's interval is `GOOD..TIP` by first parent, `GOOD` being the commit of its last executed pass in the per-identity history (not the cursor: an identity unobserved meanwhile keeps an older `GOOD`). Standing, unattributed and flaky identities are not bisected.
- **A phase of its own:** the state replacement that completes the run (section 2, step 6) also saves the pending bisection: its groups, each with identities, `GOOD`, `TIP` and candidates (`git rev-list --first-parent GOOD..TIP`, oldest first), and the bound below. The run's trim (section 7) and its posts' queuing in the outbox come first; the bisection then runs before any next run or fault retry, and never waits on the delivery of a post. Tips arriving meanwhile queue and coalesce as usual.
- **Groups:** the new identities of one pair with the same `GOOD`, probed together. Initial groups are numbered `1, 2, ...` in section 3's pair order, then oldest `GOOD` first. At each probe a group whose identities' outcomes differ splits into parts numbered by appending `.1` (bad), `.2` (good), `.3` (unknown), only for the outcomes present (group `2` gives `2.1` and `2.3`); each part continues alone with its own interval and the probes so far. The numbers are saved with the split and never reassigned.
- **A probe** of a group at a commit: switch the slot to it (detached, clean) and run `tools/tiers/run TREE TIER -- -E '<the group's exact filters joined with |>'` (prerequisites as usual, only the pair's packages); the selection must be exactly the group's identities. Per identity, a failure confirmed by a rerun alone at the same commit is **bad**; an executed pass is **good**; a failure passing on its rerun, or an identity skipped or not executed, is **unknown** at that commit. A commit that does not build (nextest's build-failure exit) is **unbuildable** for the group. Any other failure to run (heavy refused or cancelled other than by the deadline, section 2's own wall bound, `tools/tiers/run` exit 2, a different selection) is a **fault**: it ends the bisection, and goes to ops once per episode (section 5).
- **Endpoints:** the bad end is `TIP`, by the run's confirmed failure there (same slot and commit; not probed again). The good end must be probed: first `GOOD` again, and each identity must be good there; one bad, unknown or unbuildable at `GOOD` (the environment, not a commit) ends its part of the group.
- **Search per group:** the interval is (last good, first bad), from (`GOOD`, `TIP`); probe its middle candidate; on unbuildable or unknown, the nearest untried candidate older than the middle, then newer, alternating outward. Each good or bad narrows the interval; the search ends when no untried candidate is left inside it.
- **Results per group,** each with its final interval (last good, first bad, the commits between) and its probes:

  | end | result |
  |---|---|
  | the interval's first bad `C` has its first parent as last good (`C` may be `TIP`) | `culprit proven`: the failure appears at `C` on top of a passing parent |
  | candidates left inside the interval, all unbuildable or unknown | `range` |
  | the bound reached (the deadline, including an invocation cut short by it, or the 16th invocation) | `range` |
  | `GOOD` not good now, or a fault | `inconclusive` |

  A proven merge `Merge ready/<key>/<task>` names that branch; any other commit is named by commit and subject. No other suspect is cleared by it: commits after `C` were not all probed.
- **Bound,** one per bisection and persisted: a deadline 45 minutes after its start (absolute: restarts count) and 16 `tools/tiers/run` invocations, confirmations included, across its groups, counted at each launch. Each invocation's wall bound is the lesser of section 2's and the time left; an invocation cut short by the deadline is cancelled and drained as section 2, step 3 says (its unknown end holds the slot and is told to ops like any), then every unresolved group ends as the table says.
- **Told:** once its events are written, one outbox group as `after-landing`, resolved by section 5's resolver when it is created: to each coordinator the run's new-red post went to, a proven culprit's coordinator if not among them, and ops when a culprit is an other suspect. Its body names the run's event id it follows, each group's result, identities, interval and culprit, and the path of a detail file with every probe's commit, outcomes and log paths. It is delivered and retried as section 5 says, after the run's outbox group (saved as a dependency on the run's id, so a reader gets `several suspects` first); a delivery waiting on it never holds the slot or the next run.
- **Recorded:** one `after-landing-bisect` event per final group (tip, attempt, identities, `GOOD`, candidate count, result, interval, culprit commit and branch, wall, tips that arrived meanwhile, the detail file's path), id `<tip>:<attempt>:bisect:<number>` (the group's number above); join keys `commit` (the culprit's, else the tip) and, for a branch culprit, `branch`. The hourly coverage post adds the minutes spent bisecting.
- **Restart:** a probe (its grouped run and all its confirmations) is one transaction: its outcomes, any split and the narrowed intervals are saved in one replacement at its end, never in part; before each launch, the invocation with its heavy token and the incremented count are saved. On start, an unknown heavy completion is drained first (section 2, step 3); a probe without a saved end is redone whole at the same commit, its partial results discarded (they were never evidence); saved probes, splits and numbers stay. After the last group, the phase's events, outbox group and a trim (section 7) are saved in one replacement, and the loop takes the next tip.

