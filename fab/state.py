"""A plan's tasks and their status, folded from the specs and the log (docs/design/fab.md, 3-4)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from fab.plan import Task

STATUSES = ("waiting", "runnable", "running", "parked", "done", "ready", "landed", "rejected")


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
    - question.asked: parked, question = text. question.answered: runnable, question = None.
    - branch.ready: ready, tip. branch.landed: landed, tip, main. branch.rejected: rejected.
    A task never started is waiting while any need is not landed, otherwise runnable.
    """
    raise NotImplementedError


def runnable(views: Mapping[str, TaskView]) -> list[str]:
    """Ids whose status is runnable, in the views' order."""
    raise NotImplementedError


def main(argv: list[str]) -> int:
    """`fab status PLAN_DIR`: one line per task, `<id> <status> <runs> <branch>`; exit 1 on plan problems.

    PLAN_DIR holds plan.toml and tasks/; the log is FAB_HOME's.
    """
    raise NotImplementedError
