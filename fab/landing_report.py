"""The landing report: the merge queue's metrics from its record (docs/design/fab.md, 10).

The metrics are the landing draft's (docs/design/draft/landing-pipeline.md, 3) that the
queue's record holds: its `batch`, `landed` and `rejected` records (fab.queue.Queue.attempt),
joined with the log's branch.ready for latency, and heavy's records on the gate machine.
Every function here is pure; `render` puts them together for one window.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from fab.hosts import Host
from fab.report import Figure, Signal, Sources, Window

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
    raise NotImplementedError


def busy_seconds(batch: dict) -> float:
    """The seconds of the batch's steps, summed: the time it held the gate lane, as recorded."""
    raise NotImplementedError


def latencies(events: list[dict], queue: list[dict], window: Window) -> list[float]:
    """For each queue `landed` record in the window, the minutes since the latest branch.ready
    in events with the same branch and tip at or before it, in the records' order; a landed
    branch with no such branch.ready (marked ready by hand) is left out."""
    raise NotImplementedError


def waiting(events: list[dict], queue: list[dict], window: Window) -> list[Wait]:
    """The ready branches waiting at the window's end, oldest first: per branch, its latest
    branch.ready in events before the end, when no queue `landed` or `rejected` record for that
    branch and tip comes before the end."""
    raise NotImplementedError


def bisections(queue: list[dict], window: Window) -> list[Bisection]:
    """The window's batch records in ts order; a red one with more than one branch starts a
    bisection, and each following batch whose branches are a non-empty subset of its branches
    is one of its runs; the first batch that is not ends it (and may start the next)."""
    raise NotImplementedError


def step_rows(queue: list[dict], window: Window) -> list[tuple]:
    """One row per step name over the window's batches, by first appearance: (name, runs,
    failures (not green), timeouts (code 124), median seconds, 90th percentile seconds,
    largest seconds), seconds through fab.report.quantile and rounded to one decimal."""
    raise NotImplementedError


def figures(sources: Sources, hosts: Mapping[str, Host], window: Window) -> dict[str, Figure]:
    """Every FIGURES key for the window, from sources.queue and sources.log records whose ts it
    holds (except where said):
    - batches: batch records with at least one branch. batches_per_hour: batches over the
      window's hours. branches_per_batch: their branches' mean; None when no batch.
    - utilisation: busy_seconds of every batch record, summed, as a percentage of the window.
    - green, red, conflict, error: batch records by outcome (error ones count even with no
      branches). red_share: red over batches, a percentage; None when no batch.
    - landed, rejected: the queue's `landed` and `rejected` records.
    - collateral: rejected records whose branch and tip a later `landed` record in
      sources.queue carries. false_red_rate: collateral over rejected, a percentage; None when
      none rejected.
    - latency_median, latency_p90: fab.report.quantile 0.5 and 0.9 of latencies.
    - waiting, oldest_wait: how many waiting, and the largest minutes (None when none).
    - bisections, bisection_runs, bisection_minutes: from bisections, counted and summed.
    - repair_rounds: for the branches landed in the window, their rejected records in all of
      sources.queue before the landing, over how many landed; None when none landed.
      repair_minutes: the median of the minutes from each such branch's last rejection to its
      landing, over those rejected at least once; None when none.
    - lane_wait, disk_wait: fab.report.heavy_waits over the hosts with role gate.
    Counts are ints, minutes, rates and percentages floats."""
    raise NotImplementedError


def signals(current: Mapping[str, Figure], previous: Mapping[str, Figure],
            unread: list[str]) -> list[Signal]:
    """The draft's signals (landing-pipeline.md, 4) that need no target, in this order:
    - collateral above 0: `<n> rejections later landed unchanged`; "the red's cause found and
      ledgered; a flake goes to its owner"; "ops, the test's owner".
    - error above 0: `<n> batches in error`; "restart through the tool; the cause ledgered with
      a remedy in the tool"; "ops".
    - oldest_wait above 60 and above previous: `oldest ready wait <m> minutes (prev <p>)`;
      "look for a stuck batch; else capacity"; "ops".
    - disk_wait above 0: `<m> minutes of disk waits at the gate`; "the gate's disk: its
      target, its headroom"; "ops".
    - each unread source: `unread: <entry>`; "the report is partial: the machine's ssh and fab
      install"; "ops".
    A None figure counts as 0."""
    raise NotImplementedError


def render(sources: Sources, hosts: Mapping[str, Host], window: Window) -> str:
    """The report as Markdown, ending with a newline:
    - `# Landing report, <the window's start day>`; a line `<start> to <end>; each figure
      beside the previous window's.`
    - `## Figures`: fab.report.figure_table(FIGURES, figures for the window, figures for
      window.previous()).
    - `## Signals`: fab.report.signal_lines(signals(...)).
    - `## Red classes`: a table Step, Rejections of the window's `rejected` records by step,
      most first, then by step.
    - `## Steps`: a table Step, Runs, Failures, Timeouts, Median s, P90 s, Max s from step_rows.
    - `## Waiting`: a table Branch, Tip (12 characters), Ready since, Minutes from waiting.
    - `## Bisections`: a table Start, Branches, Runs, Minutes from bisections.
    - `## Errors`: a table Start, Error (its first line, cut to 120 characters) of the window's
      batch records with outcome error.
    Minutes are shown through fab.report.show; sections are separated by one blank line."""
    raise NotImplementedError
