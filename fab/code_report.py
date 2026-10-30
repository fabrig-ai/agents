"""The code report: a plan's code-producing metrics from the log (docs/design/fab.md, 10).

The metrics are the code-producing draft's (docs/design/draft/code-producing-pipeline.md,
3) that the log records: flow, task size in runs and minutes, questions, repairs, waits and
Claude usage. Every function here is pure; `render` puts them together for one window.

A draft's records are those whose task is `<draft>/...`; its calls are those whose subject is
the draft or one of its plan's parts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from fab.hosts import Host
from fab.plan import Plan, Task
from fab.report import Figure, Signal, Sources, Window

IDLE_GAP = 10  # minutes with none of the draft's runs in flight, while work remains, that make a gap
TOP_STOPS = 10  # stops listed, longest first

FIGURES = (  # (key, label), in the report's order
    ("runs", "Codex runs started"),
    ("done", "runs ended Done"),
    ("question", "runs ended Question"),
    ("infra", "runs ended Infra"),
    ("failed", "runs ended Failed"),
    ("ready", "branches marked ready"),
    ("landed", "tasks landed"),
    ("rejected", "landings rejected"),
    ("peak", "peak runs in flight"),
    ("places", "Codex places on the builders"),
    ("codex_minutes", "Codex minutes, runs ended"),
    ("runs_per_task", "runs per landed task"),
    ("minutes_per_task", "Codex minutes per landed task"),
    ("questions", "questions asked"),
    ("question_rate", "questions per run ended"),
    ("answer_median", "minutes to answer, median"),
    ("answer_max", "minutes to answer, longest"),
    ("open", "questions open at the end"),
    ("idle_minutes", "minutes in idle gaps"),
    ("infra_minutes", "Codex minutes of runs ended Infra"),
    ("calls", "Claude calls ended"),
    ("call_minutes", "Claude call minutes"),
    ("input_tokens", "Claude input tokens"),
    ("output_tokens", "Claude output tokens"),
    ("lane_wait", "heavy lane wait minutes, builders"),
    ("disk_wait", "heavy disk wait minutes, builders"),
    ("disk_refused", "builds refused for disk"),
)


@dataclass(frozen=True)
class Span:
    run: str
    task: str
    kind: str
    start: str  # run.started's ts
    end: str | None  # run.ended's ts; None while in flight
    outcome: str | None  # run.ended's outcome


@dataclass(frozen=True)
class Hour:
    start: str  # the hour's first ts
    peak: int  # most of the draft's runs in flight at once within the hour
    started: int  # run.started
    ready: int  # branch.ready
    landed: int  # branch.landed


@dataclass(frozen=True)
class Gap:
    start: str
    minutes: float
    cause: str  # the not-landed tasks' statuses at its start: "parked 2, runnable 1"


@dataclass(frozen=True)
class Stop:
    kind: str  # question, failed, infra or rejected
    task: str
    start: str
    minutes: float
    open: bool  # still unresolved at the window's end
    detail: str


def spans(draft: str, events: list[dict]) -> list[Span]:
    """One Span per run.started of the draft's tasks, in log order, with the first run.ended of
    the same run after it (end and outcome), or end and outcome None."""
    raise NotImplementedError


def peak(runs: list[Span], start: str, end: str) -> int:
    """The most spans in flight at one instant within [start, end). A span is in flight over
    [span.start, span.end), or from span.start on when end is None; at a ts where one ends and
    another starts, the one ending counts as gone."""
    raise NotImplementedError


def hourly(draft: str, events: list[dict], window: Window) -> list[Hour]:
    """One Hour per whole UTC hour from the window's start (the last one cut at the window's
    end): peak over spans(draft, events) within it, and the counts of the draft's run.started,
    branch.ready and branch.landed whose ts it holds."""
    raise NotImplementedError


def gaps(plan: Plan, tasks: Mapping[str, Task], events: list[dict], window: Window) -> list[Gap]:
    """The idle gaps within the window, in order: each maximal interval of the window with none
    of spans(plan.draft, events) in flight, IDLE_GAP minutes or longer (one still open at the
    window's end is cut there), counted only when at its start some task is not landed by
    fab.state.fold(tasks, <events with ts before the start>). cause: the counts of those
    not-landed statuses, `<status> <n>` joined by ", ", most first, then by name."""
    raise NotImplementedError


def stops(draft: str, events: list[dict], window: Window) -> list[Stop]:
    """What stopped the draft's tasks, from events whose ts the window holds, longest first
    (then by start), the first TOP_STOPS:
    - question: a question.asked, until the task's next question.answered; detail its text's
      first line, cut to 80 characters.
    - failed: a run.ended with outcome failed, until the task's next run.started; detail the
      report path.
    - infra: a run.ended with outcome infra, for its own minutes; detail the run; never open.
    - rejected: a branch.rejected, until the task's next branch.landed; detail its step.
    With no such later event before the window's end, minutes run to the end and open is True."""
    raise NotImplementedError


def figures(plan: Plan, tasks: Mapping[str, Task], events: list[dict],
            heavy: Mapping[str, list[dict]], hosts: Mapping[str, Host], window: Window) -> dict[str, Figure]:
    """Every FIGURES key for the window, from the draft's events whose ts it holds:
    - runs: run.started. done, question, infra, failed: run.ended by outcome.
    - ready, landed, rejected: branch.ready, branch.landed, branch.rejected.
    - peak: peak over spans(plan.draft, events) within the window. places: the places of the
      hosts with role builder, summed.
    - codex_minutes: run.ended minutes summed. infra_minutes: those with outcome infra.
    - runs_per_task, minutes_per_task: for the tasks with a branch.landed in the window, their
      run.started count and run.ended minutes over the whole log, divided by how many they
      are; None when none landed.
    - questions: question.asked. question_rate: questions over run.ended; None when no run
      ended.
    - answer_median, answer_max: for each question.answered, the minutes since the task's
      latest question.asked before it; fab.report.quantile 0.5 and the largest; None when none.
    - open: fab.calls.open_questions over the events before the window's end, the draft's only.
    - idle_minutes: the minutes of gaps(plan, tasks, events, window), summed.
    - calls, call_minutes: the draft's call.ended and their minutes summed. input_tokens,
      output_tokens: from call.ended tokens `in/cached/out`, input being in plus cached; a
      malformed value adds 0.
    - lane_wait, disk_wait, disk_refused: fab.report.heavy_waits over the hosts with role
      builder.
    Counts are ints, minutes and rates floats."""
    raise NotImplementedError


def parts(plan: Plan, tasks: Mapping[str, Task], events: list[dict], window: Window) -> list[tuple]:
    """One row per part of the plan that has tasks, in the plan's order: (part id, its tasks,
    those landed by fab.state.fold over the whole log, its run.started in the window, its
    run.ended minutes in the window rounded to one decimal, its question.asked in the
    window)."""
    raise NotImplementedError


def signals(current: Mapping[str, Figure], previous: Mapping[str, Figure],
            unread: list[str]) -> list[Signal]:
    """The draft's signals (code-producing-pipeline.md, 4) that need no target, in this order:
    - idle_minutes above 0: `<n> minutes in idle gaps`; "its cause: a missing pre-approved list,
      a parked task, no free place"; "the dispatcher's keeper".
    - rejected above 0 and above previous: `rejections rising: <n> (prev <m>)`; "readers'
      tests before ready; the precheck; the task's scope"; "the skeleton author; ops".
    - infra or disk_refused above 0: `<n> runs ended Infra, <m> builds refused for disk`;
      "capacity: bounded slots, more or bigger builders"; "ops".
    - each unread source: `unread: <entry>`; "the report is partial: the machine's ssh and fab
      install"; "ops".
    A None figure counts as 0."""
    raise NotImplementedError


def render(plan: Plan, tasks: Mapping[str, Task], sources: Sources, hosts: Mapping[str, Host],
           window: Window) -> str:
    """The report as Markdown, ending with a newline:
    - `# Code report: <draft>, <the window's start day>`; a line `<start> to <end>; each figure
      beside the previous window's.`; a line `First run <ts>; first landing <ts>, <m> minutes
      later.` over the whole log (`No run yet.` or `No landing yet.` in its place).
    - `## Figures`: fab.report.figure_table(FIGURES, figures for the window, figures for
      window.previous()).
    - `## Signals`: fab.report.signal_lines(signals(...)).
    - `## Hours`: a table Hour (`HH:00`), In flight, Started, Ready, Landed from hourly.
    - `## Idle gaps`: a table Start, Minutes, Cause from gaps.
    - `## Stops, longest first`: a table Kind, Task, Start, Minutes, Open (yes or no), Detail
      from stops.
    - `## Parts`: a table Part, Tasks, Landed, Runs, Codex minutes, Questions from parts.
    - `## Rejections by step`: a table Step, Count of the window's branch.rejected by step,
      most first, then by step.
    Minutes are shown through fab.report.show; sections are separated by one blank line."""
    raise NotImplementedError
