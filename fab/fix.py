"""Shared Fix-mode foremen and repair tasks (docs/design/fab-qa.md, 2)."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from pathlib import Path

from fab import foreman, log, run as runs
from fab.plan import Task

FIX_KINDS = ("red", "finding")  # repair task kinds sharing Fix mode
RUNS = 2  # failed repair runs before the answerer
SECTION_LINES = 30  # report lines retained after the verdict and optional skipped line


def launch(task_id: str, host: runs.Host, tip: str, brief: Callable[[str, str], str],
           events: Sequence[dict], *, sh: runs.Runner = runs.run,
           log_path: Path | None = None, **fields) -> str:
    """Launch a numbered, read-only fabrig foreman and return its run id.

    brief receives the run id and remote report path. Caller fields join run.started;
    branch is task_id, base and run.started tip are tip (docs/design/fab-qa.md, 2).
    """
    run_id = runs.next_run(foreman.task_field(task_id), events)
    text = brief(run_id, report_path(host, run_id))
    return runs.launch_detached(host, run_id, "fabrig", tip, sh=sh, log_path=log_path,
                                task=foreman.task_field(task_id), kind=foreman.KIND,
                                branch=task_id, base=tip, brief=text, effort=foreman.EFFORT,
                                tip=tip, **fields)


def report_path(host: runs.Host, run: str) -> str:
    """Return the foreman's report path on host (docs/design/fab-qa.md, 2)."""
    return str(Path(runs.remote_home(host)) / "runs" / run / "report.md")


def parse(report: str, *, skip: Callable[[str], bool] | None = None
          ) -> tuple[str, str, list[str], list[str]]:
    """Return (verdict, reason, lines, skipped) from the first nonblank report line.

    Done: fix: <reason> keeps SECTION_LINES right-stripped following lines; retry
    returns left, other forms none. skip may remove only the immediate next line,
    returned verbatim in skipped (docs/design/fab-qa.md, 2).
    """
    lines = report.splitlines()
    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    head = lines[first].strip() if first is not None else ""
    match = re.fullmatch(r"Done\s*:\s*(fix|retry)\s*:\s*(.+)", head)
    if match is None or not match[2].strip():
        return "none", "no verdict: " + head[:120], [], []
    reason = match[2].strip()
    if match[1] == "retry":
        return "left", reason, [], []
    rest, skipped = lines[first + 1:], []
    if rest and skip is not None and skip(rest[0]):
        skipped.append(rest.pop(0))
    return "fix", reason, [line.rstrip() for line in rest[:SECTION_LINES]], skipped


def section(heading: str, reason: str, lines: Sequence[str]) -> str:
    """Return heading, a blank line, reason and lines, ending in one newline.

    Drop trailing blank lines (docs/design/fab-qa.md, 2).
    """
    kept = [reason, *lines]
    while kept and not kept[-1].strip():
        kept.pop()
    return heading + "\n\n" + "\n".join(kept) + "\n"


def settle(ev: str, fields: Callable[[str], dict], *, log_path: Path | None = None) -> dict:
    """Append ev with fields(day), returning the record; one clock read supplies its
    timestamp and day (docs/design/fab-qa.md, 2).
    """
    stamp = log.now()
    return log.append(ev, path=log_path, ts=stamp, **fields(stamp[:10]))


def answers(events: Sequence[dict]) -> dict[str, list[str]]:
    """Return each task's nonempty question.answered answers in log order; pure
    (docs/design/fab-qa.md, 2).
    """
    found = {}
    for event in events:
        if event.get("ev") == "question.answered" and "task" in event and event.get("answer"):
            found.setdefault(event["task"], []).append(event["answer"])
    return found


def sections(events: Sequence[dict]) -> dict[str, list[str]]:
    """Return each task's nonempty refusal.settled fix sections in log order; pure
    (docs/design/fab-qa.md, 2).
    """
    found = {}
    for event in events:
        if event.get("ev") == "refusal.settled" and event.get("verdict") == "fix" and event.get("section"):
            found.setdefault(event.get("task"), []).append(event["section"])
    return found


def task(task_id: str, kind: str, part: str, body: str, answers: Sequence[str]) -> Task:
    """Return a specless fabrig repair task, appending answers under ## Answers.

    No needs, files **, high effort, 20 minutes (docs/design/fab-qa.md, 2).
    """
    if answers:
        body += "\n## Answers\n\n" + "\n".join(f"- {answer}" for answer in answers) + "\n"
    return Task(task_id, part, kind, "fabrig", (), ("**",), "high", 20, body, "")
