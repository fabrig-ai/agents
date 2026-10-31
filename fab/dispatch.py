"""The dispatcher: one idempotent tick keeps a plan's tasks moving (docs/design/fab.md, 13).

`decide` is pure: from the plan, its tasks, the log and the machines it returns the actions
to take now. `tick` gathers those inputs, carries the actions out through `fab.run`,
`fab.land` and git, and prints what it did. Running tick twice in a row is harmless.
"""

from __future__ import annotations

import argparse
import fcntl
import io
import sys
from collections import Counter
from collections.abc import Sequence, Iterable, Mapping
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from fab import call_review, calls, flow, foreman, gates, hosts as machines, land, log, plan as specs, run as runs, state
from fab.hosts import Host
from fab.plan import Plan, Task
from fab.sh import Failed, Runner, run, ssh

MAX_RUNS = 4  # a task with this many runs (rebases aside) and still not landed parks for judgement
ANSWER_AFTER = 30  # minutes the oldest queued question waits before an answer call (the user, 10-30)
ANSWER_AT = 4  # queued questions that start an answer call at once
REVIEW_AT = 10  # tasks landed since the last review call that start one at once
REVIEW_AFTER = 4 * 60  # minutes since the last review call that start one with any landed


def blocking(tasks: Mapping[str, Task], events: list[dict], questions: list[dict], *,
             calls_in_flight: bool = False, design: Sequence[str] = ()) -> bool:
    """Whether an open question holds up other work, so it is answered at once rather than
    batched (the user, 10-30: keep the system live): a task not landed needs a task that is
    parked on one of the questions; or nothing moves while work remains: no run or call in
    flight, no task runnable or rejected, no part waiting for design, and some task not
    landed."""
    views = state.fold(tasks, events)
    parked = {event["task"] for event in questions}
    open_work = [view for view in views.values() if view.status != "landed"]
    if any(need in parked for view in open_work for need in tasks[view.id].needs):
        return True
    moving = (calls_in_flight or bool(design) or bool(in_flight(events))
              or any(view.status in ("runnable", "rejected") for view in open_work))
    return not moving and bool(open_work)


def call_actions(plan: Plan, tasks: Mapping[str, Task], events: list[dict], design: list[str],
                 now: str) -> list[Action]:
    """Advance each call review chain in root-ending order, then start eligible calls.

    Review yields vet, approved yields finish, amend yields an amend call, and hold parks
    the subject. Reviewing, amending, parked and finished chains take no step. Open chains
    block their subject and further answer or review calls of their role. Calls in flight
    also reserve their role. Skeleton parts whose calls ended done stay designed.
    Answer calls count only queued questions, aged from their queued since timestamp,
    using ANSWER_AT or ANSWER_AFTER; structure reviews use REVIEW_AT or
    REVIEW_AFTER since the last review started. Question outcomes park a subject until
    question.answered names it. Pure; see docs/design/fab.md, 12 and 13.1."""
    started = {event["call"]: event for event in events if event.get("ev") == "call.started"}
    ended = {event["call"] for event in events if event.get("ev") == "call.ended"}
    flight = {key: event for key, event in started.items() if key not in ended}
    chains = call_review.chains(events)
    actions = _chain_actions(chains, any(event["role"] == "amend" for event in flight.values()))
    open_chains = [chain for chain in chains.values() if chain.state != "finished"]
    subjects = {chain.subject for chain in open_chains}
    roles = {event["role"] for event in flight.values()}
    roles.update(chain.role for chain in open_chains if chain.role in ("answer", "review"))
    questions = [question for question in foreman.questions(tasks, events)
                 if question.state == "queued"]
    if "answer" not in roles and plan.draft not in subjects and questions:
        old_enough = (datetime.fromisoformat(now) -
                      min(datetime.fromisoformat(question.since) for question in questions)
                      >= timedelta(minutes=ANSWER_AFTER))
        if len(questions) >= ANSWER_AT or old_enough or blocking(
                tasks, events, [{"task": question.task} for question in questions],
                calls_in_flight=bool(roles), design=design):
            actions.append(Action("call", task=plan.draft, run_kind="answer"))
    # A part whose skeleton call succeeded is designed even before its specs reach this plan:
    # the tick that lands them decides on the plan it read before landing.
    designed = {started[identifier].get("subject") for identifier in started
                if any(event.get("ev") == "call.ended" and event.get("call") == identifier
                       and event.get("outcome") == "done" for event in events)}
    parked = _parked_subjects(events, started)
    fresh = [part for part in design if f"{plan.draft}/{part}" not in designed | parked | subjects]
    if "skeleton" not in roles and fresh:
        actions.append(Action("call", task=fresh[0], run_kind="skeleton"))
    subject = f"{plan.draft}/review"
    if "review" not in roles and subject not in parked | subjects and _review_due(tasks, events, now):
        actions.append(Action("call", task=subject, run_kind="review"))
    return actions


def _chain_actions(chains: Mapping[str, call_review.Chain], amending: bool) -> list[Action]:
    """Translate chain states in order, reserving at most one amend call at a time."""
    actions = []
    for chain in chains.values():
        if chain.state in ("review", "approved"):
            actions.append(Action("vet" if chain.state == "review" else "finish",
                                  task=chain.root, run=chain.latest, branch=chain.branch,
                                  run_kind=chain.role))
        elif chain.state == "amend" and not amending:
            actions.append(Action("call", task=chain.root, run_kind="amend"))
            amending = True
        elif chain.state == "hold":
            actions.append(Action("hold", task=chain.subject, run=chain.root, detail=chain.reason))
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
    kind: str  # collect, land, ready, start, park, design, foreman, settle, call, vet, hold, finish
    task: str | None = None
    run: str | None = None
    host: str | None = None
    run_kind: str | None = None  # for start: implement, repair or rebase
    branch: str | None = None
    detail: str = ""
    rejection: dict | None = None


def foreman_actions(tasks: Mapping[str, Task], events: list[dict]) -> list[Action]:
    """Start foremen or settle their answers in question order, leaving deciding and queued
    questions alone. Pure; only questions of tasks in this plan are considered."""
    actions = []
    for question in foreman.questions(tasks, events):
        if question.state == "foreman":
            actions.append(Action("foreman", task=question.task, run=question.run,
                                  detail=question.run))
        elif question.state == "settled":
            actions.append(Action("settle", task=question.task, run=question.foreman,
                                  detail=question.foreman))
    return actions


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
    free = {name: max(0, host.places - occupied[name]) for name, host in hosts.items()
            if "builder" in host.roles}
    for name in free:
        host = hosts[name]
        if not free[name] and (calm or {}).get(name) and (not host.slots or occupied[name] < host.slots):
            free[name] = 1
    return free


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
    4. design: when fewer tasks are runnable or rejected than plan.low times the flow's
       current target (its starting target without prior events), one design action whose
       detail lists, in plan order, parts not designed whose needs are designed or done.
       A need in needs_landed or on a probe part must be done; plan.toml's done counts too.
    Task statuses come from fab.state.fold, part statuses from fab.state.part_statuses.
    """
    flight = in_flight(events)
    free = places(hosts, flight, calm)
    limit = flow.target(plan.draft, events)
    occupied = sum(event["task"].startswith(plan.draft + "/") for event in flight)
    views = state.fold(tasks, events)
    actions = [Action("flow", task=plan.draft, detail=f"target {limit}, {occupied} in flight")]
    actions.extend(Action("collect", task=event["task"], run=event["run"], host=event["host"],
                          detail=event["run"]) for event in flight)
    for identifier, view in views.items():
        if view.status == "done":
            actions.append(Action("land" if tasks[identifier].repo == "agents" else "ready",
                                  task=identifier, branch=view.branch, detail=view.branch or ""))

    candidates = [identifier for status in ("rejected", "runnable")
                  for identifier, view in views.items() if view.status == status]
    actions.extend(_starts(candidates, views, events, free, limit - occupied))

    if len(candidates) < plan.low * limit:
        design = _design_action(plan, tasks, views, hosts, len(candidates))
        if design is not None:
            actions.append(design)
    return actions


def _design_action(plan: Plan, tasks: Mapping[str, Task], views: Mapping[str, state.TaskView],
                   hosts: Mapping[str, Host], ready: int) -> Action | None:
    """List eligible parts after decide checks the ready buffer against the flow target.

    Needs must be designed or done; needs_landed and probe needs must be done.
    """
    statuses = state.part_statuses(plan, tasks, {key: view.status for key, view in views.items()})
    eligible = [part.id for part in plan.parts.values()
                if statuses[part.id] == "not designed" and all(
                    statuses.get(need) == "done" or (
                        statuses.get(need) == "designed" and need not in part.needs_landed
                        and plan.parts[need].mode != "probe")
                    for need in part.needs)]
    return Action("design", detail=", ".join(eligible)) if eligible else None


def _starts(candidates: Iterable[str], views: Mapping[str, state.TaskView], events: list[dict],
            free: dict[str, int], budget: int) -> list[Action]:
    """Reserve places up to the draft's remaining target, parking exhausted tasks for free."""
    actions = []
    for identifier in candidates:
        view = views[identifier]
        # Rebase runs are mechanical (the model's foreman writes them) and do not count.
        kinds = {event["run"]: event.get("kind") for event in events if event.get("ev") == "run.started"}
        if sum(kinds.get(run_id) != "rebase" for run_id in view.runs) >= MAX_RUNS:
            actions.append(Action("park", task=identifier,
                                  run=view.runs[-1],
                                  detail=f"{MAX_RUNS} runs without landing; needs judgement"))
            continue
        if budget <= 0:
            continue
        available = [name for name in free if free[name] > 0]
        if not available:
            continue
        host = min(available, key=lambda name: (-free[name], name))
        kind, rejection = _start_kind(view, events)
        actions.append(Action("start", task=identifier, host=host, run_kind=kind,
                              detail=f"{kind} {host}", rejection=rejection))
        free[host] -= 1
        budget -= 1

    return actions


def _start_kind(view: state.TaskView, events: list[dict]) -> tuple[str, dict | None]:
    """Choose implement, repair or rebase, preserving a refusal since the last run as context."""
    history = [event for event in reversed(events) if event.get("task") == view.id]
    kind = "implement"
    rejection = None
    # history is newest first: a refusal since the last run still decides the kind, even
    # when the task was parked and answered in between.
    last = next((event for event in history if event.get("ev") in ("branch.rejected", "run.started")), {})
    if view.status == "rejected" or last.get("ev") == "branch.rejected":
        rejection = next(event for event in history if event.get("ev") == "branch.rejected")
        kind = "rebase" if rejection.get("step") in ("rebase", "merge") else "repair"
    else:
        ended = next((event for event in history if event.get("ev") == "run.ended"), {})
        if ended.get("outcome") == "infra":
            kind = "repair"
    return kind, rejection


def _import_queue(tasks: Mapping[str, Task], events: list[dict], hosts: Mapping[str, Host], *,
                  sh: Runner, log_path: Path | None) -> None:
    """Append new merge queue records for this plan, skipping torn remote lines."""
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
        for entry in log.records(result.out) if result.ok else ():
            if entry.get("ev") not in ("landed", "rejected"):
                continue
            branch = entry.get("branch")
            if not isinstance(branch, str):
                continue
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


def _land_branch(argv: list[str]) -> None:
    """Land with captured output so a refusal becomes one action failure line."""
    output = io.StringIO()
    with redirect_stdout(output):
        refused = land.main(argv)
    if refused:
        raise RuntimeError(output.getvalue().strip() or "landing refused")


def _land(action: Action, tasks: Mapping[str, Task], *, sh: Runner,
          log_path: Path | None) -> str:
    """Screen a task branch before landing, returning the action's printed detail."""
    findings = (gates.screen(tasks[action.task], log.read(log_path),
                            sh=sh, log_path=log_path)
                if tasks[action.task].repo in gates.REPOS else [])
    if findings:
        return "rejected gate:" + ",".join(dict.fromkeys(
            finding.gate for finding in findings))
    _land_branch([action.branch, "--task", action.task])
    return action.detail


def _ready(action: Action, task: Task, hosts: Mapping[str, Host], *, sh: Runner,
           log_path: Path | None) -> None:
    """Push a repository branch to ready, clearing a same-tip rejection on the gate first."""
    gate_hosts = sorted(name for name, host in hosts.items() if "gate" in host.roles)
    repo = log.home() / "repos" / task.repo
    if not (repo / ".git").exists():
        repo.parent.mkdir(parents=True, exist_ok=True)
        sh(["git", "clone", "-q", runs.REMOTES[task.repo], str(repo)],
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


def _call(action: Action, plan_dir: Path, *, sh: Runner, log_path: Path | None) -> None:
    """Launch a designer or amend call in its numbered user unit, passing the part or root."""
    events = log.read(log_path)
    number = 1 + sum(event.get("ev") == "call.started" and
                     event.get("role") == action.run_kind for event in events)
    argv = ["fab", "call", action.run_kind]
    if action.run_kind in ("skeleton", "amend"):
        argv.append(action.task)
    argv.extend(["--plan", str(plan_dir.resolve())])
    sh(["systemd-run", "--user", "--collect", "--unit",
        f"fab-call-{action.run_kind}-{number}", *argv], check=True)


def _finish(action: Action, *, log_path: Path | None) -> None:
    """Land an approved branch and record answers from the latest call's report or its root's."""
    _land_branch([action.branch])
    chain = call_review.chains(log.read(log_path))[action.task]
    if chain.role == "answer":
        for identifier in dict.fromkeys(_answered(chain)):
            log.append("question.answered", path=log_path, task=identifier, call=chain.latest)


def _take(action: Action, tasks: Mapping[str, Task], hosts: Mapping[str, Host], plan_dir: Path, *,
          plan: Plan, checkout: Path, sh: Runner, log_path: Path | None) -> None:
    """Take a task, foreman or call-chain action, isolating failures and logging each finish
    outcome. A foreman prints its asking run and chosen builder; a failed settlement leaves
    the question unanswered for the next tick."""
    detail = action.detail
    outcome = "failed"
    try:
        match action.kind:
            case "collect":
                _collect(action, hosts, sh=sh, log_path=log_path)
            case "land":
                detail = _land(action, tasks, sh=sh, log_path=log_path)
            case "ready":
                _ready(action, tasks[action.task], hosts, sh=sh, log_path=log_path)
            case "start":
                _start(action, tasks, hosts, sh=sh, log_path=log_path)
            case "call":
                _call(action, plan_dir, sh=sh, log_path=log_path)
            case "foreman":
                detail = _foreman(action, tasks, hosts, sh=sh, log_path=log_path)
            case "settle":
                _settle(action, tasks, plan_dir, sh=sh, log_path=log_path)
            case "vet":
                _vet(action, plan, checkout, hosts, sh=sh, log_path=log_path)
            case "hold":
                _hold(action, log_path=log_path)
            case "finish":
                _finish(action, log_path=log_path)
                outcome = "done"
            case "park":
                _park(action, log_path=log_path)
    except Exception as error:
        detail = "failed: " + " ".join(str(error).splitlines())
        log.append("note", path=log_path,
                   text=f"{action.kind} {action.task or '-'} {detail}")
    finally:
        if action.kind == "finish":
            log.append("call.finished", path=log_path, call=action.run,
                       role=action.run_kind, outcome=outcome)
    print(f"{action.kind} {action.task or '-'} {detail}")


def tick(plan_dir: Path, *, sh: Runner = run, hosts: Mapping[str, Host] | None = None,
         log_path: Path | None = None) -> list[Action]:
    """Fetch the plan checkout and take task, foreman, then call review chain steps.

    Hold a nonblocking FAB_HOME/tick.lock, validate the plan, import queue events and measure
    builders through fab.flow.measure before deciding. Collect runs, gate and land tasks,
    publish ready branches and start runs through the runner. Re-read events to start foremen and land settled answers, then again for
    call decisions counting only queued questions: vet on the freest builder, amend in a user
    unit, park refusals once, or land approved branches and record answers and call.finished.
    Every action reports one line; a failure logs a note and leaves later actions running.
    Return the actions taken. See docs/design/fab.md, 12 and 13.1."""
    home = log.home()
    home.mkdir(parents=True, exist_ok=True)
    with open(home / "tick.lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return []
        result = sh(["git", "rev-parse", "--show-toplevel"], cwd=str(plan_dir))
        checkout = Path(result.out.strip()) if result.ok and result.out.strip() else plan_dir.resolve()
        if result.ok and result.out.strip():
            sh(["git", "fetch", "origin"], cwd=str(checkout), check=True)
        plan, tasks = specs.load(plan_dir)
        hosts = machines.load() if hosts is None else hosts
        events = log.read(log_path)
        _import_queue(tasks, events, hosts, sh=sh, log_path=log_path)
        calm = flow.measure(hosts, log.now(), sh=sh)
        actions = decide(plan, tasks, events, hosts, calm)
        for action in actions:
            _take(action, tasks, hosts, plan_dir, plan=plan, checkout=checkout,
                  sh=sh, log_path=log_path)
        questions = foreman_actions(tasks, log.read(log_path))
        for action in questions:
            _take(action, tasks, hosts, plan_dir, plan=plan, checkout=checkout,
                  sh=sh, log_path=log_path)
        actions.extend(questions)
        design = [part for action in actions if action.kind == "design"
                  for part in action.detail.split(", ")]
        followups = call_actions(plan, tasks, log.read(log_path), design, log.now())
        actions.extend(followups)
        for action in followups:
            _take(action, tasks, hosts, plan_dir, plan=plan, checkout=checkout,
                  sh=sh, log_path=log_path)
        return actions


def _collect(action: Action, hosts: Mapping[str, Host], *, sh: Runner,
             log_path: Path | None) -> None:
    """Collect an in-flight task or call review run using current events."""
    runs.collect(action.run, log.read(log_path), hosts, sh=sh, log_path=log_path)


def _start(action: Action, tasks: Mapping[str, Task], hosts: Mapping[str, Host], *,
           sh: Runner, log_path: Path | None) -> None:
    """Start a task run with current events and the decision's rejection context."""
    runs.start(tasks[action.task], hosts[action.host], kind=action.run_kind,
               events=log.read(log_path), sh=sh, log_path=log_path, rejection=action.rejection)


def _vet(action: Action, plan: Plan, checkout: Path, hosts: Mapping[str, Host], *,
         sh: Runner, log_path: Path | None) -> None:
    """Review the current chain using the builder selection shared with foreman runs."""
    events = log.read(log_path)
    host = _builder(hosts, events)
    chain = call_review.chains(events)[action.task]
    call_review.start(chain, plan.repo, checkout, host, events, sh=sh, log_path=log_path)


def _builder(hosts: Mapping[str, Host], events: list[dict]) -> Host:
    """Choose the builder with most free places, even at zero, breaking ties by name."""
    free = places(hosts, in_flight(events))
    if not free:
        raise ValueError("no builder configured")
    return hosts[min(free, key=lambda name: (-free[name], name))]


def _question(action: Action, tasks: Mapping[str, Task], events: list[dict],
              status: str) -> foreman.Question:
    """Find the action's question in the current state, refusing stale actions."""
    for question in foreman.questions(tasks, events):
        identifier = question.run if status == "foreman" else question.foreman
        if question.task == action.task and identifier == action.run and question.state == status:
            return question
    raise ValueError(f"no {status} question for {action.task} {action.run}")


def _foreman(action: Action, tasks: Mapping[str, Task], hosts: Mapping[str, Host], *,
             sh: Runner, log_path: Path | None) -> str:
    """Recompute a pending question and start its foreman on the freest builder."""
    events = log.read(log_path)
    question = _question(action, tasks, events, "foreman")
    host = _builder(hosts, events)
    foreman.start(question, tasks[action.task], host, log.read(log_path), sh=sh, log_path=log_path)
    return f"{question.run} {host.name}"


def _settle(action: Action, tasks: Mapping[str, Task], plan_dir: Path, *,
            sh: Runner, log_path: Path | None) -> None:
    """Commit and land a settled answer before recording it; failures leave it retryable.

    Resolve the plan's git checkout through the runner, refusing a non-checkout. An answer
    already recorded by commit needs no landing. Read the collected report locally and log
    its first answer line with both the asking and foreman runs after success."""
    question = _question(action, tasks, log.read(log_path), "settled")
    result = sh(["git", "rev-parse", "--show-toplevel"], cwd=str(plan_dir), check=True)
    if not result.out.strip():
        raise ValueError("plan is not a git checkout")
    answer = foreman.answer((log.home() / "runs" / action.run / "report.md").read_text())
    branch = foreman.commit(question, tasks[action.task], answer, Path(result.out.strip()),
                            run_id=action.run, day=log.now()[:10], sh=sh)
    if branch is not None:
        _land_branch([branch])
    log.append("question.answered", path=log_path, task=question.task, by=action.run,
               run=question.run, answer=answer.splitlines()[0])


def _hold(action: Action, *, log_path: Path | None) -> None:
    """Park a chain's subject with the last refusing review's report path, when available."""
    events = log.read(log_path)
    chain = call_review.chains(events)[action.run]
    refusal = chain.refusals[-1] if chain.refusals else None
    report = next((event.get("report", "") for event in reversed(events)
                   if refusal is not None and event.get("ev") == "run.ended"
                   and event.get("run") == refusal), "")
    log.append("call.parked", path=log_path, call=chain.root, subject=chain.subject,
               reason=action.detail, report=report)


def _answered(chain: call_review.Chain) -> list[str]:
    """Read the latest call's Answered line, falling back to the root when absent or unreadable."""
    for identifier in dict.fromkeys((chain.latest, chain.root)):
        try:
            report = (log.home() / "calls" / identifier / "report.md").read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for line in report.splitlines():
            if line.startswith("Answered:"):
                return line.removeprefix("Answered:").split()
    return []


def _park(action: Action, *, log_path: Path | None) -> None:
    """Park a task that exhausted its run allowance by asking for judgement."""
    log.append("question.asked", path=log_path, task=action.task, run=action.run, text=action.detail)


def main(argv: list[str]) -> int:
    """`fab tick PLAN_DIR [--dry-run]`: one tick, or with --dry-run only print decide's actions
    (no builder measured, so none is calm)."""
    parser = argparse.ArgumentParser(prog="fab tick", description=__doc__)
    parser.add_argument("plan_dir", type=Path, metavar="PLAN_DIR")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.dry_run:
            plan, tasks = specs.load(args.plan_dir)
            for action in decide(plan, tasks, log.read(), machines.load()):
                print(f"{action.kind} {action.task or '-'} {action.detail}")
        else:
            tick(args.plan_dir)
    except (OSError, ValueError, Failed) as error:
        print("fab tick: " + " ".join(str(error).splitlines()), file=sys.stderr)
        return 1
    return 0
