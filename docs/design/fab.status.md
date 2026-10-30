# fab status

2026-10-30. Contract: `docs/design/fab.md`. Plan:
`docs/plan/agents-rebuild/plan.toml` (`bin/fab status docs/plan/agents-rebuild`).

## Present

- **Package and tests:** `bin/fab`, the runner seam, the test runner with its
  30 s budget, the test helpers; about 250 tests in about 3 s.
- **The event log** on hel8 (`~/src/fabrig/fab/log.jsonl`) holds every run,
  landing and note since 10-30 20:11Z; `fab status` folds it.
- **Runs:** `fab run start|status|collect` with worktrees for this repository
  and slots for fabrig (claim, switch, release with the sweep at collect);
  `fab codex` launches Codex as user units (live on hetzner6 since 20:30Z;
  codex-run is no longer called). A failed start gives back what it took.
- **Landing this repository:** `bin/fab land`, live since 20:22Z; every
  change to `fab/` since then landed through it.
- **The dispatcher:** `fab tick PLAN_DIR` collects, lands, starts and parks;
  run by hand, live since 20:27Z.
- **Slots and disk:** `fab slot` (claims, release sweep, reclaim of idle
  slots) and `heavy` (flock lanes, capped disk wait with reclaim), on main;
  fab is installed on hetzner6 and hetzner8 (`~/src/fabrig/fab/install`,
  `fab` on PATH). hetzner6's slots 5 and 7 carry fab claims mirroring the
  paused ladder work's old claims.
- **fabrig's landing:** `fab gate`, `fab queue`, `fab precheck` on main.

## Gaps and departures

- **Live, but transient:** fab's heavy on hel8, hetzner6 and hetzner8; fab's
  queue (`fab-queue.service`) on hetzner8 since 10-30 21:15Z, which landed
  the cutover; the tick (`fab-tick.timer`, every 2 minutes) on hel8. The
  queue and the tick are transient user units: a reboot loses them. They
  become fleet units with retire's second step.
- **Retire, step 1 done by hand** (the user's OK, 10-30 23:17Z): the dead
  `claim`, `precheck`, `ready-check` and `codex-run` links removed on all
  three hosts; hel8 on fab's heavy, the old reconcile timer disabled;
  `pipeline-watch` and the `record-collect-*` timers stopped and disabled.
  Each host's `~/src/fabrig/fab/retire-step1.txt` says what it was.
  `fleet-sync` is still enabled and stopped: run as it is, it would rebuild
  `~/.local/bin` from fabrig's deleted `tools/installed`; it must learn fab
  first. The rest of retire (post, the session launcher, lease, watch and
  the collector's code, the old role files) waits, parked, for gates and
  after-landing to be live.
- **Claude calls** are made by the tick (skeleton, review, amend, answer);
  the cut still starts by hand.
- **Reports are a skeleton:** `fab/report.py`, `fab/code_report.py` and
  `fab/landing_report.py` hold section 10's signatures and contracts, filled
  by the tasks `report-base`, `report-code`, `report-landing` and
  `report-command`; `fab report` is not a command until the last lands. No
  timer runs `fab report daily` yet.
- **After landing is a skeleton:** `fab/nextest.py`, `fab/tiers.py` and
  `fab/after_landing.py` hold section 11's signatures and contracts, filled
  by the tasks `nextest`, `tiers`, `after-landing-verdicts` and
  `after-landing-runner`; `fab tiers` and `fab after-landing` are listed
  commands that do nothing until those land. The old
  `tools/after-landing` (hetzner7, slot 4) keeps running and posting; no
  unit runs fab's yet, and its builder and slot are the user's to choose.
- **Gates and the structure review are a skeleton:** `fab/digest.py` and
  `fab/gates.py` hold section 12's signatures and contracts, and
  `fab.calls.review_brief`, `last_review` and `landed_after` the review
  call's; `fab/taste.md` and `fab/roles/reviewer.md` are written. The tasks
  `digest`, `digest-render`, `gates`, `taste-brief` and `review-call` fill
  them; `gates-tick` turns the gates on in the tick. Until it lands every
  branch lands ungated and no review call starts. Once it does, a change to a
  function already over 60 lines (`fab.dispatch.tick` among them) fails
  `size` and must split it.
- **The review of calls' output is a skeleton:** `fab/call_review.py`
  (chains, the review run's brief and start, the amend brief) and
  `fab.run.fetch_clone` and `fab.run.launch` hold 13.1's contracts.
  `fab/roles/call-reviewer.md` and `fab/roles/amender.md` are written. The
  task `call-review` fills them; `call-review-tick` makes the tick review
  calls' branches and run amend calls, after `review-call` and
  `gates-tick`. Until it lands, a call's branch lands unreviewed.
- **The foreman is a skeleton:** `fab/foreman.py` (where each question
  stands, the foreman run's brief and start, the answer written into the
  spec) and `fab.run.launch_detached`, the read-only start review and
  foreman runs share, hold 13.1's contracts; `fab/roles/foreman.md` is
  written. The task `foreman` fills them, after `call-review`;
  `foreman-tick` sends questions to the foreman from the tick, after
  `call-review-tick`. Until it lands, every question waits for the
  answerer. Answers land through `fab land`, so a plan whose specs live
  outside this repository cannot be settled by its foreman yet.
- **The foreman only settles questions.** The user's execution model
  (`docs/design/draft/execution-modes.md`, roles) also has it write rebase
  and mechanical repair tasks; here the dispatcher starts rebase and repair
  runs on the rejected task itself (sections 6 and 13.1), and no part gives
  the foreman that duty. The model lists the foreman without read-only;
  13.1 makes it read-only, and code writes its answer into the spec.
- **Subjects can share a task's id:** a skeleton call's subject
  `<draft>/<part>` equals the id of a task named after its part (`gates`).
  A `question.answered` that unparks the subject also makes that task
  runnable in the fold, even after it has landed. 13.6 names subjects
  apart from tasks (`call.answered`); until `channel-tick` lands, a
  subject still unparks on a `question.answered` naming it, and call
  questions are answered that way by hand.
- **The flow is a skeleton:** `fab/flow.py` holds 13.2's target, calm and
  measure, and `fab.dispatch.places` and `decide` take a `calm` argument they
  do not use yet. The task `flow` fills them after `gates-tick`; until then
  the tick fills every builder's `places` and never passes them.
- **The designer's calls are a skeleton:** `fab/designer.py` holds 13.3's
  briefs, the changed-designs and retire checks and `fab call cut|contract|
  decision|retire`; `fab.state.part_statuses` and the plan's `contract`,
  `retired` and `[[question]]` fields are declared but not read yet. The
  role texts `cut.md`, `contract.md`, `decision.md`, `retire.md` and
  `consistency.md` are written. The task `designer` fills the module, the
  plan's fields and the commands; `designer-tick` makes the tick start
  contract and retire calls, tick a plan being cut, skip a retired plan and
  review a retire call with the consistency pass. Until then every part is
  designed by a skeleton call, and plans are cut by hand.
- **The user's channel is a skeleton:** `fab/channel.py` holds 13.6's
  fold of the user's open questions, the page and `fab page
  show|write|answer`. The task `channel` fills the fold, the reports'
  listing and the page's text; `channel-tick` fills the command and the
  page's writing, and makes the tick rewrite the page. It also makes
  `call.answered` the only answer that unparks a subject or resets a
  chain, and carries the user's answers into every later brief of the
  subject, and makes an answer call's `Question:` park its draft. Until
  then nothing writes `FAB_HOME/user.md`, and an answer call that ends
  `Question:` starts again on the next tick. The open question
  of the log today is the retire skeleton call's; the accounting call's was
  answered in 13.5 (measured, not capped). The page
  is a file on hel8: where else the user reads it is the user's (14).
- **Accounting is a skeleton:** `fab/accounting.py` holds 13.5's weights,
  the draft's calls and runs and the code report's Claude and Codex
  figures; `fab.calls.Usage` and `claude_usage` the reading of claude's
  stream, and `fab.codex.tokens_field` the run's tokens. The task
  `accounting` fills them, switches calls to claude's stream-json output,
  makes `fab run status` read the run's result and adds the figures and the
  Calls table to the code report. Until it lands, run.ended carries no
  tokens, call.ended no peak, turns or cache writes, and no weight is shown.
  A call's subject draws its calls into the report only when it is the draft
  or one of its parts; the task widens that to every subject under the
  draft (review, cut, retire, decision).
- **Parts done by hand have no task specs** (package, slot-probe), so the
  tick's design line lists them.
- **The slot bound of 25 GB is one measurement** (10-30 20:18Z): a
  whole-workspace build from a swept slot. Repeated scoped builds within one
  task are not measured yet; heavy.jsonl and the sweep's freed bytes will
  show them.
