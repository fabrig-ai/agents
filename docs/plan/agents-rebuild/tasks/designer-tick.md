+++
id = "designer-tick"
part = "designer"
kind = "interface"
needs = ["designer", "flow", "tick-split", "call-review-tick"]
files = ["fab/dispatch.py", "fab/call_review.py", "fab/tests/test_dispatch.py", "fab/tests/test_call_review.py"]
effort = "high"
minutes = 50
+++
# The tick runs the designer's calls

After `designer`, the four calls run by hand. This task makes the tick
drive them:

- it starts a contract call for a contract part, and a retire call when
  every part is done;
- it ticks a plan directory that a cut is still writing;
- it skips a retired plan;
- it reviews a retire call with the consistency pass.

The plan's user questions hold back the parts they name. Update the
docstrings of every function you change to say what it now does. Design:
`docs/design/fab.md`, 13.3, 13.1 and 4.

`flow`, `tick-split` and `call-review-tick` all change `fab/dispatch.py`
and land first. The size gate holds every new or changed function to 60
lines; put new steps in private functions as `tick-split` does.

## What to build

- **`fab/call_review.py`:**
  - `REVIEWED` gains `fab.designer.ROLES`.
  - `brief` gains the keyword `designs: Sequence[str] = ()`. For a chain
    whose role is retire:
    - its first section is CONSISTENCY's text, in place of ROLE's;
    - after `# Your review` comes the section `# Designs changed since the
      plan started`, one line `- \`<path>\`` per design, or `(none)`.
  - `start` passes, for a retire chain, `designs =
    fab.designer.changed_designs(checkout, <draft>, rev=<tip>, sh=sh)`.
    The draft is the chain's subject before its last `/`. A ValueError
    there starts nothing, as a git failure does.
- **`fab.dispatch.decide`, step 4 (design):**
  - a part is eligible when `fab.state.part_statuses` calls it `not
    designed`, its needs meet `_design_action`'s existing rule (design 4:
    a need is `designed` or `done`; a `needs_landed` or probe need is
    `done`), and no question of `plan.questions` with an empty answer
    names it;
  - the open-question exclusion is the only change to that rule.
- **`fab.dispatch.call_actions`:**
  - Only chains of the plan's draft take steps: those whose subject is the
    draft or starts with `<draft>/`.
  - The design list's first fresh part that is not a contract gets a
    skeleton call when none is in flight, as now. Its first fresh contract
    part gets `Action("call", task=<part>, run_kind="contract")` when no
    contract call is in flight. Both may start in one tick.
  - Last, after the review: `Action("call",
    task=fab.designer.subject(<draft>, "retire"), run_kind="retire")` when
    all of these hold:
    - `fab.designer.retire_due(plan, tasks, events)`;
    - no retire call is in flight;
    - the subject is not parked;
    - no chain of the subject is open.
- **`fab.dispatch.tick`:**
  - **A plan being cut:** after the fetch, a PLAN_DIR without plan.toml
    ticks on `fab.designer.uncut(<PLAN_DIR's name>,
    fab.designer.repository(<checkout root>, sh=sh))` with no tasks, when
    the log holds a call.started with role cut and subject `<name>/cut`.
    Without one, it is a PlanError naming PLAN_DIR. Everything after
    loading runs as for any plan.
  - **A retired plan:** after loading, it prints `retired <draft>` and
    returns `[]`. There is no queue import and no action.
  - **The call action's argv:** `fab call <role>`, then the part for
    skeleton and contract, then `--plan PLAN_DIR`. Retire takes no part.
    The unit name is unchanged.
- `main --dry-run` handles a plan being cut and a retired plan as tick
  does.

## Acceptance

- `fab/tests/test_call_review.py`:
  - `chains` takes a cut, contract, decision and retire call as roots;
  - `brief` for a retire chain: CONSISTENCY's text and the designs
    section, in order;
  - `brief` for another role: unchanged, even when designs are given;
  - `start` for a retire chain passes the changed designs, with
    `fab.designer.changed_designs` patched.
- `fab/tests/test_dispatch.py`:
  - `decide` leaves out a part named by an open question, and designs it
    once the question has an answer;
  - `decide` still designs a part whose need is only designed, and holds
    one whose `needs_landed` need is only designed;
  - `call_actions`:
    - a contract call for a contract part;
    - a skeleton call and a contract call in the same tick;
    - no contract call while one is in flight;
    - a retire call when every part is done, and none while one is in
      flight, while its subject is parked, while its chain is open, or
      after one ended done;
    - another draft's chain takes no step.
  - `tick` with `support.FakeRunner`:
    - a plan being cut moves its cut chain (`fab.call_review.start`
      patched, `git remote get-url` scripted);
    - a PLAN_DIR with neither plan.toml nor a cut call fails;
    - a retired plan prints its line and runs nothing, not even the queue
      import;
    - the unit argv for contract and retire.
  - The existing tests pass, adjusted only where a fixture plan now needs
    `contract` or a question.
- `bin/fab test` passes. The touched test modules stay within their
  budgets.

## Options, settled up front

- An uncut plan's tick still imports the queue's records and measures the
  builders. It is the same code path, and both are cheap.
- `retire_due` does not look at chains or parked subjects. call_actions
  checks those for every call, so the retire start follows the same rule.
- A cut that ended with a question parks `<draft>/cut`. Its plan directory
  then ticks with nothing to do until `question.answered` names the
  subject.
- A contract call and a skeleton call count as different roles for "one
  call of a role in flight". 13.4 lifts the limit later.

## Answers

- 2026-10-31. Q: should design eligibility keep flow's dependency rule or
  require every need done? A: keep flow's rule (`docs/design/fab.md`,
  section 4: needs designed or done; `needs_landed` and probe needs done)
  and add only the open-question exclusion. The decide bullet and its
  acceptance line above are corrected to match; the existing eligibility
  tests stand unchanged.
