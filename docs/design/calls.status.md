# calls status

2026-11-01. Contract: `docs/design/calls.md`. Split from `docs/design/fab.status.md`.

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
- **Report-only calls** (2; qa.md 2, plan findings-loop, retired
  11-01): `fab.calls.start(report_only=True)` detaches a worktree at
  `origin/<base>`, logs no branch and pushes nothing; `settle` and the
  `triage` call (`fab call triage --plan PLAN_DIR`, `fab/triage.py`,
  `fab/roles/triager.md`, effort medium, outside
  `fab.call_review.REVIEWED`) run so. The tick starts triage when
  `fab.triage.due` holds and records its decisions from the report.
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
  retire (11-01, ~106k characters, every design quoted, none listed), and
  findings-loop's (~194 KB with six designs listed; ~404k quoted whole),
  and findings-repair's (~195 KB, eleven listed: the designs' rename,
  477b3e0, made every design changed in its window).
- **The tick drives the calls of 2 and 3:** call reviews and amend calls
  (`fab/call_review.py`), the foreman's answers (`fab/foreman.py`), the
  refusal foreman's repairs and rebases (`fab/repairs.py`,
  `fab/spec_edit.py`), and the designer's contract and retire calls, a
  retire chain reviewed by the consistency pass (`fab/designer.py`,
  `fab/roles/consistency.md`); the tick skips a retired plan and ticks a
  plan being cut. Until 11-01 these lines still called them skeletons.
- **The foreman reads a QA finding** (2, qa.md 2; plan findings-repair,
  retired 11-01): `fab/fixes.py` and `fab/roles/foreman-finding.md`, the
  red foreman's form through `fab/fix.py`; its fix makes the specless
  `<draft>/finding-<n>`, whose questions skip the foreman and queue for
  the answerer as a red task's do.
- **A `fab land` refusal counts as a refusal of the chain** (2; plan
  `docs/plan/call-rebase`, retired 11-01; baaf496, ab3a6d5; its acceptance
  fixes by plan `docs/plan/call-rebase-fixes`, retired 11-01; bb8b86b,
  c99a936). The tick's
  finish (`fab/dispatch.py`, `_finish_outcome` through `_record_finish`)
  logs no `call.finished` when `fab land` logged a `branch.rejected` for
  the branch during it, at any step; it logs done for a branch a
  `branch.landed` already names (running `_finish`), failed for a `fetch`
  refusal whose branch `git ls-remote --exit-code` reports absent (exit 2),
  and failed, as before, when nothing was logged. Fabrig and integration
  plans keep their path. `fab.call_review.land_refusal` tells `fab land`'s
  record (no `queue_ts`, a step in `LAND_STEPS`) from queue and trunk
  rejections; the amend brief heads it `` `fab land` refused at <step> ``
  with the log, and a retire's amend (`_retire_designs`, `fab/calls.py`)
  lists the designs changed at `origin/main` and not at `origin/<branch>`.
  The hold's reason is `LAND_HOLD`; its settle brief allows amend or user,
  then user only, and `_judge_chain` parks a land verdict on it with
  `settle failed`. Any other `ls-remote` code (0, 1, or 128 for network
  or auth) leaves the refusal open for its amend; `test_dispatch.py`'s
  `test_finish_land_refusal_steps_and_terminal_exceptions` holds 0, 1, 2
  and 128. `fab/roles/settle.md` says land is not an option when the brief
  says it would land a tip `fab land` refused; `fab/roles/amender.md`
  rebases onto `origin/main` at `test` as at `rebase` before it reproduces
  and fixes what the log names, then force-pushes with lease. Tested with
  temporary homes, fake runners and log folds; not yet run live.

## Gaps and departures

- **A `fab land` refusal amended from its own heading** (2, 11-01): the
  amender's rebase at `rebase` and `test`, its `--force-with-lease` push
  and a retire's listed designs are role text (`fab/roles/amender.md`), not
  checked by code; settle's refusal to land a refused tip is role text too
  (`fab/roles/settle.md`), which `_judge_chain` enforces by parking a land
  verdict with `settle failed`; a
  failing `git fetch` in `_retire_designs` fails the amend's start like
  any brief that cannot be compiled (5, its first bullet).
- **Retire's changed designs are main's window, not the plan's** (3,
  11-01, seen at paper-cuts' retire): `changed_designs` takes every design
  a commit on main changed since the cut's parent. paper-cuts' designs
  (calls.md 3, integration.md 4) landed before its cut (9842398),
  so its brief quoted neither, and quoted machines.md and tick.md,
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
  runnable in the fold, even after it has landed. channel.md 2 names subjects
  apart from tasks (`call.answered`); until `channel-tick` lands, a
  subject still unparks on a `question.answered` naming it, and call
  questions are answered that way by hand.
