"""The code report: a plan's code-producing metrics from the log (docs/design/fab.md, 10).

The metrics are the code-producing draft's (docs/design/draft/code-producing-pipeline.md,
3) that the log records: flow, task size in runs and minutes, questions, repairs, waits and
Claude and Codex usage (fab.accounting). Every function here is pure; `render` puts them together for one window.

A draft's records are those whose task is `<draft>/...`; its calls and their review runs are
fab.accounting's draft_calls and draft_runs.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from fab import accounting, report
from fab.calls import open_questions
from fab.hosts import Host
from fab.plan import Plan, Task
from fab.report import Figure, Signal, Sources, Window
from fab.state import fold

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
    *accounting.FIGURES,
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
    endings = {}
    runs = []
    for event in reversed(events):
        if event.get("ev") == "run.ended":
            endings[event["run"]] = event
        elif event.get("ev") == "run.started" and _belongs(draft, event):
            ended = endings.get(event["run"], {})
            runs.append(Span(event["run"], event["task"], event.get("kind", ""),
                             event["ts"], ended.get("ts"), ended.get("outcome")))
    return list(reversed(runs))


def peak(runs: list[Span], start: str, end: str) -> int:
    """The most spans in flight at one instant within [start, end). A span is in flight over
    [span.start, span.end), or from span.start on when end is None; at a ts where one ends and
    another starts, the one ending counts as gone."""
    changes = Counter()
    for run in runs:
        left, right = max(start, run.start), min(end, run.end or end)
        if left < right:
            changes[left] += 1
            changes[right] -= 1
    active = most = 0
    for ts in sorted(changes):
        active += changes[ts]
        most = max(most, active)
    return most


def hourly(draft: str, events: list[dict], window: Window) -> list[Hour]:
    """One Hour per whole UTC hour from the window's start (the last one cut at the window's
    end): peak over spans(draft, events) within it, and the counts of the draft's run.started,
    branch.ready and branch.landed whose ts it holds."""
    runs = spans(draft, events)
    records = [event for event in report.within(events, window) if _belongs(draft, event)]
    hours = []
    start = window.start
    while start < window.end:
        hour = int(start[11:13])
        if hour < 23:
            boundary = f"{start[:11]}{hour + 1:02}:00:00.000Z"
        else:
            tomorrow = date.fromisoformat(start[:10]) + timedelta(days=1)
            boundary = f"{tomorrow.isoformat()}T00:00:00.000Z"
        end = min(boundary, window.end)
        counts = Counter(event["ev"] for event in records if start <= event["ts"] < end)
        hours.append(Hour(start, peak(runs, start, end), counts["run.started"],
                          counts["branch.ready"], counts["branch.landed"]))
        start = end
    return hours


def gaps(plan: Plan, tasks: Mapping[str, Task], events: list[dict], window: Window) -> list[Gap]:
    """The idle gaps within the window, in order: each maximal interval of the window with none
    of spans(plan.draft, events) in flight, IDLE_GAP minutes or longer (one still open at the
    window's end is cut there), counted only when at its start some task is not landed by
    fab.state.fold(tasks, <events with ts before the start>). cause: the counts of those
    not-landed statuses, `<status> <n>` joined by ", ", most first, then by name."""
    occupied = sorted((max(window.start, run.start), min(window.end, run.end or window.end))
                      for run in spans(plan.draft, events)
                      if run.start < window.end and (run.end is None or run.end > window.start))
    idle = []
    cursor = window.start
    for start, end in occupied:
        if start >= end:
            continue
        if cursor < start:
            idle.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < window.end:
        idle.append((cursor, window.end))
    result = []
    for start, end in idle:
        duration = report.minutes(start, end)
        if duration < IDLE_GAP:
            continue
        views = fold(tasks, (event for event in events if event["ts"] < start))
        counts = Counter(view.status for view in views.values() if view.status != "landed")
        if counts:
            cause = ", ".join(f"{status} {count}" for status, count in
                              sorted(counts.items(), key=lambda item: (-item[1], item[0])))
            result.append(Gap(start, duration, cause))
    return result


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
    result = []
    for index, event in enumerate(events):
        if not _belongs(draft, event) or not window.holds(event["ts"]):
            continue
        kind, closing, detail = "", "", ""
        if event["ev"] == "question.asked":
            kind, closing = "question", "question.answered"
            detail = event["text"].split("\n", 1)[0][:80]
        elif event["ev"] == "run.ended" and event.get("outcome") == "failed":
            kind, closing, detail = "failed", "run.started", event["report"]
        elif event["ev"] == "run.ended" and event.get("outcome") == "infra":
            result.append(Stop("infra", event["task"], event["ts"],
                               float(event.get("minutes", 0)), False, event["run"]))
            continue
        elif event["ev"] == "branch.rejected":
            kind, closing, detail = "rejected", "branch.landed", event["step"]
        if not kind:
            continue
        ended = next((later for later in events[index + 1:]
                      if later.get("task") == event["task"] and later.get("ev") == closing
                      and later["ts"] < window.end), None)
        end = ended["ts"] if ended is not None else window.end
        result.append(Stop(kind, event["task"], event["ts"],
                           report.minutes(event["ts"], end), ended is None, detail))
    return sorted(result, key=lambda stop: (-stop.minutes, stop.start))[:TOP_STOPS]


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
    - the keys of fab.accounting.FIGURES: fab.accounting.figures(plan.draft, events,
      window), which reads its own records (the draft's calls and Codex runs).
    - lane_wait, disk_wait, disk_refused: fab.report.heavy_waits over the hosts with role
      builder.
    Counts are ints, minutes and rates floats."""
    history = [event for event in events if _belongs(plan.draft, event)]
    records = report.within(history, window)
    counts = Counter(event["ev"] for event in records)
    ended = [event for event in records if event["ev"] == "run.ended"]
    outcomes = Counter(event.get("outcome") for event in ended)
    landed = {event["task"] for event in records if event["ev"] == "branch.landed"}
    task_runs = [event for event in history if event["task"] in landed]
    answers, latest = [], {}
    for event in history:
        if event["ev"] == "question.asked":
            latest[event["task"]] = event["ts"]
        elif event["ev"] == "question.answered" and window.holds(event["ts"]):
            if event["task"] in latest:
                answers.append(report.minutes(latest[event["task"]], event["ts"]))
    builders = [name for name, host in hosts.items() if "builder" in host.roles]
    waits = report.heavy_waits(heavy, builders, window)
    return {
        "runs": counts["run.started"],
        **{outcome: outcomes[outcome] for outcome in ("done", "question", "infra", "failed")},
        "ready": counts["branch.ready"],
        "landed": counts["branch.landed"],
        "rejected": counts["branch.rejected"],
        "peak": peak(spans(plan.draft, events), window.start, window.end),
        "places": sum(hosts[name].places for name in builders),
        "codex_minutes": _run_minutes(ended),
        "runs_per_task": sum(event["ev"] == "run.started" for event in task_runs) / len(landed)
                         if landed else None,
        "minutes_per_task": _run_minutes(task_runs) / len(landed) if landed else None,
        "questions": counts["question.asked"],
        "question_rate": counts["question.asked"] / len(ended) if ended else None,
        "answer_median": report.quantile(answers, 0.5),
        "answer_max": max(answers, default=None),
        "open": len(open_questions(event for event in history if event["ts"] < window.end)),
        "idle_minutes": sum((gap.minutes for gap in gaps(plan, tasks, events, window)), 0.0),
        "infra_minutes": _run_minutes(event for event in ended if event.get("outcome") == "infra"),
        **accounting.figures(plan.draft, events, window),
        **{key: waits[key] for key in ("lane_wait", "disk_wait", "disk_refused")},
    }


def parts(plan: Plan, tasks: Mapping[str, Task], events: list[dict], window: Window) -> list[tuple]:
    """One row per part of the plan that has tasks, in the plan's order: (part id, its tasks,
    those landed by fab.state.fold over the whole log, its run.started in the window, its
    run.ended minutes in the window rounded to one decimal, its question.asked in the
    window)."""
    views = fold(tasks, events)
    records = report.within(events, window)
    rows = []
    for part in plan.parts:
        identifiers = {task.id for task in tasks.values() if task.part == part}
        if not identifiers:
            continue
        history = [event for event in records if event.get("task") in identifiers]
        rows.append((part, len(identifiers),
                     sum(views[identifier].status == "landed" for identifier in identifiers),
                     sum(event["ev"] == "run.started" for event in history),
                     round(_run_minutes(history), 1),
                     sum(event["ev"] == "question.asked" for event in history)))
    return rows


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
    result = []
    idle, rejected = current.get("idle_minutes") or 0, current.get("rejected") or 0
    before = previous.get("rejected") or 0
    infra, refused = current.get("infra") or 0, current.get("disk_refused") or 0
    if idle > 0:
        result.append(Signal(f"{report.show(idle)} minutes in idle gaps",
                             "its cause: a missing pre-approved list, a parked task, no free place",
                             "the dispatcher's keeper"))
    if rejected > 0 and rejected > before:
        result.append(Signal(f"rejections rising: {report.show(rejected)} (prev {report.show(before)})",
                             "readers' tests before ready; the precheck; the task's scope",
                             "the skeleton author; ops"))
    if infra > 0 or refused > 0:
        result.append(Signal(f"{report.show(infra)} runs ended Infra, "
                             f"{report.show(refused)} builds refused for disk",
                             "capacity: bounded slots, more or bigger builders", "ops"))
    result.extend(Signal(f"unread: {entry}",
                         "the report is partial: the machine's ssh and fab install", "ops")
                  for entry in unread)
    return result


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
    - `## Calls`: a table Call, Role, Subject, Minutes, Turns, Peak context, Weight (M),
      Over target from fab.accounting.call_rows, numbers through fab.report.show.
    - `## Rejections by step`: a table Step, Count of the window's branch.rejected by step,
      most first, then by step.
    Minutes are shown through fab.report.show; sections are separated by one blank line."""
    events = sources.log
    current = figures(plan, tasks, events, sources.heavy, hosts, window)
    previous = figures(plan, tasks, events, sources.heavy, hosts, window.previous())
    history = [event for event in events if _belongs(plan.draft, event)]
    first_run = next((event["ts"] for event in history if event["ev"] == "run.started"), None)
    first_landing = next((event["ts"] for event in history if event["ev"] == "branch.landed"), None)
    if first_run is None:
        first = "No run yet."
    elif first_landing is None:
        first = f"First run {first_run}; No landing yet."
    else:
        first = (f"First run {first_run}; first landing {first_landing}, "
                 f"{report.show(report.minutes(first_run, first_landing))} minutes later.")
    sections = [
        [f"# Code report: {plan.draft}, {window.start[:10]}",
         f"{window.start} to {window.end}; each figure beside the previous window's.", first],
        ["## Figures", *report.figure_table(FIGURES, current, previous)],
        ["## Signals", *report.signal_lines(signals(current, previous, sources.unread))],
        ["## Hours", *report.table(("Hour", "In flight", "Started", "Ready", "Landed"),
            ((hour.start[11:13] + ":00", hour.peak, hour.started, hour.ready, hour.landed)
             for hour in hourly(plan.draft, events, window)))],
        ["## Idle gaps", *report.table(("Start", "Minutes", "Cause"),
            ((gap.start, report.show(gap.minutes), gap.cause)
             for gap in gaps(plan, tasks, events, window)))],
        ["## Stops, longest first", *report.table(("Kind", "Task", "Start", "Minutes", "Open", "Detail"),
            ((stop.kind, stop.task, stop.start, report.show(stop.minutes),
              "yes" if stop.open else "no", stop.detail)
             for stop in stops(plan.draft, events, window)))],
        ["## Parts", *report.table(("Part", "Tasks", "Landed", "Runs", "Codex minutes", "Questions"),
            ((*row[:4], report.show(row[4]), row[5]) for row in parts(plan, tasks, events, window)))],
        ["## Calls", *report.table(("Call", "Role", "Subject", "Minutes", "Turns", "Peak context",
                                   "Weight (M)", "Over target"),
            ((*row[:3], *(report.show(value) for value in row[3:7]), row[7])
             for row in accounting.call_rows(plan.draft, events, window)))],
    ]
    rejections = Counter(event.get("step", "") for event in report.within(history, window)
                         if event["ev"] == "branch.rejected")
    sections.append(["## Rejections by step", *report.table(("Step", "Count"),
                     sorted(rejections.items(), key=lambda item: (-item[1], item[0])))])
    return "\n\n".join("\n".join(section) for section in sections) + "\n"


def _belongs(draft: str, event: dict) -> bool:
    return event.get("task", "").startswith(draft + "/")


def _run_minutes(events: Iterable[dict]) -> float:
    return sum((float(event.get("minutes", 0)) for event in events
                if event["ev"] == "run.ended"), 0.0)
