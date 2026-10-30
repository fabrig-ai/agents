"""The dispatcher: one idempotent tick keeps a plan's tasks moving (docs/design/fab.md, 10).

`decide` is pure: from the plan, its tasks, the log and the machines it returns the actions
to take now. `tick` gathers those inputs, carries the actions out through `fab.run`,
`fab.land` and git, and prints what it did. Running tick twice in a row is harmless.
"""

from __future__ import annotations

import argparse
import fcntl
import io
import json
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path

from fab import hosts as machines, land, log, plan as specs, run as runs, state
from fab.hosts import Host
from fab.plan import Plan, Task
from fab.sh import Failed, Runner, run, ssh

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
    events = list(events)
    ended = {event["run"] for event in events if event.get("ev") == "run.ended"}
    return [event for event in events
            if event.get("ev") == "run.started" and event["run"] not in ended]


def places(hosts: Mapping[str, Host], flight: Iterable[dict]) -> dict[str, int]:
    """Free Codex places per builder: its `places` minus its runs in flight (never below 0)."""
    occupied = Counter(event["host"] for event in flight)
    return {name: max(0, host.places - occupied[name]) for name, host in hosts.items()
            if "builder" in host.roles}


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
    flight = in_flight(events)
    free = places(hosts, flight)
    views = state.fold(tasks, events)
    actions = [Action("collect", task=event["task"], run=event["run"], host=event["host"],
                      detail=event["run"]) for event in flight]
    for identifier, view in views.items():
        if view.status == "done":
            actions.append(Action("land" if tasks[identifier].repo == "agents" else "ready",
                                  task=identifier, branch=view.branch, detail=view.branch or ""))

    candidates = [identifier for status in ("rejected", "runnable")
                  for identifier, view in views.items() if view.status == status]
    for identifier in candidates:
        view = views[identifier]
        if len(view.runs) >= MAX_RUNS:
            actions.append(Action("park", task=identifier,
                                  run=view.runs[-1],
                                  detail=f"{MAX_RUNS} runs without landing; needs judgement"))
            continue
        available = [name for name in free if free[name] > 0]
        if not available:
            continue
        host = min(available, key=lambda name: (-free[name], name))
        history = [event for event in reversed(events) if event.get("task") == identifier]
        kind = "implement"
        if view.status == "rejected":
            rejection = next(event for event in history if event.get("ev") == "branch.rejected")
            kind = "rebase" if rejection.get("step") in ("rebase", "merge") else "repair"
        else:
            ended = next((event for event in history if event.get("ev") == "run.ended"), {})
            if ended.get("outcome") == "infra":
                kind = "repair"
        actions.append(Action("start", task=identifier, host=host, run_kind=kind,
                              detail=f"{kind} {host}"))
        free[host] -= 1

    capacity = sum(host.places for host in hosts.values() if "builder" in host.roles)
    if len(candidates) < plan.low * capacity:
        by_part = {part: [identifier for identifier, task in tasks.items() if task.part == part]
                   for part in plan.parts}
        eligible = [part.id for part in plan.parts.values() if not by_part[part.id]
                    and all(by_part.get(need) and all(views[identifier].status == "landed"
                                                     for identifier in by_part[need])
                            for need in part.needs)]
        if eligible:
            actions.append(Action("design", detail=", ".join(eligible)))
    return actions


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
    home = log.home()
    home.mkdir(parents=True, exist_ok=True)
    with open(home / "tick.lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return []
        checkout = sh(["git", "rev-parse", "--show-toplevel"], cwd=str(plan_dir))
        if checkout.ok and checkout.out.strip():
            sh(["git", "fetch", "origin"], cwd=checkout.out.strip(), check=True)
        plan = specs.load_plan(plan_dir / "plan.toml")
        tasks = specs.load_tasks(plan_dir / "tasks", plan.draft, plan.repo)
        issues = specs.problems(plan, tasks)
        if issues:
            raise specs.PlanError("\n".join(issues))
        hosts = machines.load() if hosts is None else hosts
        events = log.read(log_path)
        gates = sorted(name for name, host in hosts.items() if "gate" in host.roles)
        if gates:
            imported = {(event.get("queue_ts"), event.get("ev"), event.get("branch"),
                         event.get("tip")) for event in events if "queue_ts" in event}
            since = max((event["queue_ts"] for event in events if "queue_ts" in event), default="")
            result = sh(ssh(hosts[gates[0]].ssh, ["fab", "queue", "log", "--since", since]))
            if not result.ok:
                # The queue's record is read again next tick; the other actions still run.
                failure = " ".join((result.err or result.out).strip().splitlines()[-3:])
                log.append("note", path=log_path, text=f"queue import failed: {failure}")
                print(f"import - failed: {failure}")
            for line in result.out.splitlines() if result.ok else ():
                entry = json.loads(line)
                if entry.get("ev") not in ("landed", "rejected"):
                    continue
                branch = entry["branch"]
                identifier = land.task_of(branch)
                if identifier not in tasks:
                    continue
                ev = "branch." + entry["ev"]
                key = (entry["ts"], ev, branch, entry.get("tip"))
                if key in imported:
                    continue
                fields = {field: entry[field] for field in ("tip", "main", "step", "log")
                          if field in entry}
                events.append(log.append(ev, path=log_path, task=identifier, branch=branch,
                                         queue_ts=entry["ts"], **fields))
                imported.add(key)

        actions = decide(plan, tasks, events, hosts)
        for action in actions:
            detail = action.detail
            try:
                match action.kind:
                    case "collect":
                        runs.collect(action.run, log.read(log_path), hosts, sh=sh, log_path=log_path)
                    case "land":
                        output = io.StringIO()
                        with redirect_stdout(output):
                            refused = land.main([action.branch, "--task", action.task])
                        if refused:
                            raise RuntimeError(output.getvalue().strip() or "landing refused")
                    case "ready":
                        repo = home / "repos" / tasks[action.task].repo
                        if not (repo / ".git").exists():
                            repo.parent.mkdir(parents=True, exist_ok=True)
                            sh(["git", "clone", "-q", runs.REMOTES[tasks[action.task].repo], str(repo)],
                               check=True)
                        sh(["git", "fetch", "origin"], cwd=str(repo), check=True)
                        tip = sh(["git", "rev-parse", "--verify",
                                  f"refs/remotes/origin/{action.branch}^{{commit}}"],
                                 cwd=str(repo), check=True).out.strip()
                        if not tip:
                            raise ValueError("branch has no tip")
                        sh(["git", "push", "origin", f"{tip}:refs/heads/ready/{action.branch}"],
                           cwd=str(repo), check=True)
                        log.append("branch.ready", path=log_path, task=action.task,
                                   branch=action.branch, tip=tip)
                    case "start":
                        runs.start(tasks[action.task], hosts[action.host], kind=action.run_kind,
                                   events=log.read(log_path), sh=sh, log_path=log_path)
                    case "park":
                        log.append("question.asked", path=log_path, task=action.task,
                                   run=action.run, text=action.detail)
            except Exception as error:
                detail = "failed: " + " ".join(str(error).splitlines())
                log.append("note", path=log_path,
                           text=f"{action.kind} {action.task or '-'} {detail}")
            print(f"{action.kind} {action.task or '-'} {detail}")
        return actions


def main(argv: list[str]) -> int:
    """`fab tick PLAN_DIR [--dry-run]`: one tick, or with --dry-run only print decide's actions."""
    parser = argparse.ArgumentParser(prog="fab tick", description=__doc__)
    parser.add_argument("plan_dir", type=Path, metavar="PLAN_DIR")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.dry_run:
            plan = specs.load_plan(args.plan_dir / "plan.toml")
            tasks = specs.load_tasks(args.plan_dir / "tasks", plan.draft, plan.repo)
            issues = specs.problems(plan, tasks)
            if issues:
                raise specs.PlanError("\n".join(issues))
            for action in decide(plan, tasks, log.read(), machines.load()):
                print(f"{action.kind} {action.task or '-'} {action.detail}")
        else:
            tick(args.plan_dir)
    except (OSError, ValueError, Failed) as error:
        print("fab tick: " + " ".join(str(error).splitlines()), file=sys.stderr)
        return 1
    return 0
