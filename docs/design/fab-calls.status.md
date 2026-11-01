# fab-calls status

2026-11-01. Contract: `docs/design/fab-calls.md`. Split from `docs/design/fab.status.md`.

## Present

- **Held call chains go to settle** (2; 11-01, the user: second refusals are
  not the user's): a second refusal, failed amend or three infra reviews
  starts a report-only medium-effort `settle` call under the plan's answer
  limit. Land approves, amend resets review counts and carries guidance into
  later briefs, user parks with its reason; failed settlement parks. After
  amend, one final settlement permits only land or user. `chain.settled`
  closes older parked asks for forge sync; legacy automatic parks settle when
  their plan next ticks. Tested with temporary homes, fake runners and log
  folds; not run live.
- **Retire's brief is bounded** (3, 11-01): built by plan
  `docs/plan/paper-cuts` (`retire-diffs`, 38f8e66, landed 13:16Z).
  `fab.designer.plan_start` and `design_diff` sit beside `changed_designs`,
  whose paths and signature are unchanged; `retire_brief` (now with `rev`
  and `sh`) quotes each changed design as the shorter of its diff and its
  text with status file at rev, fills in path order within `BRIEF_LIMIT`
  less the other sections and one list line reserved for every changed
  design up front (the cut's decision 3: no second pass, a few hundred
  characters of budget lost), and lists the rest under `Did not fit:`.
  `fab/roles/retire.md` says designs come as diffs or text and that it
  reads a design whole when it needs more. Tested against real git
  repositories (`fab/tests/test_designer.py`). Live once: paper-cuts' own
  retire (11-01, ~106k characters, every design quoted, none listed).
- **The tick drives the calls of 2 and 3:** call reviews and amend calls
  (`fab/call_review.py`), the foreman's answers (`fab/foreman.py`), the
  refusal foreman's repairs and rebases (`fab/repairs.py`,
  `fab/spec_edit.py`), and the designer's contract and retire calls, a
  retire chain reviewed by the consistency pass (`fab/designer.py`,
  `fab/roles/consistency.md`); the tick skips a retired plan and ticks a
  plan being cut. Until 11-01 these lines still called them skeletons.

## Gaps and departures

- **Retire's changed designs are main's window, not the plan's** (3,
  11-01, seen at paper-cuts' retire): `changed_designs` takes every design
  a commit on main changed since the cut's parent. paper-cuts' designs
  (fab-calls.md 3, fab-integration.md 4) landed before its cut (9842398),
  so its brief quoted neither, and quoted fab-machines.md and fab-tick.md,
  which another session's builder-install work changed meanwhile. The
  retire call found its own designs from plan.toml's `design` fields.
  Code and design agree; the gap is with the role's "the designs this plan
  changed" (5, Later).
- **Designs a retire brief lists are read by the call** (3, 11-01), as the
  cut's design index names designs the cut reads itself: a departure from
  `execution-modes.md`'s "compiled by code" only for what the budget leaves
  out.
- **Claude calls** are made by the tick (skeleton, review, amend, answer);
  the cut still starts by hand.
- **The foreman is read-only by design, not by the model:** the model
  lists the foreman without read-only; 2 makes it read-only, and code
  writes its answers and sections into the spec. A plan whose specs live
  outside this repository cannot be settled by its foreman yet (5).
- **Subjects can share a task's id:** a skeleton call's subject
  `<draft>/<part>` equals the id of a task named after its part (`gates`).
  A `question.answered` that unparks the subject also makes that task
  runnable in the fold, even after it has landed. fab-channel.md 2 names subjects
  apart from tasks (`call.answered`); until `channel-tick` lands, a
  subject still unparks on a `question.answered` naming it, and call
  questions are answered that way by hand.
