# Request: call-rebase's acceptance fixes

From the director, 2026-11-01 (agents/loop's brief, backlog item 2). Plan
`docs/plan/call-rebase` (retired 11-01) built `docs/design/calls.md` 2's
"A `fab land` refusal counts as a refusal of the chain". Its separate
acceptance review (main 1dc102c) refused it with one blocking finding and
two minor ones (`~/src/fabrig/coord/main-sync/handover.md`, last section).
The design is right; bring the code and role texts to it:

1. **Blocking: only a branch gone from origin ends the chain.** In
   `fab/dispatch.py` `_finish_outcome` (~951), a `fetch` refusal ends the
   chain `call.finished` failed whenever `git ls-remote --exit-code origin
   refs/heads/<branch>` is not ok, including exit 128 (network or auth), so a
   passing network failure loses the chain for good. calls.md 2 says "a
   `fetch` refusal whose branch is gone from origin". Build: failed only on
   exit 2 (the ref is absent); any other non-zero code returns None, so the
   refusal goes on to amend as any passing `fetch` failure does. Change the
   test case `("fetch", 128, False, "failed")` in
   `fab/tests/test_dispatch.py` (`test_finish_land_refusal_steps_and_terminal_exceptions`)
   to expect no `call.finished`, and word `docs/design/calls.status.md` (~57)
   as "a `fetch` refusal whose branch `git ls-remote --exit-code` reports
   absent (exit 2)".
2. **Minor: settle's role text.** `fab/roles/settle.md` (its `Done: land`
   and `Done: amend` lines): add "When the brief says land would land a tip
   `fab land` refused, land is not an option: choose amend, or user when the
   brief says user only."
3. **Minor: the amender at `test`.** `fab/roles/amender.md` ("A refusal
   headed `fab land` refused at"): at `test`, rebase onto `origin/main`
   first (as at `rebase`) before reproducing and fixing what the log names,
   since `fab land` tested the branch rebased onto main.

The user's rule: dogfood. Built by fab's loop (landed through `bin/fab
land`); the plan's landing is `queue` (the cut is started with `--set
'landing="queue"'`). Small work: one direct part, one or two tasks.
