"""The dispatcher: one idempotent tick keeps a plan's tasks moving (docs/design/fab.md, 13).

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
from datetime import datetime, timedelta
from pathlib import Path

from fab import calls, gates, hosts as machines, land, log, plan as specs, run as runs, state
from fab.hosts import Host
from fab.plan import Plan, Task
from fab.sh import Failed, Runner, run, ssh

MAX_RUNS = 4  # a task with this many runs and still not landed parks for judgement
ANSWER_AFTER = 120  # minutes the oldest open question waits before an answer call
ANSWER_AT = 4  # open questions that start an answer call at once
REVIEW_AT = 10  # tasks landed since the last review call that start one at once
REVIEW_AFTER = 4 * 60  # minutes since the last review call that start one with any landed


def call_actions(plan: Plan, tasks: Mapping[str, Task], events: list[dict], design: list[str],
                 now: str) -> list[Action]:
    """The Claude calls to start or finish now (docs/design/fab.md, 13), after decide's actions.

    A call is in flight from its call.started to its call.ended; at most one call of each role
    is in flight. finish: every call.ended with outcome done and no later call.finished for
    it, with branch from its call.started: land its branch (agents repo), and for an answer
    call log question.answered for each task its report's `Answered:` line names. start:
    an answer call (subject the plan's draft) when no answer call is in flight and the open
    questions (fab.calls.open_questions) number ANSWER_AT or more, or the oldest is ANSWER_AFTER
    minutes old at `now`; a skeleton call for the first part of decide's design list that has
    no successful skeleton call yet (subject `<draft>/<part>`) and is not parked by a call
    that ended with a question (until question.answered names the subject), when no skeleton
    call is in flight; a review call (subject `<draft>/review`), when no review call is in
    flight, the subject is not parked, and the branches landed since the last review call
    (fab.calls.landed_after with fab.calls.last_review(events): any outcome, so a failed one
    waits for the next threshold) number REVIEW_AT or more, or are at least one with
    REVIEW_AFTER minutes passed at `now` since that call.started (since the first of them when
    there was no review call). Actions: Action("call", task=<subject>, run_kind=<role>) and
    Action("finish", run=<call id>, run_kind=<role>, branch=<branch>), the review last."""
    started = {event["call"]: event for event in events if event.get("ev") == "call.started"}
    flight = dict(started)
    pending = {}
    for event in events:
        identifier = event.get("call")
        if event.get("ev") == "call.ended":
            flight.pop(identifier, None)
            if event.get("outcome") == "done" and identifier in started:
                pending[identifier] = started[identifier]
        elif event.get("ev") == "call.finished":
            pending.pop(identifier, None)
    actions = [Action("finish", run=identifier, run_kind=event["role"], branch=event["branch"])
               for identifier, event in pending.items()]
    roles = {event["role"] for event in flight.values()}
    questions = [event for event in calls.open_questions(events) if event["task"] in tasks]
    if "answer" not in roles and questions:
        old_enough = (datetime.fromisoformat(now) -
                      min(datetime.fromisoformat(event["ts"]) for event in questions)
                      >= timedelta(minutes=ANSWER_AFTER))
        if len(questions) >= ANSWER_AT or old_enough:
            actions.append(Action("call", task=plan.draft, run_kind="answer"))
    # A part whose skeleton call succeeded is designed even before its specs reach this plan:
    # the tick that lands them decides on the plan it read before landing.
    designed = {started[identifier].get("subject") for identifier in started
                if any(event.get("ev") == "call.ended" and event.get("call") == identifier
                       and event.get("outcome") == "done" for event in events)}
    parked = _parked_subjects(events, started)
    fresh = [part for part in design if f"{plan.draft}/{part}" not in designed | parked]
    if "skeleton" not in roles and fresh:
        actions.append(Action("call", task=fresh[0], run_kind="skeleton"))
    subject = f"{plan.draft}/review"
    if "review" not in roles and subject not in parked and _review_due(tasks, events, now):
        actions.append(Action("call", task=subject, run_kind="review"))
    return actions


def _parked_subjects(events: list[dict], started: Mapping[str, dict]) -> set[str | None]:
    # A call that asked a question parks its subject until question.answered names it.
    parked = set()
    for event in events:
        if event.get("ev") == "call.ended" and event.get("outcome") == "question":
            parked.add(started.get(event.get("call"), {}).get("subject"))
        elif event.get("ev") == "question.answered":
            parked.discard(event.get("task"))
    return parked


def _review_due(tasks: Mapping[str, Task], events: list[dict], now: str) -> bool:
    previous = calls.last_review(events)
    landed = calls.landed_after(events, tasks, previous)
    return bool(landed) and (len(landed) >= REVIEW_AT or
                            datetime.fromisoformat(now) - datetime.fromisoformat(previous or landed[0]["ts"])
                            >= timedelta(minutes=REVIEW_AFTER))


@dataclass(frozen=True)
class Action:
    kind: str  # collect, land, ready, start, park, design
    task: str | None = None
    run: str | None = None
    host: str | None = None
    run_kind: str | None = None  # for start: implement, repair or rebase
    branch: str | None = None
    detail: str = ""
    rejection: dict | None = None


def in_flight(events: Iterable[dict]) -> list[dict]:
    """run.started records without a run.ended for the same run, in log order."""
    events = list(events)
    ended = {event["run"] for event in events if event.get("ev") == "run.ended"}
    return [event for event in events
            if event.get("ev") == "run.started" and event["run"] not in ended]


def places(hosts: Mapping[str, Host], flight: Iterable[dict],
           calm: Mapping[str, bool] | None = None) -> dict[str, int]:
    """Free Codex places per builder: its `places` minus its runs in flight (never below 0).

    `places` is a hint (docs/design/fab.md, 13.2): a builder with none free that calm names
    True (fab.flow.measure) gets 1, while its runs in flight are fewer than its `slots` (any
    number when slots is 0). calm None is no builder calm."""
    occupied = Counter(event["host"] for event in flight)
    return {name: max(0, host.places - occupied[name]) for name, host in hosts.items()
            if "builder" in host.roles}


def decide(plan: Plan, tasks: Mapping[str, Task], events: list[dict], hosts: Mapping[str, Host],
           calm: Mapping[str, bool] | None = None) -> list[Action]:
    """The actions for now, in this order:

    0. flow: one Action("flow", task=plan.draft, detail="target <n>, <m> in flight"), n being
       fab.flow.target(plan.draft, events) and m the runs in flight of the draft's tasks
       (task starting with `<draft>/`). It is printed, never carried out.
    1. collect: every run in flight.
    2. land (repo "agents") or ready (any other repo): every task whose status is done, with
       the branch of its last run.
    3. start: for rejected tasks first, then runnable ones in the tasks' order, while the
       draft's runs in flight plus the starts so far are below the target and a builder has a
       free place by places(hosts, flight, calm) (the builder with most free places first;
       ties by name). A rejected task's run_kind is rebase when its last branch.rejected step
       is rebase or merge, otherwise repair; a runnable task's is implement, or repair when its
       last run ended infra. A task that already has MAX_RUNS runs gets park instead of start,
       whatever the target and the places.
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
        rejection = None
        if view.status == "rejected":
            rejection = next(event for event in history if event.get("ev") == "branch.rejected")
            kind = "rebase" if rejection.get("step") in ("rebase", "merge") else "repair"
        else:
            ended = next((event for event in history if event.get("ev") == "run.ended"), {})
            if ended.get("outcome") == "infra":
                kind = "repair"
        actions.append(Action("start", task=identifier, host=host, run_kind=kind,
                              detail=f"{kind} {host}", rejection=rejection))
        free[host] -= 1

    capacity = sum(host.places for host in hosts.values() if "builder" in host.roles)
    if len(candidates) < plan.low * capacity:
        by_part = {part: [identifier for identifier, task in tasks.items() if task.part == part]
                   for part in plan.parts}
        def landed(part_id):
            part = plan.parts.get(part_id)
            return part is not None and (part.done or bool(by_part[part_id]) and all(
                views[identifier].status == "landed" for identifier in by_part[part_id]))

        eligible = [part.id for part in plan.parts.values() if not part.done and not by_part[part.id]
                    and all(landed(need) for need in part.needs)]
        if eligible:
            actions.append(Action("design", detail=", ".join(eligible)))
    return actions


def tick(plan_dir: Path, *, sh: Runner = run, hosts: Mapping[str, Host] | None = None,
         log_path: Path | None = None) -> list[Action]:
    """One tick for the plan in plan_dir (a checkout of its repository's main, fetched first).

    First, import the merge queue's new records: `fab queue log --since <ts>` over ssh on the
    host with role gate, ts being the latest `queue_ts` already imported; each `landed` or
    `rejected` record naming a task of this plan becomes branch.landed or branch.rejected,
    carrying queue_ts. Then measure the builders (fab.flow.measure with sh, at fab.log.now())
    and take decide's actions, given that calm: flow is only printed, collect through
    fab.run.collect, land through fab.land.main with the branch (a task of a repository in fab.gates.REPOS first
    through fab.gates.screen: with any finding the branch is not landed, screen having
    logged branch.rejected, and the action's detail is `rejected gate:<gate>[,<gate>...]`,
    the findings' gates in order), ready by pushing the branch's tip to `ready/<branch>`
    in its repository's clone under FAB_HOME/repos (logging branch.ready), start through
    fab.run.start, park by logging question.asked with the detail as text. Design actions are
    printed; call_actions' follow them: call starts `fab call <role> [<part>] --plan PLAN_DIR`
    in a user unit (`systemd-run --user --collect --unit fab-call-<role>-<n>`), which logs
    the call's own events, and returns at once; finish lands the call's branch through
    fab.land.main, logs any question.answered, then call.finished (call, role, outcome of the
    landing). A failed action is printed and logged as a note; the others still
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
        gate_hosts = sorted(name for name, host in hosts.items() if "gate" in host.roles)
        if gate_hosts:
            imported = {(event.get("queue_ts"), event.get("ev"), event.get("branch"),
                         event.get("tip")) for event in events if "queue_ts" in event}
            since = max((event["queue_ts"] for event in events if "queue_ts" in event), default="")
            result = sh(ssh(hosts[gate_hosts[0]].ssh, ["fab", "queue", "log", "--since", since]))
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

        def take(action):
            detail = action.detail
            outcome = "failed"
            try:
                match action.kind:
                    case "collect":
                        runs.collect(action.run, log.read(log_path), hosts, sh=sh, log_path=log_path)
                    case "land":
                        findings = (gates.screen(tasks[action.task], log.read(log_path),
                                                sh=sh, log_path=log_path)
                                    if tasks[action.task].repo in gates.REPOS else [])
                        if findings:
                            detail = "rejected gate:" + ",".join(dict.fromkeys(
                                finding.gate for finding in findings))
                        else:
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
                        rejection = next((event for event in reversed(log.read(log_path))
                                          if event.get("ev") == "branch.rejected"
                                          and event.get("task") == action.task), None)
                        if rejection is not None and tip == rejection.get("tip"):
                            if not gate_hosts:
                                raise ValueError("no gate host configured for queue untry")
                            sh(ssh(hosts[gate_hosts[0]].ssh,
                                   ["fab", "queue", "untry", action.branch]), check=True)
                            log.append("note", path=log_path,
                                       text=f"retry {action.task}: same tip after repair")
                        sh(["git", "push", "origin", f"{tip}:refs/heads/ready/{action.branch}"],
                           cwd=str(repo), check=True)
                        log.append("branch.ready", path=log_path, task=action.task,
                                   branch=action.branch, tip=tip)
                    case "start":
                        runs.start(tasks[action.task], hosts[action.host], kind=action.run_kind,
                                   events=log.read(log_path), sh=sh, log_path=log_path,
                                   rejection=action.rejection)
                    case "call":
                        events = log.read(log_path)
                        number = 1 + sum(event.get("ev") == "call.started" and
                                         event.get("role") == action.run_kind for event in events)
                        argv = ["fab", "call", action.run_kind]
                        if action.run_kind == "skeleton":
                            argv.append(action.task)
                        argv.extend(["--plan", str(plan_dir.resolve())])
                        sh(["systemd-run", "--user", "--collect", "--unit",
                            f"fab-call-{action.run_kind}-{number}", *argv], check=True)
                    case "finish":
                        output = io.StringIO()
                        with redirect_stdout(output):
                            refused = land.main([action.branch])
                        if refused:
                            raise RuntimeError(output.getvalue().strip() or "landing refused")
                        if action.run_kind == "answer":
                            report = (home / "calls" / action.run / "report.md").read_text(encoding="utf-8")
                            answered = next((line.removeprefix("Answered:").split()
                                             for line in report.splitlines()
                                             if line.startswith("Answered:")), [])
                            for identifier in dict.fromkeys(answered):
                                log.append("question.answered", path=log_path, task=identifier,
                                           call=action.run)
                        outcome = "done"
                    case "park":
                        log.append("question.asked", path=log_path, task=action.task,
                                   run=action.run, text=action.detail)
            except Exception as error:
                detail = "failed: " + " ".join(str(error).splitlines())
                log.append("note", path=log_path,
                           text=f"{action.kind} {action.task or '-'} {detail}")
            finally:
                if action.kind == "finish":
                    log.append("call.finished", path=log_path, call=action.run,
                               role=action.run_kind, outcome=outcome)
            print(f"{action.kind} {action.task or '-'} {detail}")

        for action in actions:
            take(action)
        design = [part for action in actions if action.kind == "design"
                  for part in action.detail.split(", ")]
        followups = call_actions(plan, tasks, log.read(log_path), design, log.now())
        actions.extend(followups)
        for action in followups:
            take(action)
        return actions


def main(argv: list[str]) -> int:
    """`fab tick PLAN_DIR [--dry-run]`: one tick, or with --dry-run only print decide's actions
    (no builder measured, so none is calm)."""
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
