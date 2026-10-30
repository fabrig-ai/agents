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

- **heavy is not switched over:** builders still run fabrig's old heavy;
  fab's replaces it at the cutover, which waits for the user's word.
- **fab queue does not run yet** on hetzner8; the old queue is stopped.
  `cutover-fabrig` is the first change meant to land through it.
- **The tick is run by hand,** not on a timer.
- **Claude calls** (`fab/calls.py`) are being filled; skeletons and task
  specs are still written by hand.
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
- **Subjects can share a task's id:** a skeleton call's subject
  `<draft>/<part>` equals the id of a task named after its part (`gates`).
  A `question.answered` that unparks the subject also makes that task
  runnable in the fold, even after it has landed. Nothing answers a call's
  question by hand yet; the user's channel (13.6) must name subjects apart
  from tasks.
- **The flow is a skeleton:** `fab/flow.py` holds 13.2's target, calm and
  measure, and `fab.dispatch.places` and `decide` take a `calm` argument they
  do not use yet. The task `flow` fills them after `gates-tick`; until then
  the tick fills every builder's `places` and never passes them.
- **Parts done by hand have no task specs** (package, slot-probe), so the
  tick's design line lists them.
- **The slot bound of 25 GB is one measurement** (10-30 20:18Z): a
  whole-workspace build from a swept slot. Repeated scoped builds within one
  task are not measured yet; heavy.jsonl and the sweep's freed bytes will
  show them.
