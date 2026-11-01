# integration status

2026-11-01. Contract: `docs/design/integration.md`. Split from `docs/design/fab.status.md`.

## Present

- **Drafts beside each other** (4, 11-01): built by fab's loop as plan
  `docs/plan/trunk-overlaps` (four tasks, landed 12:09-12:27Z): the overlap
  probe (`fab/overlaps.py`, its cache, its call after every plan ticks), the
  page's `overlaps` panel, and the cut brief's `Drafts beside this one`.
  Untried live: no integration plan with `ready` runs yet, so no
  `trunks.overlap` has been logged. Retired by hand: its retire call's brief
  exceeded `BRIEF_LIMIT` (fab.md and fab.status.md, ~216k characters before
  the split).
- **The overlap probe's paper cuts** (4, 11-01, from its acceptance review):
  built by plan `docs/plan/paper-cuts` (landed 13:13-13:19Z). The cache
  holds `trees`, `pairs` and `conflicts` (a conflicting catch-up is not
  merged again while nothing moved), reads the first format without
  `conflicts`, keeps only the keys a probe looked up or stored, drops a
  tree a failed pair used, and is written only when it changed
  (`overlaps-cache`, 048cabd). `fab.overlaps.well_formed` is the one rule
  for a `trunks.overlap` record; `is_news`, `open_pairs` and through it
  `gone_pairs` and the page's `_public_overlaps` read only well-formed
  records, and `fab/serve.py` did not change (`overlaps-records`,
  1f8666b). `fab/tests/test_overlaps_git.py` runs the probe on real git
  (`git_pair()`): two trunks off main with a conflicting path holding a
  space, main moved ahead, the path logged; a planted cached tree missing
  from the object store is a failure, not an overlap (`overlaps-git`,
  08afbf7). The checkout wording of 4 was matched to the code with the
  design.
- **Every call works from main once the trunk has landed** (3, "It then
  works from main"; plans `docs/plan/dogfood-faults`, retired 11-01, 600f5a4,
  and `docs/plan/df-followups`, retired 11-01, 009d591):
  `fab.integration.call_base` is `main` for an integration plan once
  `trunk_landed` (this draft's queue `branch.landed` for
  `<draft>/integration`), else `plan.trunk`; `fab.designer.main` (every
  role, the retire among them), `fab.calls.main` (skeleton, answer, review,
  amend, settle), `fab.triage.main`, and `fab.dispatch`'s `_start` (tasks),
  `_foreman` and `_examine` (refusal repairs) start from it, a fix kind
  keeping `main`.
  `fab.dispatch._integration` returns after `_lift_catch_up` once the trunk
  has landed, before any `_contains` or `rev-parse` of `origin/<trunk>`, so
  the tick logs no `failed:` note for the gone trunk. `fab.dispatch._deliver`
  merges into the trunk only until then, after which a call's branch goes
  through the queue plan's path (`_queue_branch` for fabrig); `_checkout`,
  given the round's events, detaches the plan checkout at `origin/main` on
  every fetch once the landing is logged, and fast-forwards to the upstream
  otherwise. Departure: `_checkout` runs before the plan loads, so it takes
  the draft from the plan directory's name (`docs/plan/<draft>`, as every
  plan's is) rather than `trunk_landed`'s `plan.draft`. Tested with fake
  runners and fixture logs (`test_integration.py`, `test_designer.py`,
  `test_calls.py`, `test_triage.py`, `test_dispatch.py`).
- **A stop asks the answerer** (3, "A stop asks" and "The answerer judges a
  stop"; plan dogfood-faults; 6e03edc, 4962fb5, feb2272):
  `fab.integration.stopped` gives the `plan.stopped` (`why` `red`,
  `catch-up` or `queue`, `report` the last red check's report, the gate's
  `<host>:<log>` or "" with the refusal's findings, at most 20 lines, in
  the text) and its parked `question.asked` (`run` the red check's or ""),
  once since the last lift; `fab.dispatch._integration` logs them. `lifted`
  is the last `question.answered` for `<draft>/integration`: `next_step`'s
  end reds, `catch_up_waiting`, `_catch_up_refusals` (its `merged` set
  cleared too) and `queue_step`'s rejections count from it; repair ids
  count on. `_repair_answers` folds an answer not by `tick` into every
  repair not merged when it was logged. `fab.dispatch._lift_catch_up` logs
  `lifted by a clean catch-up` (`by` `tick`) when `catch_up_lifts`.
  `fab.foreman.questions` takes the stop's question with no task (specless,
  queued); `fab.calls._answer_questions` attaches the `plan.stopped`'s
  report and `answer_brief` shows `Question: <draft>/integration (stop)`
  with no spec, its `Report:` line `(none: the findings are quoted below)`
  when the stop's report is "" (df-followups, 56bd6f9); `fab/roles/answerer.md` has the request's sentence.
  `plan.stopped` joins no wake list (`question.asked` is in `wake.AGAIN`).
  Tested with fixture logs (`test_integration.py`, `test_dispatch.py`,
  `test_foreman.py`, `test_calls.py`).
- **The start commands** (3, "The plan lives on its trunk"; the user,
  11-01; plan `docs/plan/start-commands`, retired 11-01; c7c8fa6,
  e2eebfa). `fab trunk make PLAN_PATH [--base REV]` (`fab/trunk.py`,
  `make`): after `fetch --prune` of `FAB_HOME/repos/fabrig` it refuses a
  PLAN_PATH that is not a relative `<prefix>docs/plan/<draft>` (and, beyond
  the design, one with a `..` part), a `plan.toml` at REV, an origin or
  local `<draft>/integration` and an occupied worktree path (a dangling
  symlink included); then `worktree add -b`, the push with the empty lease
  and `-u`, the worktree and branch removed on any push failure, and
  `trunk.made` (draft, base, tip) last; it prints the plan directory.
  `fab plan inputs PLAN_DIR FILE... [--replace]` (`fab/inputs.py`, `add`):
  the refusals of 3 before any commit; a temporary worktree detached at
  `origin/<trunk>`, removed in a `finally`; the commit `<draft>: inputs`
  by fab; the push per checkout kind (the trunk fast-forward only, this
  repository's `inputs/<draft>` through `fab.land.main`, deleted on a
  refusal naming the logged step, fabrig's `ready/inputs/<draft>`, which
  `--replace` force-pushes); the fast-forward of the checkout under
  `FAB_HOME/tick.lock` after a trunk push or a landing, and for a ready
  ref the printed wait (and, detached, that the operator moves it). Both
  are in `fab/cli.py` `COMMANDS` (`trunk` after `check`, `plan` after
  `status`). Tested on real git in temporary directories (`git_pair`) and
  fake runners, the landing faked (`test_trunk.py`, `test_inputs.py`).
- **A rebase onto the trunk consumes the amendment** (2, "Optimistic
  start"; plan dogfood-faults; f19f942): `fab.call_review.task_rebase`
  takes `trunk` (default `main`) and counts a done rebase run from
  `origin/<trunk>`; `fab.dispatch` passes `plan.trunk`. Tested in
  `test_call_review.py` and `test_dispatch.py`.

## Gaps and departures

- **An integration trunk through the queue is untried live:** the catch-up
  with main (before a check and along the way), catch-up repairs, the
  re-check after a rejection and the stops are tested against fakes and real
  git only. So are the stop's question and its lift. The retire from main
  ran live once (the probe phase-case, 11-01): its trunk landed through the
  queue at 17:17:58Z, its retire started from main (17:27:16Z), went through
  `ready/calls/retire-2c39…` and landed at fc1651448b, and the plan
  checkout detached there; its landing was imported only at 18:16:57Z, once
  a retired plan's import was built (tick.md 5, `tick.status.md`). No trunk
  has stopped since the stop's records were built. The other calls, foremen
  and repairs from main after the landing (df-followups, 11-01) are untried
  live: no trunk has landed since.
- **A foreman's answer or a repair's section after the landing still
  commits from the trunk** (3, "so does every other call, foreman and
  repair"): `fab.dispatch._settle` and `_remedy` pass `trunk=plan.trunk` to
  `fab.foreman.commit` and `fab.repairs.commit`, whose `fab.spec_edit.commit`
  adds its worktree at `origin/<trunk>`; once the queue deleted the trunk
  and the clone pruned it, that settle fails each tick. Only a question or
  refusal still open when the trunk lands reaches it (every task has merged
  by then); df-followups' request named the starts, not the settles.
- **The start commands are unused live** (3, start-commands, 11-01): hel8's
  log holds no `trunk.made` at the plan's retire, and no plan's `inputs/`
  has gone through `fab plan inputs`; the next replay or `ready` probe is
  their first run. On fabrig's main path the command ends at a ready ref,
  as designed: the operator starts the cut once the queue's `queue.landed`
  is imported and the tick has moved the checkout.
- **The flow of a real run (3) is on main, not run live yet**
  (10-31): the options with the run's defaults (agents-rebuild names the
  old flow), the trunk throughout, the tick's merges with the baseline
  recount and the trunk's ratchet, the end check (`fab check`), its
  repairs and the ready, reviews off, answers at once, the flow kept at
  the builders' places, and the run-derived texts (`cut-direct.md`,
  `fabrig-integration.md`). Simulated against codex-kit
  (`coord/fab-replay/simulation.md`), then run live once (10-31,
  15:32-16:49Z, hetzner11 and hetzner12): `component-kit/integration` green
  on the first end check at T+76.1 (codex-kit 54.75), never landed
  (`coord/fab-replay/report.md`). Five bugs found live are fixed on main. At the user's word
  (10-31, after the replay) three changes are being built: light merges
  without gates and the `files` gate removed (`light-merges`), the cut's
  early release of specs (`cut-early`) and the run's own texts
  (`run-texts`);
  `cut-run.md` allows designer subagents where the design is too wide for
  one writer (the user, 10-31: the playground replay's cut started four,
  then hit the call's 40-minute limit before they ended; the limit is now
  60 minutes); a park at the run limit goes to the answerer, never the
  foreman, and its answer grants fresh runs (the playground replay's loop);
  a repair's question queues, answer calls see and record it, and its answer
  folds into its body; after the playground replay, the answerer leaves what
  is not the task's, reruns start from their pushed branch, the cut writes
  plan.md and its report early, and a full builder hands a start on; early
  starts and checks along the way (3) are built (not run live yet);
  a run may leave what is not its own (3: the implementer's allowed
  edits and `## Left`, the foreman's `Accept:`, the cut's contracts note;
  not run live yet);
  and, with fabrig's `agents/` gone from its main
  (`2c39875fd2`), `cut-run.md` and `fabrig-run.md` no longer name it;
  what is left to match the run is in section 5. The replay ticked from
  its own install on hel8 (`FAB_HOME/replay-install`, a local hosts.toml),
  as a background command of a session, not a unit.
