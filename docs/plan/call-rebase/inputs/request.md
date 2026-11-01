# Request: a call's branch refused at rebase

From the user, 2026-11-01 (via the session fab-landing-queue-concurrency):
"repair any paper cut you found". Build `docs/design/calls.md` section 2's
bullet **A `fab land` refusal counts as a refusal of the chain**, as
designed: the tick's finish path (`fab/dispatch.py`: no `call.finished` when
`fab land` refuses a call's branch, at any step), the amend brief's heading and
the retire's extra designs (`amend_brief` and `_findings` in
`fab/call_review.py`, the design list computed in `_chain_call`,
`fab/calls.py`, and passed in), the hold reason, its settle briefs and
`_judge_chain`'s land verdict on it (`fab/call_review.py`, `fab/dispatch.py`),
and the amender's role text (`fab/roles/amender.md`) for a rebase. The chain
fold already counts the refusal.

The user's rule: dogfood. Built by fab's loop (this plan's tasks, landed
through `bin/fab land`). Small work: keep the plan small. The plan's landing
is `queue` (the cut is started with `--set 'landing="queue"'`).
