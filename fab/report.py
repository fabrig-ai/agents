"""Standing reports, computed from records alone (docs/design/fab.md, 10).

Two reports: the code report of a plan (`fab.code_report`) and the landing report
(`fab.landing_report`). This module holds what both share: the day's window, the records
gathered from hel8's log, the gate's queue record and the machines' heavy records, the
figures' formatting, and the command that writes the reports under FAB_HOME/reports.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from fab.hosts import Host
from fab.sh import Runner, run

LOOKBACK_DAYS = 7  # the queue's and heavy's records read before the window's start
LANDING = "landing"  # the landing report's directory under FAB_HOME/reports

Figure = int | float | None


@dataclass(frozen=True)
class Window:
    start: str  # a record ts, inclusive: "YYYY-MM-DDTHH:MM:SS.mmmZ"
    end: str  # a record ts, exclusive

    def holds(self, ts: str) -> bool:
        """start <= ts < end, comparing the strings (every ts has the same fixed format)."""
        raise NotImplementedError

    def hours(self) -> float:
        """The window's length in hours."""
        raise NotImplementedError

    def previous(self) -> Window:
        """The window of the same length that ends where this one starts."""
        raise NotImplementedError


@dataclass
class Sources:
    log: list[dict]  # hel8's whole event log, oldest first
    queue: list[dict]  # the gate's queue.jsonl records since the lookback, oldest first
    heavy: dict[str, list[dict]]  # host name -> its heavy.jsonl records since the lookback
    unread: list[str] = field(default_factory=list)  # "<source>: <why>" per source not read


@dataclass(frozen=True)
class Signal:
    text: str  # what was seen, with its figure: "2 collateral rejections"
    action: str  # the draft's first action
    owner: str  # the draft's owner of that action


def stamp(moment: datetime) -> str:
    """A datetime (aware, UTC) as a record ts: `YYYY-MM-DDTHH:MM:SS.mmmZ`, as fab.log.now."""
    raise NotImplementedError


def moment(ts: str) -> datetime:
    """A record ts as an aware UTC datetime; ValueError when it is not one."""
    raise NotImplementedError


def minutes(start: str, end: str) -> float:
    """Minutes from ts start to ts end (negative when end is earlier)."""
    raise NotImplementedError


def day_window(day: str | None, now: str) -> Window:
    """The window a report covers. day "YYYY-MM-DD": that UTC day, [00:00:00.000Z, the next
    day's 00:00:00.000Z). None: today so far, [today's 00:00:00.000Z, now). ValueError for a
    day that does not parse or is after now's day."""
    raise NotImplementedError


def within(records: Iterable[dict], window: Window) -> list[dict]:
    """The records whose ts the window holds, in their order; records without a ts are skipped."""
    raise NotImplementedError


def quantile(values: Iterable[float], q: float) -> float | None:
    """Nearest rank: the value at index ceil(q * n) - 1 (at least 0) of the sorted values; None
    when there are none. quantile(v, 0.5) is the report's median, 0.9 its 90th percentile."""
    raise NotImplementedError


def show(value: Figure) -> str:
    """A figure as text: None "-", an int (or a bool) as is, a float to one decimal."""
    raise NotImplementedError


def trend(current: Figure, previous: Figure) -> str:
    """`show(current)`, then ` (prev <show(previous)>)`: every figure carries the previous
    window's beside it until the user sets targets."""
    raise NotImplementedError


def table(header: Sequence[str], rows: Iterable[Sequence[object]]) -> list[str]:
    """A Markdown table: the header row, a `| --- |` row, then one row per entry, each cell
    str() of the value with `|` escaped as `\\|` and newlines as spaces. No rows: the header and
    its rule only."""
    raise NotImplementedError


def figure_table(labels: Sequence[tuple[str, str]], current: Mapping[str, Figure],
                 previous: Mapping[str, Figure]) -> list[str]:
    """table(("Figure", "Value"), ...) with one row per (key, label) in labels' order:
    (label, trend(current[key], previous[key])); a key missing from a mapping counts as None."""
    raise NotImplementedError


def heavy_waits(heavy: Mapping[str, list[dict]], hosts: Iterable[str], window: Window) -> dict[str, Figure]:
    """What heavy recorded on the named hosts within the window (ev "heavy" records only; a
    host absent from heavy adds nothing): commands (their count), lane_wait and disk_wait (the
    records' seconds summed, in minutes), disk_refused (records with code
    fab.heavy.EX_TEMPFAIL)."""
    raise NotImplementedError


def signal_lines(signals: Sequence[Signal]) -> list[str]:
    """`- **<text>:** <action> (<owner>)` per signal; `- none` when there are none."""
    raise NotImplementedError


def gather(hosts: Mapping[str, Host], since: str, *, sh: Runner = run,
           log_path: Path | None = None) -> Sources:
    """The records the reports read, from this machine (hel8).

    log: fab.log.read(log_path), whole. queue: on the first host (sorted by name) with role
    gate, `fab queue log --since <since>` over fab.sh.ssh, one JSON record per output line.
    heavy: on every host with role builder or gate, sorted by name, over fab.sh.ssh,
    `sh -c 'test ! -e "$1" || cat "$1"' sh <fab.run.remote_home(host)>/heavy.jsonl`, keeping
    the records with ts >= since (a missing file is no records). Lines that do not parse as a
    JSON object with a string ts are skipped, as fab.log.read skips them. A command that fails
    adds `queue <host>: <last line of its stderr or stdout>` or `heavy <host>: ...` to unread
    and leaves that source empty; no host with role gate adds `queue: no gate host`. Never
    raises for a remote failure."""
    raise NotImplementedError


def report_path(name: str, day: str) -> Path:
    """FAB_HOME/reports/<name>/<day>.md: name is a plan's draft, or LANDING."""
    raise NotImplementedError


def main(argv: list[str]) -> int:
    """`fab report code PLAN_DIR [--day DAY] [--write]`, `fab report landing [--day DAY]
    [--write]` and `fab report daily PLAN_DIR...`.

    code and landing: the window is day_window(DAY, fab.log.now()); gather from fab.hosts.load()
    with since = the window's previous().start less LOOKBACK_DAYS days; print the report
    (fab.code_report.render with the plan and tasks loaded from PLAN_DIR as `fab status` loads
    them, or fab.landing_report.render); with --write also write it to report_path(<draft> or
    LANDING, <the window's day>) through fab.run._write and print that path last.
    daily: for yesterday (UTC), write each plan's code report and the landing report whose
    report_path does not exist yet, gathering once; print one line per report, `<path> written`
    or `<path> kept`. Exit 0; 1 when a plan does not load or has problems (the message on
    stderr, nothing written for it, the other reports still written); 2 on bad arguments or a
    bad day."""
    raise NotImplementedError
