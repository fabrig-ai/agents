+++
id = "fabrig-calls-land"
part = "fabrig-calls"
kind = "feature"
needs = ["plans-tick", "repairs-tick", "foreman-tick"]
files = ["fab/dispatch.py", "fab/call_review.py", "fab/foreman.py", "fab/repairs.py", "fab/tests/test_dispatch.py", "fab/tests/test_call_review.py", "fab/tests/test_foreman.py", "fab/tests/test_repairs.py"]
effort = "high"
minutes = 60
+++
# A fabrig plan ticks, and its calls, answers and repair sections land through fabrig's queue

docs/design/fab.md 13.11 ("A fabrig plan" and "Its calls land through
fabrig's queue"). Today every call branch, answer branch and repair-section
branch lands through `fab land`, which serves this repository only.

## What to change

- A fabrig plan loads and ticks: a plan directory nested in a fabrig
  checkout (`skein/docs/plan/<draft>` in `FAB_HOME/repos/fabrig`), listed in
  `FAB_HOME/plans` beside this repository's plan; one fetch per checkout;
  its tasks start in slots and are readied as now.
- A plan whose repo is readied through the queue (`fabrig`): an approved
  chain's branch is readied (push `ready/<branch>` from the fabrig clone,
  log `branch.ready`), not landed with `fab land`; `call.finished` (and an
  answer chain's `question.answered`) is logged once the queue's imported
  record says the branch landed. The queue import must import `calls/`,
  `answers/` and `repairs/` branches of the plan's draft, not only task
  branches.
- A queue rejection of a call's branch counts as a refusal in the chain's
  fold (`fab/call_review.py`): an amend call quoting the queue's failing
  step once, then `call.parked`.
- The foreman's answers and repair sections for a fabrig plan's specs:
  commit on `answers/<run>` or `repairs/<run>` in the plan's checkout, push
  and ready them; log `question.answered` or `refusal.settled` when the
  branch lands, and keep the question or refusal at its current state until
  then, so a later tick neither reruns the task early nor commits twice.
- This repository's plans keep `fab land` unchanged.

## Acceptance

- Tests with the fake runner and hand-built events: a fabrig plan nested in
  a checkout loads beside an agents plan; an approved fabrig skeleton chain
  readies and finishes only after the imported landing; a queue rejection
  starts one amend call, a second parks; a fabrig answer and a fabrig fix
  section are readied and recorded on landing; agents plans unchanged.
- `bin/fab test` passes within the 30 s budget.
