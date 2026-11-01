# fab-calls status

2026-11-01. Contract: `docs/design/fab-calls.md`. Split from `docs/design/fab.status.md`.

## Present

- (nothing yet)

## Gaps and departures

- **Claude calls** are made by the tick (skeleton, review, amend, answer);
  the cut still starts by hand.
- **The review of calls' output is a skeleton:** `fab/call_review.py`
  (chains, the review run's brief and start, the amend brief) and
  `fab.run.fetch_clone` and `fab.run.launch` hold 2's contracts.
  `fab/roles/call-reviewer.md` and `fab/roles/amender.md` are written. The
  task `call-review` fills them; `call-review-tick` makes the tick review
  calls' branches and run amend calls, after `review-call` and
  `gates-tick`. Until it lands, a call's branch lands unreviewed.
- **The foreman is a skeleton:** `fab/foreman.py` (where each question
  stands, the foreman run's brief and start, the answer written into the
  spec) and `fab.run.launch_detached`, the read-only start review and
  foreman runs share, hold 2's contracts; `fab/roles/foreman.md` is
  written. The task `foreman` fills them, after `call-review`;
  `foreman-tick` sends questions to the foreman from the tick, after
  `call-review-tick`. Until it lands, every question waits for the
  answerer. Answers land through `fab land`, so a plan whose specs live
  outside this repository cannot be settled by its foreman yet.
- **The foreman's repairs are a skeleton:** `fab/repairs.py` (where each
  open refusal stands, the refusal foreman's brief and start, its verdict,
  the `## Repair` or `## Rebase` section written into the spec),
  `fab/spec_edit.py` (a spec changed on a branch to land, which
  `fab.foreman.commit` is to use), `fab.run.excerpt` and
  `fab.run.refusal_text`, and `fab.dispatch.repair_actions` hold 2's
  contracts; `fab/roles/foreman-repair.md` is written. The task `repairs`
  fills the modules; `repairs-tick` makes the tick start refusal foremen,
  act on their verdicts, hold a refused task's repair run until its foreman
  has decided, and carry the section into that run's brief. Until it lands
  the dispatcher starts rebase and repair runs on the refused task itself,
  with the refusal alone. The model lists the foreman without read-only;
  2 makes it read-only, and code writes its answers and sections into
  the spec.
- **Subjects can share a task's id:** a skeleton call's subject
  `<draft>/<part>` equals the id of a task named after its part (`gates`).
  A `question.answered` that unparks the subject also makes that task
  runnable in the fold, even after it has landed. fab-channel.md 2 names subjects
  apart from tasks (`call.answered`); until `channel-tick` lands, a
  subject still unparks on a `question.answered` naming it, and call
  questions are answered that way by hand.
- **The designer's calls are a skeleton:** `fab/designer.py` holds 3's
  briefs, the changed-designs and retire checks and `fab call cut|contract|
  decision|retire`; `fab.state.part_statuses` and the plan's `contract`,
  `retired` and `[[question]]` fields are declared but not read yet. The
  role texts `cut.md`, `contract.md`, `decision.md`, `retire.md` and
  `consistency.md` are written. The task `designer` fills the module, the
  plan's fields and the commands; `designer-tick` makes the tick start
  contract and retire calls, tick a plan being cut, skip a retired plan and
  review a retire call with the consistency pass. Until then every part is
  designed by a skeleton call, and plans are cut by hand.
