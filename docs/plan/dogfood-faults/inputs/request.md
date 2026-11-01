# Request: fab faults found by dogfood/design

From the director, 2026-11-01 (agents/loop's brief, backlog item 1): fix the
fab faults the session dogfood/design found while writing temper's landing
model from fab's code, and bring the designs and status files back in line
with the code. Each fault was confirmed in the code on agents main 1dc102c
before this request (item 5 by reading only). The designs now say what fab should do, each
fix marked "fixed 11-01"; build them as designed:

1. **An integration plan's retire works from main** (`docs/design/integration.md`
   3, "Retire waits for main"). Today the finish path (`fab/dispatch.py`
   `_take` "finish" → `_deliver` → `_merge_branch`) merges the retire call's
   branch into the already-landed trunk, and the retire call starts from the
   trunk (`fab/designer.py`, `calls.start(..., base=plan.trunk)`). Build: once
   the trunk has landed (`fab.integration.trunk_landed`), the retire call
   starts from `main` and its branch, and any other call of the plan
   delivered after that, is delivered as a queue plan's call is
   (`_deliver`'s queue-plan path; integration plans are fabrig's, so
   fabrig's queue), never merged into the trunk; and `_checkout`
   (`fab/dispatch.py`, given the log) detaches a plan checkout at
   `origin/main` once its trunk has landed, so the tick reads the retired
   plan.toml from main (the queue deletes the trunk branch when it lands it).
2. **The queue takes ready refs of any depth** (`docs/design/landing.md` 2).
   `fab.queue.candidates` (`fab/queue.py:49`) takes only two-segment names, so
   `ready/ladder/<draft>/backlog-<n>`, and a queue plan's `answers/<run>` and
   `repairs/<run>` (run ids hold slashes), are never taken. Live today:
   `ready/ladder/v0.1.0-ladder/backlog-1` has sat unlanded since 14:52Z. Build:
   two segments or more; check the rest of the queue (retire, record, import
   in `fab/dispatch.py` `_import_queue`) for the same assumption.
3. **A stop asks the answerer** (`docs/design/integration.md` 3, "A stop
   asks" and "The answerer judges a stop"). Today `fab.integration.next_step`'s
   `Step("stop", ...)` becomes a log note only (`fab/dispatch.py`
   `_integration`). Build:
   - `plan.stopped` and the stop's `question.asked` (task
     `<draft>/integration`, `park` true), logged when the trunk stops and
     none since the stop's last lift; none on merges while it holds;
   - `fab.foreman.questions` and the answer call's brief (`fab/calls.py`,
     `integration.with_repairs`) take that question though
     `<draft>/integration` is no task: it must never fold as one in
     `fab.state.fold` or count in `next_step`'s tasks; the answer call's
     `Answer <draft>/integration: <text>` line is logged as its
     `question.answered`, as a repair's is;
   - the lift: counts start afresh after that `question.answered` in
     `next_step`, `queue_step`, `catch_up_waiting` and `_catch_up_refusals`
     (its `merged` set too: a main sha's repair counts as merged only when
     it merged after the answer); repair ids keep counting; the answer is
     folded under Answers into the repairs not merged when it was logged
     and every later one (`repair_tasks`);
   - a clean catch-up after a `catch-up` stop logs the stop's
     `question.answered` (answer `lifted by a clean catch-up`, `by` `tick`);
   - `plan.stopped` joins no wake list (`fab/wake.py`): it changes no
     decision, and the question's answer call starts in the same round.
   No change to `fab/channel.py`, `fab/forge.py` or `fab/serve.py`: an answer
   call that cannot settle the stop ends `Question:`, an ask they already show.
4. **A rebase onto the trunk consumes the amendment** (`docs/design/integration.md`
   2, "Optimistic start"). `fab.call_review.task_rebase` (`fab/call_review.py`
   ~552) counts a completed rebase run only with base `origin/main`; an
   integration plan's runs log `origin/<trunk>`, so the rebase repeats forever.
   Build: compare with the plan's trunk (pass it in from `fab/dispatch.py`).
5. **An `Infra:` rerun starts when nothing was pushed** (`docs/design/tick.md`
   3). After an `Infra:` outcome the next start is kind `repair`
   (`fab.dispatch._start_kind`), and `fab.run.start` switches to
   `origin/<branch>` in both the slot and the worktree path, which a run that
   never pushed lacks. Found by code reading only. Build: fall back to the
   task's base when `origin/<branch>` is absent after the fetch.
6. **Status files current.** fab's status files still call built things
   skeletons: `docs/design/tick.status.md` ("The flow is a skeleton",
   "Several plans are a skeleton", "The buffer's order is a skeleton",
   "Events are a skeleton", "Design waits for implementation") and
   `docs/design/gates.status.md` ("Gates and the structure review are a
   skeleton", "Present: (nothing yet)"). Check each against the code on main
   (`fab/flow.py`, `fab/drafts.py`, `fab/buffer.py`, `fab/wake.py`,
   `fab/gates.py`, `fab/digest.py`, `fab.dispatch.decide`, `_check_calls`) and
   move what is built and wired into the tick to Present, in the files' style
   (what is there, where, since when if the log or git says), leaving under
   Gaps only what is not. Also record in the status files: `fab draft start`
   not built (`docs/design/tick.md` 7 now says so) and the gates on skeleton
   and contract tips (`docs/design/gates.md` 2, now designed).

Not in this request: units for `fab issues sync` and `fab report daily`
(agents/status and ops own the units); `fab draft start` itself.

The user's rule: dogfood. Built by fab's loop (this plan's tasks, landed
through `bin/fab land`); the plan's landing is `queue` (the cut is started
with `--set 'landing="queue"'`). Keep the plan small: the fixes are
independent of each other, each with its tests in `fab/tests/` (fakes and
fixture logs, as the touched modules' tests are).
