+++
id = "plans-tick"
part = "plans"
kind = "interface"
needs = ["drafts", "designer-tick", "channel-tick", "accounting"]
files = ["fab/dispatch.py", "fab/calls.py", "fab/cli.py", "fab/tests/test_dispatch.py", "fab/tests/test_calls.py"]
effort = "high"
minutes = 55
+++
# Every plan in one tick; design calls in parallel

Today `fab tick PLAN_DIR` ticks one plan. It collects every run in flight,
whoever's it is. It starts at most one skeleton call and one contract call
at a time, in units numbered by role. This task makes one tick take every
plan in `FAB_HOME/plans`. Each plan collects and limits only what its draft
owns, and shares the builders with the others. A plan runs design calls in
parallel up to its flow target. Design: `docs/design/fab.md`, 13.4, with
13.2, 13.3, 12 and 13.6.

It uses `fab/drafts.py` (task `drafts`), `fab.channel.plan_dirs` and
`fab.designer`, all on main by then. `designer-tick`, `channel-tick` and
`accounting` change `fab/dispatch.py`, `fab/calls.py` and `fab/cli.py`,
and they land first. Read their result, not this spec's picture of it. The
size gate holds every new or changed function to 60 lines, so put new
steps in private functions, as `tick-split` does. Update the docstring of
every function you change to say what it now does.

## What to build

- **`fab.dispatch.tick(*plan_dirs: Path, sh=run, hosts=None, log_path=None)
  -> list[Action]`.** The plans are `fab.channel.plan_dirs(plan_dirs)`.
  With no plans it prints `plans - none` and returns `[]`. Under the lock,
  as now:
  1. **Load** each directory in order, in a private function. Fetch each
     checkout root once per tick: several plans in one checkout share one
     `git fetch`. Then load as the tick does after `designer-tick`
     (plan.toml, or a plan being cut). A retired plan prints `retired
     <draft>` and is left out. A directory whose draft an earlier one
     already gave fails with `draft <draft> is already ticked from <dir>`.
     A PlanError, OSError, ValueError or `fab.sh.Failed` while fetching or
     loading gives `Action("load", task=str(<dir>), detail="failed:
     <error on one line>")`. It is printed as every action is, logs
     nothing, and the other plans still tick.
  2. When no plan loaded, return the actions so far. There is no import,
     no measure and no page.
  3. **One queue import** (`_import_queue`) over every loaded plan's tasks
     together, then **one `fab.flow.measure`**. The import keeps a cursor
     per draft, never one for the log: a draft's cursor is the newest
     `queue_ts` of the log's records whose task is the draft's
     (`fab.drafts.under`), or `""` when it has none. Its `since` is the
     oldest cursor of the loaded drafts. A record whose task is in no
     loaded plan is left, as now, and is read again on a later tick, so a
     plan that failed to load, or is newly listed, gets the records it
     missed when it next loads. The import's key, as now, keeps a record
     read twice from being logged twice. A draft with no imported record
     reads the queue's whole record each tick until its first one; that
     record is one short line per batch, landing and rejection.
  4. **Each plan in order** takes what one plan's tick takes today:
     decide, its actions, the foreman's, then the calls'. It decides on
     `log.read(log_path)` read at its turn, so the runs that earlier plans
     started fill the shared places. After each plan, `calm =
     fab.drafts.spend(calm, <the hosts of its start actions>)`.
  5. **Strays:** `Action("collect", ...)` for each record of
     `fab.drafts.strays(<the loaded drafts>, in_flight(events), events)`
     on a fresh read, taken as decide's collects are.
  6. **The page** (`channel-tick`'s step) is written once, after the
     strays, from `fab.channel.plan_dirs(plan_dirs)`.
  Return every action in order: the loads, each plan's, then the strays.
- **`decide`, step 1:** collect only `fab.drafts.owned(plan.draft, flight,
  events)`. Places still count every run in flight, which is how plans
  share builders.
- **`blocking`** gains the keyword `draft: str | None = None`. When it is
  given, only the draft's runs (`fab.drafts.owned`) count as moving.
  `call_actions` passes `draft=plan.draft`.
- **`call_actions`:**
  - The calls in flight, and the roles they reserve, are only those whose
    subject is the draft's (`fab.drafts.under`). One draft's answer,
    review or amend call never holds back another draft's.
  - Design: the skeleton and contract branches become one. For each
    `(part, role)` of `fab.drafts.design_calls(plan, fresh, events)`, add
    `Action("call", task=part, run_kind=role)`, in that order.
  - The review is due on the draft's own last review:
    `fab.calls.last_review(events, draft=plan.draft)`.
- **`_call`'s unit:** `fab.drafts.unit(role, key)`. The key is
  `<draft>/<part>` for skeleton and contract, and the action's task for
  every other role: the draft, a subject, or an amend's root. The
  per-role count goes, and `_call` takes the plan's draft.
- **`main`:** `fab tick [PLAN_DIR...] [--dry-run]` (nargs `*`) calls
  `tick(*plan_dirs)`. It exits 1 when an action is a failed load, after
  the other plans have ticked. `--dry-run` covers the same plans. Each is
  loaded as tick loads it, with no fetch: its load line, `retired
  <draft>`, or decide's actions on `log.read()` with `machines.load()` and
  no calm. Plans are not chained: each one decides on the same log.
- **`fab.calls.last_review`** gains the keyword `draft: str | None =
  None`. When it is given, only call.started records whose subject is
  `<draft>/review` count. `review_brief` passes `draft=plan.draft`.
- **`fab/cli.py`:** the tick's line reads `collect, land and start every
  plan's tasks`.

## Acceptance

Write the tests with `fab/tests/support.py`'s `write_plan`,
`run_started`, `run_ended`, `call_started`, `call_ended` and `units`, and
`fab.designer.enlist` to list a plan.

- `fab/tests/test_dispatch.py`, `tick` with `support.FakeRunner`:
  - two plans, one listed and one given, tick in that order;
  - two plans in one checkout make one fetch;
  - one queue import imports both drafts' records, its `since` the older
    of the two drafts' cursors;
  - recovery: plan `two`'s plan.toml does not parse for a tick in which
    `one` imports a record newer than `two`'s; when `two` loads again,
    the next tick imports `two`'s older record, once, and logs none of
    `one`'s again;
  - a plan newly listed beside one with imported records reads from `""`
    and imports its records older than the other's cursor;
  - one probe ssh per builder;
  - places are shared: a builder with one place and a runnable task in
    each plan starts only the first plan's;
  - a calm builder's extra place goes to the first plan only;
  - a plan.toml that does not parse gives its load line, and the other
    plan still ticks; `main` then exits 1;
  - a second directory of the same draft fails to load;
  - a retired plan among others is skipped;
  - with only a retired plan, there is no import and no page;
  - each plan collects only its own runs and its calls' review runs, and
    a stray is collected once, after the plans;
  - design calls in parallel: two fresh parts start two calls in one tick,
    with units `fab-call-skeleton-draft_<part>` (`support.units`);
  - with three fresh parts and START, two calls start; with one still in
    flight, the next tick starts one;
  - a contract call and a skeleton call share the limit;
  - draft `one`'s answer call in flight does not stop draft `two`'s answer
    call;
  - another draft's review call does not reset the review threshold;
  - `main` with two PLAN_DIRs, and `--dry-run` over two plans.
- `fab/tests/test_calls.py`: `last_review` with and without `draft`;
  `review_brief` lists what landed since its own draft's last done review.
- Existing tests change only where they pin a behaviour this task
  changes, and then to the new behaviour, keeping what they test where
  it still holds:
  - unit names: `fab.drafts.unit` for the per-role count;
  - one skeleton call (and one contract call) at a time: now design calls
    up to the flow target, skeleton and contract sharing it;
  - collection, `blocking`, the answer, review and amend limits and the
    review's last review counting every draft's runs and calls: now only
    the plan's own, so such a test gives its runs and calls the plan's
    draft, or asserts that another draft's do not count;
  - the queue import's `since`: now the oldest draft cursor;
  - a load failure that is now an action, not a raise. `designer-tick`'s
    "neither plan.toml nor a cut call" test is one of those.
  No other existing test changes. The commit names the tests changed and
  which of these each follows.
- `bin/fab test` passes. `test_dispatch.py` and `test_calls.py` stay
  within their budgets.

## Options, settled up front

- One lock for the whole tick, as now. A plan never ticks alone beside
  another tick.
- The flow target stays per plan. Sharing it across plans is Later
  (`docs/design/fab.md`, 14).
- A load failure logs no note. Since the tick runs every 2 minutes, a
  broken plan would fill the log. The printed line and the exit status are
  its record.
- Amend calls are not part of the design limit, and still go one at a
  time per draft.
- The live timer passes `docs/plan/agents-rebuild`. `plan_dirs` drops it
  when `FAB_HOME/plans` lists the same directory, so the unit needs no
  change.
