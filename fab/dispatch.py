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
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path

from fab import after_landing, buffer, call_review, calls, channel, designer, drafts, flow, foreman, gates, hosts as machines, integration, land, log, overlaps, plan as specs, receipts, repairs, run as runs, rust_gates, state, tier_reds, wake
from fab.hosts import Host
from fab.plan import Plan, Task
from fab.sh import Failed, Result, Runner, run, ssh

FAB_GIT = ("git", "-c", "user.name=fab", "-c", "user.email=fab@localhost")  # the tick's own commits

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
    Reply calls and issues/ subjects reserve nothing.
    Queued questions use ANSWER_AT, ANSWER_AFTER or draft-local blocking; reviews use
    REVIEW_AT or REVIEW_AFTER since this draft's last review started. Retire follows
    review once every part is done. Pure; docs/design/fab.md, 12, 13.1 and 13.4.
    """
    ignored = {event["call"] for event in events if event.get("ev") == "call.started"
               and (event.get("role") == "reply"
                    or str(event.get("subject", "")).startswith("issues/"))}
    events = [event for event in events if event.get("call") not in ignored]
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
    kind: str  # collect, land, ready, merge, start, park, design, foreman, settle, examine, remedy,
    # examine-red, remedy-red, call, vet, hold, finish
    task: str | None = None
    run: str | None = None
    host: str | None = None
    run_kind: str | None = None  # for start: implement, repair or rebase
    branch: str | None = None
    detail: str = ""
    rejection: dict | None = None
    early: tuple[tuple[str, str], ...] = ()  # for start: (need, branch) of an early start


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


def red_actions(plan: Plan, folded: Sequence[tier_reds.Red]) -> list[Action]:
    """Start or settle this plan's reds in opening order; closed reds take no action."""
    return [Action("examine-red", task=red.task, detail=red.id) if red.state == "foreman"
            else Action("remedy-red", task=red.task, run=red.foreman, detail=red.id)
            for red in folded if red.draft == plan.draft and red.state in ("foreman", "decided")]


def retire_ready(plan: Plan, tasks: Mapping[str, Task], events: Sequence[dict],
                 folded: Sequence[tier_reds.Red], *, after_landing: bool) -> bool:
    """A fabrig plan waits for its last main landing's verdict and its active reds."""
    if plan.repo != "fabrig":
        return True
    if any(red.draft == plan.draft and red.state in
           ("foreman", "deciding", "decided", "repairing", "landed") for red in folded):
        return False
    if not after_landing:
        return True
    landed = [event for event in events
              if event.get("ev") == "branch.landed" and event.get("into", "main") == "main"
              and (event.get("task") in tasks or event.get("task") == f"{plan.draft}/integration")]
    if not landed:
        return False
    last = landed[-1]
    identifier = land.task_of(last.get("branch", last.get("task", "")))
    return identifier is not None and any(event.get("ev") == "tiers.run" and any(
        land.task_of(branch) is not None and land.task_of(branch) == identifier
        for branch in event.get("branches", ())) for event in events)


def _red_steps(plan: Plan, tasks: Mapping[str, Task], folded: Sequence[tier_reds.Red],
               hosts: Mapping[str, Host], *, sh: Runner, log_path: Path | None) -> list[Action]:
    """Launch and settle reds against the same snapshot, logging failures for a later tick."""
    actions = red_actions(plan, folded)
    by_id = {red.id: red for red in folded}
    for action in actions:
        red = by_id[action.detail]
        detail = action.detail
        try:
            if action.kind == "examine-red":
                host = _builder(hosts, log.read(log_path))
                tier_reds.start(red, host, log.read(log_path), plan_tasks=tasks, sh=sh, log_path=log_path)
                detail += " " + host.name
            else:
                detail = _remedy_red(red, tasks, log_path=log_path)
        except (OSError, ValueError, Failed) as error:
            detail = "failed: " + " ".join(str(error).splitlines())
            log.append("note", path=log_path, text=f"{action.kind} {action.task} {detail}")
        print(f"{action.kind} {action.task} {detail}")
    return actions


def _remedy_red(red: tier_reds.Red, tasks: Mapping[str, Task], *, log_path: Path | None) -> str:
    """Settle a red's collected foreman report; unreadable reports give the repair the red alone."""
    try:
        report = Path(red.report).read_text()
    except (OSError, UnicodeError):
        report = ""
    record = tier_reds.settle(red, report, plan_tasks=tasks, log_path=log_path)
    return f"{record['verdict']} {record['reason']}"


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
           calm: Mapping[str, bool] | None = None, pushed: frozenset[str] = frozenset()) -> list[Action]:
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
       last run ended infra. A task that already has MAX_RUNS runs (tier_reds.RED_RUNS
       for kind red) gets park instead of start, whatever the target and the places. An open refusal permits neither start nor park
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
    early = early_starts(plan, tasks, views, events, pushed)
    candidates += [identifier for identifier in buffer.order(plan, tasks, list(early), set())
                   if identifier not in candidates]
    refusals = {refusal.task: refusal for refusal in repairs.refusals(tasks, events)
                if refusal.task not in rebases}
    step = integration.next_step(plan, tasks, events)
    startable = ([identifier for identifier in candidates if tasks[identifier].kind == tier_reds.KIND]
                 if step is not None and step.kind == "stop" else candidates)
    if startable:
        actions.extend(replace(action, early=early.get(action.task, ())) if action.kind == "start" else action
                       for action in _run_starts(startable, views, events, free, limit - occupied, refusals,
                                                 {identifier: tier_reds.RED_RUNS for identifier, task in tasks.items()
                                                  if task.kind == tier_reds.KIND}))

    if len(candidates) < plan.low * limit:
        design = _design_action(plan, tasks, views, hosts, len(candidates))
        if design is not None:
            actions.append(design)
    return actions


def early_starts(plan: Plan, tasks: Mapping[str, Task], views: Mapping[str, state.TaskView],
                 events: list[dict], pushed: frozenset[str]) -> dict[str, tuple[tuple[str, str], ...]]:
    """The waiting tasks that may start early, each with (need, branch) for its needs not merged
    (docs/design/fab.md, 13.12). An integration plan with early: every need is landed, or is
    running or done with its branch in pushed (origin's branches, read by the tick) and every
    need of its own landed (one level only). A task whose early start was refused
    (early.refused) waits as usual. Pure."""
    if plan.landing != "integration" or not plan.early:
        return {}
    # One early start per task: one that was refused, or that already started early, waits.
    refused = {event.get("task") for event in events if event.get("ev") == "early.refused"
               or (event.get("ev") == "run.started" and event.get("early"))}
    result = {}
    for identifier, view in views.items():
        if view.status != "waiting" or identifier in refused:
            continue
        open_needs = [need for need in tasks[identifier].needs
                      if need not in views or views[need].status != "landed"]
        if not open_needs or not all(
                need in views and views[need].status in ("running", "done") and views[need].branch in pushed
                and all(views.get(own) is not None and views[own].status == "landed" for own in tasks[need].needs)
                for need in open_needs):
            continue
        result[identifier] = tuple((need, views[need].branch) for need in open_needs)
    return result


def _design_action(plan: Plan, tasks: Mapping[str, Task], views: Mapping[str, state.TaskView],
                   hosts: Mapping[str, Host], ready: int) -> Action | None:
    """List eligible parts after decide checks the ready buffer against the flow target.

    Needs must be designed or done; needs_landed and probe needs must be done.
    Parts named by a plan question with an empty answer wait until it is answered.
    """
    statuses = state.part_statuses(plan, tasks, {key: view.status for key, view in views.items()})
    questioned = {part for question in plan.questions if not question.answer for part in question.parts}
    eligible = [part.id for part in plan.parts.values()
                if part.mode != "direct" and statuses[part.id] == "not designed"
                and part.id not in questioned and all(
                    statuses.get(need) == "done" or (
                        statuses.get(need) == "designed" and need not in part.needs_landed
                        and plan.parts[need].mode != "probe")
                    for need in part.needs)]
    return Action("design", detail=", ".join(eligible)) if eligible else None


def _run_starts(candidates: Iterable[str], views: Mapping[str, state.TaskView], events: list[dict],
                free: dict[str, int], budget: int, refusals: Mapping[str, repairs.Refusal],
                limits: Mapping[str, int] | None = None) -> list[Action]:
    """Reserve starts with each task's allowance; refusal foremen must finish first.

    Settled fixes carry their section in the rejection; none and fallback keep it alone.
    Unlisted tasks and limits None use MAX_RUNS.
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
        counted = _since_park(identifier, view.runs, events)
        allowance = (limits or {}).get(identifier, MAX_RUNS)
        if not (rejection or {}).get("skeleton") and sum(
                kinds.get(run_id) != "rebase" for run_id in counted) >= allowance:
            actions.append(Action("park", task=identifier,
                                  run=view.runs[-1],
                                  detail=f"{allowance} runs without landing; needs judgement"))
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
    """Import loaded tasks' and unowned branches' queue records once.

    Read from the oldest loaded draft cursor, or the newest queue_ts without loaded
    drafts. Log-known task branches and fab branch forms never become queue.* records.
    Only tasks' and owned fab branches' records advance a draft cursor. Skip torn lines;
    deduplicate by queue timestamp, event kind, branch and tip (docs/design/fab.md, 13.8).
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
    known_branches = {event["branch"] for event in events
                      if event.get("ev") in ("branch.ready", "run.started")
                      and isinstance(event.get("branch"), str)}
    known_tasks = {event["task"] for event in events if event.get("ev") == "run.started"
                   and isinstance(event.get("task"), str)}
    gate_hosts = sorted(name for name, host in hosts.items() if "gate" in host.roles)
    if gate_hosts:
        imported = {(event.get("queue_ts"), event.get("ev"), event.get("branch"),
                     event.get("tip")) for event in events if "queue_ts" in event}
        since = min((max((event["queue_ts"] for event in events if "queue_ts" in event
                           and (drafts.under(draft, event.get("task"))
                                or owners.get(event.get("branch")) == draft)), default="")
                     for draft in plan_drafts),
                    default=max((event["queue_ts"] for event in events if "queue_ts" in event),
                                default=""))
        result = sh(ssh(hosts[gate_hosts[0]].ssh, ["fab", "queue", "log", "--since", since]))
        if not result.ok:
            # The queue's record is read again next tick; the other actions still run.
            failure = " ".join((result.err or result.out).strip().splitlines()[-3:])
            log.append("note", path=log_path, text=f"queue import failed: {failure}")
            print(f"import - failed: {failure}")
        for entry in log.records(result.out) if result.ok else ():
            if entry.get("ev") not in ("landed", "rejected", "collateral"):
                continue
            branch = entry.get("branch")
            if not isinstance(branch, str):
                continue
            identifier = branch if branch in owners else land.task_of(branch)
            owned = identifier in tasks or branch in owners
            if owned and entry["ev"] == "collateral":
                continue
            if not owned and (branch in known_branches or identifier in known_tasks
                              or branch.startswith(("calls/", "answers/", "repairs/"))
                              or branch.endswith("/integration")):
                continue
            ev = ("branch." if owned else "queue.") + entry["ev"]
            key = (entry["ts"], ev, branch, entry.get("tip"))
            if key in imported:
                continue
            if owned:
                fields = {field: entry[field] for field in ("tip", "main", "step", "log", "findings")
                          if field in entry}
                fields["task"] = identifier
            else:
                fields = {"gate": gate_hosts[0]}
                names = ("tip", "main") if entry["ev"] == "landed" else ("tip", "step", "log")
                fields.update({field: entry[field] for field in names if field in entry})
                if entry["ev"] != "landed":
                    tests = entry.get("tests")
                    fields["tests"] = ([test for test in tests if isinstance(test, str)]
                                       if isinstance(tests, list) else [])
            events.append(log.append(ev, path=log_path, branch=branch,
                                     queue_ts=entry["ts"], **fields))
            imported.add(key)


def _import_after_landing(events: list[dict], hosts: Mapping[str, Host], *, sh: Runner,
                          log_path: Path | None) -> None:
    """Import the after-landing machine's records (after_landing.imported) into the log once,
    reading from the newest imported al_ts. No machine with the role imports nothing; a read
    that fails is a note, and the next tick reads again."""
    machine = next((hosts[name] for name in sorted(hosts) if after_landing.ROLE in hosts[name].roles), None)
    if machine is None:
        return
    since = max((event["al_ts"] for event in events if "al_ts" in event), default="")
    result = sh(ssh(machine.ssh, ["fab", "after-landing", "log", "--since", since]))
    if not result.ok:
        failure = " ".join((result.err or result.out).strip().splitlines()[-3:])
        log.append("note", path=log_path, text=f"after-landing import failed: {failure}")
        return
    seen = {(event["al_ts"], event.get("ev"), event.get("profile"), event.get("binary"), event.get("test"))
            for event in events if "al_ts" in event}
    for entry in log.records(result.out):
        record = after_landing.imported(entry)
        if record is None or "ts" not in entry:
            continue
        ev = record.pop("ev")
        key = (entry["ts"], ev, record.get("profile"), record.get("binary"), record.get("test"))
        if key not in seen:
            events.append(log.append(ev, path=log_path, al_ts=entry["ts"], host=machine.name, **record))
            seen.add(key)


def _merge_branch(branch: str, plan: Plan, checkout: Path, *, task: str | None = None,
                  sh: Runner, log_path: Path | None) -> bool:
    """Merge a branch into the plan's trunk once; log conflicts and retry refused pushes."""
    events = log.read(log_path)
    landed = [event for event in events if event.get("ev") == "branch.landed"
              and event.get("branch") == branch and event.get("into") == plan.trunk]
    if landed and not branch.startswith("calls/"):
        return True
    sh(["git", "fetch", "origin"], cwd=str(checkout), check=True)
    sh(["git", "reset", "-q", "--hard", f"origin/{plan.trunk}"], cwd=str(checkout), check=True)
    tip = sh(["git", "rev-parse", "--verify", f"refs/remotes/origin/{branch}^{{commit}}"],
             cwd=str(checkout), check=True).out.strip()
    if not tip:
        raise ValueError("branch has no tip")
    if any(event.get("tip") == tip for event in landed):
        return True
    merged = sh([*FAB_GIT, "merge", "--no-ff", "--no-edit", tip], cwd=str(checkout))
    findings = _settle_merge(merged, checkout, sh=sh)
    if findings is not None:
        ended = {event["call"] for event in events if event.get("ev") == "call.ended"}
        cutting = any(event.get("ev") == "call.started" and event.get("role") == "cut"
                      and event.get("subject") == f"{plan.draft}/cut"
                      and f"calls/{event['call']}" == branch and event["call"] not in ended
                      for event in events)
        if cutting:
            log.append("note", path=log_path, task=task or branch, branch=branch,
                       tip=tip, text=f"cut merge conflict: {findings}")
        else:
            log.append("branch.rejected", path=log_path, task=task or branch, branch=branch,
                       tip=tip, step="merge", findings=findings)
        return False
    sha = integration.catch_up_main(plan, events, task or branch)
    contained = _contains(sha, "HEAD", checkout, sh=sh) if sha else False
    sh(["git", "push", "origin", f"HEAD:refs/heads/{plan.trunk}"], cwd=str(checkout), check=True)
    main = sh(["git", "rev-parse", "HEAD"], cwd=str(checkout), check=True).out.strip()
    log.append("branch.landed", path=log_path, task=task or branch, branch=branch,
               tip=tip, main=main, into=plan.trunk)
    if sha:
        if contained:
            log.append("branch.landed", path=log_path, task=f"{plan.draft}/integration", branch="main",
                       tip=sha, main=main, into=plan.trunk, by="repair")
        else:
            log.append("branch.rejected", path=log_path, task=f"{plan.draft}/integration", branch="main",
                       tip=main, main=sha, step=integration.CATCH_UP,
                       findings=f"Catch-up repair {task or branch} merged without main sha {sha}.")
    return True


def _settle_merge(merged: Result, checkout: Path, *, sh: Runner) -> str | None:
    """None when a merge went through, or its only conflicts were old-form baselines, then
    recounted and committed; otherwise abort it and return its findings: the last 40 lines of
    its output, and a recount's failure."""
    if merged.ok:
        return None
    paths = sh(["git", "diff", "--name-only", "--diff-filter=U"],
               cwd=str(checkout), check=True).out.splitlines()
    trees = integration.baselines(paths)
    findings = "\n".join((merged.out.splitlines() + merged.err.splitlines())[-40:])
    try:
        if trees:
            integration.recount(checkout, trees, sh=sh)
            sh([*FAB_GIT, "commit", "--no-edit"], cwd=str(checkout), check=True)
            return None
    except Exception as error:
        findings += f"\nRecount failed: {error}"
    sh(["git", "merge", "--abort"], cwd=str(checkout), check=True)
    return findings


def _catch_up(plan: Plan, tip: str, checkout: Path, *, sh: Runner,
              log_path: Path | None) -> str | None:
    """Merge origin/main into a ready plan's trunk, at tip; return the caught-up tip.

    A trunk that contains main is left as it is: tip. A merge (old-form baseline conflicts
    recounted) is pushed and logged as branch.landed into the trunk, task <draft>/integration,
    branch main. Any other conflict is aborted and logged as branch.rejected, step
    integration.CATCH_UP, at the trunk's tip with main's sha; then None."""
    subject = f"{plan.draft}/integration"
    sh(["git", "fetch", "origin"], cwd=str(checkout), check=True)
    sh(["git", "reset", "-q", "--hard", f"origin/{plan.trunk}"], cwd=str(checkout), check=True)
    if sh(["git", "merge-base", "--is-ancestor", "origin/main", "HEAD"], cwd=str(checkout)).ok:
        return tip
    main = sh(["git", "rev-parse", "origin/main"], cwd=str(checkout), check=True).out.strip()
    merged = sh([*FAB_GIT, "merge", "--no-ff", "-m", f"Merge main into {plan.trunk}", main],
                cwd=str(checkout))
    findings = _settle_merge(merged, checkout, sh=sh)
    if findings is not None:
        log.append("branch.rejected", path=log_path, task=subject, branch="main", tip=tip,
                   step=integration.CATCH_UP, main=main, findings=findings)
        return None
    sh(["git", "push", "origin", f"HEAD:refs/heads/{plan.trunk}"], cwd=str(checkout), check=True)
    caught = sh(["git", "rev-parse", "HEAD"], cwd=str(checkout), check=True).out.strip()
    log.append("branch.landed", path=log_path, task=subject, branch="main", tip=main,
               main=caught, into=plan.trunk)
    return caught


def _untry(branch: str, hosts: Mapping[str, Host], *, sh: Runner) -> None:
    """Ask the queue on the first gate by name to forget the tip it tried for branch."""
    gate_hosts = sorted(name for name, host in hosts.items() if "gate" in host.roles)
    if not gate_hosts:
        raise ValueError("no gate host configured for queue untry")
    sh(ssh(hosts[gate_hosts[0]].ssh, ["fab", "queue", "untry", branch]), check=True)


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
        _untry(action.branch, hosts, sh=sh)
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
    # The call runs the fab that started it, not whatever `fab` is on PATH: a replay's own
    # install (coord/fab-replay) beside fab's, which follows main at each tick.
    argv = [str(Path(__file__).resolve().parent.parent / "bin/fab"), "call", role]
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
        names, given = _answered(chain)
        full = (name if "/" in name else f"{chain.subject}/{name}" for name in names)
        for identifier in dict.fromkeys(full):
            # A task with no spec file (a repair) gets its answer from the report's Answer line.
            answer = given.get(identifier) or given.get(identifier.split("/", 1)[-1])
            log.append("question.answered", path=log_path, task=identifier, call=chain.latest,
                       **({"answer": answer} if answer else {}))


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
                _start(action, tasks, hosts, plan=plan, checkout=checkout, sh=sh, log_path=log_path)
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
         log_path: Path | None = None, trigger: str = "hand", only: bool = False) -> list[Action]:
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
            return _round(plan_dirs, sh=sh, hosts=hosts, log_path=log_path, only=only)
        finally:
            for line in wake.settle(trigger, taken, log.read(log_path)[count:],
                                    path=path, log_path=log_path):
                print(line)


def _reconcile_reds(loaded: Sequence[tuple[Plan, dict[str, Task], Path, Path]],
                    load_actions: Sequence[Action], hosts: Mapping[str, Host], *, sh: Runner,
                    log_path: Path | None, only: bool) -> tuple[list[dict], list[tier_reds.Red], bool]:
    """Import queue and after-landing records, then reconcile reds (docs/design/fab.md, 13.8).

    Return fresh events, folded reds and whether failed loads defer openings.
    With only, close recovered reds but open none.
    """
    after_host = next((host for _, host in sorted(hosts.items()) if "after-landing" in host.roles), None)
    openings_deferred = bool(load_actions) and after_host is not None
    events = log.read(log_path)
    folded = tier_reds.reds(events)
    tasks = {key: task for plan, plan_tasks, _, _ in loaded
             for key, task in {**plan_tasks, **tier_reds.repair_tasks(plan, events, {}, folded=folded)}.items()}
    imported_from = len(events)
    _import_queue(tasks, events, hosts, sh=sh, log_path=log_path,
                  plan_drafts=[plan.draft for plan, _, _, _ in loaded])
    _import_after_landing(events, hosts, sh=sh, log_path=log_path)
    events = log.read(log_path)
    # Queue imports and after-landing runs can advance repairs before their verdicts arrive.
    if any(event.get("ev") in ("branch.landed", "tiers.run") for event in events[imported_from:]):
        folded = tier_reds.reds(events)
    closed = tier_reds.close_reds(events, folded=folded, log_path=log_path)
    if closed:
        events += closed
        folded = tier_reds.reds(events)
    owner_map = tier_reds.owners(((plan, tasks) for plan, tasks, _, _ in loaded), events, folded=folded)
    if not only and after_host is not None and not openings_deferred:
        opened = tier_reds.open_reds(events, owner_map, after_host, sh=sh, log_path=log_path, folded=folded)
        events += opened
        folded = [*folded, *tier_reds.reds(opened)] if opened else folded
    return events, folded, openings_deferred


def _round(plan_dirs: Sequence[Path], *, sh: Runner, hosts: Mapping[str, Host] | None,
           log_path: Path | None, only: bool = False) -> list[Action]:
    """Load and run listed then given plans, sharing imports and builder measurements.

    Fetch each checkout once; print load failures and skip retired plans. Import queue
    and after-landing records, close recovered reds, then open new reds against all loaded
    owners, unless any plan failed to load; with an after-landing host, fabrig retirement
    waits in that round too. With only, open no reds and do not hold retirement for them.
    With no loaded plan, refresh the page and return without measuring or starting work.
    With no owners, new reds are signals. Decide each plan on fresh events and spend calm
    extras once. Question, refusal and red actions share a log snapshot before fresh call
    decisions. Collect unowned runs last and refresh the page.
    """
    # only: the given plans alone, no strays and no page (a replay's own tick beside fab's,
    # coord/fab-replay).
    directories = [Path(path).resolve() for path in plan_dirs] if only else channel.plan_dirs(plan_dirs)
    if not directories:
        print("plans - none")
    loaded, load_actions = _load_plans(directories, log.read(log_path), sh=sh)
    actions = list(load_actions)
    hosts = machines.load() if hosts is None else hosts
    events, folded, openings_deferred = _reconcile_reds(
        loaded, load_actions, hosts, sh=sh, log_path=log_path, only=only)
    if loaded:
        plan_tasks = {key: task for plan, tasks, _, _ in loaded
                      for key, task in {**tasks, **tier_reds.tasks(plan, events, folded=folded)}.items()}
        calm = flow.measure(hosts, log.now(), sh=sh)
        for plan, tasks, directory, checkout in loaded:
            taken = _tick_loaded(plan, tasks, directory, checkout, hosts, calm, folded, plan_tasks,
                                 sh=sh, log_path=log_path, openings_deferred=openings_deferred, only=only)
            actions.extend(taken)
            calm = drafts.spend(calm, (action.host for action in taken if action.kind == "start"))
    if not only:
        try:
            for line in overlaps.probe(loaded, log.read(log_path),
                                       not any(action.kind == "load" for action in load_actions),
                                       sh=sh, log_path=log_path):
                print(line)
        except (OSError, ValueError, Failed) as error:
            print("overlap - failed: " + " ".join(str(error).splitlines()))
    if not loaded:
        if not only:
            _page(plan_dirs, log_path)
        return actions
    events = log.read(log_path)
    # With only, fab's own tick collects the strays: this tick's hosts may not name their builder.
    for record in ([] if only else drafts.strays([plan.draft for plan, _, _, _ in loaded], in_flight(events), events)):
        action = Action("collect", task=record["task"], run=record["run"],
                        host=record["host"], detail=record["run"])
        actions.append(action)
        _take(action, tasks, hosts, directory, plan=plan, checkout=checkout, sh=sh, log_path=log_path)
    if not only:
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


def _tick_loaded(plan: Plan, tasks: Mapping[str, Task], directory: Path, checkout: Path,
                 hosts: Mapping[str, Host], calm: Mapping[str, bool], folded: Sequence[tier_reds.Red],
                 plan_tasks: Mapping[str, Task], *, sh: Runner, log_path: Path | None,
                 openings_deferred: bool = False, only: bool = False) -> list[Action]:
    """Tick with the round's reds and suspect specs; only bypasses red retirement waits."""
    released = _merge_cut(plan, directory, checkout, hosts, sh=sh, log_path=log_path)
    if released:
        plan, tasks = _load_plan(directory, log.read(log_path), checkout=checkout, sh=sh)
    events = log.read(log_path)
    tasks = _integration_tasks(plan, specs.checked_tasks(plan, tasks, events), events)
    tasks = {**{identifier: task for identifier, task in tasks.items() if task.kind != tier_reds.KIND},
             **tier_reds.tasks(plan, events, folded=folded)}
    actions = decide(plan, tasks, events, hosts, calm, pushed=_pushed_branches(plan, checkout, sh=sh))
    for action in actions:
        _take(action, tasks, hosts, directory, plan=plan, checkout=checkout, sh=sh, log_path=log_path)
    events = log.read(log_path)
    # Collection can finish a red foreman; reuse the snapshot unless that happened.
    deciding = {red.foreman for red in folded if red.state == "deciding"}
    if any(event.get("ev") == "run.ended" and event.get("run") in deciding for event in events):
        folded = tier_reds.reds(events)
    settlements = foreman_actions(tasks, events) + repair_actions(tasks, events)
    for action in settlements:
        _take(action, tasks, hosts, directory, plan=plan, checkout=checkout, sh=sh, log_path=log_path)
    actions.extend(settlements)
    actions.extend(_red_steps(plan, {**plan_tasks, **tasks}, folded, hosts, sh=sh, log_path=log_path))
    design = [part for action in actions if action.kind == "design" for part in action.detail.split(", ")]
    followups = call_actions(plan, tasks, log.read(log_path), design, log.now())
    followups = [action for action in followups if action.run_kind != "retire" or only
                 or ((plan.repo != "fabrig" or not openings_deferred)
                     and retire_ready(plan, tasks, log.read(log_path), folded,
                                      after_landing=any("after-landing" in host.roles
                                                        for host in hosts.values())))]
    actions.extend(followups)
    for action in followups:
        _take(action, tasks, hosts, directory, plan=plan, checkout=checkout, sh=sh, log_path=log_path)
    _check_calls(plan, directory, checkout, hosts, sh=sh, log_path=log_path)
    _integration(plan, tasks, checkout, hosts, sh=sh, log_path=log_path)
    return released + actions


def _merge_cut(plan: Plan, directory: Path, checkout: Path, hosts: Mapping[str, Host], *,
               sh: Runner, log_path: Path | None) -> list[Action]:
    """Merge each running cut's pushed tip before deciding tasks; failures retry next tick."""
    if plan.landing != "integration" or plan.reviews:
        return []
    events = log.read(log_path)
    ended = {event["call"] for event in events if event.get("ev") == "call.ended"}
    actions = []
    for event in events:
        if (event.get("ev") != "call.started" or event.get("role") != "cut"
                or event.get("subject") != f"{plan.draft}/cut" or event["call"] in ended):
            continue
        branch = f"calls/{event['call']}"
        try:
            pushed = sh(["git", "rev-parse", "--verify", f"refs/remotes/origin/{branch}^{{commit}}"],
                        cwd=str(checkout))
            if not pushed.ok or not pushed.out.strip():
                continue
            argv = ["git", "merge-base", "--is-ancestor", pushed.out.strip(), f"origin/{plan.trunk}"]
            ancestor = sh(argv, cwd=str(checkout))
            if ancestor.ok:
                continue
            if ancestor.code != 1:
                raise Failed(argv, ancestor)
            action = Action("merge", task=branch, branch=branch, detail=branch)
            actions.append(action)
            _take(action, {}, hosts, directory, plan=plan, checkout=checkout, sh=sh, log_path=log_path)
        except (OSError, ValueError, Failed) as error:
            log.append("note", path=log_path, task=branch,
                       text="cut merge failed: " + " ".join(str(error).splitlines()))
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
           plan: Plan, checkout: Path, sh: Runner, log_path: Path | None) -> None:
    """Start a task run with current events and the decision's rejection context.

    decide counts only fab's own runs against a host's places; other work may hold its slots
    (claims made with `fab slot claim` by other sessions). A host with no idle slot hands the
    start to the next builder by free places, so the task waits only when every builder is full
    (the playground replay, 11-01: it retried a full hetzner6 every tick)."""
    events = log.read(log_path)
    free = places(hosts, in_flight(events))
    order = [action.host, *sorted((name for name in free if name != action.host and free[name] > 0),
                                  key=lambda name: (-free[name], name))]
    for position, name in enumerate(order):
        try:
            runs.start(tasks[action.task], hosts[name], kind=action.run_kind,
                       events=events, sh=sh, log_path=log_path, rejection=action.rejection,
                       trunk="main" if tasks[action.task].kind == tier_reds.KIND else plan.trunk,
                       checkout=checkout, early=action.early)
            return
        except ValueError as error:
            if str(error).startswith("early:"):
                # It waits for its needs to merge, as any task.
                log.append("early.refused", path=log_path, task=action.task,
                           needs=[need for need, _ in action.early], text=str(error))
                return
            if not str(error).endswith("no idle slot") or position == len(order) - 1:
                raise


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
    report = (log.home() / "runs" / action.run / "report.md").read_text()
    accept = (plan.landing == "integration" and foreman.accepts(report)
              and _pushed(question, events, checkout, sh=sh))
    log.append("question.answered", path=log_path, task=question.task, by=action.run,
               run=question.run, answer=answer.splitlines()[0], **({"accept": True} if accept else {}))


def _pushed_branches(plan: Plan, checkout: Path, *, sh: Runner) -> frozenset[str]:
    """The draft's branches on origin as the plan checkout last fetched them, for early starts;
    none outside an integration plan with early, or when the checkout cannot say."""
    if plan.landing != "integration" or not plan.early:
        return frozenset()
    listed = sh(["git", "for-each-ref", "--format=%(refname:lstrip=3)", f"refs/remotes/origin/{plan.draft}/"],
                cwd=str(checkout))
    return frozenset(line.strip() for line in listed.out.splitlines() if line.strip()) if listed.ok else frozenset()


def _pushed(question: foreman.Question, events: list[dict], checkout: Path, *, sh: Runner) -> bool:
    """Whether the asking run's branch is on origin, so an accepted task has work to merge;
    without it an Accept is an ordinary answer and the task runs again."""
    branch = next((event.get("branch") for event in events if event.get("ev") == "run.started"
                   and event.get("run") == question.run), None)
    if not branch:
        return False
    found = sh(["git", "ls-remote", "origin", f"refs/heads/{branch}"], cwd=str(checkout))
    return found.ok and bool(found.out.strip())


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
                  sh=sh, log_path=log_path,
                  trunk="main" if tasks[action.task].kind == tier_reds.KIND else plan.trunk)
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
        if not tasks[action.task].path:
            log.append("refusal.settled", path=log_path, task=refusal.task, run=action.run,
                       verdict=verdict, reason=reason, branch="", section=section)
            return f"{verdict} {reason}"
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


def _answered(chain: call_review.Chain) -> tuple[list[str], dict[str, str]]:
    """Read the latest call's Answered line, falling back to the root when absent or unreadable,
    and its `Answer <task>: <text>` lines (the answers of tasks with no spec file)."""
    for identifier in dict.fromkeys((chain.latest, chain.root)):
        try:
            report = (log.home() / "calls" / identifier / "report.md").read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        given = {}
        for line in report.splitlines():
            if line.startswith("Answer ") and ":" in line:
                task, _, text = line.removeprefix("Answer ").partition(":")
                if task.strip() and " " not in task.strip() and text.strip():
                    given[task.strip()] = text.strip()
        for line in report.splitlines():
            if line.startswith("Answered:"):
                return line.removeprefix("Answered:").split(), given
    return [], {}


def _park(action: Action, *, log_path: Path | None) -> None:
    """Park a task that exhausted its run allowance by asking for judgement; `park` marks the
    question as the dispatcher's, so it never goes to the foreman (fab.foreman.questions)."""
    log.append("question.asked", path=log_path, task=action.task, run=action.run, text=action.detail,
               park=True)


def _since_park(task_id: str, runs: list[str], events: list[dict]) -> list[str]:
    """The runs of task_id started after the answer to its last answered park: an answer to a
    park grants a fresh MAX_RUNS, or the task would park again at once (the playground replay,
    10-31: a park answered every 45 s). All runs while no park has been answered."""
    parked, answered = False, -1
    for position, event in enumerate(events):
        if event.get("task") != task_id:
            continue
        if event.get("ev") == "question.asked":
            parked = bool(event.get("park"))
        elif event.get("ev") == "question.answered" and parked:
            answered, parked = position, False
    if answered < 0:
        return runs
    later = {event["run"] for event in events[answered + 1:]
             if event.get("ev") == "run.started" and event.get("task") == task_id and "run" in event}
    return [run_id for run_id in runs if run_id in later]


def main(argv: list[str]) -> int:
    """`fab tick [PLAN_DIR...] [--trigger hand|event|backstop] [--dry-run] [--only]`.

    Tick listed and given plans; fail on bad loads. With --only, tick the given plans alone,
    collect no strays and write no page: a second tick beside fab's own, for plans kept off
    FAB_HOME/plans.

    Dry-run loads each plan without fetch, prints retirement, failed loads or decide's
    actions on the same log and hosts, with no calm. It neither chains plans nor acts,
    ignores --trigger and takes no want.
    """
    parser = argparse.ArgumentParser(prog="fab tick", description=__doc__)
    parser.add_argument("plan_dirs", type=Path, nargs="*", metavar="PLAN_DIR")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--trigger", choices=wake.TRIGGERS, default="hand")
    parser.add_argument("--only", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.dry_run:
            directories = channel.plan_dirs(args.plan_dirs)
            if not directories:
                print("plans - none")
            events = log.read()
            loaded, actions = _load_plans(directories, events, sh=run, fetch=False)
            hosts = machines.load() if loaded else {}
            folded = tier_reds.reds(events)
            for plan, tasks, _, _ in loaded:
                tasks = {**tasks, **tier_reds.tasks(plan, events, folded=folded)}
                for action in decide(plan, tasks, events, hosts):
                    print(f"{action.kind} {action.task or '-'} {action.detail}")
        else:
            actions = tick(*args.plan_dirs, trigger=args.trigger, only=args.only)
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
        if view.status == "done" and plan.landing == "integration" and any(
                views.get(need) is None or views[need].status != "landed" for need in tasks[identifier].needs):
            # An early start merges only after what it built on has (13.12).
            continue
        if view.status == "done":
            amendment = call_review.task_rebase(tasks[identifier], events)
            if amendment is not None:
                rebases.append(identifier)
                events = [*events, {"ev": "branch.rejected", "task": identifier, **amendment}]
                continue
            kind = "merge" if plan.landing == "integration" and tasks[identifier].kind != tier_reds.KIND else (
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
    """Add log-derived repairs (fab.integration.with_repairs)."""
    return integration.with_repairs(plan, tasks, events)


def _contains(sha: str, descendant: str, checkout: Path, *, sh: Runner) -> bool:
    """Check git ancestry in the plan checkout; errors are failures, never missing ancestry."""
    argv = ["git", "merge-base", "--is-ancestor", sha, descendant]
    ancestor = sh(argv, cwd=str(checkout))
    if ancestor.code not in (0, 1):
        raise Failed(argv, ancestor)
    return ancestor.ok


def _integration(plan: Plan, tasks: Mapping[str, Task], checkout: Path,
                 hosts: Mapping[str, Host], *, sh: Runner, log_path: Path | None) -> None:
    """Read main's ancestry after the checkout's fetch and take the trunk's next action."""
    events = log.read(log_path)
    tasks = _integration_tasks(plan, tasks, events)
    subject = f"{plan.draft}/integration"
    step = None
    try:
        main = trunk = None
        waiting = integration.catch_up_waiting(plan, events)
        caught = False
        if plan.landing == "integration" and plan.ready:
            if not _contains("origin/main", f"origin/{plan.trunk}", checkout, sh=sh):
                main = sh(["git", "rev-parse", "origin/main"], cwd=str(checkout), check=True).out.strip()
            trunk = sh(["git", "rev-parse", f"origin/{plan.trunk}"],
                       cwd=str(checkout), check=True).out.strip()
            if waiting:
                caught = _contains(waiting, f"origin/{plan.trunk}", checkout, sh=sh)
        step = integration.next_step(plan, tasks, events, main=main, trunk=trunk, caught=caught)
        if step is None:
            return
        detail = step.detail
        if step.kind == "caught":
            log.append("branch.landed", path=log_path, task=subject, branch="main", tip=waiting,
                       main=step.tip, into=plan.trunk, by="hand")
        elif step.kind == "catch-up":
            _catch_up(plan, step.tip, checkout, sh=sh, log_path=log_path)
        elif step.kind == "check":
            tip = (_catch_up(plan, step.tip, checkout, sh=sh, log_path=log_path)
                   if plan.ready else step.tip)
            if tip is not None:
                _integration_check(plan, tip, hosts, events, sh=sh, log_path=log_path)
        elif step.kind == "mid-check":
            # A check along the way takes only a slot no task wanted; none idle, it waits.
            try:
                _integration_check(plan, step.tip, hosts, events, sh=sh, log_path=log_path, mid=True)
            except ValueError as error:
                if not str(error).endswith("no idle slot"):
                    raise
                detail = "waits for an idle slot"
        elif step.kind == "ready":
            if any(event.get("ev") == "branch.rejected" and "queue_ts" in event
                   and event.get("task") == subject and event.get("tip") == step.tip for event in events):
                _untry(plan.trunk, hosts, sh=sh)
            sh(["git", "push", "origin", f"{step.tip}:refs/heads/ready/{plan.trunk}"],
               cwd=str(checkout), check=True)
            log.append("branch.ready", path=log_path, task=subject, branch=plan.trunk, tip=step.tip)
        elif not any(event.get("ev") == "note" and event.get("task") == subject
                     and event.get("tip") == step.tip and event.get("text") == detail for event in events):
            log.append("note", path=log_path, task=subject, tip=step.tip, text=detail)
    except (OSError, ValueError, Failed) as error:
        detail = "failed: " + " ".join(str(error).splitlines())
        log.append("note", path=log_path, task=subject, text=detail)
    print(f"integration {plan.draft} {step.kind if step else '-'} {detail}")


def _integration_check(plan: Plan, tip: str, hosts: Mapping[str, Host], events: list[dict], *,
                       sh: Runner, log_path: Path | None, mid: bool = False) -> None:
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
                    branch=plan.trunk, base=tip,
                    brief=f"{'Default' if mid else 'Full'} integration check of {tip}\n",
                    effort="high", slot=slot, sh=sh, log_path=log_path,
                    command=["fab", "check", "start", "--tip", tip, "--onto", f"origin/{plan.trunk}",
                             *(["--default"] if mid else [])],
                    **({"mid": True} if mid else {}))
    except Exception:
        sh(ssh(host.ssh, ["fab", "slot", "release", str(slot), run_id]), check=True)
        raise
