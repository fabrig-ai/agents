"""The dispatcher: one idempotent tick keeps every plan's tasks moving (docs/design/fab.md, 13).

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
import tempfile
from collections import Counter
from collections.abc import Sequence, Iterable, Mapping
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from fab import buffer, call_review, calls, channel, designer, drafts, flow, foreman, gates, hosts as machines, integration, land, log, plan as specs, receipts, repairs, run as runs, rust_gates, state, wake
from fab.hosts import Host
from fab.plan import Plan, Task
from fab.sh import Failed, Runner, run, ssh

MAX_RUNS = 4  # a task with this many runs (rebases aside) and still not landed parks for judgement
ANSWER_AFTER = 30  # minutes the oldest queued question waits before an answer call (the user, 10-30)
ANSWER_AT = 4  # queued questions that start an answer call at once
REVIEW_AT = 10  # tasks landed since the last review call that start one at once
REVIEW_AFTER = 4 * 60  # minutes since the last review call that start one with any landed


def blocking(tasks: Mapping[str, Task], events: list[dict], questions: list[dict], *,
             calls_in_flight: bool = False, design: Sequence[str] = (),
             draft: str | None = None) -> bool:
    """Whether an open question holds up other work, so it is answered at once rather than
    batched (the user, 10-30: keep the system live): a task not landed needs a task that is
    parked on one of the questions; or nothing moves while work remains: no run or call in
    flight, no task runnable or rejected, no part waiting for design, and some task not
    landed. With draft, only its owned runs count as moving."""
    views = state.fold(tasks, events)
    parked = {event["task"] for event in questions}
    open_work = [view for view in views.values() if view.status != "landed"]
    if any(need in parked for view in open_work for need in tasks[view.id].needs):
        return True
    flight = in_flight(events)
    if draft is not None:
        flight = drafts.owned(draft, flight, events)
    moving = (calls_in_flight or bool(design) or bool(flight)
              or any(view.status in ("runnable", "rejected") for view in open_work))
    return not moving and bool(open_work)


def call_actions(plan: Plan, tasks: Mapping[str, Task], events: list[dict], design: list[str],
                 now: str) -> list[Action]:
    """Advance this draft's chains, then answer, design, review and retire calls.

    In-flight calls and open chains reserve answer, review and amend only within the
    draft. Fresh skeleton and contract parts share its flow target, in design order.
    Successful calls stay designed; parked subjects and open chains block their subject.
    Queued questions use ANSWER_AT, ANSWER_AFTER or draft-local blocking; reviews use
    REVIEW_AT or REVIEW_AFTER since this draft's last review started. Retire follows
    review once every part is done. Pure; docs/design/fab.md, 12, 13.1 and 13.4.
    """
    started = {event["call"]: event for event in events if event.get("ev") == "call.started"}
    ended = {event["call"] for event in events if event.get("ev") == "call.ended"}
    flight = {key: event for key, event in started.items()
              if key not in ended and drafts.under(plan.draft, event.get("subject"))}
    chains = call_review.chains(events)
    own = {root: chain for root, chain in chains.items()
           if drafts.under(plan.draft, chain.subject)}
    actions = _chain_actions(own, any(event["role"] == "amend" for event in flight.values()),
                             reviews=plan.reviews)
    open_chains = [chain for chain in own.values() if chain.state != "finished"]
    subjects = {chain.subject for chain in open_chains}
    roles = {event["role"] for event in flight.values()}
    roles.update(chain.role for chain in open_chains if chain.role in ("answer", "review"))
    questions = [question for question in foreman.questions(tasks, events)
                 if question.state == "queued"]
    parked = _parked_subjects(events)
    if "answer" not in roles and plan.draft not in parked | subjects and questions:
        old_enough = (datetime.fromisoformat(now) -
                      min(datetime.fromisoformat(question.since) for question in questions)
                      >= timedelta(minutes=ANSWER_AFTER))
        if plan.landing == "integration" or len(questions) >= ANSWER_AT or old_enough or blocking(
                tasks, events, [{"task": question.task} for question in questions],
                calls_in_flight=bool(roles), design=design, draft=plan.draft):
            actions.append(Action("call", task=plan.draft, run_kind="answer"))
    actions.extend(_part_calls(plan, design, started, events, parked | subjects))
    subject = f"{plan.draft}/review"
    if (plan.reviews and "review" not in roles and subject not in parked | subjects
            and _review_due(plan.draft, tasks, events, now)):
        actions.append(Action("call", task=subject, run_kind="review"))
    subject = designer.subject(plan.draft, "retire")
    if ("retire" not in roles and subject not in parked | subjects
            and designer.retire_due(plan, tasks, events)):
        actions.append(Action("call", task=subject, run_kind="retire"))
    return actions


def _part_calls(plan: Plan, design: list[str], started: Mapping[str, dict], events: list[dict],
                blocked: set[str | None]) -> list[Action]:
    """Start fresh design parts in order up to the draft's shared design-call limit.

    Done calls reserve their subject before their specs reach the plan; parked subjects
    and open chains also block a part. Skeleton and contract share the flow target.
    """
    completed = {event["call"] for event in events
                 if event.get("ev") == "call.ended" and event.get("outcome") == "done"}
    designed = {event.get("subject") for call, event in started.items() if call in completed}
    fresh = [part for part in design if f"{plan.draft}/{part}" not in designed | blocked]
    return [Action("call", task=part, run_kind=role)
            for part, role in drafts.design_calls(plan, fresh, events)]


def _chain_actions(chains: Mapping[str, call_review.Chain], amending: bool, *,
                   reviews: bool = True) -> list[Action]:
    """Translate chain states in order, reserving at most one amend call at a time."""
    actions = []
    for chain in chains.values():
        if chain.state in ("review", "approved"):
            actions.append(Action("vet" if chain.state == "review" and reviews else "finish",
                                  task=chain.root, run=chain.latest, branch=chain.branch,
                                  run_kind=chain.role))
        elif chain.state == "amend" and not amending:
            actions.append(Action("call", task=chain.root, run_kind="amend"))
            amending = True
        elif chain.state == "hold":
            actions.append(Action("hold", task=chain.subject, run=chain.root, detail=chain.reason))
    return actions


def _parked_subjects(events: list[dict]) -> set[str]:
    """The call questions that still wait for the user, shared with the page's fold."""
    return {ask.subject for ask in channel.asks((), events) if ask.kind == "call"}


def _review_due(draft: str, tasks: Mapping[str, Task], events: list[dict], now: str) -> bool:
    """Whether enough tasks landed, or time passed, since this draft's last review."""
    previous = calls.last_review(events, draft=draft)
    landed = calls.landed_after(events, tasks, previous)
    return bool(landed) and (len(landed) >= REVIEW_AT or
                            datetime.fromisoformat(now) - datetime.fromisoformat(previous or landed[0]["ts"])
                            >= timedelta(minutes=REVIEW_AFTER))


@dataclass(frozen=True)
class Action:
    kind: str  # collect, land, ready, merge, start, park, design, foreman, settle, examine, remedy, call, vet, hold, finish
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


def repair_actions(tasks: Mapping[str, Task], events: list[dict]) -> list[Action]:
    """Return actions to start refusal foremen or act on verdicts, one per open refusal of
    fab.repairs.refusals(tasks, events), in its order (docs/design/fab.md, 13.1):
    - foreman: Action("examine", task=<task>, branch=<refused branch>, detail="<step>
      <branch>");
    - decided: Action("remedy", task=<task>, run=<foreman run>, detail=<foreman run>);
    - deciding, settled and fallback: nothing (decide starts the run that follows a
      settled fix or none, or a fallback; a settled retry folds as done, so decide lands
      or readies it again).
    Pure; only refusals of tasks in tasks are considered."""
    actions = []
    for refusal in repairs.refusals(tasks, events):
        if refusal.state == "foreman":
            actions.append(Action("examine", task=refusal.task, branch=refusal.branch,
                                  detail=f"{refusal.step} {refusal.branch}"))
        elif refusal.state == "decided":
            actions.append(Action("remedy", task=refusal.task, run=refusal.foreman,
                                  detail=refusal.foreman))
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
       the sum of builders' places for integration plans (13.12), or fab.flow.target
       starting at those places for queue plans. m is the runs in flight of the draft's
       tasks (task starting with `<draft>/`). It is printed, never carried out.
    1. collect: only this draft's owned runs, including its calls' review runs.
    2. merge (integration plans), land (repo "agents") or ready (any other repo): done tasks with
       the branch of its last run.
    3. start: for rejected and runnable tasks in fab.buffer.order's order, refused
       being those whose start carries a refusal, while the draft's runs in flight plus
       the starts so far are below the target and a builder has a
       free place by places(hosts, flight, calm) (the builder with most free places first;
       ties by name). A rejected task's run_kind is rebase when its last branch.rejected step
       is rebase or merge, otherwise repair; a runnable task's is implement, or repair when its
       last run ended infra. A task that already has MAX_RUNS runs gets park instead of start,
       whatever the target and the places. An open refusal permits neither start nor park
       until settled fix or none, or fallback. Settled fixes add their section to the start's
       rejection; settled retries fold as done and go through step 2.
    4. design: when fewer tasks are runnable or rejected than plan.low times the flow's
       current target (its starting target without prior events), one design action whose
       detail lists, in plan order, parts not designed whose needs are designed or done.
       A need in needs_landed or on a probe part must be done; plan.toml's done counts too.
       An unanswered plan question excludes every part it names.
    Task statuses come from fab.state.fold, part statuses from fab.state.part_statuses.
    """
    flight = in_flight(events)
    free = places(hosts, flight, calm)
    capacity = sum(host.places for host in hosts.values() if "builder" in host.roles)
    limit = capacity if plan.landing == "integration" else flow.target(plan.draft, events, start=capacity)
    occupied = sum(event["task"].startswith(plan.draft + "/") for event in flight)
    tasks = {**integration.repair_tasks(plan, events, {}), **specs.checked_tasks(plan, tasks, events)}
    views = state.fold(tasks, events)
    actions = [Action("flow", task=plan.draft, detail=f"target {limit}, {occupied} in flight")]
    actions.extend(Action("collect", task=event["task"], run=event["run"], host=event["host"],
                          detail=event["run"]) for event in drafts.owned(plan.draft, flight, events))
    landings, rebases, events = _landing_actions(plan, tasks, views, events)
    actions.extend(landings)

    candidates = [identifier for status in ("rejected", "runnable")
                  for identifier, view in views.items() if view.status == status]
    refused = {identifier for identifier in candidates
               if _start_kind(views[identifier], events)[1] is not None}
    candidates = buffer.order(plan, tasks, rebases + candidates, refused | set(rebases))
    refusals = {refusal.task: refusal for refusal in repairs.refusals(tasks, events)
                if refusal.task not in rebases}
    step = integration.next_step(plan, tasks, events)
    if step is None or step.kind != "stop":
        actions.extend(_starts(candidates, views, events, free, limit - occupied, refusals))

    if len(candidates) < plan.low * limit:
        design = _design_action(plan, tasks, views, hosts, len(candidates))
        if design is not None:
            actions.append(design)
    return actions


def _design_action(plan: Plan, tasks: Mapping[str, Task], views: Mapping[str, state.TaskView],
                   hosts: Mapping[str, Host], ready: int) -> Action | None:
    """List eligible parts after decide checks the ready buffer against the flow target.

    Needs must be designed or done; needs_landed and probe needs must be done.
    Parts named by a plan question with an empty answer wait until it is answered.
    """
    statuses = state.part_statuses(plan, tasks, {key: view.status for key, view in views.items()})
    questioned = {part for question in plan.questions if not question.answer for part in question.parts}
    eligible = [part.id for part in plan.parts.values()
                if statuses[part.id] == "not designed" and part.id not in questioned and all(
                    statuses.get(need) == "done" or (
                        statuses.get(need) == "designed" and need not in part.needs_landed
                        and plan.parts[need].mode != "probe")
                    for need in part.needs)]
    return Action("design", detail=", ".join(eligible)) if eligible else None


def _starts(candidates: Iterable[str], views: Mapping[str, state.TaskView], events: list[dict],
            free: dict[str, int], budget: int, refusals: Mapping[str, repairs.Refusal]) -> list[Action]:
    """Reserve places or park exhausted tasks only after their refusal permits a run.

    Settled fixes carry their section in the rejection; none and fallback keep it alone.
    """
    actions = []
    for identifier in candidates:
        refusal = refusals.get(identifier)
        if refusal is not None and not (refusal.state == "fallback" or
                refusal.state == "settled" and refusal.verdict in ("fix", "none")):
            continue
        view = views[identifier]
        # Rebase runs are mechanical (the model's foreman writes them) and do not count.
        kinds = {event["run"]: event.get("kind") for event in events if event.get("ev") == "run.started"}
        kind, rejection = _start_kind(view, events)
        if not (rejection or {}).get("skeleton") and sum(
                kinds.get(run_id) != "rebase" for run_id in view.runs) >= MAX_RUNS:
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
        if refusal is not None and refusal.state == "settled" and refusal.verdict == "fix":
            rejection = {**rejection, "section": refusal.section}
        actions.append(Action("start", task=identifier, host=host, run_kind=kind,
                              detail=f"{kind} {host}", rejection=rejection))
        free[host] -= 1
        budget -= 1

    return actions


def _start_kind(view: state.TaskView, events: list[dict]) -> tuple[str, dict | None]:
    """Choose implement, repair or rebase using repairs.REBASE_STEPS for an open refusal,
    preserving the rejection since the last run as context."""
    history = [event for event in reversed(events) if event.get("task") == view.id]
    kind = "implement"
    rejection = None
    # history is newest first: a refusal since the last run still decides the kind, even
    # when the task was parked and answered in between.
    last = next((event for event in history if event.get("ev") in ("branch.rejected", "run.started")), {})
    if view.status == "rejected" or last.get("ev") == "branch.rejected":
        rejection = next(event for event in history if event.get("ev") == "branch.rejected")
        kind = "rebase" if rejection.get("step") in repairs.REBASE_STEPS else "repair"
    else:
        ended = next((event for event in history if event.get("ev") == "run.ended"), {})
        if ended.get("outcome") == "infra":
            kind = "repair"
    return kind, rejection


def _import_queue(tasks: Mapping[str, Task], events: list[dict], hosts: Mapping[str, Host], *,
                  sh: Runner, log_path: Path | None, plan_drafts: Sequence[str]) -> None:
    """Import all loaded tasks once, reading from the oldest draft cursor.

    Each cursor is its newest imported queue_ts, or empty before its first record.
    Remote torn lines and other plans' records are skipped; imported keys deduplicate.
    """
    owners = {f"{draft}/integration": draft for draft in plan_drafts}
    owners.update({event["branch"]: draft for event in events
              if event.get("ev") == "call.started" and isinstance(event.get("branch"), str)
              for draft in plan_drafts if drafts.under(draft, event.get("subject"))})
    for event in events:
        if (event.get("ev") == "run.started" and event.get("kind") == foreman.KIND
                and isinstance(event.get("run"), str) and isinstance(event.get("task"), str)):
            identifier = event.get("task", "").removesuffix("/foreman")
            if identifier in tasks:
                for prefix in ("answers", "repairs"):
                    owners[f"{prefix}/{event['run']}"] = tasks[identifier].draft
    gate_hosts = sorted(name for name, host in hosts.items() if "gate" in host.roles)
    if gate_hosts:
        imported = {(event.get("queue_ts"), event.get("ev"), event.get("branch"),
                     event.get("tip")) for event in events if "queue_ts" in event}
        since = min((max((event["queue_ts"] for event in events if "queue_ts" in event
                           and (drafts.under(draft, event.get("task"))
                                or owners.get(event.get("branch")) == draft)), default="")
                     for draft in plan_drafts), default="")
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
            identifier = branch if branch in owners else land.task_of(branch)
            if identifier not in tasks and branch not in owners:
                continue
            ev = "branch." + entry["ev"]
            key = (entry["ts"], ev, branch, entry.get("tip"))
            if key in imported:
                continue
            fields = {field: entry[field] for field in ("tip", "main", "step", "log", "findings")
                      if field in entry}
            events.append(log.append(ev, path=log_path, task=identifier, branch=branch,
                                     queue_ts=entry["ts"], **fields))
            imported.add(key)


def _merge_branch(branch: str, plan: Plan, checkout: Path, *, task: str | None = None,
                  sh: Runner, log_path: Path | None) -> bool:
    """Merge a branch into the plan's trunk once; log conflicts and retry refused pushes."""
    if any(event.get("ev") == "branch.landed" and event.get("branch") == branch
           and event.get("into") == plan.trunk for event in log.read(log_path)):
        return True
    sh(["git", "fetch", "origin"], cwd=str(checkout), check=True)
    sh(["git", "reset", "-q", "--hard", f"origin/{plan.trunk}"], cwd=str(checkout), check=True)
    tip = sh(["git", "rev-parse", "--verify", f"refs/remotes/origin/{branch}^{{commit}}"],
             cwd=str(checkout), check=True).out.strip()
    if not tip:
        raise ValueError("branch has no tip")
    merged = sh(["git", "-c", "user.name=fab", "-c", "user.email=fab@localhost",
                 "merge", "--no-ff", "--no-edit", tip], cwd=str(checkout))
    if not merged.ok:
        paths = sh(["git", "diff", "--name-only", "--diff-filter=U"],
                   cwd=str(checkout), check=True).out.splitlines()
        trees = integration.baselines(paths)
        findings = "\n".join((merged.out.splitlines() + merged.err.splitlines())[-40:])
        try:
            if trees:
                integration.recount(checkout, trees, sh=sh)
                sh(["git", "-c", "user.name=fab", "-c", "user.email=fab@localhost",
                    "commit", "--no-edit"], cwd=str(checkout), check=True)
        except Exception as error:
            findings += f"\nRecount failed: {error}"
            trees = []
        if not trees:
            sh(["git", "merge", "--abort"], cwd=str(checkout), check=True)
            log.append("branch.rejected", path=log_path, task=task or branch, branch=branch,
                       tip=tip, step="merge", findings=findings)
            return False
    sh(["git", "push", "origin", f"HEAD:refs/heads/{plan.trunk}"], cwd=str(checkout), check=True)
    main = sh(["git", "rev-parse", "HEAD"], cwd=str(checkout), check=True).out.strip()
    log.append("branch.landed", path=log_path, task=task or branch, branch=branch,
               tip=tip, main=main, into=plan.trunk)
    return True


def _deliver(branch: str, plan: Plan, checkout: Path, *, sh: Runner,
             log_path: Path | None, section: str = "") -> bool:
    """Deliver a call or spec branch to its plan's trunk, retaining queued repair text."""
    if plan.landing == "integration":
        return _merge_branch(branch, plan, checkout, sh=sh, log_path=log_path)
    if plan.repo == "fabrig":
        return _queue_branch(branch, checkout, sh=sh, log_path=log_path, section=section)
    _land_branch([branch])
    return True


def _queue_branch(branch: str, checkout: Path, *, sh: Runner, log_path: Path | None,
                  section: str = "") -> bool:
    """Ready a call or spec branch once; return True only after its queue landing imports."""
    events = log.read(log_path)
    if any(event.get("ev") == "branch.landed" and event.get("branch") == branch
           and "queue_ts" in event for event in events):
        return True
    ready = next((index for index in range(len(events) - 1, -1, -1)
                  if events[index].get("ev") == "branch.ready"
                  and events[index].get("branch") == branch), -1)
    calls_on_branch = {event.get("call") for event in events
                       if event.get("ev") == "call.started" and event.get("branch") == branch}
    changed = max((index for index, event in enumerate(events)
                   if event.get("ev") == "call.ended" and event.get("call") in calls_on_branch),
                  default=-1)
    if ready > changed:
        return False
    tip = sh(["git", "rev-parse", "--verify", f"refs/remotes/origin/{branch}^{{commit}}"],
             cwd=str(checkout), check=True).out.strip()
    if not tip:
        raise ValueError("branch has no tip")
    sh(["git", "push", "origin", f"{tip}:refs/heads/ready/{branch}"],
       cwd=str(checkout), check=True)
    fields = {"section": section} if section else {}
    log.append("branch.ready", path=log_path, task=branch, branch=branch, tip=tip, **fields)
    return False


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
    """Clear a same-tip rejection, deliver the tip's receipt, then push the ready ref.

    A tip without a receipt is readied all the same; the queue checks it in full.
    """
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
    receipts.deliver(action.task, tip, log.read(log_path), hosts, sh=sh, log_path=log_path)
    sh(["git", "push", "origin", f"{tip}:refs/heads/ready/{action.branch}"],
       cwd=str(repo), check=True)
    log.append("branch.ready", path=log_path, task=action.task,
               branch=action.branch, tip=tip)


def _call(action: Action, plan_dir: Path, draft: str, *, sh: Runner) -> None:
    """Launch a subject-named call unit, passing parts or amend roots and --plan.

    Skeleton and contract keys are draft/part; other roles use the action's task.
    Answer, review and retire take no positional argument.
    """
    role = action.run_kind
    key = f"{draft}/{action.task}" if role in drafts.DESIGN_ROLES else action.task
    argv = ["fab", "call", role]
    if role in ("skeleton", "contract", "amend"):
        argv.append(action.task)
    argv.extend(["--plan", str(plan_dir.resolve())])
    sh(["systemd-run", "--user", "--collect", "--unit",
        drafts.unit(role, key), *argv], check=True)


def _finish(action: Action, *, log_path: Path | None) -> None:
    """Record answers from the delivered chain's latest report or its root's."""
    events = log.read(log_path)
    chain = call_review.chains(events)[action.task]
    if chain.role == "answer":
        # An answer call's subject is its draft; a bare task name is read under it.
        names = (name if "/" in name else f"{chain.subject}/{name}" for name in _answered(chain))
        for identifier in dict.fromkeys(names):
            log.append("question.answered", path=log_path, task=identifier, call=chain.latest)


def _take(action: Action, tasks: Mapping[str, Task], hosts: Mapping[str, Host], plan_dir: Path, *,
          plan: Plan, checkout: Path, sh: Runner, log_path: Path | None) -> None:
    """Take task, question, refusal or call-chain actions, logging failures as notes.

    Foremen print their asking run or refused step and builder; remedies print verdict and
    reason. Failed settlements and integration deliveries remain open for the next tick.
    """
    detail = action.detail
    outcome = "failed"
    finish_tip = ""
    try:
        match action.kind:
            case "collect":
                _collect(action, hosts, sh=sh, log_path=log_path)
            case "land":
                detail = _land(action, tasks, sh=sh, log_path=log_path)
            case "ready":
                detail = _screen_ready(action, tasks[action.task], hosts, sh=sh, log_path=log_path)
            case "merge":
                _merge_branch(action.branch, plan, checkout, task=action.task,
                              sh=sh, log_path=log_path)
            case "start":
                _start(action, tasks, hosts, plan=plan, sh=sh, log_path=log_path)
            case "call":
                _call(action, plan_dir, plan.draft, sh=sh)
            case "foreman":
                detail = _foreman(action, tasks, hosts, plan=plan, sh=sh, log_path=log_path)
            case "settle":
                _settle(action, tasks, plan_dir, plan=plan, sh=sh, log_path=log_path)
            case "examine":
                detail = _examine(action, tasks, hosts, plan=plan, sh=sh, log_path=log_path)
            case "remedy":
                detail = _remedy(action, tasks, plan_dir, plan=plan, sh=sh, log_path=log_path)
            case "vet":
                _vet(action, plan, checkout, hosts, sh=sh, log_path=log_path)
            case "hold":
                _hold(action, log_path=log_path)
            case "finish":
                finish_tip = next((event["tip"] for event in reversed(log.read(log_path))
                                   if event.get("ev") == "call.checked" and event.get("call") == action.run), "")
                if _deliver(action.branch, plan, checkout, sh=sh, log_path=log_path):
                    _finish(action, log_path=log_path)
                    outcome = "done"
            case "park":
                _park(action, log_path=log_path)
    except Exception as error:
        detail = "failed: " + " ".join(str(error).splitlines())
        log.append("note", path=log_path,
                   text=f"{action.kind} {action.task or '-'} {detail}")
    finally:
        if action.kind == "finish" and ((plan.repo != "fabrig" and plan.landing != "integration")
                                        or outcome == "done"):
            fields = {"tip": finish_tip} if finish_tip else {}
            log.append("call.finished", path=log_path, call=action.run,
                       role=action.run_kind, outcome=outcome, **fields)
    print(f"{action.kind} {action.task or '-'} {detail}")


def tick(*plan_dirs: Path, sh: Runner = run, hosts: Mapping[str, Host] | None = None,
         log_path: Path | None = None, trigger: str = "hand") -> list[Action]:
    """Run one round under the tick lock (docs/design/fab.md, 13.9).

    Validate trigger before locking. Event ticks wait for the lock; hand and backstop
    ticks return [] when it is held, taking nothing. Under the lock:
    1. Take the want beside log_path and print its reasons when it exists.
    2. Count the records already in the log.
    3. Load plans, import, decide, collect strays and refresh the page.
    4. Finally settle the round with every record gained since the count, printing its
       lines, including after an early return or an error.
    Return load, plan and stray actions in order.
    """
    if trigger not in wake.TRIGGERS:
        raise ValueError(f"unknown tick trigger {trigger!r}")
    home = log.home()
    home.mkdir(parents=True, exist_ok=True)
    with open(home / "tick.lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | (0 if trigger == "event" else fcntl.LOCK_NB))
        except BlockingIOError:
            return []
        path = wake.want_path(log_path)
        taken = wake.take(path)
        if taken is not None:
            print("wake - " + ("; ".join(taken) or "-"))
        count = len(log.read(log_path))
        try:
            return _round(plan_dirs, sh=sh, hosts=hosts, log_path=log_path)
        finally:
            for line in wake.settle(trigger, taken, log.read(log_path)[count:],
                                    path=path, log_path=log_path):
                print(line)


def _round(plan_dirs: Sequence[Path], *, sh: Runner, hosts: Mapping[str, Host] | None,
           log_path: Path | None) -> list[Action]:
    """Load and run listed then given plans, sharing imports and builder measurements.

    Fetch each checkout once; print load failures and skip retired plans. With no loaded
    plan, return before importing, measuring or paging. Otherwise decide each plan on
    fresh events and spend calm extras once. Question and refusal actions share a log
    snapshot before fresh call decisions. Collect unowned runs last and refresh the page.
    """
    directories = channel.plan_dirs(plan_dirs)
    if not directories:
        print("plans - none")
        return []
    loaded, actions = _load_plans(directories, log.read(log_path), sh=sh)
    if not loaded:
        return actions
    hosts = machines.load() if hosts is None else hosts
    tasks = {key: task for _, plan_tasks, _, _ in loaded for key, task in plan_tasks.items()}
    _import_queue(tasks, log.read(log_path), hosts, sh=sh, log_path=log_path,
                  plan_drafts=[plan.draft for plan, _, _, _ in loaded])
    calm = flow.measure(hosts, log.now(), sh=sh)
    for plan, tasks, directory, checkout in loaded:
        taken = _tick_plan(plan, tasks, directory, checkout, hosts, calm, sh=sh, log_path=log_path)
        actions.extend(taken)
        calm = drafts.spend(calm, (action.host for action in taken if action.kind == "start"))
    events = log.read(log_path)
    for record in drafts.strays([plan.draft for plan, _, _, _ in loaded], in_flight(events), events):
        action = Action("collect", task=record["task"], run=record["run"],
                        host=record["host"], detail=record["run"])
        actions.append(action)
        _take(action, tasks, hosts, directory, plan=plan, checkout=checkout, sh=sh, log_path=log_path)
    _page(plan_dirs, log_path)
    return actions


def _checkout(plan_dir: Path, fetched: dict[Path, Exception | None], *, sh: Runner) -> Path:
    """Fetch and follow each checkout's upstream once, sharing failures across its plans."""
    result = sh(["git", "rev-parse", "--show-toplevel"], cwd=str(_plan_ancestor(plan_dir)))
    if not result.ok or not result.out.strip():
        return plan_dir.resolve()
    checkout = Path(result.out.strip()).resolve()
    if checkout not in fetched:
        fetched[checkout] = None
        try:
            sh(["git", "fetch", "origin"], cwd=str(checkout), check=True)
            upstream = sh(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
                          cwd=str(checkout))
            if upstream.ok:
                sh(["git", "merge", "--ff-only", "@{upstream}"], cwd=str(checkout), check=True)
        except (OSError, ValueError, Failed) as error:
            fetched[checkout] = error
    failure = fetched[checkout]
    if failure is not None:
        raise failure
    return checkout


def _load_plans(directories: Sequence[Path], events: list[dict], *, sh: Runner,
                fetch: bool = True) -> tuple[list[tuple[Plan, dict[str, Task], Path, Path]], list[Action]]:
    """Load plans in order, skipping retirement and reporting failures without log notes.

    Reject duplicate drafts. With fetch, share one checkout fetch including its failure;
    without it, use the same plan/cut loading path without fetching or locating normal plans.
    Return loaded (plan, tasks, directory, checkout) tuples and failed load actions.
    """
    loaded, actions, seen, fetched = [], [], {}, {}
    for directory in directories:
        try:
            checkout = _checkout(directory, fetched, sh=sh) if fetch else None
            plan, tasks = _load_plan(directory, events, checkout=checkout, sh=sh)
            if plan.retired:
                print(f"retired {plan.draft}")
                continue
            if plan.draft in seen:
                raise specs.PlanError(f"draft {plan.draft} is already ticked from {seen[plan.draft]}")
            seen[plan.draft] = directory
            loaded.append((plan, tasks, directory, checkout or directory))
        except (specs.PlanError, OSError, ValueError, Failed) as error:
            action = Action("load", task=str(directory), detail="failed: " + " ".join(str(error).splitlines()))
            actions.append(action)
            print(f"{action.kind} {action.task} {action.detail}")
    return loaded, actions


def _tick_plan(plan: Plan, tasks: Mapping[str, Task], directory: Path, checkout: Path,
               hosts: Mapping[str, Host], calm: Mapping[str, bool], *, sh: Runner,
               log_path: Path | None) -> list[Action]:
    """Take decisions, then question and refusal actions from one fresh snapshot in that
    order, then calls decided from the resulting log."""
    tasks = _integration_tasks(plan, specs.checked_tasks(plan, tasks, log.read(log_path)), log.read(log_path))
    actions = decide(plan, tasks, log.read(log_path), hosts, calm)
    for action in actions:
        _take(action, tasks, hosts, directory, plan=plan, checkout=checkout, sh=sh, log_path=log_path)
    events = log.read(log_path)
    settlements = foreman_actions(tasks, events) + repair_actions(tasks, events)
    for action in settlements:
        _take(action, tasks, hosts, directory, plan=plan, checkout=checkout, sh=sh, log_path=log_path)
    actions.extend(settlements)
    design = [part for action in actions if action.kind == "design" for part in action.detail.split(", ")]
    followups = call_actions(plan, tasks, log.read(log_path), design, log.now())
    actions.extend(followups)
    for action in followups:
        _take(action, tasks, hosts, directory, plan=plan, checkout=checkout, sh=sh, log_path=log_path)
    _check_calls(plan, directory, checkout, hosts, sh=sh, log_path=log_path)
    _integration(plan, tasks, checkout, hosts, sh=sh, log_path=log_path)
    return actions


def _page(plan_dirs: Sequence[Path], log_path: Path | None) -> None:
    """Refresh the page for listed and given plans once, printing file failures only."""
    try:
        path = channel.write(channel.compose(channel.plan_dirs(plan_dirs), log.read(log_path), log.now()))
        print(f"page - {path}")
    except (OSError, ValueError) as error:
        print(f"page - failed: {' '.join(str(error).splitlines())}")


def _plan_ancestor(plan_dir: Path) -> Path:
    """The nearest existing parent from which git can locate an uncut plan's checkout."""
    ancestor = plan_dir.resolve()
    while not ancestor.exists():
        ancestor = ancestor.parent
    return ancestor


def _load_plan(plan_dir: Path, events: list[dict], *, checkout: Path | None = None,
               sh: Runner = run) -> tuple[Plan, dict[str, Task]]:
    """Load a plan, or an empty stand-in with no tasks when its cut is logged.

    Without plan.toml, require a cut start for <directory name>/cut or raise PlanError
    naming the directory. Resolve the checkout through the runner from the nearest
    existing parent when not supplied, and identify its repository from origin.
    Dry-run uses this path without fetching.
    """
    if (plan_dir / "plan.toml").exists():
        plan = specs.load_plan(plan_dir / "plan.toml")
        tasks = specs.load_tasks(plan_dir / "tasks", plan.draft, plan.repo)
        tasks = specs.checked_tasks(plan, tasks, events)
        issues = specs.problems(plan, tasks)
        if issues:
            raise specs.PlanError(f"{plan_dir}: " + "\n".join(issues))
        return plan, _integration_tasks(plan, tasks, events)
    draft = plan_dir.name
    cut = next((event for event in reversed(events)
                if event.get("ev") == "call.started" and event.get("role") == "cut"
                and event.get("subject") == designer.subject(draft, "cut")), None)
    if cut is None:
        raise specs.PlanError(f"{plan_dir}: no plan.toml or cut call")
    if checkout is None:
        result = sh(["git", "rev-parse", "--show-toplevel"], cwd=str(_plan_ancestor(plan_dir)), check=True)
        checkout = Path(result.out.strip())
    return designer.uncut(draft, designer.repository(checkout, sh=sh),
                          options=specs.parse_options(cut.get("options", ()))), {}


def _collect(action: Action, hosts: Mapping[str, Host], *, sh: Runner,
             log_path: Path | None) -> None:
    """Collect an in-flight task or call review run using current events."""
    runs.collect(action.run, log.read(log_path), hosts, sh=sh, log_path=log_path)


def _start(action: Action, tasks: Mapping[str, Task], hosts: Mapping[str, Host], *,
           plan: Plan, sh: Runner, log_path: Path | None) -> None:
    """Start a task run with current events and the decision's rejection context."""
    runs.start(tasks[action.task], hosts[action.host], kind=action.run_kind,
               events=log.read(log_path), sh=sh, log_path=log_path, rejection=action.rejection,
               trunk=plan.trunk)


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
             plan: Plan, sh: Runner, log_path: Path | None) -> str:
    """Recompute a pending question and start its foreman on the freest builder."""
    events = log.read(log_path)
    question = _question(action, tasks, events, "foreman")
    host = _builder(hosts, events)
    foreman.start(question, tasks[action.task], host, log.read(log_path),
                  sh=sh, log_path=log_path, trunk=plan.trunk)
    return f"{question.run} {host.name}"


def _settle(action: Action, tasks: Mapping[str, Task], plan_dir: Path, *,
            plan: Plan, sh: Runner, log_path: Path | None) -> None:
    """Commit and land a settled answer before recording it; failures leave it retryable.

    Share checkout resolution with refusal remedies, refusing a non-checkout. An answer
    already recorded by commit needs no landing. Read the collected report locally and log
    its first answer line with both the asking and foreman runs after success."""
    events = log.read(log_path)
    question = _question(action, tasks, events, "settled")
    queued = plan.repo == "fabrig" and plan.landing == "queue"
    pending = f"answers/{action.run}"
    ready = queued and any(event.get("ev") == "branch.ready" and event.get("branch") == pending
                           for event in events)
    checkout = _spec_checkout(plan_dir, sh=sh)
    answer = foreman.answer((log.home() / "runs" / action.run / "report.md").read_text())
    branch = pending if ready else foreman.commit(
        question, tasks[action.task], answer, checkout,
        run_id=action.run, day=log.now()[:10], sh=sh, trunk=plan.trunk)
    if branch is not None and not _deliver(branch, plan, checkout, sh=sh, log_path=log_path):
        return
    log.append("question.answered", path=log_path, task=question.task, by=action.run,
               run=question.run, answer=answer.splitlines()[0])


def _spec_checkout(plan_dir: Path, *, sh: Runner) -> Path:
    """Resolve the plan's checkout root for question or refusal spec commits."""
    result = sh(["git", "rev-parse", "--show-toplevel"], cwd=str(plan_dir), check=True)
    if not result.out.strip():
        raise ValueError("plan is not a git checkout")
    return Path(result.out.strip())


def _refusal(action: Action, tasks: Mapping[str, Task], events: list[dict],
             status: str) -> repairs.Refusal:
    """Recompute the task's open refusal, refusing stale state or a different foreman."""
    for refusal in repairs.refusals(tasks, events):
        if refusal.task == action.task and refusal.state == status and (
                status == "foreman" or refusal.foreman == action.run):
            return refusal
    raise ValueError(f"no {status} refusal for {action.task} {action.run}")


def _examine(action: Action, tasks: Mapping[str, Task], hosts: Mapping[str, Host], *,
             plan: Plan, sh: Runner, log_path: Path | None) -> str:
    """Recompute a pending refusal and start its foreman on the freest builder, even full."""
    events = log.read(log_path)
    refusal = _refusal(action, tasks, events, "foreman")
    host = _builder(hosts, events)
    repairs.start(refusal, tasks[action.task], host, log.read(log_path),
                  sh=sh, log_path=log_path, trunk=plan.trunk)
    return f"{refusal.step} {host.name}"


def _remedy(action: Action, tasks: Mapping[str, Task], plan_dir: Path, *,
            plan: Plan, sh: Runner, log_path: Path | None) -> str:
    """Settle a decided refusal from its collected report, treating unreadable as empty.

    Land a fix's spec section before recording it; retry and none need no commit.
    Failures leave the refusal decided for the next tick. Return verdict and reason.
    """
    events = log.read(log_path)
    refusal = _refusal(action, tasks, events, "decided")
    try:
        report = (log.home() / "runs" / action.run / "report.md").read_text()
    except (OSError, UnicodeError):
        report = ""
    verdict, reason, body = repairs.remedy(refusal, report)
    branch, section = None, ""
    if verdict == "fix":
        section = repairs.section(refusal, day=log.now()[:10], run_id=action.run, body=body)
        queued = plan.repo == "fabrig" and plan.landing == "queue"
        pending = f"repairs/{action.run}"
        ready = next((event for event in events if queued and event.get("ev") == "branch.ready"
                      and event.get("branch") == pending), None)
        if ready is not None:
            section = ready.get("section", section)
        checkout = _spec_checkout(plan_dir, sh=sh)
        branch = pending if ready else repairs.commit(
            refusal, tasks[action.task], section, checkout, run_id=action.run, sh=sh, trunk=plan.trunk)
        if branch is not None:
            if queued and ready is None:
                relative = Path(tasks[action.task].path).resolve().relative_to(checkout.resolve())
                spec = sh(["git", "show", f"refs/remotes/origin/{branch}:{relative.as_posix()}"],
                          cwd=str(checkout), check=True).out.splitlines(keepends=True)
                heading = next((index for index, line in enumerate(spec)
                                if line.startswith(("## Repair (", "## Rebase ("))
                                and line.rstrip().endswith(f" foreman {action.run})")), None)
                if heading is not None:
                    end = next((index for index in range(heading + 1, len(spec))
                                if spec[index].startswith("## ")), len(spec))
                    section = "".join(spec[heading:end]).rstrip("\n") + "\n"
            if not _deliver(branch, plan, checkout, sh=sh, log_path=log_path, section=section):
                return f"{verdict} {reason}"
    log.append("refusal.settled", path=log_path, task=refusal.task, run=action.run,
               verdict=verdict, reason=reason, branch=branch or "", section=section)
    return f"{verdict} {reason}"


def _hold(action: Action, *, log_path: Path | None) -> None:
    """Park a chain's subject with the last refusing review's report path, when available."""
    events = log.read(log_path)
    chain = call_review.chains(events)[action.run]
    refusal = chain.refusals[-1] if chain.refusals else None
    report = next((event.get("report", "") for event in reversed(events)
                   if refusal is not None and event.get("ev") == "run.ended"
                   and event.get("run") == refusal), "")
    if refusal is not None and refusal.startswith("queue:"):
        report = json.loads(refusal.removeprefix("queue:")).get("log", "")
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
    """`fab tick [PLAN_DIR...] [--trigger hand|event|backstop] [--dry-run]`.

    Tick listed and given plans; fail on bad loads.

    Dry-run loads each plan without fetch, prints retirement, failed loads or decide's
    actions on the same log and hosts, with no calm. It neither chains plans nor acts,
    ignores --trigger and takes no want.
    """
    parser = argparse.ArgumentParser(prog="fab tick", description=__doc__)
    parser.add_argument("plan_dirs", type=Path, nargs="*", metavar="PLAN_DIR")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--trigger", choices=wake.TRIGGERS, default="hand")
    args = parser.parse_args(argv)
    try:
        if args.dry_run:
            directories = channel.plan_dirs(args.plan_dirs)
            if not directories:
                print("plans - none")
            events = log.read()
            loaded, actions = _load_plans(directories, events, sh=run, fetch=False)
            hosts = machines.load() if loaded else {}
            for plan, tasks, _, _ in loaded:
                for action in decide(plan, tasks, events, hosts):
                    print(f"{action.kind} {action.task or '-'} {action.detail}")
        else:
            actions = tick(*args.plan_dirs, trigger=args.trigger)
        return int(any(action.kind == "load" and action.detail.startswith("failed:") for action in actions))
    except (OSError, ValueError, Failed) as error:
        print("fab tick: " + " ".join(str(error).splitlines()), file=sys.stderr)
        return 1


def _check_calls(plan: Plan, directory: Path, checkout: Path, hosts: Mapping[str, Host], *,
                 sh: Runner, log_path: Path | None) -> None:
    """Check each completed design output once, independently of its Codex review.

    Infra failures leave no checked mark and retry next tick. A check result pins the
    tip and its task specs together; no task can start from untested spec text.
    """
    events = log.read(log_path)
    for chain in call_review.chains(events).values():
        if (chain.role not in ("skeleton", "contract") or chain.state in ("finished", "hold", "parked", "amending")
                or chain.subject not in {f"{plan.draft}/{part}" for part in plan.parts}
                or any(event.get("ev") == "call.checked" and event.get("call") == chain.latest
                       for event in events)):
            continue
        try:
            _check_call(chain, plan, directory, checkout, hosts, sh=sh, log_path=log_path)
        except (OSError, ValueError, Failed) as error:
            print(f"check {chain.latest} failed: {' '.join(str(error).splitlines())}")


def _check_call(chain: call_review.Chain, plan: Plan, directory: Path, checkout: Path,
                hosts: Mapping[str, Host], *, sh: Runner, log_path: Path | None) -> None:
    """Resolve and test a design tip, then log its green or red result and exact specs."""
    sh(["git", "fetch", "origin"], cwd=str(checkout), check=True)
    tip = sh(["git", "rev-parse", "--verify", f"refs/remotes/origin/{chain.branch}^{{commit}}"],
             cwd=str(checkout), check=True).out.strip()
    if not tip:
        raise ValueError("branch has no tip")
    task = Task(chain.root, chain.subject.rsplit("/", 1)[1], "interface", plan.repo,
                (), ("**",), "high", 25, "", "")
    started = {"ev": "run.started", "task": task.id, "run": f"checks/{chain.latest}",
               "branch": chain.branch, "tip": tip}
    screen = rust_gates.screen if plan.repo == "fabrig" else gates.screen

    def pinned(argv, **kwargs):
        if list(argv) == ["git", "rev-parse", "--verify", f"refs/remotes/origin/{chain.branch}^{{commit}}"]:
            argv = ["git", "rev-parse", "--verify", f"{tip}^{{commit}}"]
        return sh(argv, **kwargs)

    findings = screen(task, [started], sh=pinned,
                      log_path=log.home() / "calls" / chain.latest / "checks.jsonl")
    green = _call_tests(chain, plan, checkout, tip, hosts, sh=sh, log_path=log_path) and not findings
    records, spec_paths = [], []
    identifiers = []
    if green:
        paths = sh(["git", "ls-tree", "-r", "--name-only", tip],
                   cwd=str(checkout), check=True).out.splitlines()
        relative = directory.resolve().relative_to(checkout.resolve()).as_posix()
        for path in sorted(paths):
            if not path.startswith(relative + "/tasks/") or not path.endswith(".md"):
                continue
            text = sh(["git", "show", f"{tip}:{path}"], cwd=str(checkout), check=True).out
            spec = specs.parse_task(text, str(checkout / path), plan.draft, plan.repo)
            if spec.part == task.part:
                identifiers.append(spec.id)
                spec_paths.append(spec.path)
                records.append(text)
    log.append("call.checked", path=log_path, call=chain.latest, root=chain.root,
               subject=chain.subject, branch=chain.branch, tip=tip,
               outcome="green" if green else "red", tasks=identifiers, specs=records, paths=spec_paths,
               findings=gates.findings_text(findings))
    if green:
        wake.want(f"call.checked {chain.latest}", path=wake.want_path(log_path))
    print(f"check {chain.latest} {'green' if green else 'red'} {tip}")


def _call_tests(chain: call_review.Chain, plan: Plan, checkout: Path, tip: str,
                hosts: Mapping[str, Host], *, sh: Runner, log_path: Path | None) -> bool:
    """Run agents tests in a detached worktree or fabrig precheck in a claimed slot."""
    if plan.repo == "fabrig":
        host = _builder(hosts, log.read(log_path))
        root = Path(runs.remote_home(host))
        listed = sh(ssh(host.ssh, ["fab", "slot", "list"]), check=True)
        idle = []
        for line in listed.out.splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (isinstance(entry, dict) and entry.get("claim", True) is None
                    and isinstance(entry.get("slot"), int) and isinstance(entry.get("idle"), (int, float))):
                idle.append(entry)
        if not idle:
            raise ValueError(f"{host.name}: no idle slot")
        slot = str(min(idle, key=lambda entry: entry["idle"])["slot"])
        run_id = f"checks/{chain.latest}"
        sh(ssh(host.ssh, ["fab", "slot", "claim", slot, run_id, chain.root]), check=True)
        try:
            worktree = root.parent / "slots" / slot
            sh(ssh(host.ssh, ["git", "-C", str(worktree), "fetch", "origin"]), check=True)
            return sh(ssh(host.ssh, ["fab", "precheck", str(worktree), tip])).ok
        finally:
            sh(ssh(host.ssh, ["fab", "slot", "release", slot, run_id]), check=True)
    home = log.home()
    home.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="call-check-", dir=home) as directory:
        worktree = Path(directory) / "tip"
        sh(["git", "worktree", "add", "--detach", str(worktree), tip], cwd=str(checkout), check=True)
        try:
            return sh([str(worktree / "bin/fab"), "test"], cwd=str(worktree)).ok
        finally:
            sh(["git", "worktree", "remove", "--force", str(worktree)], cwd=str(checkout), check=True)


def _landing_actions(plan: Plan, tasks: Mapping[str, Task], views: Mapping[str, state.TaskView],
                     events: list[dict]) -> tuple[list[Action], list[str], list[dict]]:
    """Hold optimistic landings until the skeleton lands, scheduling amendments as rebases.

    Rebase context is local to this decision; it is no refusal event and changes no flow.
    """
    actions, rebases = [], []
    for identifier, view in views.items():
        source = call_review.task_source(tasks[identifier], events)
        if source is not None:
            _, chain = source
            finished = any(event.get("ev") == "call.finished" and event.get("call") in chain.calls
                           and event.get("outcome") == "done" for event in events)
            if not finished:
                continue
        if view.status == "done":
            amendment = call_review.task_rebase(tasks[identifier], events)
            if amendment is not None:
                rebases.append(identifier)
                events = [*events, {"ev": "branch.rejected", "task": identifier, **amendment}]
                continue
            kind = "merge" if plan.landing == "integration" else (
                "land" if tasks[identifier].repo == "agents" else "ready")
            actions.append(Action(kind, task=identifier, branch=view.branch, detail=view.branch or ""))

    return actions, rebases, events


def _screen_ready(action: Action, task: Task, hosts: Mapping[str, Host], *,
                  sh: Runner, log_path: Path | None) -> str:
    """Run the Rust gates before delivering receipts or pushing a task's ready ref."""
    findings = rust_gates.screen(task, log.read(log_path), sh=sh, log_path=log_path)
    if findings:
        return "rejected gate:" + ",".join(dict.fromkeys(finding.gate for finding in findings))
    _ready(action, task, hosts, sh=sh, log_path=log_path)
    return action.detail


def _integration_tasks(plan: Plan, tasks: Mapping[str, Task], events: list[dict]) -> dict[str, Task]:
    """Add log-derived repairs, reading collected check reports locally; unreadable is empty."""
    reports = {}
    for event in events:
        if (event.get("ev") == "run.started" and event.get("kind") == "check"
                and event.get("task") == f"{plan.draft}/integration"):
            try:
                reports[event["run"]] = (log.home() / "runs" / event["run"] / "report.md").read_text()
            except (OSError, UnicodeError):
                reports[event["run"]] = ""
    return {**tasks, **integration.repair_tasks(plan, events, reports)}


def _integration(plan: Plan, tasks: Mapping[str, Task], checkout: Path,
                 hosts: Mapping[str, Host], *, sh: Runner, log_path: Path | None) -> None:
    """Take the trunk's next check, ready or stop after the plan's other actions."""
    events = log.read(log_path)
    tasks = _integration_tasks(plan, tasks, events)
    step = integration.next_step(plan, tasks, events)
    if step is None:
        return
    subject = f"{plan.draft}/integration"
    detail = step.detail
    try:
        if step.kind == "check":
            _integration_check(plan, step.tip, hosts, events, sh=sh, log_path=log_path)
        elif step.kind == "ready":
            sh(["git", "push", "origin", f"{step.tip}:refs/heads/ready/{plan.trunk}"],
               cwd=str(checkout), check=True)
            log.append("branch.ready", path=log_path, task=subject, branch=plan.trunk, tip=step.tip)
        elif not any(event.get("ev") == "note" and event.get("task") == subject
                     and event.get("tip") == step.tip and event.get("text") == detail for event in events):
            log.append("note", path=log_path, task=subject, tip=step.tip, text=detail)
    except (OSError, ValueError, Failed) as error:
        detail = "failed: " + " ".join(str(error).splitlines())
        log.append("note", path=log_path, task=subject, text=detail)
    print(f"integration {plan.draft} {step.kind} {detail}")


def _integration_check(plan: Plan, tip: str, hosts: Mapping[str, Host], events: list[dict], *,
                       sh: Runner, log_path: Path | None) -> None:
    """Claim an idle slot on the builder with most free places and launch the full check.
    A failure after claiming releases the slot before propagating."""
    host = _builder(hosts, events)
    listed = sh(ssh(host.ssh, ["fab", "slot", "list"]), check=True)
    idle = []
    for line in listed.out.splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (isinstance(entry, dict) and entry.get("claim", True) is None
                and type(entry.get("slot")) is int and isinstance(entry.get("idle"), (int, float))):
            idle.append(entry)
    if not idle:
        raise ValueError(f"{host.name}: no idle slot")
    slot = min(idle, key=lambda entry: entry["idle"])["slot"]
    subject = f"{plan.draft}/integration"
    run_id = runs.next_run(subject, events)
    sh(ssh(host.ssh, ["fab", "slot", "claim", str(slot), run_id, subject]), check=True)
    try:
        worktree = Path(runs.remote_home(host)).parent / "slots" / str(slot)
        sh(ssh(host.ssh, ["git", "-C", str(worktree), "fetch", "origin"]), check=True)
        runs.launch(host, run_id, task=subject, kind="check", workdir=str(worktree),
                    branch=plan.trunk, base=tip, brief=f"Full integration check of {tip}\n",
                    effort="high", slot=slot, sh=sh, log_path=log_path,
                    command=["fab", "check", "start", "--tip", tip, "--onto", f"origin/{plan.trunk}"])
    except Exception:
        sh(ssh(host.ssh, ["fab", "slot", "release", str(slot), run_id]), check=True)
        raise
