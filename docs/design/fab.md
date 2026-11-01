# fab: the pipelines' code

2026-10-30. Owner: the user's pipeline session. Code: `fab/`, `bin/fab`.
Code departures: `docs/design/fab.status.md` and each design's own status file. Inputs: the drafts
`docs/design/draft/code-producing-pipeline.md` and `landing-pipeline.md`, and
the user's "Execution modes for the code-producing pipeline" (Claude Docs,
2026-10-30; Feature mode is the one built first).


## 1. In one page

- **One package, one log.** `fab/` holds the code of both pipelines. Its
  memory is files: plans and tasks authored in git, and one append-only event
  log that only the dispatcher writes. State, metrics and reports are computed
  from them, never kept by hand.
- **Interim by intent.** temper's own primitives replace fab in time. Until
  then fab must be cheap to run, easy to change and good enough to prove the
  execution model. It uses the model's words (draft, part, slice, task, run,
  call), so the move to temper is a translation, not a redesign.
- **Pure core, thin shell.** Every decision is a pure function of files and
  the log. The shell runs git, ssh, codex-run and cargo through one injected
  runner (`fab/sh.py`). Tests check the core directly and the shell against a
  fake runner.
- **The whole suite runs in under 30 s.** `bin/fab test` runs every test and
  fails past 30 s of CPU time (section 4).
- **Builders own their disk.** A sweep bounds each slot's footprint at the end
  of every task. A build short of disk waits while the builder reclaims idle
  slots. No implementer stops or asks because of disk (machines.md 2).
- **Strangler, not big bang.** Each fab part replaces an existing tool once its
  slice's story passes. The old tool stays live until then, and is deleted
  after.
- **Minimal now, with room left.** The current tools' safety layers (receipts,
  custody proofs, acknowledgements, recovery journals) are left out. Section 5
  says where each would attach if numbers show it is needed.

## 2. Where things live

| Place | What |
|---|---|
| `fab/` in this repository | the package; `fab/tests/` its tests; `fab/roles/` the role texts briefs are compiled from; `fab/hosts.toml` the machines |
| `bin/fab` | the command; `bin/fab COMMAND ...`, Python 3.13 standard library only |
| `docs/plan/<draft>/plan.toml` in the draft's repository | the thin cut: parts, slices, modes (tick.md 2) |
| `docs/plan/<draft>/tasks/<task>.md` in the same repository | task specs, landed with their part's skeleton |
| `~/src/fabrig/fab/` on every machine (`FAB_HOME`) | runtime data, never in git |
| `FAB_HOME/log.jsonl` on the dispatcher's machine (hel8) | the event log (section 3) |
| `FAB_HOME/runs/<run>/` on hel8 | each run's brief, its collected report and metadata |
| `FAB_HOME/reports/` on hel8 | the standing reports, one file per draft and day (reports.md 2) |
| `FAB_HOME/digests/<run>.md` on hel8 | each gated branch's structure digest (gates.md 2) |
| `FAB_HOME/hosts.local.toml` on any machine | live overrides of `fab/hosts.toml` there, by hand (machines.md 2) |
| `FAB_HOME/user.md` on hel8 | the user's page: their open questions and the latest reports (channel.md 2) |
| `FAB_HOME/tick.want` on hel8 | the reasons the tick was woken since it last ran (tick.md 6) |
| `FAB_HOME/repos/<repo>` on each machine | fab's own clones; `FAB_HOME/wt/<run>` worktrees for runs that build nothing |
| `~/src/fabrig/slots/<n>` on a builder | warm fabrig checkouts (unchanged); `slots/<n>.claim` the slot's claim (machines.md 2) |
| `FAB_HOME/after-landing.jsonl` on the after-landing builder | its verdicts; `FAB_HOME/after-landing/` its state and each run's logs (after-landing.md 2) |
| `FAB_HOME/reds/<red>.md` on hel8 | an after-landing red's evidence, written when it opens (after-landing.md 2) |
| `FAB_HOME/walks/<walk>/` on hel8 | a QA walk's compiled brief, its walker's `report.md` and `result.toml` (qa.md 2) |
| `~/src/fabrig/logins/shelf/` on hel8 | every login at rest or its placeholder while lent (machines.md 3) |

- **hel8** runs the dispatcher, Claude calls and `fab land` for this
  repository. **Builders** (hetzner6 today) run Codex and builds. **hetzner8**
  runs fabrig's merge queue.

## 3. The event log

- **Format:** one JSON object per line: `{"ts": "<UTC, ms, Z>", "ev": "<type>", ...}`.
  Fields are flat strings, numbers or lists. A line is never changed or
  deleted.
- **One writer:** `fab.log.append` on hel8, under a flock beside the log. A
  torn last line (a crash mid-write) is ignored on read. Builders report by
  being asked (`fab run status` over ssh); they never write the log.
- **The events:**

| ev | fields | meaning |
|---|---|---|
| `task.added` | draft, task, repo, path, sha | a task spec exists on its repository's main |
| `run.started` | run, task, kind, host, dir, branch, base | a Codex run began; kind is implement, repair, rebase, review or foreman; check is an integration branch's full check (integration.md 3); a foreman's carries `asked`, `refused`, `red` (calls.md 2) or `finding` (qa.md 2) |
| `run.ended` | run, task, outcome, report, minutes, tokens | outcome is done, question, infra or failed (tick.md 3); tokens is Codex's (reports.md 3) |
| `branch.ready` | task, branch, tip | handed to the landing pipeline; a ladder's backlog branch carries `render`, its file's sha256 (qa.md 2) |
| `branch.landed` | task, branch, tip, main, into | on main; with into, merged into an integration plan's trunk, main being its new tip (integration.md 3) |
| `branch.rejected` | task, branch, tip, step, log | the landing refused it; its foreman decides what follows (calls.md 2) |
| `refusal.settled` | task, run, verdict, reason, branch, section | the tick acted on a refusal's foreman run: fix (its section landed in the spec), retry (the tip goes back unchanged) or none (calls.md 2) |
| `question.asked` | task, run, text | the task parks until answered |
| `question.answered` | task, by, answer | the task may run again; it names a task, never a call's subject |
| `call.started` / `call.ended` | call, role, subject; outcome, tokens, cache_write, peak, turns, minutes | a Claude call; its usage (reports.md 3) |
| `call.finished` | call, role, outcome | the dispatcher landed a call's branch, or failed to |
| `call.parked` | call, subject, role, reason, report | a call's branch waits for the user, or a call the tick started could not compile its brief (call "", or its chain's root for amend and settle; calls.md 2) |
| `trunk.made` | draft, base, tip | an integration trunk made for a fabrig plan, base the REV given, tip its sha (integration.md 3) |
| `chain.settled` | call, subject, settle, verdict, text | a held chain judged by a settle call: land, amend or user (calls.md 2) |
| `call.answered` | subject, call, by, question, answer | the user answered a subject's question or parked chain (channel.md 2) |
| `issue.opened` | subject, kind, number, url | an open user ask has a forge issue (channel.md 3) |
| `issue.comment` | number, subject, comment | a user comment consumed before its reply call (channel.md 3) |
| `issue.replied` | number, call; outcome | the loop posted a reply; outcome is failed only for an unreadable or failed call (channel.md 3) |
| `issue.closed` | number, subject | the subject no longer has an open ask; its issue is closed (channel.md 3) |
| `tiers.run` / `tiers.red` / `tiers.recovered` | tip, verdict, counts, branches, commits, faults, reds, log; tip, key, state, profile, binary, test, error, branches, log, rerun; tip, key, profile, binary, test | imported from the after-landing machine, `al_ts` its record's time, `host` the machine's name (after-landing.md 2) |
| `red.opened` | red, tip, keys, suspects, tasks, draft, route, reason | an after-landing red's tests, grouped, sent to a foreman or to the page (after-landing.md 2) |
| `red.settled` | red, run, verdict, reason, owner, section | the tick acted on a red's foreman: fix or none (a repair task follows) or left (the page) (calls.md 2) |
| `red.closed` | red, reason, tip | every test of the red recovered or is no longer red in a run without faults, or its signal was cleared (after-landing.md 2) |
| `queue.rejected` / `queue.landed` / `queue.collateral` | branch, tip, step, log, tests; branch, tip, main; branch, tip, step, tests, log | the queue's record of a branch no fab task owns, `queue_ts` its time, `gate` the gate host's name (landing.md 3) |
| `signal.cleared` | signal, by, text | a signal taken off the user's page by hand (channel.md 2) |
| `walk.started` / `walk.ended` | walk, draft, rung, backend, edition, commit, by; walk, verdict, reason, report, findings | a QA walk of a ladder plan's rung; verdict pass, fail or void (qa.md 2) |
| `finding.raised` | finding, draft, walk, index, rung, backend, commit, edition, kind, title, severity, area, blocking, reproduction, expected, seen, evidence, again | a walk's finding, from its `result.toml` (qa.md 2) |
| `finding.merged` | finding, into, by, reason | the same finding as `into`: named by the walker (by the walk) or judged by triage (by the call) |
| `finding.triaged` | finding, call, decision, owner, reason, question, into | a triage call's decision: path, backlog, user, brief, drop, or again (a merge into a fixed finding) |
| `finding.settled` | finding, run, verdict, reason, section | the tick acted on a finding's foreman: fix or none (a repair task follows) or left (the page) |
| `rung.passed` | draft, rung, walk, edition, commit | a rung's brief rerun unchanged and passing, its lower rungs passed (qa.md 2) |
| `login.checked` | id, email, plan, used, resets, error, limit_names, limit_used, limit_resets | account check and limits (machines.md 3); the three limit lists hold scalars of equal length in the same order, with null use or reset when unknown |
| `trunks.overlap` | drafts, tips, files, more, reason | two ready trunks, each merged with main, conflict on these paths; empty files: cleared, or `gone` (integration.md 4) |
| `note` | text | anything a person wants on the record |

- **New kinds are additive.** The fold ignores types it does not know, so a
  new event never breaks an old reader.
- **Ids:** a task is `<draft>/<task>`; a run is `<task>-<n>`, n counting the
  task's runs from 1; a branch is `<draft>/<task>` and a rebase pushes
  `<draft>/<task>-r<n>`.

## 4. Tests

- **Under 30 s for everything,** measured by `bin/fab test`, which fails past
  it. The budget is the process's CPU time, user and system, children
  included, not wall time: a busy machine must not fail a suite that is
  fast (11-01: under QA's load, a run ended `Infra:` and two hand runs
  failed on wall time with every test passing). The wall time is printed
  beside it. A module's tests run in about a second.
- **The core is tested directly:** decisions (`decide`, `fold`, selection,
  bisection, sweep plans) are pure functions over plain data.
- **The shell is tested against a fake:** commands take a runner
  (`fab.sh.run` by default). Tests pass `fab.tests.support.FakeRunner`, which
  records each argv and returns scripted results. No ssh, systemd, codex or
  cargo runs in a test.
- **One git fixture per module:** `support.git_repo()` builds a template
  repository once per process, and each test copies it. Real git only where
  git's own behaviour is the point (merges, rebases, pushes).
- **Temporary HOME and FAB_HOME** for every test that touches files. Python
  runs with `-B`.

## 5. Left out for now

- **Evidence hashes** (precheck's `result.json` bound to trees): the log's
  `run.ended` and `branch.*` events carry tips, and the queue reuses a
  receipt only for its tip and main (landing.md 3); a check binding receipts to
  trees attaches at `fab land` and the queue's intake.
- **Acknowledgement protocols for reclaiming:** reclaim touches unclaimed
  slots only, so no acknowledgement is needed; a slot kept for inspection is
  claimed by a person.
- **Mail between agents:** the dispatcher asks; nobody waits on a mailbox. One
  notification path to the user, when a question is the user's, comes with the
  answer queue.
- **Leases:** one writer per crate becomes the dispatcher's choice of
  runnable tasks (their `files`), not a lock.

## 6. The designs

fab is designed in one document per subsystem, each with its status file
beside it (`tick.status.md` beside `tick.md`) and its own Later
section. This document holds what they share: the overview, where things
live, the event log, the tests and what is left out. Split from one
document on 2026-11-01 at the user's word; citations written before then
name `docs/design/fab.md` and its old section numbers, which the second
table maps. The split first named each design `fab-<name>.md`; the prefix
was dropped the same day, so a citation of `fab-tick.md` means `tick.md`.

The old document's section 13, "Growing toward the full model", held what the
user's execution model asks that fab did not do yet, cut into parts the loop
designs and builds itself (`docs/plan/agents-rebuild/plan.toml`, slice 6);
its subsections are now spread over the designs below. Two rules hold
throughout: whoever designs a thing never accepts it, and the flow grows from
a small start rather than to a fixed cap.

The old pipeline's designs (pipeline, sessions, records, watch, status-page,
fleet, gate, qa and after-landing, for `tools/`, `fleet/`, `pipeline/` and
`prompts/`) were deleted with that code on 2026-11-01 (retire, the user's
go); they are readable in history at 7a7df4f.

| Design | Subsystem | Old sections |
|---|---|---|
| `docs/design/tick.md` | plans, runs and the tick | 4, 5, 13.2, 13.4, 13.9, 13.10 |
| `docs/design/calls.md` | Claude calls, review and the designer | 13.1, 13.3, 13.7 |
| `docs/design/landing.md` | landing | 6, 13.8 |
| `docs/design/machines.md` | builders, slots, disk and logins, the dispatcher's units | 7, 13.13 |
| `docs/design/reports.md` | reports, accounting and the status page | 10, 13.5, 13.14 |
| `docs/design/after-landing.md` | after landing | 11 |
| `docs/design/gates.md` | gates and the structure review | 12 |
| `docs/design/channel.md` | the channel to the user | 13.6, 13.16 |
| `docs/design/integration.md` | plans on fabrig and integration trunks | 13.11, 13.12, 13.17 |
| `docs/design/qa.md` | QA findings | 13.15 |

| Old section | Title | Now |
|---|---|---|
| 1 | In one page | `docs/design/fab.md`, section 1 |
| 2 | Where things live | `docs/design/fab.md`, section 2 |
| 3 | The event log | `docs/design/fab.md`, section 3 |
| 4 | Plans and tasks | `docs/design/tick.md`, section 2 |
| 5 | Runs | `docs/design/tick.md`, section 3 |
| 6 | Landing | `docs/design/landing.md`, section 2 |
| 7 | Slots and disk | `docs/design/machines.md`, section 2 |
| 8 | Tests | `docs/design/fab.md`, section 4 |
| 9 | Left out for now | `docs/design/fab.md`, section 5 |
| 10 | Reports | `docs/design/reports.md`, section 2 |
| 11 | After landing | `docs/design/after-landing.md`, section 2 |
| 12 | Gates and the structure review | `docs/design/gates.md`, section 2 |
| 13 | Growing toward the full model | `docs/design/fab.md`, section 6 |
| 13.1 | Design and acceptance are separate | `docs/design/calls.md`, section 2 |
| 13.2 | The flow grows | `docs/design/tick.md`, section 4 |
| 13.3 | The designer's calls | `docs/design/calls.md`, section 3 |
| 13.4 | Several plans, calls in parallel | `docs/design/tick.md`, section 5 |
| 13.5 | Accounting | `docs/design/reports.md`, section 3 |
| 13.6 | A channel to the user | `docs/design/channel.md`, section 2 |
| 13.7 | Probes | `docs/design/calls.md`, section 4 |
| 13.8 | The landing side | `docs/design/landing.md`, section 3 |
| 13.9 | Events drive the tick | `docs/design/tick.md`, section 6 |
| 13.10 | The timeline's flow | `docs/design/tick.md`, section 7 |
| 13.11 | The entry path to fabrig | `docs/design/integration.md`, section 2 |
| 13.12 | The flow of a real run | `docs/design/integration.md`, section 3 |
| 13.13 | Logins | `docs/design/machines.md`, section 3 |
| 13.14 | The status page | `docs/design/reports.md`, section 4 |
| 13.15 | QA findings | `docs/design/qa.md`, section 2 |
| 13.16 | The user's questions on the forge | `docs/design/channel.md`, section 3 |
| 13.17 | Drafts beside each other | `docs/design/integration.md`, section 4 |

## 7. Later

- Deleting the frozen legacy checkouts on the machines (`~/src/rust/agents`,
  `~/src/fabrig/agents`, `~/src/fabrig/current`) and the disabled old units'
  files, once nothing reads them.
