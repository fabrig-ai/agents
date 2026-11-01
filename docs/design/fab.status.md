# fab status

2026-10-30. Contract: `docs/design/fab.md`. Plan:
`docs/plan/agents-rebuild/plan.toml` (`bin/fab status docs/plan/agents-rebuild`).

## Present

- **Queue CPU and starvation** (11-01): default/fuzzy reuse `fab/cpu.py`
  with the queue's package scope and gate lane, one wrapper per batch, and
  separate collector directories per step. Batch records and logs report
  package-mapped per-tree CPU, summed test wall, pass/fail/starved/unobserved
  counts, full versus partial selection, and the ten highest-CPU tests per
  tree. Optional `[gate.<tree>.<profile>]` limits start unset; excesses are
  report only, suite totals evaluated only for full selections. Starvation
  alone is green; real failures and other exit-code checks stand. Fake
  services/JUnit/records cover both. A real slot-5 scoped gate-lane run on
  fabrig `eb6c40aaf5` passed 265 default and 7 fuzzy tests, reporting smith
  and jig CPU separately. The lead lands and deploys this change; no live
  queue unit was changed. Turning budget excesses red remains in Later (6, 14).

- **After-landing CPU and starvation** (11-01): every pair and rerun uses
  the tested checkout's CPU collector, with one heavy-built wrapper per tip.
  Pair/test/run records and the page report CPU, wall, starvation and possible
  hangs. Optional `[after-landing]` limits have no default figures; per-pair
  budgets are diagnostic. Wall timeout passes as starved, unstarted tests
  stay unobserved, and removed profiles retire without a fault. Tests use
  fake services/JUnit/records; real slot-5 qa-smith and browser-jig checks
  and a scratch five-second total wall limit exercised the integration.
  The lead deploys the branch after landing; no live unit was changed here.

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
- **Logins:** `fab logins` (13.13): the shelf, capture, lend, return, swap,
  retire, check and borrow; live on hel8 since 10-31 23:3xZ, holding every
  machine's logins, the user's new sign-ins and QA's six (moved 11-01).
  `fab after-landing --live` borrows them for `live-skein` (whose tests
  read logins' files since fabrig 978e17e); the after-landing unit on
  hetzner8 runs with it, on the cheapest models. `live-temper` is out
  (11-01): its owner-run live stories are ignored, and since fabrig
  eb6c40aaf its live binaries have no harness unit tests; nextest exits 4,
  faulting every run and holding the cursor. It awaits the user's decision
  on which ignored stories, if any, to run with `--run-ignored` (11, 13.13).
  Borrowing and its `chatgpt` / `claude-box` kinds remain tested with a
  test-only live table.
  `live-smith` was taken out 11-01 ~02:00Z (red on 831e86f27 and
  e4f852afa: `SMITH_LIVE` unset): it needs a smith live root signed in by
  `smith login`, a directory kind the shelf does not have yet.

## Gaps and departures

- **Live, but transient:** fab's heavy on hel8, hetzner6 and hetzner8; the
  tick (`fab-tick.timer`, every 2 minutes) on hel8, a transient user unit a
  reboot loses. It becomes a unit installed by `fab wake --install`.
- **The queue is fab's unit, not fleet's:** `fab-queue.service`, written by
  `fab queue install`, which the deploy runs on every machine (section 6).
  It ran as a transient unit on hetzner8 from 10-30 21:15Z (it landed the
  cutover) until 10-31 10:08Z, when hetzner8 also became a builder.
- **An integration trunk through the queue is untried live:** the catch-up
  with main, the re-check after a rejection and the stops are tested against
  fakes and real git only; no plan has yet run with `ready = true`.
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
- **After landing is live:** `fab-after-landing.service` on hetzner8,
  slot 7, since 11-01 (hetzner10 until it retired, 11-01); the tick imports its verdicts onto the user's page.
  The old `tools/after-landing` (hetzner7, slot 4) stopped with hetzner7,
  which no longer answers. A new red reaches no task yet: the page is where
  it is heard.
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
- **The foreman's repairs are a skeleton:** `fab/repairs.py` (where each
  open refusal stands, the refusal foreman's brief and start, its verdict,
  the `## Repair` or `## Rebase` section written into the spec),
  `fab/spec_edit.py` (a spec changed on a branch to land, which
  `fab.foreman.commit` is to use), `fab.run.excerpt` and
  `fab.run.refusal_text`, and `fab.dispatch.repair_actions` hold 13.1's
  contracts; `fab/roles/foreman-repair.md` is written. The task `repairs`
  fills the modules; `repairs-tick` makes the tick start refusal foremen,
  act on their verdicts, hold a refused task's repair run until its foreman
  has decided, and carry the section into that run's brief. Until it lands
  the dispatcher starts rebase and repair runs on the refused task itself,
  with the refusal alone. The model lists the foreman without read-only;
  13.1 makes it read-only, and code writes its answers and sections into
  the spec.
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
- **Several plans are a skeleton:** `fab/drafts.py` holds 13.4's rules:
  which runs in flight a draft owns, the strays no plan owns, a plan's
  design calls up to its flow target, the calm a plan leaves the next, and
  a call's unit named by its subject. The task `drafts` fills it.
  `plans-tick` makes one tick take every plan in `FAB_HOME/plans`, after
  `designer-tick`, `channel-tick` and `accounting`. Until it lands, `fab
  tick PLAN_DIR` ticks one plan and collects every run in flight. It
  starts one skeleton call at a time (one contract call beside it once
  `designer-tick` lands), in units numbered by role. Its answer and review
  limits, and the review's last-review time, count every draft's calls,
  and its queue import reads from the log's newest record of any draft.
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
- **The landing checks are a skeleton:** `fab/receipts.py` (a receipt
  kept on the gate, read, reusable for a tip and main, covering a test, and
  carried from the builder at ready) and `fab/reds.py` (the test steps'
  JUnit, the retry of a failed test alone, the verdict) hold 13.8's
  contracts; `fab.queue.Queue.attempt`, `cycle` and `main` say how the queue
  uses them. The task `receipts` fills the first and the queue's reuse and
  `fab queue receipt`; `red-classes` the second, the queue's classing and
  the landing report's figures; `receipts-ready` makes the dispatcher carry
  each tip's receipt when it readies it, after the tick's other tasks on
  `fab/dispatch.py`. Until then every batch runs its full checks and every
  red rejects or bisects. The bound of two collateral reds per tip and five
  retried tests per red are first guesses, to be set from the queue's
  records.
- **The buffer's order is a skeleton:** `fab/buffer.py` holds 13.10's
  groups and the sort, `fab.plan.Task` its `consolidation` field, and
  `fab/roles/reviewer.md` asks the review call to mark its specs with it.
  The task `buffer-order` fills the sort, reads the header and makes
  `decide` start runs in the sort's order, after `receipts-ready` and
  `plans-tick`. Until then `decide` starts rejected tasks first, then
  runnable ones in their specs' order, and a spec's `consolidation` key is
  ignored.
- **Events are a skeleton:** `fab/wake.py` holds 13.9's want file, the
  wake from any machine, the round's close (the lost-event note, the tick
  waking itself) and the tick's four units; `fab.hosts.this` names this
  machine's entry. The task `wake` fills the module, registers `fab wake`
  and makes the wakers wake: a Codex unit's ExecStopPost, a call's end, `fab
  land`, `fab page answer` and the queue's cycle. `wake-tick` makes the tick
  take the want, wait for its lock as an event tick, close each round, and
  fills `fab wake --install`, after `buffer-order` since it changes
  `fab/dispatch.py`. Until both land the transient `fab-tick.timer` ticks
  every 2 minutes and wants pile up unread in `FAB_HOME/tick.want`. Once
  they land, `fab wake --install` on hel8 starts the units, and each
  builder needs ssh to hel8 for its runs' wakes.
- **The flow of a real run (13.12) is on main, not run live yet**
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
  plan.md and its report early, and a full builder hands a start on (not run
  live yet);
  a run may leave what is not its own (13.12: the implementer's allowed
  edits and `## Left`, the foreman's `Accept:`, the cut's contracts note;
  not run live yet);
  and, with fabrig's `agents/` gone from its main
  (`2c39875fd2`), `cut-run.md` and `fabrig-run.md` no longer name it;
  what is left to match the run is in section 14. The replay ticked from
  its own install on hel8 (`FAB_HOME/replay-install`, a local hosts.toml),
  as a background command of a session, not a unit.
- **Parts done by hand have no task specs** (package, slot-probe), so the
  tick's design line lists them.
- **The slot bound of 25 GB is one measurement** (10-30 20:18Z): a
  whole-workspace build from a swept slot. Repeated scoped builds within one
  task are not measured yet; heavy.jsonl and the sweep's freed bytes will
  show them.
- **Design waits for implementation:** `fab.dispatch.decide` makes a part
  eligible only when every task of its needs has landed, and sizes the
  buffer against nominal places; section 4 now says otherwise, and the task
  `design-eligibility` brings the code to it.
