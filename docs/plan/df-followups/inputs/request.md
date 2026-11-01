# Request: dogfood-faults' acceptance follow-ups

From agents/loop, 2026-11-01. The acceptance review of `docs/plan/dogfood-faults` (ACCEPT, main
1fc8818) found these. None blocks, but item 1 must land before the next fabrig integration plan
lands its trunk.

1. **Calls after a trunk lands start from main** (`docs/design/integration.md` 3, "Retire waits
   for main", widened in this request's commit).
   - Today only the retire moves to main: `fab/designer.py` ~509 for the retire;
     `fab/calls.py` ~773 `start(..., base=plan.trunk)` for the other roles. The queue deletes
     `<draft>/integration`, and the clone prunes `refs/remotes/origin/<trunk>`.
   - So between the trunk's landing and the retire's, two things fail:
     - an answer, review, triage or amend call fails at `worktree add` every round;
     - `_integration` (`fab/dispatch.py` ~1946-1950) logs a "failed:" note every tick from its
       `_contains`/`rev-parse` of `origin/<trunk>`.
   - Build:
     - in `designer.main` and `calls.main`, use `base = "main" if plan.landing ==
       "integration" and integration.trunk_landed(plan, events) else plan.trunk` for every role,
       and flip `test_other_designer_roles_keep_trunk_after_queue_landing`;
     - in `_integration`, return before the git reads when `trunk_landed`;
     - the foreman and refusal starts that pass `trunk=plan.trunk` (dispatch.py ~1501, ~1522,
       ~1612) pass main after landing.
2. **The branch probe tells an error from an absent branch** (`fab/run.py` ~327-329). Today any
   failure, an ssh 255 or a git 128 among them, reads as "absent", and the rerun starts from the
   base. Build: `probe.code not in (0, 1)` raises `Failed`, as `dispatch._contains` does.
3. **A catch-up stop's brief shows no empty report** (`fab/calls.py` ~350-352). When the stop's
   report is "", render `- Report: (none: the findings are quoted below)`.
4. **Two stale status lines:**
   - `docs/design/integration.status.md` ~72-78, "An integration trunk through the queue is
     untried live": drop "no plan has yet run with `ready = true`". After "So are the stop's
     question and its lift", say: "The retire from main ran live once (the probe phase-case,
     11-01): its trunk landed through the queue at 17:17:58Z, its retire started from main
     (17:27:16Z), went through `ready/calls/retire-2c39…` and landed at fc1651448b, and the plan
     checkout detached there; its landing was never imported (no `branch.landed` or
     `call.finished`; tick.md 5, start-commands item 4). No trunk has stopped since the stop's
     records were built."
   - `docs/design/tick.status.md`, "The dispatcher: … run by hand, live since 20:27Z" becomes
     "…; on hel8 started by `fab-events.path` and the 10-minute `fab-backstop.timer` (Events
     drive the tick, below)".

The user's rule: dogfood. Built by fab's loop (landed through `bin/fab land`); the plan's landing
is `queue` (the cut is started with `--set 'landing="queue"'`). Two tasks: item 1 by itself, and
items 2-4 together. Tests in `fab/tests/` (fakes, fixture logs). Run beside
`docs/plan/mechanisms-out` and `docs/plan/start-commands`: item 1 touches `fab/calls.py` `main`
and `fab/designer.py` `main` at the `start(...)` call only.
