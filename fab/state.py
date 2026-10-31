"""A plan's tasks and their status, folded from the specs and the log (docs/design/fab.md, 3-4)."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from fab import log
from fab.plan import Plan, PlanError, Task, load_plan, load_tasks, problems

STATUSES = ("waiting", "runnable", "running", "parked", "done", "ready", "landed", "rejected")
PART_STATUSES = ("not designed", "designed", "done")


@dataclass
class TaskView:
    id: str
    status: str = "waiting"
    runs: list[str] = field(default_factory=list)
    branch: str | None = None
    tip: str | None = None
    main: str | None = None
    question: str | None = None


def fold(tasks: Mapping[str, Task], events: Iterable[dict]) -> dict[str, TaskView]:
    """Each task's view after the events, in the tasks' order.

    Events for tasks not in `tasks`, and event types not listed here, are ignored.
    - run.started: running; the run id is appended to runs; branch is taken from the event.
    - run.ended: outcome done -> done; question -> parked; failed -> parked, question is
      "Failed: " plus the event's report path; infra -> runnable.
    - question.asked: parked, question = text. question.answered: a parked task becomes
      runnable; every task's question = None.
    - branch.ready: ready, tip. branch.landed: landed, tip, main. branch.rejected: rejected.
    A task never started is waiting while any need is not landed, otherwise runnable.
    """
    views = {identifier: TaskView(identifier) for identifier in tasks}
    for event in events:
        view = views.get(event.get("task"))
        if view is None:
            continue
        match event.get("ev"):
            case "run.started":
                view.status = "running"
                view.runs.append(event["run"])
                view.branch = event.get("branch")
            case "run.ended":
                outcome = event.get("outcome")
                if outcome == "done":
                    view.status = "done"
                elif outcome in ("question", "failed"):
                    view.status = "parked"
                    if outcome == "failed":
                        view.question = "Failed: " + event["report"]
                elif outcome == "infra":
                    view.status = "runnable"
            case "question.asked":
                view.status = "parked"
                view.question = event["text"]
            case "question.answered":
                # An answer unparks a parked task; a task already past its question stays put.
                if view.status == "parked":
                    view.status = "runnable"
                view.question = None
            case "branch.ready":
                view.status = "ready"
                view.tip = event["tip"]
            case "branch.landed":
                view.status = "landed"
                view.tip = event["tip"]
                view.main = event["main"]
            case "branch.rejected":
                view.status = "rejected"
    for identifier, view in views.items():
        if view.status == "waiting" and all(
            need in views and views[need].status == "landed" for need in tasks[identifier].needs
        ):
            view.status = "runnable"
    return views


def runnable(views: Mapping[str, TaskView]) -> list[str]:
    """Ids whose status is runnable, in the views' order."""
    return [identifier for identifier, view in views.items() if view.status == "runnable"]


def part_statuses(plan: Plan, tasks: Mapping[str, Task], statuses: Mapping[str, str]) -> dict[str, str]:
    """Each part's status (PART_STATUSES), keyed by id in the plan's order (docs/design/fab.md, 4):
    done when the plan marks the part done or it has task specs that all have status landed;
    designed when it has task specs; else not designed. statuses maps task ids to fold's
    statuses; a task missing from it is not landed. fab.calls' parts table, fab.dispatch.decide's
    design step and fab.designer.retire_due read it."""
    result = {}
    for part in plan.parts.values():
        specs = [task for task in tasks.values() if task.part == part.id]
        result[part.id] = ("done" if part.done or specs and all(
            statuses.get(task.id) == "landed" for task in specs)
            else "designed" if specs else "not designed")
    return result


def main(argv: list[str]) -> int:
    """`fab status PLAN_DIR`: one line per task, `<id> <status> <runs> <branch>`; exit 1 on plan problems.

    PLAN_DIR holds plan.toml and tasks/; the log is FAB_HOME's.
    """
    parser = argparse.ArgumentParser(prog="fab status", description=__doc__)
    parser.add_argument("plan_dir", type=Path, metavar="PLAN_DIR")
    args = parser.parse_args(argv)
    try:
        plan = load_plan(args.plan_dir / "plan.toml")
        tasks = load_tasks(args.plan_dir / "tasks", plan.draft, plan.repo)
    except PlanError as error:
        print(error, file=sys.stderr)
        return 1
    issues = problems(plan, tasks)
    if issues:
        print("\n".join(issues), file=sys.stderr)
        return 1
    views = fold(tasks, log.iterate())
    rows = [(view.id, view.status, str(len(view.runs)), view.branch or "-")
            for view in views.values()]
    if rows:
        widths = [max(len(row[column]) for row in rows) for column in range(3)]
        for row in rows:
            print(" ".join(f"{cell:<{width}}" for cell, width in zip(row[:3], widths)) + " " + row[3])
    return 0
