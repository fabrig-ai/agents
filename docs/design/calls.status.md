# calls status

2026-11-01. Contract: `docs/design/calls.md`. Split from `docs/design/fab.status.md`.

## Present

- **The designer's calls run at xhigh** (1; the user, 11-01; plan
  `docs/plan/designer-effort`, retired 11-01; 502d014). `fab.calls.EFFORTS`
  names `cut`, `contract`, `decision` and `retire` at `xhigh`, by name, since
  `fab/designer.py` imports `fab.calls`; a test over `designer.ROLES` fails a
  fifth role with no entry. `start` passes `role_effort(role)` to `claude_argv`.
  `EFFORT` stays `high` for the skeleton author, `amend` (a designer chain's
  too) and the structure reviewer; answer, reply, triage and settle stay
  medium. A cut's sub-agents are `integration.status.md`'s. Tested with fake
  runners (`test_calls.py` `test_role_effort_keeps_designers_above_other_claude_roles`,
  `test_cut_call_uses_xhigh_effort`). Not seen live: this plan's own retire ran
  at high (below) and no designer call has started since.
- **Held call chains go to settle** (2; 11-01, the user: second refusals are
  not the user's): a second refusal, failed amend or three infra reviews
  starts a report-only medium-effort `settle` call under the plan's answer
  limit. Land approves, amend resets review counts and carries guidance into
  later briefs, user parks with its reason; failed settlement parks. After
  amend, one final settlement permits only land or user. `chain.settled`
  closes older parked asks for forge sync; legacy automatic parks settle when
  their plan next ticks. Tested with temporary homes, fake runners and log
  folds; not run live.
- **A call whose brief cannot be compiled parks its subject** (2; the user,
  11-01; plan `docs/plan/start-commands`, retired 11-01; 580befa).
  `fab.dispatch._call` ends every role's argv with `--tick`, which
  `fab/calls.py`, `fab/designer.py` and `fab/triage.py` parse. Each `main`
  turns a ValueError or OSError from its brief builders into
  `fab.calls.BriefError` at its compile step only (`_compile_call`,
  `designer._compile`, triage's `brief`), after the preconditions; a
  `fab.sh.Failed` (`_retire_designs`' and `changed_designs`' git
  included) and `fab.calls.start` never park. With `--tick` and without
  `--brief-only`, `fab.calls.park` logs `call.parked` (subject, role,
  `brief failed: <first line>`, report "", `call` "", or for amend and
  settle the chain's root with the chain's subject) and then
  `wake.want("park <subject>")`. `_parked_subjects` adds open `parked`
  asks whose call is "", and `call_actions` checks it before triage;
  `fab.channel._log_asks` closes such an ask at a later `call.started` of
  its subject, chain parks untouched; `fab/forge.py` gives a report-less
  parked ask its reason alone, with no excerpt and no `Read:` line in the
  issue body or reply brief. Tested with temporary homes and fake runners
  (`test_calls.py`, `test_designer.py`, `test_triage.py`,
  `test_dispatch.py`, `test_channel.py`, `test_forge.py`); not seen live:
  hel8's log holds no `brief failed` park at the plan's retire.
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
  477b3e0, made every design changed in its window), dogfood-faults'
  (~156 KB, every changed design quoted, none listed) and mechanisms-out's
  (~144 KB, none listed).
- **`retired = true` is code's** (3; the user, 11-01; plan
  `docs/plan/mechanisms-out`, retired 11-01; b951d3f). `_take`'s `finish`
  runs `fab.dispatch._pre_deliver` before `_deliver`. For a retire chain it
  skips a branch a `branch.landed` names and one absent from origin after a
  fetch, reads `origin/<branch>`'s plan.toml (the path from the plan
  directory, as `_check_call` finds it; a missing file fails that `git show`,
  before `_retire_plan`'s own `missing plan.toml`) and, unless `tomllib` reads
  `retired` True, calls `fab.spec_edit.commit_path` on the call's branch from
  `origin/<branch>`, worktree `FAB_HOME/retire/<root>`, author fab, message
  `<draft>: retired`. `_retire_plan` replaces the top-level assignment however
  the `retired` key is spelled, inserts `retired = true` before the first table
  only when the key is absent, and refuses final text that does not parse with
  `retired` True (plan `docs/plan/edge-fixes`, retired 11-01; 32deb33). It
  finds the statement through `fab.designer._plan_header` and `tomllib`, so a
  multi-line value holding the text stays, and replaces the whole statement,
  so a trailing comment goes. `[retired]` and split dotted keys, which
  `load_plan` also refuses, raise inside the edit. A failure is `_take`'s
  note `finish <root> failed: ...`; the delivery not having run, `_take`'s
  `finally` records no `call.finished`, and the next tick tries again.
  `_queue_branch` reads origin's tip and readies again when it differs from
  the last `branch.ready`'s `tip`, beside the `call.ended` rule.
  `fab/roles/retire.md` says fab sets it and `fab/roles/consistency.md` no
  longer checks it. Tested with fake runners and fixture logs
  (`test_dispatch.py`, `test_retire_*`,
  `test_fabrig_queue_readies_moved_tip_without_later_call_end`). Live on this
  repository at three retires, each `<draft>: retired` by fab: precheck-starved
  (ab4e3ba), df-followups (7e143f7) and start-commands (18b5d7f), which it
  carried through three refusals at `rebase`. The key spelling and final
  validation cases have not run live. The re-ready is untried live: no fabrig
  retire has been delivered since.
- **`fab land` refusals, code first** (2; the user, 11-01; plan
  mechanisms-out; db47677). `_fold_review` skips `fab land`'s `fetch` and
  `push` refusals (no `queue_ts`), so they count toward no amend.
  `fab.call_review.land_tries(chain, events, step)`, pure and not a `Chain`
  field (the cut's decision 7), gives the refusals at that step on the branch
  since the later of `chain.latest`'s `call.ended`, a `call.answered` for the
  subject and this root's `chain.settled` amend, by log position, never by
  `tip`. `fab.dispatch._chain_actions` (which now takes `events` and `now`)
  asks `_land_action` for a chain's finish: `land-park` at `LAND_TRIES` (3) at
  either step, nothing within `LAND_AFTER` (10) minutes of either step's last
  refusal, otherwise the finish. `_land_park` logs `call.parked` (subject, the
  root as call, `fab land refused at <step> 3 times`, `report` the refusal's
  `log`); the fold then parks the chain, and an answer clears the count and
  lets the finish run at once. `fab.calls._amend_rebase` (from `_chain_call`
  before `amend_brief`, only when the chain's last refusal is a `fab land`
  `test`) fetches, detaches `FAB_HOME/amend/<root>` at `origin/calls/<root>`,
  rebases onto `origin/main` as fab, aborts a conflict (`conflicted`, nothing
  pushed) and otherwise pushes with
  `--force-with-lease=refs/heads/calls/<root>:<fetched tip>` (`rebased`),
  removing the worktree in a `finally`; `--brief-only` rebases nothing
  (`pending`). A failed fetch, rebase abort or push is `fab.sh.Failed`, which
  fails the amend's start without parking, and the next tick tries again.
  `amend_brief`'s `rebase` adds the outcome to `Findings`;
  `fab/roles/amender.md` is in step. Tested with fake runners and fixture logs
  (`test_call_review.py` `test_land_tries_*`, `test_calls.py`
  `test_main_test_refusal_amend_rebases_before_brief_and_start`,
  `test_dispatch.py`). Not seen live: at this retire hel8's log holds no `fetch`,
  `push` or `test` refusal of a call's branch since it landed, and no land
  park.
- **A direct queue plan's cut reads that its branch lands on main** (3;
  plan `docs/plan/dogfood-faults`, retired 11-01; 7a8eeea):
  `fab/roles/cut-direct.md`, which `fab.designer._cut_role_options` gives
  only direct queue plans (a direct integration plan gets `cut-run.md`),
  says a spec's base is main's tip once its needs have landed and that the
  branch lands on main once reviewed (this repository through `bin/fab
  land`, fabrig through its queue); it said the branch merged into the
  trunk.
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
- **One task set for answers** (2; plan `docs/plan/answer-findings`,
  retired 11-01; d4c2145): `fab.calls.answer_tasks(plan, tasks, events, *,
  folded=None)` is `integration.with_repairs` (for any plan; it adds
  nothing without check runs), the loaded `fix.FIX_KINDS` tasks dropped,
  then `tier_reds.tasks` (reusing the round's `folded` reds) and
  `fixes.tasks`. Its callers: `fab/dispatch.py` `_tick_loaded` (over
  `specs.checked_tasks`), `main`'s dry run, and `fab/calls.py` `main`'s
  answer brief. Until then the brief's set lacked `fixes.tasks`, and on
  fabrig's `v0.1.0-ladder` (11-01, from 15:26Z) the tick started an answer
  call about once a minute, each ending `Done: 0` with an empty brief,
  while finding-4's and finding-5's questions waited. The answer's path
  needed no change: `_finish` logs `Answer <draft>/finding-<n>:` as its
  `question.answered` and `fixes.tasks` folds it under `## Answers`.
  Tested with temporary homes and fake runners (`test_calls.py`
  `test_answer_tasks_*`, `test_answer_includes_ladder_finding_question_and_repair_body`;
  `test_dispatch.py` `test_finding_answer_*`); not yet seen live on the
  ladder plan.
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
  or auth) leaves the refusal open for its retry (`fetch` and `push`
  above); `test_dispatch.py`'s
  `test_finish_land_refusal_steps_and_terminal_exceptions` holds 0, 1, 2
  and 128. `fab/roles/settle.md` says land is not an option when the brief
  says it would land a tip `fab land` refused; `fab/roles/amender.md`
  rebases onto `origin/main` at `rebase`, and at `test` only when the brief
  says that rebase conflicted, then force-pushes with lease. Tested with
  temporary homes, fake runners and log folds. Live once, at `rebase`
  (start-commands' retire, 11-01): refused at 18:19:36Z, amended, refused
  again at 18:21:45Z, held, settled amend at 18:23:05Z, refused and amended
  once more, landed at 18:25:30Z (18b5d7f) with `call.finished` done.

## Gaps and departures

- **A designer's surveys are role text, in two roles** (1; designer-effort):
  a sub-agent's `model` and `effort` are what `cut-run.md` and `cut-direct.md`
  say, and `test_cut_roles_set_claude_survey_and_designer_efforts` pins those
  words only; nothing checks what a call starts, and `call.started` logs no
  effort. `opus` is the Agent tool's alias, not `fab.calls.MODEL`'s explicit
  id. `cut-run.md` says read-only but names no agent type, where
  `cut-direct.md`'s Explore is read-only by definition. `cut.md`,
  `cut-fabrig.md`, `contract.md`, `decision.md` and `retire.md` say nothing of
  surveys (the request: "No other role changes"), so 1's line reaches only
  the cuts those two texts serve (5).
- **A `fab land` refusal amended from its own heading** (2, 11-01): the
  amender's rebase at `rebase` (and at `test` after a conflicted
  `_amend_rebase`), its `--force-with-lease` push
  and a retire's listed designs are role text (`fab/roles/amender.md`), not
  checked by code; settle's refusal to land a refused tip is role text too
  (`fab/roles/settle.md`), which `_judge_chain` enforces by parking a land
  verdict with `settle failed`; a
  failing `git fetch` in `_retire_designs` fails the amend's start without
  parking (a git failure is not a brief's, 2), and the next tick tries
  again.
- **A `fab land` park's report is the log's text, not a path** (2, channel.md
  2; mechanisms-out): the request and 2 say "the refusal's log as report", and
  `_land_park` does that, but `fab land`'s `log` is the output's text while
  every other `call.parked`'s `report` is a path. `fab/channel.py` and
  `fab/forge.py` read it as one, so the page says `(report missing)` under the
  reason, with the text in its `- Read:` line (reproduced with a temporary
  home); the issue likewise. The reason and the log still reach the user.
  `test_dispatch.py`'s fixture uses `refusal.log`, a path, so it does not
  show this (5).
- **A `fetch` or `push` retry waits for a tick** (2): nothing wakes the tick
  at `LAND_AFTER`. `_land_action` only holds the finish back until a round at
  or after it, so with no other wake the backstop's ten minutes can make the
  wait nearly twenty (5).
- **A call from main can start behind main** (3, seen at mechanisms-out's
  retire and acceptance-fixes', whose worktree, inventory and diffs were
  32deb33 with its second part, ad63a0c, landed 28 s before the brief; the
  call fast-forwarded by hand; 5): `fab.calls.start` fetches first only for a report-only call, a
  supplied branch, fabrig or a base other than main. `land-code-first` landed
  at 18:26:21Z, the retire's `call.started` is 18:26:22Z, and its worktree and
  inventory were 18b5d7f, one commit behind: no `land_tries`, and `amend_brief`
  without `rebase`. The call brought itself to `origin/main` by hand; a retire
  that trusted its brief would have called the part unbuilt. Seen again at
  edge-fixes' retire (11-01): `retire-spelling` landed as 32deb33 at 19:11:55Z,
  the brief is 19:12:24Z, and its worktree and inventory were 717f4d5, one
  commit behind, so it showed the old `_retire_plan` and no calls.md diff for
  a part it called done. The call fast-forwarded by hand. Seen again at
  citation-sweep's retire (11-01): its worktree and inventory were 15a7d55,
  one commit behind its only part, 032cb12, and `changed_designs` on the stale
  ref listed no designs, though that commit changed `qa.status.md`. The call
  fast-forwarded by hand. Seen again at designer-effort's retire (11-01):
  `effort` landed as 502d014 at 21:21:44Z and the retire started in that tick's
  round, its worktree and inventory e95ef79, one commit behind; the call
  fast-forwarded by hand. The same window holds the code: the install follows
  main at the next tick (machines.md, "Following main"; 21:21:47Z here), so
  this `fab call retire` ran the old `EFFORTS`, `claude --effort high`, not the
  xhigh its plan had just landed.
- **Retire's changed designs are main's window, not the plan's** (3,
  11-01, seen at paper-cuts' retire): `changed_designs` takes every design
  a commit on main changed since the cut's parent. paper-cuts' designs
  (calls.md 3, integration.md 4) landed before its cut (9842398),
  so its brief quoted neither, and quoted machines.md and tick.md,
  which another session's builder-install work changed meanwhile. The
  retire call found its own designs from plan.toml's `design` fields.
  Seen again at dogfood-faults' retire (11-01): its brief quoted calls.md,
  fab.md, machines.md and reports.md, which mechanisms-out and hel8-units
  changed, and channel.md, which the plan changed and restored, beside the
  four it changed (gates, integration, landing, tick). Seen again at
  start-commands' retire (11-01): the designs it built against (calls.md 2,
  integration.md 3, tick.md 5) were written before its cut (de5edc2,
  1fc8818), so its brief quoted none of them, and quoted integration.md
  and landing.md, which df-followups and precheck-starved changed. Seen
  again at mechanisms-out's retire (11-01): calls.md 2 and 3 and
  integration.md 3 were written before its cut (f2d3ddb to f380344, 0a3a84e),
  so the seven designs its brief quoted carried only other plans' diffs.
  Seen again at edge-fixes' retire (11-01): of its three designs, fab.md's
  diff is d6fc657's and landing.md's is acceptance-fixes'. Seen again at
  designer-effort's retire (11-01): calls.md 1, integration.md 3 and tick.md 7
  changed with the request (3e9e59f), before its cut, so its brief quoted none.
  Code and design agree; the gap is with the role's "the designs this plan
  changed" (5, Later).
- **The request's third spelling is a reading** (3; plan
  `docs/plan/edge-fixes`): `inputs/request.md` lists `"retired"`, `'retired'`
  and `"retired"`, the first and last the same bytes. The cut took the third
  for a unicode escape a tool layer decoded (`notes/decisions.md` 6), and
  `test_retire_key_spellings_preserve_complete_plan` covers the bare key, both
  quotings and `"r\u0065tired"`. The request does not say so.
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
