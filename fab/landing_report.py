"""The landing report: the merge queue's metrics from its record (docs/design/fab.md, 10).

The metrics are the landing draft's (docs/design/draft/landing-pipeline.md, 3) that the
queue's record holds: its `batch`, `landed` and `rejected` records (fab.queue.Queue.attempt),
joined with the log's branch.ready for latency, and heavy's records on the gate machine.
The log also supplies after-landing red routes, settlements, repairs and closures, and
hand-pushed rejections; their open signals follow the user's page. QA records supply
walk verdicts, findings, triage decisions, repair landings and time to a rung's next pass.
Every function here is pure; `render` puts them together for one window.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

from fab import channel, tier_reds
from fab.gate import NO_TESTS
from fab.hosts import Host
from fab.report import (Figure, Signal, Sources, Window, figure_table, heavy_waits, minutes,
                        quantile, show, signal_lines, table, within)

FIGURES = (  # (key, label), in the report's order
    ("batches", "batches"),
    ("batches_per_hour", "batches per hour"),
    ("branches_per_batch", "branches per batch"),
    ("utilisation", "share of the window in gate steps, %"),
    ("green", "batches green"),
    ("red", "batches red"),
    ("conflict", "batches with a conflict"),
    ("error", "batches in error"),
    ("red_share", "share of batches red, %"),
    ("landed", "branches landed"),
    ("rejected", "branches rejected"),
    ("collateral", "rejections later landed unchanged"),
    ("false_red_rate", "false-red rate, %"),
    ("retried", "branches retried after a collateral red"),
    ("reused", "batches landed on a precheck receipt"),
    ("latency_median", "minutes ready to landed, median"),
    ("latency_p90", "minutes ready to landed, 90th percentile"),
    ("waiting", "ready branches waiting at the end"),
    ("oldest_wait", "oldest wait at the end, minutes"),
    ("bisections", "red batches bisected"),
    ("bisection_runs", "extra batches in bisection"),
    ("bisection_minutes", "minutes of gate steps in bisection"),
    ("repair_rounds", "rejections per landed branch"),
    ("repair_minutes", "minutes from last rejection to landing, median"),
    ("lane_wait", "heavy lane wait minutes, gate"),
    ("disk_wait", "heavy disk wait minutes, gate"),
    ("reds_opened", "after-landing reds opened"),
    ("reds_foreman", "after-landing reds sent to a foreman"),
    ("reds_page", "after-landing reds sent to the page"),
    ("reds_fix", "after-landing reds settled fix"),
    ("reds_none", "after-landing reds settled none"),
    ("reds_left", "after-landing reds settled left"),
    ("red_repairs_landed", "red repairs landed"),
    ("reds_closed", "after-landing reds closed"),
    ("reds_closed_recovered", "after-landing reds closed recovered"),
    ("reds_closed_absent", "after-landing reds closed absent"),
    ("reds_closed_cleared", "after-landing reds closed cleared"),
    ("red_recovery_hours", "hours opened to recovered, median"),
    ("hand_rejected", "hand-pushed rejections"),
    ("walks_pass", "walks ended pass"),
    ("walks_fail", "walks ended fail"),
    ("walks_void", "walks ended void"),
    ("findings_raised", "findings raised"),
    ("findings_merged", "findings merged"),
    ("triaged_path", "findings triaged path"),
    ("triaged_backlog", "findings triaged backlog"),
    ("triaged_user", "findings triaged user"),
    ("triaged_brief", "findings triaged brief"),
    ("triaged_drop", "findings triaged drop"),
    ("triaged_again", "findings triaged again"),
    ("finding_repairs_landed", "finding repairs landed"),
    ("rungs_passed", "rungs passed"),
    ("walk_pass_hours", "hours failed walk to rung passed, median"),
)


@dataclass(frozen=True)
class StepRun:
    name: str
    code: int
    seconds: float
    green: bool  # as fab.gate.run_steps decides: code 0, or NO_TESTS for build, default, fuzzy


@dataclass(frozen=True)
class Wait:
    branch: str
    tip: str
    since: str  # its branch.ready's ts
    minutes: float  # to the window's end


@dataclass(frozen=True)
class Bisection:
    start: str  # the red batch's ts
    branches: int  # in the red batch
    runs: int  # the batches after it that split it
    minutes: float  # their steps' seconds, in minutes


def steps(batch: dict) -> list[StepRun]:
    """The batch record's steps, each "name:code:seconds" split at its last two colons, in order;
    an entry that does not split into a name, an int and a float is skipped."""
    result = []
    for entry in batch.get("steps", []):
        try:
            name, code, seconds = entry.rsplit(":", 2)
            code, seconds = int(code), float(seconds)
        except (AttributeError, TypeError, ValueError):
            continue
        green = code == 0 or (name in ("build", "default", "fuzzy") and code == NO_TESTS)
        result.append(StepRun(name, code, seconds, green))
    return result


def busy_seconds(batch: dict) -> float:
    """The seconds of the batch's steps, summed: the time it held the gate lane, as recorded."""
    return sum((step.seconds for step in steps(batch)), 0.0)


def latencies(events: list[dict], queue: list[dict], window: Window) -> list[float]:
    """For each queue `landed` record in the window, the minutes since the latest branch.ready
    in events with the same branch and tip at or before it, in the records' order; a landed
    branch with no such branch.ready (marked ready by hand) is left out."""
    ready = {}
    for event in events:
        if event.get("ev") == "branch.ready":
            key = (event["branch"], event["tip"])
            ready.setdefault(key, []).append(event["ts"])
    result = []
    for record in within(queue, window):
        if record.get("ev") != "landed":
            continue
        starts = [ts for ts in ready.get((record["branch"], record["tip"]), [])
                  if ts <= record["ts"]]
        if starts:
            result.append(minutes(max(starts), record["ts"]))
    return result


def waiting(events: list[dict], queue: list[dict], window: Window) -> list[Wait]:
    """The ready branches waiting at the window's end, oldest first: per branch, its latest
    branch.ready in events before the end, when no queue `landed` or `rejected` record for that
    branch and tip comes before the end."""
    latest = {}
    for event in events:
        if event.get("ev") != "branch.ready" or event["ts"] >= window.end:
            continue
        branch = event["branch"]
        if branch not in latest or event["ts"] >= latest[branch]["ts"]:
            latest[branch] = event
    resolved = {(record["branch"], record["tip"]) for record in queue
                if record.get("ev") in ("landed", "rejected") and record["ts"] < window.end}
    return [Wait(event["branch"], event["tip"], event["ts"], minutes(event["ts"], window.end))
            for event in sorted(latest.values(), key=lambda event: event["ts"])
            if (event["branch"], event["tip"]) not in resolved]


def bisections(queue: list[dict], window: Window) -> list[Bisection]:
    """The window's batch records in ts order; a red one with more than one branch starts a
    bisection, and each following batch whose branches are a non-empty subset of its branches
    is one of its runs; the first batch that is not ends it (and may start the next)."""
    result = []
    active = None
    branches = set()
    runs, seconds = 0, 0.0
    batches = sorted((record for record in within(queue, window) if record.get("ev") == "batch"),
                     key=lambda record: record["ts"])
    for batch in batches:
        group = set(batch.get("branches", []))
        if active is not None:
            if group and group <= branches:
                runs += 1
                seconds += busy_seconds(batch)
                continue
            result.append(Bisection(active, len(branches), runs, seconds / 60))
            active = None
        if batch.get("outcome") == "red" and len(group) > 1:
            active, branches = batch["ts"], group
            runs, seconds = 0, 0.0
    if active is not None:
        result.append(Bisection(active, len(branches), runs, seconds / 60))
    return result


def step_rows(queue: list[dict], window: Window) -> list[tuple]:
    """One row per step name over the window's batches, by first appearance: (name, runs,
    failures (not green), timeouts (code 124), median seconds, 90th percentile seconds,
    largest seconds), seconds through fab.report.quantile and rounded to one decimal."""
    grouped = {}
    for record in within(queue, window):
        if record.get("ev") == "batch":
            for step in steps(record):
                grouped.setdefault(step.name, []).append(step)
    rows = []
    for name, runs in grouped.items():
        seconds = [step.seconds for step in runs]
        rows.append((name, len(runs), sum(not step.green for step in runs),
                     sum(step.code == 124 for step in runs), round(quantile(seconds, 0.5), 1),
                     round(quantile(seconds, 0.9), 1), round(max(seconds), 1)))
    return rows


def _repairs(landed: list[dict], rejections: dict[str, list[str]]) -> tuple[int, list[float]]:
    """Earlier rejections counted per landed branch and minutes since each last rejection."""
    rounds, repairs = 0, []
    for record in landed:
        earlier = [ts for ts in rejections.get(record["branch"], []) if ts < record["ts"]]
        rounds += len(earlier)
        if earlier:
            repairs.append(minutes(max(earlier), record["ts"]))
    return rounds, repairs


def _red_figures(events: list[dict], window: Window) -> dict[str, Figure]:
    """Count the tick's red decisions in the window, retaining earlier opening times.

    Page routes use the red fold's signal_ts for openings, left settlements and unfixed
    repairs, even after closing. Queue rejections and repair landings use queue_ts when
    present, including records imported after the window. Other decisions use ts.
    Recovery uses the reports' nearest-rank median, in hours. Future decisions do not count.
    """
    queue_records = []
    for event in events:
        stamp = event.get("queue_ts", event.get("ts"))
        if isinstance(stamp, str) and window.holds(stamp):
            queue_records.append(event)
    events = [event for event in events if isinstance(event.get("ts"), str)
              and event["ts"] < window.end]
    folded = tier_reds.reds(events)
    by_id = {red.id: red for red in folded}
    opened = [red for red in folded if window.holds(red.at)]
    records = within(events, window)
    settled = Counter(event.get("verdict") for event in records
                      if event.get("ev") == tier_reds.SETTLED)
    closed = Counter(event.get("reason") for event in records
                     if event.get("ev") == tier_reds.CLOSED)
    recoveries = [minutes(by_id[event["red"]].at, event["ts"]) / 60
                  for event in records if event.get("ev") == tier_reds.CLOSED
                  and event.get("reason") == "recovered" and event.get("red") in by_id]
    repairs = {red.task for red in folded if red.repair}
    return {
        "reds_opened": len(opened),
        "reds_foreman": sum(red.route == "foreman" for red in opened),
        "reds_page": sum(bool(red.signal_ts) and window.holds(red.signal_ts) for red in folded),
        "reds_fix": settled["fix"],
        "reds_none": settled["none"],
        "reds_left": settled["left"],
        "red_repairs_landed": sum(event.get("ev") == "branch.landed"
                                  and event.get("task") in repairs for event in queue_records),
        "reds_closed": sum(closed.values()),
        "reds_closed_recovered": closed["recovered"],
        "reds_closed_absent": closed["absent"],
        "reds_closed_cleared": closed["cleared"],
        "red_recovery_hours": quantile(recoveries, 0.5),
        "hand_rejected": sum(event.get("ev") == "queue.rejected" for event in queue_records),
    }


def _qa_figures(events: list[dict], window: Window) -> dict[str, Figure]:
    """Count raw QA records by ts in the window (docs/design/fab.md, 10).

    Join failed walk endings to their starts' draft and rung, then to that rung's
    next pass in log order. Include failures before the window for passes within it;
    leave failures without a later pass out. Hours use the report's nearest-rank median.
    """
    records = within(events, window)
    kinds = Counter(event.get("ev") for event in records)
    verdicts = Counter(event.get("verdict") for event in records
                       if event.get("ev") == "walk.ended")
    decisions = Counter(event.get("decision") for event in records
                        if event.get("ev") == "finding.triaged")
    walks, failures, hours = {}, {}, []
    for event in events:
        kind = event.get("ev")
        if kind == "walk.started":
            walks[event["walk"]] = (event["draft"], event["rung"])
        elif kind == "walk.ended" and event.get("verdict") == "fail":
            rung = walks.get(event.get("walk"))
            if rung is not None:
                failures.setdefault(rung, []).append(event["ts"])
        elif kind == "rung.passed":
            starts = failures.pop((event["draft"], event["rung"]), [])
            if window.holds(event["ts"]):
                hours.extend(minutes(start, event["ts"]) / 60 for start in starts)
    return {
        "walks_pass": verdicts["pass"],
        "walks_fail": verdicts["fail"],
        "walks_void": verdicts["void"],
        "findings_raised": kinds["finding.raised"],
        "findings_merged": kinds["finding.merged"],
        **{f"triaged_{decision}": decisions[decision]
           for decision in ("path", "backlog", "user", "brief", "drop", "again")},
        "finding_repairs_landed": sum(event.get("ev") == "branch.landed"
                                      and isinstance(event.get("task"), str)
                                      and re.fullmatch(r".+/finding-[0-9]+", event["task"]) is not None
                                      for event in records),
        "rungs_passed": kinds["rung.passed"],
        "walk_pass_hours": quantile(hours, 0.5),
    }


def _open_signals(events: list[dict], window: Window) -> list[Signal]:
    """Ownerless reds and hand-pushed rejections still open at the window's end.

    Reuse the page's lifecycle fold, including hand clears. The landing draft's first
    actions are sending confirmed reds with evidence (section 2) and teaching precheck
    about real rejections (section 4). Faults belong to the page, not this red signal.
    """
    opened = channel.signals(event for event in events if isinstance(event.get("ts"), str)
                             and event["ts"] < window.end)
    result = []
    for signal in opened:
        if signal.id.startswith("red-"):
            result.append(Signal(f"after-landing red {signal.id} has no owner fab knows",
                                 "a confirmed red goes to its owner with its evidence; "
                                 f"see the user's page {signal.id}", "the branch's owner"))
        elif signal.id.startswith("queue:"):
            result.append(Signal(f"hand-pushed rejection {signal.id.removeprefix('queue:')} "
                                 "has no owner fab knows",
                                 "the precheck learns it (a tool check), not a role's text (a rule); "
                                 f"see the user's page {signal.id}", "ops"))
    return result


def figures(sources: Sources, hosts: Mapping[str, Host], window: Window) -> dict[str, Figure]:
    """Every FIGURES key for the window, from sources.queue and sources.log records whose ts it
    holds (except where said):
    - batches: batch records with at least one branch. batches_per_hour: batches over the
      window's hours. branches_per_batch: their branches' mean; None when no batch.
    - utilisation: busy_seconds of every batch record, summed, as a percentage of the window.
    - green, red, conflict, error: batch records by outcome (error ones count even with no
      branches); collateral batches have none of these outcomes. red_share: red over batches,
      a percentage; None when no batch.
    - landed, rejected: the queue's `landed` and `rejected` records.
    - collateral: rejected records whose branch and tip a later `landed` record in
      sources.queue carries. false_red_rate: collateral over rejected, a percentage; None when
      none rejected.
    - retried: the queue's `collateral` records. reused: green batch records with a receipt field.
    - latency_median, latency_p90: fab.report.quantile 0.5 and 0.9 of latencies.
    - waiting, oldest_wait: how many waiting, and the largest minutes (None when none).
    - bisections, bisection_runs, bisection_minutes: from bisections, counted and summed.
    - repair_rounds: for the branches landed in the window, their rejected records in all of
      sources.queue before the landing, over how many landed; None when none landed.
      repair_minutes: the median of the minutes from each such branch's last rejection to its
      landing, over those rejected at least once; None when none.
    - lane_wait, disk_wait: fab.report.heavy_waits over the hosts with role gate.
    - after-landing and hand-pushed decisions: _red_figures; raw QA counts and failed-walk
      hours to the next rung pass: _qa_figures (docs/design/fab.md, 10).
    Counts are ints; minutes, hours, rates and percentages are floats."""
    records = within(sources.queue, window)
    all_batches = [record for record in records if record.get("ev") == "batch"]
    batches = [batch for batch in all_batches if batch.get("branches")]
    outcomes = Counter(batch.get("outcome") for batch in all_batches)
    landed = [record for record in records if record.get("ev") == "landed"]
    rejected = [record for record in records if record.get("ev") == "rejected"]
    last_landed = {}
    rejections = {}
    for record in sources.queue:
        if record.get("ev") == "landed":
            key = (record["branch"], record["tip"])
            last_landed[key] = max(last_landed.get(key, ""), record["ts"])
        elif record.get("ev") == "rejected":
            rejections.setdefault(record["branch"], []).append(record["ts"])
    collateral = sum(last_landed.get((record["branch"], record["tip"]), "") > record["ts"]
                     for record in rejected)
    rounds, repairs = _repairs(landed, rejections)
    latency = latencies(sources.log, sources.queue, window)
    waits = waiting(sources.log, sources.queue, window)
    splits = bisections(sources.queue, window)
    heavy = heavy_waits(sources.heavy, (name for name, host in hosts.items() if "gate" in host.roles),
                        window)
    hours = window.hours()
    return {
        "batches": len(batches),
        "batches_per_hour": len(batches) / hours if hours else 0.0,
        "branches_per_batch": sum(len(batch["branches"]) for batch in batches) / len(batches)
                              if batches else None,
        "utilisation": sum(busy_seconds(batch) for batch in all_batches) / (hours * 3600) * 100
                       if hours else 0.0,
        "green": outcomes["green"],
        "red": outcomes["red"],
        "conflict": outcomes["conflict"],
        "error": outcomes["error"],
        "red_share": outcomes["red"] / len(batches) * 100 if batches else None,
        "landed": len(landed),
        "rejected": len(rejected),
        "collateral": collateral,
        "false_red_rate": collateral / len(rejected) * 100 if rejected else None,
        "retried": sum(record.get("ev") == "collateral" for record in records),
        "reused": sum(batch.get("outcome") == "green" and "receipt" in batch for batch in all_batches),
        "latency_median": quantile(latency, 0.5),
        "latency_p90": quantile(latency, 0.9),
        "waiting": len(waits),
        "oldest_wait": max((wait.minutes for wait in waits), default=None),
        "bisections": len(splits),
        "bisection_runs": sum(split.runs for split in splits),
        "bisection_minutes": sum((split.minutes for split in splits), 0.0),
        "repair_rounds": rounds / len(landed) if landed else None,
        "repair_minutes": quantile(repairs, 0.5),
        "lane_wait": heavy["lane_wait"],
        "disk_wait": heavy["disk_wait"],
        **_red_figures(sources.log, window),
        **_qa_figures(sources.log, window),
    }


def signals(current: Mapping[str, Figure], previous: Mapping[str, Figure],
            unread: list[str]) -> list[Signal]:
    """The draft's signals (landing-pipeline.md, 4) that need no target, in this order:
    - collateral above 0: `<n> rejections later landed unchanged`; "the red's cause found and
      ledgered; a flake goes to its owner"; "ops, the test's owner".
    - retried above 0: `<n> branches retried after a collateral red`; "a flake goes to its
      owner"; "ops, the test's owner".
    - error above 0: `<n> batches in error`; "restart through the tool; the cause ledgered with
      a remedy in the tool"; "ops".
    - oldest_wait above 60 and above previous: `oldest ready wait <m> minutes (prev <p>)`;
      "look for a stuck batch; else capacity"; "ops".
    - disk_wait above 0: `<m> minutes of disk waits at the gate`; "the gate's disk: its
      target, its headroom"; "ops".
    - each unread source: `unread: <entry>`; "the report is partial: the machine's ssh and fab
      install"; "ops".
    A None figure counts as 0."""
    result = []
    collateral = current.get("collateral") or 0
    if collateral > 0:
        result.append(Signal(f"{show(collateral)} rejections later landed unchanged",
                             "the red's cause found and ledgered; a flake goes to its owner",
                             "ops, the test's owner"))
    retried = current.get("retried") or 0
    if retried > 0:
        result.append(Signal(f"{show(retried)} branches retried after a collateral red",
                             "a flake goes to its owner", "ops, the test's owner"))
    errors = current.get("error") or 0
    if errors > 0:
        result.append(Signal(f"{show(errors)} batches in error",
                             "restart through the tool; the cause ledgered with a remedy in the tool",
                             "ops"))
    oldest, before = current.get("oldest_wait") or 0, previous.get("oldest_wait") or 0
    if oldest > 60 and oldest > before:
        result.append(Signal(f"oldest ready wait {show(oldest)} minutes (prev {show(before)})",
                             "look for a stuck batch; else capacity", "ops"))
    disk = current.get("disk_wait") or 0
    if disk > 0:
        result.append(Signal(f"{show(disk)} minutes of disk waits at the gate",
                             "the gate's disk: its target, its headroom", "ops"))
    result.extend(Signal(f"unread: {entry}", "the report is partial: the machine's ssh and fab install",
                         "ops") for entry in unread)
    return result


def render(sources: Sources, hosts: Mapping[str, Host], window: Window) -> str:
    """The report as Markdown, ending with a newline:
    - `# Landing report, <the window's start day>`; a line `<start> to <end>; each figure
      beside the previous window's.`
    - `## Figures`: fab.report.figure_table(FIGURES, figures for the window, figures for
      window.previous()).
    - `## Signals`: fab.report.signal_lines(signals(...)), then ownerless reds and
      hand-pushed rejections still open at the window's end, with the draft's actions.
    - `## Red classes`: a table Step, Rejections of the window's `rejected` records by step,
      most first, then by step.
    - `## Steps`: a table Step, Runs, Failures, Timeouts, Median s, P90 s, Max s from step_rows.
    - `## Waiting`: a table Branch, Tip (12 characters), Ready since, Minutes from waiting.
    - `## Bisections`: a table Start, Branches, Runs, Minutes from bisections.
    - `## Errors`: a table Start, Error (its first line, cut to 120 characters) of the window's
      batch records with outcome error.
    Minutes are shown through fab.report.show; sections are separated by one blank line."""
    current = figures(sources, hosts, window)
    previous = figures(sources, hosts, window.previous())
    records = within(sources.queue, window)
    red_classes = Counter(record["step"] for record in records if record.get("ev") == "rejected")
    red_rows = sorted(red_classes.items(), key=lambda item: (-item[1], item[0]))
    sections = [
        [f"# Landing report, {window.start[:10]}",
         f"{window.start} to {window.end}; each figure beside the previous window's."],
        ["## Figures", *figure_table(FIGURES, current, previous)],
        ["## Signals", *signal_lines([*signals(current, previous, sources.unread),
                                     *_open_signals(sources.log, window)])],
        ["## Red classes", *table(("Step", "Rejections"), red_rows)],
        ["## Steps", *table(("Step", "Runs", "Failures", "Timeouts", "Median s", "P90 s", "Max s"),
                            step_rows(sources.queue, window))],
        ["## Waiting", *table(("Branch", "Tip", "Ready since", "Minutes"),
                              ((wait.branch, wait.tip[:12], wait.since, show(wait.minutes))
                               for wait in waiting(sources.log, sources.queue, window)))],
        ["## Bisections", *table(("Start", "Branches", "Runs", "Minutes"),
                                 ((split.start, split.branches, split.runs, show(split.minutes))
                                  for split in bisections(sources.queue, window)))],
        ["## Errors", *table(("Start", "Error"),
                             ((record["ts"], (record.get("error", "").splitlines() or [""])[0][:120])
                              for record in records if record.get("ev") == "batch"
                              and record.get("outcome") == "error"))],
    ]
    return "\n\n".join("\n".join(section) for section in sections) + "\n"
