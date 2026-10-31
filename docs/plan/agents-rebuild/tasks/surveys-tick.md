+++
id = "surveys-tick"
part = "surveys"
kind = "interface"
needs = ["surveys", "plans-tick", "repairs-tick"]
files = ["fab/dispatch.py", "fab/calls.py", "fab/designer.py", "fab/tests/test_dispatch.py", "fab/tests/test_calls.py", "fab/tests/test_designer.py"]
effort = "high"
minutes = 45
+++
# A survey before each design call, its report in the call's brief

Today the tick starts a skeleton or contract call as soon as its part is
eligible, and the brief carries only the code-built inventory. This task
makes the tick run one survey (`fab/surveys.py`, task `surveys`) before
each skeleton and contract call, and puts the surveys' reports into the
skeleton, contract and cut briefs. Design: `docs/design/fab.md`, 13.10,
with 13.4 and 13.1.

`plans-tick` rewrites `call_actions`, `_call` and `tick`, and `repairs-tick`
changes `decide` and `_take`; both land first. Read their result, not this
spec's picture of it. The size gate holds every new or changed function to
60 lines, so put new steps in private functions. Update the docstring of
every function you change to say what it now does.

## What to build

- **`fab.dispatch.call_actions`, design calls:** for each `(part, role)` of
  `fab.drafts.design_calls(plan, fresh, events)`, in that order, with
  subject `<draft>/<part>`:
  - `fab.surveys.ready(subject, role, events, now)`: `Action("call",
    task=part, run_kind=role)`, as now;
  - else one `Action("survey", task=subject, run_kind=role, detail=topic)`
    per topic of `fab.surveys.due(subject, role, events, now)`;
  - else nothing: its survey is in flight. The part stays in `fresh`, so
    it keeps its place among the design calls until its call starts.
- **`_take`, case `survey`:** a private `_survey(action, plan, checkout,
  hosts, sh=, log_path=)` starts `fab.surveys.start(plan, action.task,
  action.detail, checkout, host, events, part=<the subject after the
  draft's slash>)` on `_builder(hosts, events)` (most free places, even at
  none, since it builds nothing), events a fresh `log.read(log_path)`. It
  returns `<topic> <run> <host>` as the printed detail. The Action kind
  comment gains `survey`.
- **Collection needs no change:** a survey's task is under its draft, so
  `fab.drafts.owned` gives it to its plan and decide collects it at the
  start of the next tick; the call then starts in that same tick.
- **Briefs:** `fab.calls.skeleton_brief` and `fab.designer.cut_brief` gain
  the keyword `surveys: str = "(none)"`, a section `fab.surveys.SECTION`
  holding it right after `Inventory`. `fab.calls.main` (skeleton) passes
  `fab.surveys.section(<subject>, "skeleton", events)`; `fab.designer.main`
  passes `section(<subject>, "contract", events)` for contract and
  `section(designer.subject(draft, "cut"), "cut", events)` for cut, events
  read once with `log.read()`. `--brief-only` shows the same section.
  `fab.surveys` imports `fab.calls` at its top, so `fab.calls` imports
  `fab.surveys` inside `main`, as it imports `call_review` and `designer`;
  `fab.designer` and `fab.dispatch` import it at their top.

## Acceptance

Write the tests with `fab/tests/support.py`'s `write_plan`,
`survey_started`, `survey_ended`, `write_report`, `call_started`,
`call_ended` and `units`.

- `fab/tests/test_dispatch.py`:
  - `call_actions` as a pure function: a fresh part with no survey gives
    one survey action and no call; with its survey in flight, nothing;
    with it ended (done, and failed) within FRESH, the call; ended longer
    ago, a survey again; after the part's call ended `Question:` and was
    answered, a survey before the next call; two fresh parts at the
    flow's start give two survey actions; a contract part's survey and
    call carry role contract.
  - `tick` with `support.FakeRunner`: a survey starts on the builder with
    most free places, read-only at medium effort, and prints `survey
    <subject> primitives <run> <host>`; on the next tick its run is
    collected and the skeleton call's unit starts in the same tick.
- `fab/tests/test_calls.py`: `skeleton_brief` with and without `surveys`
  (the section after Inventory, `(none)` by default); `main skeleton
  --brief-only` quotes the subject's latest survey report.
- `fab/tests/test_designer.py`: `cut_brief` with `surveys`; `main cut
  --brief-only` and `main contract --brief-only` quote their surveys.
- Existing tests change only where they pin a design call starting at
  once: they now give the part an ended survey (`survey_started`,
  `survey_ended`) or assert the survey action first. The commit names the
  tests changed.
- `bin/fab test` passes; the touched test modules stay within their
  budgets.

## Options, settled up front

- Surveys go before skeleton and contract calls only (`fab.surveys.BEFORE`);
  amend, answer, review and retire calls have none. The cut's surveys are
  the part `intake`'s to start; until then the cut's brief says `(no
  survey)` per topic.
- A survey run counts among its draft's runs in flight, as a foreman run
  does: it holds a Codex place on its builder.
- A survey that fails to start is a failed action, as any: a note, and the
  next tick tries again.
