# acceptance-fixes: the cut's decisions

What the request and its designs left to the cut, each settled with its
reason. The specs bind them.

1. **Two direct parts, one task each,** as the request says: items 1-2, then
   items 3-5. Neither is a contract, and neither reads the other's code.
2. **`trunk-landed` needs `precheck-receipt`, though they share no file.** The
   request says twice that items 1-2 come first, and only `needs` makes
   that hold at landing; slice order alone only sets who starts first. Items
   3-5 are not urgent: no trunk has landed since df-followups. This departs
   from "a task waits only for code or files it shares", at the cost of the
   critical path below.
3. **`fab/receipts.py`'s fix needs a machine action.** `fab-queue.service`
   on the gate calls `reusable` and runs for days; services move only with
   `bin/install.sh HOST` (`docs/design/machines.md` 2, `tick.md` 3), so the
   gate keeps reusing starved receipts until it is run for the gate.
   `precheck-receipt`'s commit says so. `fab/precheck.py` runs on builders
   and `fab/dispatch.py` in the tick, which follow main unaided.
4. **Skipped cases are counted, never named.** The request names only the
   count. A stopped run has hundreds (938 in the case at hand), and each
   tree's `unobserved` total is already in the log (`fab/queue_cpu.py` ~151).
5. **`records` is the fabrig collector's** (`tools/tiers/cpu.py`), written
   under each profile by `fab.cpu.collect`'s worker. No `fab/` code names the
   directory, and by the end of `_checks` everything read from a profile has
   been read: `junit.xml`, `inventory.json`, `summary.json` and
   `gate-junit.xml`, all kept. The removal goes after the loop over `reports`,
   and `reports` holds only profiles that ran, so a red run that stopped
   before fuzzy has nothing to remove there.
6. **Tests past the request's list.** Item 1's count and item 2's removal get
   a precheck test each, and item 4 a dispatch test: the request names none,
   and `AGENTS.md` wants every tool tested.
7. **`_settle` and `_remedy` use `call_base` for every kind,** as the request
   writes it, unlike `_foreman` and `_examine`, where a fix kind keeps
   `main`. Before the landing that is `plan.trunk` as today; after it both
   are `main`.
8. **`queued` in `_settle` and `_remedy` stays.** It is false for an
   integration plan even after its landing, but the retry still works: on a
   fabrig plan, `foreman.commit` and `repairs.commit` find their pushed branch
   and return it without a new commit while `_queue_branch` waits; once the
   queue deleted it, the edit is already on main and they return None. Only a
   `_remedy` retried across midnight commits again, its section's date
   changed, and that readies a new tip: harmless, and outside the request.
9. **Left as they are:** `_merge_branch` (nothing reaches it after the fix),
   `_landing_actions`' hold on a task's needs (~2041), and the cut's merge
   check of `origin/<plan.trunk>` (~1513): the request does not name them.
10. **`kind = "feature"` for both:** `reusable` keeps its signature, and
    `_settle`, `_remedy` and `_landing_actions` are private.
11. **No counted forms and no user's questions:** the request sets no counts,
    this repository has no `scripts/old_forms.py`, and the request settles
    everything that is the user's.
12. **Critical path:** `precheck-receipt` 30 minutes, then `trunk-landed` 45:
    75 implementer-minutes, against 45 without decision 2.
