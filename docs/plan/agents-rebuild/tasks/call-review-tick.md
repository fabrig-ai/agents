+++
id = "call-review-tick"
part = "call-review"
kind = "interface"
needs = ["call-review", "review-call", "gates-tick"]
files = ["fab/calls.py", "fab/dispatch.py", "fab/tests/test_calls.py", "fab/tests/test_dispatch.py"]
effort = "high"
minutes = 45
+++
# The tick reviews every call's branch before it lands it

Today `fab.dispatch.call_actions` finishes every call that ended done by
landing its branch. From this change on, a skeleton, answer or review call's
branch lands only after a read-only Codex review run approves it. A refusal
starts one amend call on the same branch. A second refusal parks the call's
subject until `question.answered` names it. The chains and their states are
`fab.call_review.chains` (filled by `call-review`); this task drives them
from the tick and lets `fab call` run the amend call. Update the docstrings
of every function you change to say what it now does. Design:
`docs/design/fab.md`, 13.1 and 12; the events in section 3.

## What to build

- **`fab/calls.py`:**
  - `ROLES` gains `"amend": fab.call_review.AMENDER`.
  - `start` gains keywords `branch: str | None = None` and
    `amends: str | None = None`. With a branch, it first runs `git fetch
    origin` in repo, then `git worktree add -B <branch> <worktree>
    origin/<branch>` in place of the new branch from origin/main. With
    amends, call.started carries `amends`. Everything else is unchanged:
    the call's own id, directory and report.
  - `main` takes `fab call amend ROOT --plan PLAN_DIR [--brief-only]`. The
    chain is `fab.call_review.chains(events)[ROOT]`; an unknown root, or a
    state other than amend, is a ValueError (exit 1). The brief is
    `fab.call_review.amend_brief`. The call runs with subject the chain's
    subject, branch the chain's branch and amends the root.
- **`fab.dispatch.call_actions`:** the finish of every done call is
  replaced by one step per chain of `fab.call_review.chains(events)`, in
  its order, before any call start:
  - review: `Action("vet", task=<root>, run=<latest>, branch=<branch>,
    run_kind=<role>)`;
  - approved: `Action("finish", task=<root>, run=<latest>,
    run_kind=<role>, branch=<branch>)`;
  - amend, when no amend call is in flight: `Action("call", task=<root>,
    run_kind="amend")`;
  - hold: `Action("hold", task=<subject>, run=<root>, detail=<reason>)`;
  - the other states: nothing.
  A subject with a chain that is not finished starts no call. No answer
  call starts while an answer chain is open, and no review call while a
  review chain is open. Skeleton parts are already left out once their
  call ended done.
- **`fab.dispatch.tick`'s take:**
  - vet: the builder is the one with most free places
    (`places(hosts, in_flight(log.read()))`, ties by name). A builder at
    no free place is still taken, since a review run builds nothing; no
    builder at all is a failed action. Start the run with
    `fab.call_review.start(chain, plan.repo, <the checkout root>, host,
    log.read(), sh=sh, log_path=log_path)`, the chain recomputed from the
    log.
  - hold: log `call.parked` (call the root, subject, reason, report: the
    path in the run.ended of the chain's last refusal, or "").
  - call with run_kind amend: run `fab call amend <root> --plan PLAN_DIR`
    in its unit, as any call.
  - finish: lands the branch as today. For a chain whose role is answer,
    it logs question.answered from the `Answered:` line of the latest
    call's report, else of the root's (FAB_HOME/calls/<call>/report.md).
    call.finished names the latest call.
  - Collect needs no change: review runs are run.started records, and
    decide collects them as any run in flight.

## Acceptance

- `fab/tests/test_dispatch.py` (`CallActionsTest` and the tick tests):
  - each chain state's action;
  - no amend call while one is in flight;
  - no answer call while an answer chain is open, and one once it is
    finished;
  - no review call while a review chain is open;
  - the steps come before the call starts.
  - In tick, with `support.FakeRunner` and patched `fab.call_review.start`
    and `fab.land.main`, check that:
    - vet takes the builder with most free places, even at none;
    - hold logs call.parked once (the next tick sees parked);
    - the amend unit's argv is right;
    - finish of an answer chain reads the amend call's `Answered:` line;
    - a call that ended done is no longer landed without its review.
- `fab/tests/test_calls.py`: `start` with a branch (the fetch, `worktree
  add -B`, `amends` in call.started); `main amend --brief-only` for a chain
  in state amend, and its refusal for one in another state.
- `bin/fab test` passes; the touched test modules stay under a second each.

## Options, settled up front

- `gates-tick` lands first, so this branch is gated. `fab.dispatch.tick`
  and its nested `take` are over 60 lines, so this change splits them:
  each action's body becomes a private module-level function, and each new
  or changed function stays within 60 lines (`fab.calls.start` too).
- `Action.kind`'s comment lists the new kinds vet and hold.
- The kind is `interface` because `fab.calls.start` gains keywords; no
  existing caller changes.
