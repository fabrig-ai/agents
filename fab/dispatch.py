"""The dispatcher: one idempotent tick keeps a plan's tasks moving (docs/design/fab.md, 10).

`decide` is pure: from the plan, its tasks, the log and the machines it returns the actions
to take now. `tick` gathers those inputs, carries the actions out through `fab.run`,
`fab.land` and git, and prints what it did. Running tick twice in a row is harmless.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from fab.hosts import Host
from fab.plan import Plan, Task
from fab.sh import Runner, run

MAX_RUNS = 4  # a task with this many runs and still not landed parks for judgement


@dataclass(frozen=True)
class Action:
    kind: str  # collect, land, ready, start, park, design
    task: str | None = None
    run: str | None = None
    host: str | None = None
    run_kind: str | None = None  # for start: implement, repair or rebase
    branch: str | None = None
    detail: str = ""


def in_flight(events: Iterable[dict]) -> list[dict]:
    """run.started records without a run.ended for the same run, in log order."""
    raise NotImplementedError


def places(hosts: Mapping[str, Host], flight: Iterable[dict]) -> dict[str, int]:
    """Free Codex places per builder: its `places` minus its runs in flight (never below 0)."""
    raise NotImplementedError


def decide(plan: Plan, tasks: Mapping[str, Task], events: list[dict], hosts: Mapping[str, Host]) -> list[Action]:
    """The actions for now, in this order:

    1. collect: every run in flight.
    2. land (repo "agents") or ready (any other repo): every task whose status is done, with
       the branch of its last run.
    3. start: for rejected tasks first, then runnable ones in the tasks' order, while a builder
       has a free place (the builder with most free places first; ties by name). A rejected
       task's run_kind is rebase when its last branch.rejected step is rebase or merge,
       otherwise repair; a runnable task's is implement, or repair when its last run ended infra.
       A task that already has MAX_RUNS runs gets park instead of start.
    4. design: when fewer tasks are runnable or rejected than plan.low times the builders'
       total places, one design action whose detail lists, in plan order, the parts that
       have no task spec yet and whose needs all have every task landed.
    Statuses come from fab.state.fold.
    """
    raise NotImplementedError


def tick(plan_dir: Path, *, sh: Runner = run, hosts: Mapping[str, Host] | None = None,
         log_path: Path | None = None) -> list[Action]:
    """One tick for the plan in plan_dir (a checkout of its repository's main, fetched first).

    First, import the merge queue's new records: `fab queue log --since <ts>` over ssh on the
    host with role gate, ts being the latest `queue_ts` already imported; each `landed` or
    `rejected` record naming a task of this plan becomes branch.landed or branch.rejected,
    carrying queue_ts. Then take decide's actions: collect through fab.run.collect, land
    through fab.land.main with the branch, ready by pushing the branch's tip to `ready/<branch>`
    in its repository's clone under FAB_HOME/repos (logging branch.ready), start through
    fab.run.start, park by logging question.asked with the detail as text. Design actions are
    printed, not acted on. A failed action is printed and logged as a note; the others still
    run. Returns the actions taken. One tick at a time: a flock on FAB_HOME/tick.lock (a second
    tick exits at once)."""
    raise NotImplementedError


def main(argv: list[str]) -> int:
    """`fab tick PLAN_DIR [--dry-run]`: one tick, or with --dry-run only print decide's actions."""
    raise NotImplementedError
