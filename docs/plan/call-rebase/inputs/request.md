# Request: a call's branch refused at rebase

From the user, 2026-11-01 (via the session fab-landing-queue-concurrency):
"repair any paper cut you found". Build `docs/design/calls.md` section 2's
bullet **A `fab land` refusal counts as a refusal of the chain**, as
designed: the tick's finish path (`fab/dispatch.py`: the step of the refusal
`fab land` logged; no `call.finished` for rebase, test, paths, fetch or push;
fetch and push retried), the amend brief's heading and the retire's extra
designs (`fab/calls.py`), the hold reason and its settle brief
(`fab/call_review.py`), and the amender's role text (`fab/roles/amender.md`)
for a rebase. The chain fold already counts the refusal.

The user's rule: dogfood. Built by fab's loop (this plan's tasks, landed
through `bin/fab land`). Small work: keep the plan small. The plan's landing
is `queue` (the cut is started with `--set 'landing="queue"'`).
