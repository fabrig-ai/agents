"""The self-critique's test vocabulary (docs/design/fab.md, 13.1): a task, a builder host, the
log of the task's runs and critiques as a builder, and the stage assertion that
test_critique and test_dispatch speak in."""

from __future__ import annotations

import unittest
from pathlib import Path

from fab import critique
from fab.hosts import Host
from fab.plan import Task

TASK = Task("draft/task", "part", "feature", "agents", (), ("fab/x.py", "fab/tests/test_x.py"),
            "high", 30, "# Fill x\n\nFill `fab.x.y` as its docstring says.\n",
            "docs/plan/draft/tasks/task.md")
HOST = Host("builder", "worker@builder.invalid", ("builder",), places=2, slots=2)
ROOT = Path("/home/worker/src/fabrig/fab")  # fab.run.remote_home(HOST)
REPORTS = Path("/fab/runs")  # where Story's run.ended records say the collected reports are
DIGEST = "# Digest of draft/task-1\n\n## Long functions\n\n- none\n"


class Story:
    """A task's log in order, as fab.run.start, launch_detached and collect write it: each
    record one second after the last, every run numbered as fab.run.next_run numbers it.
    Methods return the story, so a test reads as the order of what happened."""

    def __init__(self, task: Task = TASK) -> None:
        self.task = task
        self.events: list[dict] = []
        self._open: list[str] = []  # runs started and not yet ended, oldest first

    def add(self, ev: str, **fields) -> Story:
        """Append one record of type ev with its next ts."""
        second = len(self.events)
        self.events.append({"ev": ev, "ts": f"2026-10-31T00:{second // 60:02d}:{second % 60:02d}.000Z",
                            **fields})
        return self

    def started(self, kind: str = "implement") -> Story:
        """A run.started of kind: a critic run (critique.KIND) under the task's critique field
        on the branch of the task's last run, with `of` naming that run; any other kind a run
        of the task itself, on the task's branch."""
        own = [event for event in self.events
               if event["ev"] == "run.started" and event["task"] == self.task.id]
        if kind == critique.KIND:
            field = f"{self.task.id}/{critique.KIND}"
            count = sum(event["ev"] == "run.started" and event["task"] == field
                        for event in self.events)
            run_id = f"{field}-{count + 1}"
            fields = {"task": field, "branch": own[-1]["branch"], "of": own[-1]["run"]}
        else:
            run_id = f"{self.task.id}-{len(own) + 1}"
            fields = {"task": self.task.id, "branch": self.task.id}
        self._open.append(run_id)
        return self.add("run.started", run=run_id, kind=kind, host=HOST.name,
                        dir=str(ROOT / "wt" / run_id), base="origin/main", **fields)

    def ended(self, outcome: str = "done") -> Story:
        """The run.ended of the oldest run still open, its report under REPORTS."""
        run_id = self._open.pop(0)
        task = next(event["task"] for event in self.events
                    if event["ev"] == "run.started" and event["run"] == run_id)
        return self.add("run.ended", run=run_id, task=task, outcome=outcome,
                        report=str(REPORTS / run_id / "report.md"), minutes=1.0)

    def ran(self, kind: str = "implement", outcome: str = "done") -> Story:
        """A run of kind that started and ended with outcome."""
        return self.started(kind).ended(outcome)

    def critiqued(self, outcome: str = "done") -> Story:
        """A critic run of the task's branch that ended with outcome."""
        return self.ran(critique.KIND, outcome)

    def fixed(self, outcome: str = "done") -> Story:
        """The task's fix run (critique.FIX) that ended with outcome."""
        return self.ran(critique.FIX, outcome)

    def rejected(self, step: str = "gate:files") -> Story:
        """A branch.rejected of the task's branch at step."""
        return self.add("branch.rejected", task=self.task.id, branch=self.task.id, tip="tip",
                        step=step, log="")


def critic(n: int = 1, task: Task = TASK) -> str:
    """The id of the task's nth critic run, as Story numbers it."""
    return f"{task.id}/{critique.KIND}-{n}"


def assert_stage(case: unittest.TestCase, story: Story, stage: str, *,
                 critic_run: str | None = None, reason: str = "") -> None:
    """critique.stages over the story's events gives its task this stage, last critic run and
    reason, and a report that is the critic's collected one once it ended ("" before)."""
    folded = critique.stages({story.task.id: story.task}, iter(story.events))
    ended = critic_run is not None and any(
        event["ev"] == "run.ended" and event["run"] == critic_run for event in story.events)
    report = str(REPORTS / critic_run / "report.md") if ended else ""
    case.assertEqual(folded.get(story.task.id),
                     critique.Stage(story.task.id, stage, critic_run, report, reason))
