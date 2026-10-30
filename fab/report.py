"""Standing reports, computed from records alone (docs/design/fab.md, 10).

Two reports: the code report of a plan (`fab.code_report`) and the landing report
(`fab.landing_report`). This module holds what both share: the day's window, the records
gathered from hel8's log, the gate's queue record and the machines' heavy records, the
figures' formatting, and the command that writes the reports under FAB_HOME/reports.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fab import atomic, log
from fab.heavy import EX_TEMPFAIL
from fab.hosts import Host
from fab.run import remote_home
from fab.sh import Runner, run, ssh

LOOKBACK_DAYS = 7  # the queue's and heavy's records read before the window's start
LANDING = "landing"  # the landing report's directory under FAB_HOME/reports

Figure = int | float | None


@dataclass(frozen=True)
class Window:
    start: str  # a record ts, inclusive: "YYYY-MM-DDTHH:MM:SS.mmmZ"
    end: str  # a record ts, exclusive

    def holds(self, ts: str) -> bool:
        """start <= ts < end, comparing the strings (every ts has the same fixed format)."""
        return self.start <= ts < self.end

    def hours(self) -> float:
        """The window's length in hours."""
        return (moment(self.end) - moment(self.start)).total_seconds() / 3600

    def previous(self) -> Window:
        """The window of the same length that ends where this one starts."""
        start, end = moment(self.start), moment(self.end)
        return Window(stamp(start - (end - start)), self.start)


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
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def moment(ts: str) -> datetime:
    """A record ts as an aware UTC datetime; ValueError when it is not one."""
    parsed = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    if stamp(parsed) != ts:
        raise ValueError(f"not a record timestamp: {ts!r}")
    return parsed


def minutes(start: str, end: str) -> float:
    """Minutes from ts start to ts end (negative when end is earlier)."""
    return (moment(end) - moment(start)).total_seconds() / 60


def day_window(day: str | None, now: str) -> Window:
    """The window a report covers. day "YYYY-MM-DD": that UTC day, [00:00:00.000Z, the next
    day's 00:00:00.000Z). None: today so far, [today's 00:00:00.000Z, now). ValueError for a
    day that does not parse or is after now's day."""
    today = moment(now).replace(hour=0, minute=0, second=0, microsecond=0)
    if day is None:
        return Window(stamp(today), now)
    start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if start.strftime("%Y-%m-%d") != day or start > today:
        raise ValueError(f"invalid report day: {day!r}")
    return Window(stamp(start), stamp(start + timedelta(days=1)))


def within(records: Iterable[dict], window: Window) -> list[dict]:
    """The records whose ts the window holds, in their order; records without a ts are skipped."""
    return [record for record in records if "ts" in record and window.holds(record["ts"])]


def quantile(values: Iterable[float], q: float) -> float | None:
    """Nearest rank: the value at index ceil(q * n) - 1 (at least 0) of the sorted values; None
    when there are none. quantile(v, 0.5) is the report's median, 0.9 its 90th percentile."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)] if ordered else None


def show(value: Figure) -> str:
    """A figure as text: None "-", an int (or a bool) as is, a float to one decimal."""
    if value is None:
        return "-"
    return f"{value:.1f}" if isinstance(value, float) else str(value)


def trend(current: Figure, previous: Figure) -> str:
    """`show(current)`, then ` (prev <show(previous)>)`: every figure carries the previous
    window's beside it until the user sets targets."""
    return f"{show(current)} (prev {show(previous)})"


def table(header: Sequence[str], rows: Iterable[Sequence[object]]) -> list[str]:
    """A Markdown table: the header row, a `| --- |` row, then one row per entry, each cell
    str() of the value with `|` escaped as `\\|` and newlines as spaces. No rows: the header and
    its rule only."""
    def row(cells):
        return "| " + " | ".join(str(cell).replace("|", "\\|").replace("\n", " ")
                                 for cell in cells) + " |"

    return [row(header), row(["---"] * len(header)), *(row(cells) for cells in rows)]


def figure_table(labels: Sequence[tuple[str, str]], current: Mapping[str, Figure],
                 previous: Mapping[str, Figure]) -> list[str]:
    """table(("Figure", "Value"), ...) with one row per (key, label) in labels' order:
    (label, trend(current[key], previous[key])); a key missing from a mapping counts as None."""
    return table(("Figure", "Value"),
                 ((label, trend(current.get(key), previous.get(key))) for key, label in labels))


def heavy_waits(heavy: Mapping[str, list[dict]], hosts: Iterable[str], window: Window) -> dict[str, Figure]:
    """What heavy recorded on the named hosts within the window (ev "heavy" records only; a
    host absent from heavy adds nothing): commands (their count), lane_wait and disk_wait (the
    records' seconds summed, in minutes), disk_refused (records with code
    fab.heavy.EX_TEMPFAIL)."""
    records = [record for host in hosts for record in within(heavy.get(host, []), window)
               if record.get("ev") == "heavy"]
    return {
        "commands": len(records),
        "lane_wait": sum((record.get("lane_wait", 0.0) for record in records), 0.0) / 60,
        "disk_wait": sum((record.get("disk_wait", 0.0) for record in records), 0.0) / 60,
        "disk_refused": sum(record.get("code") == EX_TEMPFAIL for record in records),
    }


def signal_lines(signals: Sequence[Signal]) -> list[str]:
    """`- **<text>:** <action> (<owner>)` per signal; `- none` when there are none."""
    return [f"- **{signal.text}:** {signal.action} ({signal.owner})" for signal in signals] or ["- none"]


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
    sources = Sources(log.read(log_path), [], {})

    def read_remote(host, command, source):
        result = sh(ssh(host.ssh, command))
        if not result.ok:
            detail = (result.err.strip() or result.out.strip()).splitlines()
            sources.unread.append(f"{source} {host.name}: " +
                                  (detail[-1] if detail else f"exit {result.code}"))
            return []
        records = []
        for line in result.out.splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and isinstance(record.get("ts"), str):
                records.append(record)
        return records

    ordered = sorted(hosts.values(), key=lambda host: host.name)
    gate = next((host for host in ordered if "gate" in host.roles), None)
    if gate is None:
        sources.unread.append("queue: no gate host")
    else:
        sources.queue = read_remote(gate, ["fab", "queue", "log", "--since", since], "queue")
    for host in ordered:
        if "builder" in host.roles or "gate" in host.roles:
            records = read_remote(host, ["sh", "-c", 'test ! -e "$1" || cat "$1"', "sh",
                                         remote_home(host) + "/heavy.jsonl"], "heavy")
            sources.heavy[host.name] = [record for record in records if record["ts"] >= since]
    return sources


def report_path(name: str, day: str) -> Path:
    """FAB_HOME/reports/<name>/<day>.md: name is a plan's draft, or LANDING."""
    return log.home() / "reports" / name / f"{day}.md"


def main(argv: list[str]) -> int:
    """`fab report code PLAN_DIR [--day DAY] [--write]`, `fab report landing [--day DAY]
    [--write]` and `fab report daily PLAN_DIR...`.

    code and landing: the window is day_window(DAY, fab.log.now()); gather from fab.hosts.load()
    with since = the window's previous().start less LOOKBACK_DAYS days; print the report
    (fab.code_report.render with the plan and tasks loaded from PLAN_DIR as `fab status` loads
    them, or fab.landing_report.render); with --write also write it to report_path(<draft> or
    LANDING, <the window's day>) through fab.atomic.write and print that path last.
    daily: for yesterday (UTC), write each plan's code report and the landing report whose
    report_path does not exist yet, gathering once; print one line per report, `<path> written`
    or `<path> kept`. Exit 0; 1 when a plan does not load or has problems (the message on
    stderr, nothing written for it, the other reports still written); 2 on bad arguments or a
    bad day."""
    import argparse
    import sys

    from fab import code_report, hosts, landing_report
    from fab.plan import PlanError, load_plan, load_tasks, problems

    parser = argparse.ArgumentParser(prog="fab report")
    commands = parser.add_subparsers(dest="command", required=True)
    code = commands.add_parser("code")
    code.add_argument("plan_dir", type=Path, metavar="PLAN_DIR")
    landing = commands.add_parser("landing")
    for command in (code, landing):
        command.add_argument("--day")
        command.add_argument("--write", action="store_true")
    daily = commands.add_parser("daily")
    daily.add_argument("plan_dirs", type=Path, nargs="+", metavar="PLAN_DIR")
    args = parser.parse_args(argv)
    now = log.now()
    day = (stamp(moment(now) - timedelta(days=1))[:10] if args.command == "daily"
           else args.day)
    try:
        window = day_window(day, now)
    except ValueError as error:
        parser.error(str(error))
    day = window.start[:10]
    since = stamp(moment(window.previous().start) - timedelta(days=LOOKBACK_DAYS))

    def load(directory):
        plan = load_plan(directory / "plan.toml")
        tasks = load_tasks(directory / "tasks", plan.draft, plan.repo)
        issues = problems(plan, tasks)
        if issues:
            raise PlanError(f"{directory}: " + "\n".join(issues))
        return plan, tasks

    try:
        selected = hosts.load()
        sources = gather(selected, since)
        if args.command == "daily":
            failed = False
            for directory in args.plan_dirs:
                try:
                    plan, tasks = load(directory)
                except PlanError as error:
                    print(error, file=sys.stderr)
                    failed = True
                    continue
                path = report_path(plan.draft, day)
                if path.exists():
                    print(f"{path} kept")
                else:
                    atomic.write(path, code_report.render(plan, tasks, sources, selected, window))
                    print(f"{path} written")
            path = report_path(LANDING, day)
            if path.exists():
                print(f"{path} kept")
            else:
                atomic.write(path, landing_report.render(sources, selected, window))
                print(f"{path} written")
            return 1 if failed else 0
        if args.command == "code":
            plan, tasks = load(args.plan_dir)
            name = plan.draft
            text = code_report.render(plan, tasks, sources, selected, window)
        else:
            name = LANDING
            text = landing_report.render(sources, selected, window)
        print(text, end="")
        if args.write:
            path = report_path(name, day)
            atomic.write(path, text)
            print(path)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"fab report: {error}", file=sys.stderr)
        return 1
    return 0
