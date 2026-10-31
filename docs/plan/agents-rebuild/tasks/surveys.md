+++
id = "surveys"
part = "surveys"
kind = "feature"
needs = []
files = ["fab/surveys.py", "fab/tests/test_surveys.py"]
effort = "high"
minutes = 35
+++
# Survey runs: when one is due, its brief and start, its report for a call

Fill the bodies of `fab/surveys.py` as their docstrings say. Design:
`docs/design/fab.md`, 13.10, with 13.1 (read-only runs) and 5. The role
text the brief starts with is `fab/roles/surveyor.md`, written. Nothing
calls the module yet: `surveys-tick` makes the tick start surveys before
design calls and puts their reports in the briefs; the part `intake` starts
the cut's.

It uses what is on main: `fab.run.next_run`, `fab.run.launch_detached`
(as `fab.foreman.start` does), `fab.run.remote_home`, `fab.calls.inventory`,
`fab.calls.render_inventory` and `fab.calls._brief` (the section builder
`fab.designer` uses too), and `fab.report.minutes`. Import `fab.calls` and
`fab.run` at the module's top, as the skeleton does; neither imports
`fab.surveys` at its top, so there is no cycle.

Its tests speak in `fab/tests/support.py`'s vocabulary: `survey_started`,
`survey_ended`, `write_report`, `launcher`, with `call_started`,
`call_ended`, `write_plan` and `tmp_home`.

## What to fill

- `task_field` and `surveys`: a subject's survey runs, folded from the log.
- `due` and `ready`: whether a call of a role waits for a survey, and which
  topics to start.
- `brief` and `start`: one survey run on a builder.
- `section`: the surveys' reports as a call's brief quotes them.

## Acceptance

- `fab/tests/test_surveys.py`:
  - Remove the skip from the exemplar test. It passes unchanged.
  - `task_field`: a part's subject, the cut's, and a ValueError for "".
  - `surveys`: the join with run.ended; another subject's survey, a
    foreman run of a task named like the part (`one/core/foreman`) and a
    record without a topic are left out; a run.ended without its
    run.started is ignored; records missing fields do not raise.
  - `due` and `ready`:
    - nothing in the log: every topic of the role is due;
    - in flight: not due and not ready, even hours old;
    - ended done or failed within FRESH: ready; ended more than FRESH
      minutes before now: due;
    - a survey from before the subject's last skeleton, contract or cut
      call is due again; an amend, answer or review call of the subject
      does not count; another subject's call does not count;
    - the cut's three topics: one ended and two missing gives the two,
      in BEFORE's order; all three ended gives ready;
    - a ValueError for a role not in BEFORE.
  - `brief`: the five sections in order, for a part and for the cut; the
    topic's TOPICS text; `(none)` for an empty inventory; a ValueError for
    an unknown topic or part.
  - `start` with `support.launcher()` in a temporary FAB_HOME: the worktree
    added detached at origin/main, `fab codex start --effort medium --model
    <fab.run.MODEL> --read-only`, run.started's task, kind, topic, branch
    and base, the brief's copy in FAB_HOME/runs/<run>/brief.md, the second
    survey of a subject numbered 2; an unknown topic starts nothing.
  - `section`: a done report quoted; one longer than REPORT_LIMIT cut with
    its line; a failed survey's line; an unreadable report; a topic with
    no survey; the latest ended survey wins over an earlier one and over
    one still in flight.
- `bin/fab test` passes; `test_surveys.py` takes under a second.

## Options, settled up front

- One survey run per topic per call. An ended survey of any outcome lets
  the call start, so no call waits for a second survey run; the brief
  says what became of it.
- FRESH is 60 minutes: a survey whose call starts later than that is run
  again, so a part pushed back by a full buffer is not designed on an old
  survey.
- `due` and `ready` compare the survey's run.started with the subject's
  last design call by their positions in the log, not by ts.
- run.started's branch is `main` and its base `origin/main`: a survey has
  no branch of its own.
- The survey report is read from FAB_HOME/runs/<run>/report.md, where
  `fab.run.collect` copies it, as `fab.foreman.start` reads the asking run's.
