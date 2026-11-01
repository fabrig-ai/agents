"""The integration trunk's end check and repairs (docs/design/integration.md, 3)."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from fab import atomic, codex, fix, gate, log, precheck, state
from fab.plan import Plan, Task
from fab.sh import Failed, Runner, run


CATCH_UP = "catch-up"  # the step of a rejection when main does not merge into the trunk
CATCH_LIMIT = 3  # refusals since the last clean catch-up before stopping for judgement
QUEUE_LIMIT = 3  # queue rejections of a trunk before its plan stops for judgement


@dataclass(frozen=True)
class Step:
    """The next action, trunk tip, printed detail and stop cause (empty for other actions)."""

    kind: str
    tip: str
    detail: str
    why: str = ""


MID_EVERY = 10  # task merges since the last check that call for a check along the way (integration.md 3)
MID_AFTER = 45  # minutes since the last check (or the first merge) that call for one, with a merge since
CATCH_AFTER = 30  # minutes since the last catch-up (or first task merge) before catching up again
MID_WITHOUT = ("fuzzy",)  # a check along the way runs the end check's steps but these


def trunk_landed(plan: Plan, events: Sequence[dict]) -> bool:
    """Whether the queue logged this draft's integration trunk landed on main.

    Only branch.landed for <draft>/integration carrying queue_ts counts; merges
    into the trunk and its landed tasks do not (docs/design/integration.md, 4).
    """
    return any(event.get("ev") == "branch.landed"
               and event.get("task") == f"{plan.draft}/integration" and "queue_ts" in event
               for event in events)


def call_base(plan: Plan, events: Sequence[dict]) -> str:
    """Use main for calls after an integration plan's queue landing, else its trunk.

    Only this draft's trunk landing counts (docs/design/integration.md, 3,
    Retire waits for main); queue plans always keep their configured trunk.
    """
    return "main" if plan.landing == "integration" and trunk_landed(plan, events) else plan.trunk


def trunk_tip(plan: Plan, events: Sequence[dict]) -> str | None:
    """The main of the last branch.landed into this plan's trunk, or None."""
    return next((event.get("main") for event in reversed(events)
                 if event.get("ev") == "branch.landed" and event.get("into") == plan.trunk), None)


def _first_merge(plan: Plan, events: Sequence[dict]) -> int | None:
    """The position of the first merge of one of the plan's tasks into its trunk; the
    cut's, answers', repair sections' and main's branches are not tasks."""
    return next((position for position, event in enumerate(events)
                 if event.get("ev") == "branch.landed" and event.get("into") == plan.trunk
                 and str(event.get("task", "")).startswith(f"{plan.draft}/")
                 and event.get("task") != f"{plan.draft}/integration"), None)


def _checks(plan: Plan, events: Sequence[dict]) -> list[dict]:
    """This plan's check starts after its first task merge, in log order, carrying their
    collected outcomes when ended. A check before any task merged checks no work of the
    plan and is ignored."""
    first = _first_merge(plan, events)
    if first is None:
        return []
    ended = {event["run"]: event for event in events if event.get("ev") == "run.ended"}
    return [{**event, "outcome": ended.get(event["run"], {}).get("outcome")}
            for position, event in enumerate(events) if position > first
            and event.get("ev") == "run.started"
            and event.get("kind") == "check" and event.get("task") == f"{plan.draft}/integration"]


def _clean_catch_up(plan: Plan, event: dict) -> bool:
    """A logged merge of main into this plan's trunk, by the tick, a checked repair or by hand."""
    return (event.get("ev") == "branch.landed" and event.get("into") == plan.trunk
            and event.get("task") == f"{plan.draft}/integration" and event.get("branch") == "main")


def _catch_up_refusals(plan: Plan, events: Sequence[dict]) -> dict[int, str | None]:
    """Catch-up refusals in log order: their repair id, or None after a repair for that
    main sha has merged into the trunk or CATCH_LIMIT refusals since a clean catch-up.
    Only a merge after the last lift and before the refusal counts. Lifts reset the
    refusal count; repair numbering spans lifts and clean catch-ups."""
    result = {}
    repairs = {}
    merged = set()
    refused = 0
    for position, event in enumerate(events):
        if event.get("ev") == "question.answered" and event.get("task") == f"{plan.draft}/integration":
            refused = 0
            merged.clear()
        if _clean_catch_up(plan, event):
            refused = 0
        if (event.get("ev") == "branch.landed" and event.get("into") == plan.trunk
                and event.get("task") in repairs):
            merged.add(repairs[event["task"]])
        if (event.get("ev") != "branch.rejected" or event.get("step") != CATCH_UP
                or event.get("task") != f"{plan.draft}/integration"):
            continue
        main = event.get("main")
        refused += 1
        identifier = (None if (main and main in merged) or refused >= CATCH_LIMIT
                      else f"{plan.draft}/catch-up-{len(repairs) + 1}")
        result[position] = identifier
        if identifier is not None:
            repairs[identifier] = main
    return result


def catch_up_main(plan: Plan, events: Sequence[dict], identifier: str) -> str | None:
    """The main sha named by the refusal that made this catch-up repair, or None. Pure."""
    return next((events[position].get("main")
                 for position, repair in _catch_up_refusals(plan, events).items()
                 if repair == identifier), None)


def catch_up_waiting(plan: Plan, events: Sequence[dict]) -> str | None:
    """The first stopping refusal's sha after both the last clean catch-up and lift, or None. Pure."""
    clean = next((position for position in range(len(events) - 1, -1, -1)
                  if _clean_catch_up(plan, events[position])), -1)
    since = max(clean, lifted(plan, events))
    return next((events[position].get("main")
                 for position, identifier in _catch_up_refusals(plan, events).items()
                 if identifier is None and position > since), None)


def repair_tasks(plan: Plan, events: Sequence[dict], reports: Mapping[str, str],
                 plan_tasks: Mapping[str, Task] | None = None) -> dict[str, Task]:
    """Check and catch-up repairs in log order, numbered separately, with no spec file.

    Check reports quote at most 120 lines. Mid repairs list tasks not merged at the check,
    given plan_tasks. Both kinds fold question.answered text into Answers in log order.
    Stop answers also reach repairs unmerged at the answer and all later repairs;
    tick lifts reach none. A stopping catch-up refusal generates no further repair.
    """
    if plan.landing != "integration":
        return {}
    repairs = {}
    checks = {check["run"]: check for check in _checks(plan, events) if check["outcome"] == "failed"}
    refusals = _catch_up_refusals(plan, events)
    red = 0
    for position, event in enumerate(events):
        if position in refusals:
            identifier = refusals[position]
            if identifier is None:
                continue
            body = _catch_up_body(event)
        elif event.get("ev") == "run.started" and event.get("run") in checks:
            check = checks[event["run"]]
            red += 1
            identifier = f"{plan.draft}/repair-{red}"
            report = "\n".join(reports.get(check["run"], "").splitlines()[:120])
            body = (f"# Repair the integration check\n\n"
                    f"- Tip: `{check['base']}`\n- Run: `{check['run']}`\n\n"
                    f"{report}\n\n## Acceptance\n\n"
                    "The failing step must be green on the trunk with this change. "
                    "Run the narrowest checks first, then the failing step itself.\n")
            if check.get("mid") and plan_tasks:
                landed = {event.get("task") for event in events if event.get("ev") == "branch.landed"
                          and event.get("ts", "") <= check.get("ts", "")}
                pending = [task for name, task in plan_tasks.items()
                           if name not in landed and task.kind not in ("repair", *fix.FIX_KINDS)]
                if pending:
                    body += ("\n## Not merged yet\n\nThis was a check along the way: these tasks had not "
                             "merged. Leave a red that lies in what one of them owns, or that one of them "
                             "will fix by its spec; repair the rest.\n\n"
                             + "\n".join(f"- {task.id}: {', '.join(task.files) or '(no files named)'}"
                                          for task in pending) + "\n")
        else:
            continue
        answers = _repair_answers(plan, events, identifier)
        if answers:
            body += "\n## Answers\n\n" + "\n".join(f"- {answer}" for answer in answers) + "\n"
        sections = [event["section"] for event in events if event.get("ev") == "refusal.settled"
                    and event.get("task") == identifier and event.get("verdict") == "fix" and event.get("section")]
        for section in sections:
            body += "\n" + section.rstrip("\n") + "\n"
        repairs[identifier] = Task(identifier, "integration", "repair", plan.repo, (),
                                 ("**",), "high", 20, body, "")
    return repairs


def _catch_up_body(event: dict) -> str:
    """Describe the refused main merge and its repair's acceptance."""
    return ("# Repair the catch-up with main\n\n"
            f"- Trunk tip: `{event['tip']}`\n- Main sha: `{event.get('main', '?')}`\n\n"
            f"## Findings\n\n{event.get('findings', '')}\n\n"
            "Merge that main sha into your branch, which starts at the trunk's tip. "
            "Resolve each conflict keeping both sides' intent: main's side is other drafts' "
            "landed work, the trunk's is this draft's. Fix what main's changes break in "
            "this draft's code, and push.\n\n## Acceptance\n\n"
            "The pushed branch contains the main sha and has no conflict markers. "
            "The crates the conflicts touched build and pass clippy and their tests; "
            "the trunk's next check runs the rest.\n")


def _repair_answers(plan: Plan, events: Sequence[dict], identifier: str) -> list[str]:
    """Own answers and human stop answers before this repair merged, in log order."""
    answers = []
    merged = False
    for event in events:
        if (event.get("ev") == "branch.landed" and event.get("into") == plan.trunk
                and event.get("task") == identifier):
            merged = True
        if event.get("ev") != "question.answered" or not event.get("answer"):
            continue
        if (event.get("task") == identifier or (not merged and event.get("by") != "tick"
                and event.get("task") == f"{plan.draft}/integration")):
            answers.append(event["answer"])
    return answers


def with_repairs(plan: Plan, tasks: Mapping[str, Task], events: Sequence[dict]) -> dict[str, Task]:
    """tasks plus the log-derived check and catch-up repairs, reading check reports locally; an
    unreadable report is empty. Shared by the tick and the answer call's brief."""
    reports = {}
    for event in events:
        if (event.get("ev") == "run.started" and event.get("kind") == "check"
                and event.get("task") == f"{plan.draft}/integration"):
            try:
                reports[event["run"]] = (log.home() / "runs" / event["run"] / "report.md").read_text()
            except (OSError, UnicodeError):
                reports[event["run"]] = ""
    return {**tasks, **repair_tasks(plan, events, reports, tasks)}


def next_step(plan: Plan, tasks: Mapping[str, Task], events: Sequence[dict], *,
              main: str | None = None, trunk: str | None = None, caught: bool = False) -> Step | None:
    """Check an entirely merged trunk, ready its green tip when requested (queue_step), or stop
    after three failed end checks started since the last lift. Wait for unfinished tasks,
    absent merges and checks in flight.
    The third end red stops before its generated repair can start. A catch-up refusal after
    its main sha's repair merged, or the third since a clean catch-up, stops for judgement.
    main is origin/main's sha when the trunk lacks it, otherwise None; trunk is the fetched
    origin/<trunk> tip. caught says that trunk contains catch_up_waiting's sha, so a stopped
    ready plan can log a hand catch-up even if main has moved on. Pure."""
    if plan.landing != "integration":
        return None
    tasks = {identifier: task for identifier, task in tasks.items() if task.kind not in fix.FIX_KINDS}
    ended = {event["call"] for event in events if event.get("ev") == "call.ended"}
    if any(event.get("ev") == "call.started" and event.get("role") == "cut"
           and event.get("subject") == f"{plan.draft}/cut" and event["call"] not in ended
           for event in events):
        return None
    tip = trunk_tip(plan, events)
    checks = _checks(plan, events)
    if tip is None or _first_merge(plan, events) is None or any(
            check["outcome"] is None for check in checks):
        return None
    since = {event["run"] for event in events[lifted(plan, events) + 1:]
             if event.get("ev") == "run.started"}
    if sum(check["outcome"] == "failed" and not check.get("mid") and check["run"] in since
           for check in checks) >= 3:
        return Step("stop", tip, "red 3 times; needs judgement", why="red")
    if catch_up_waiting(plan, events):
        if plan.ready and caught and trunk:
            return Step("caught", trunk, "main caught up by hand")
        return Step("stop", tip, "main catch-up refused repeatedly; needs judgement", why="catch-up")
    views = state.fold(tasks, events)
    if any(view.status != "landed" for view in views.values()):
        return _mid_step(plan, tasks, views, events, tip, checks, main=main)
    checked = next((check for check in reversed(checks) if check.get("base") == tip and not check.get("mid")), None)
    if checked is None:
        return Step("check", tip, tip)
    if checked["outcome"] == "done" and plan.ready:
        return queue_step(plan, events, tip)
    return None


def lifted(plan: Plan, events: Sequence[dict]) -> int:
    """The last log position answering <draft>/integration, or -1 if none. Pure."""
    return next((position for position in range(len(events) - 1, -1, -1)
                 if events[position].get("ev") == "question.answered"
                 and events[position].get("task") == f"{plan.draft}/integration"), -1)


def catch_up_lifts(plan: Plan, events: Sequence[dict]) -> bool:
    """Whether a clean catch-up follows the unlifted catch-up stop. Pure.

    Accept the tick's, a checked repair's or a hand merge of main into this trunk.
    A clean catch-up before the stop or after another kind of stop cannot lift it.
    """
    stop = next((position for position in range(len(events) - 1, lifted(plan, events), -1)
                 if events[position].get("ev") == "plan.stopped"
                 and events[position].get("task") == f"{plan.draft}/integration"), None)
    return (stop is not None and events[stop].get("why") == "catch-up"
            and any(_clean_catch_up(plan, event) for event in events[stop + 1:]))


def stopped(plan: Plan, events: Sequence[dict], step: Step, gate: str) -> list[tuple[str, dict]]:
    """The stop and parked question to log once since the last integration answer. Pure.

    A red names its last failed end check's run and local report; a queue stop names
    its last rejection's log on gate. A catch-up quotes at most 20 lines of the
    stopping refusal's findings. Merges while a stop holds do not ask again.
    """
    subject = f"{plan.draft}/integration"
    if step.kind != "stop" or any(event.get("ev") == "plan.stopped" and event.get("task") == subject
                                  for event in events[lifted(plan, events) + 1:]):
        return []
    text, report, run_id = step.detail, "", ""
    if step.why == "red":
        check = next(check for check in reversed(_checks(plan, events))
                     if check["outcome"] == "failed" and not check.get("mid"))
        run_id = check["run"]
        report = str(log.home() / "runs" / run_id / "report.md")
    elif step.why == "queue":
        rejected = next(event for event in reversed(events) if event.get("task") == subject
                        and event.get("ev") == "branch.rejected" and "queue_ts" in event)
        report = f"{gate}:{rejected.get('log', '')}"
    elif step.why == "catch-up":
        clean = next((position for position in range(len(events) - 1, -1, -1)
                      if _clean_catch_up(plan, events[position])), -1)
        refusal = next(events[position] for position, repair in _catch_up_refusals(plan, events).items()
                       if repair is None and position > max(clean, lifted(plan, events)))
        findings = "\n".join(refusal.get("findings", "").splitlines()[:20])
        if findings:
            text += "\n\n" + findings
    return [("plan.stopped", dict(task=subject, tip=step.tip, why=step.why, text=text, report=report)),
            ("question.asked", dict(task=subject, run=run_id, text=text, park=True))]


def _mid_step(plan: Plan, tasks: Mapping[str, Task], views: Mapping[str, state.TaskView],
              events: Sequence[dict], tip: str, checks: Sequence[dict], *,
              main: str | None = None) -> Step | None:
    """Catch up first when main moved and CATCH_AFTER elapsed since the last catch-up (or
    first merge). Otherwise check along the way (integration.md 3) once MID_EVERY task merges came since
    the last check, or MID_AFTER minutes passed since it (or since the first merge) with one
    merge since; never while a repair is open or for a tip already checked. Its reds never count
    toward the three that stop a plan. Now is the last event's time. Pure."""
    if any(task.kind == "repair" and views[identifier].status != "landed"
           for identifier, task in tasks.items() if identifier in views):
        return None
    now = max((event.get("ts", "") for event in events), default="")
    if plan.ready and main:
        catch = next((event for event in reversed(events)
                      if event.get("task") == f"{plan.draft}/integration"
                      and ((event.get("ev") == "branch.landed" and event.get("branch") == "main")
                           or (event.get("ev") == "branch.rejected" and event.get("step") == CATCH_UP))), None)
        since = (catch if catch is not None else events[_first_merge(plan, events)]).get("ts", "")
        minutes = (_time(now) - _time(since)).total_seconds() / 60 if now and since else 0
        if minutes >= CATCH_AFTER:
            return Step("catch-up", tip, f"main {main}, {minutes:.0f} min since the last catch-up")
    if any(check.get("base") == tip for check in checks):
        return None
    last = checks[-1] if checks else None
    since = (last if last is not None else events[_first_merge(plan, events)]).get("ts", "")
    merges = sum(1 for event in events if event.get("ev") == "branch.landed" and event.get("into") == plan.trunk
                 and event.get("task") in tasks and event.get("task") != f"{plan.draft}/integration"
                 and (last is None or event.get("ts", "") > since))
    minutes = (_time(now) - _time(since)).total_seconds() / 60 if now and since else 0
    if merges >= MID_EVERY or (merges and minutes >= MID_AFTER):
        return Step("mid-check", tip, f"{merges} merges, {minutes:.0f} min since the last check")
    return None


def _time(stamp: str):
    from datetime import datetime
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def queue_step(plan: Plan, events: Sequence[dict], tip: str) -> Step | None:
    """What the queue's record asks of a ready plan's trunk, green at tip. Pure.

    Landed by the queue (an imported branch.landed): nothing. Rejected by the queue
    QUEUE_LIMIT times since the last lift: stop for judgement. Not readied at tip yet:
    ready it. Readied at tip and rejected since: check again (the tick catches the trunk
    up with main first), and once that check has started, ready again. Otherwise wait."""
    subject = f"{plan.draft}/integration"
    mine = [(position, event) for position, event in enumerate(events) if event.get("task") == subject]
    if trunk_landed(plan, events):
        return None
    since = lifted(plan, events)
    rejections = [(position, event) for position, event in mine
                  if event.get("ev") == "branch.rejected" and "queue_ts" in event]
    if sum(position > since for position, event in rejections) >= QUEUE_LIMIT:
        return Step("stop", tip, f"rejected by the queue {QUEUE_LIMIT} times; needs judgement", why="queue")
    readied = [(position, event) for position, event in mine if event.get("ev") == "branch.ready"]
    if not readied or readied[-1][1].get("tip") != tip:
        return Step("ready", tip, tip)
    rejected = next(((position, event) for position, event in reversed(rejections)
                     if position > readied[-1][0]), None)
    if rejected is None:
        return None
    if any(position > rejected[0] and event.get("ev") == "run.started"
           and event.get("kind") == "check" and event.get("base") == tip for position, event in mine):
        return Step("ready", tip, tip)
    return Step("check", tip, f"queue rejected {rejected[1].get('step', '?')}: catch up and check again")


def baselines(paths: Sequence[str]) -> list[str]:
    """Trees in gate.TREES order when every unmerged path is an old-form baseline;
    empty when paths is empty or any path is not such a baseline."""
    expected = {f"{tree}/scripts/old-forms.txt": tree for tree in gate.TREES}
    if not paths or any(path not in expected for path in paths):
        return []
    return [tree for tree in gate.TREES if f"{tree}/scripts/old-forms.txt" in paths]


def recount(checkout: Path, trees: Sequence[str], *, sh: Runner = run) -> None:
    """Resolve each tree's baseline from ours, recount with --write and stage it.
    A nonzero command raises Failed, so a failed recount cannot complete a merge."""
    for tree in trees:
        baseline = f"{tree}/scripts/old-forms.txt"
        sh(["git", "checkout", "--ours", "--", baseline], cwd=str(checkout), check=True)
        sh(["python3", "-I", "-B", "scripts/old_forms.py", "--write"],
           cwd=str(checkout / tree), check=True)
        sh(["git", "add", "--", baseline], cwd=str(checkout), check=True)


def main(argv: list[str]) -> int:
    """`fab check start --tip TIP --onto REF BRIEF WORKDIR REPORT` starts a user unit
    under FAB_HOME/check/<id> and prints `<id> <state>`. `_exec ID` runs the full precheck,
    writes REPORT, result.json (exit, ended), then the ended marker last."""
    parser = argparse.ArgumentParser(prog="fab check", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    starting = commands.add_parser("start")
    starting.add_argument("--tip", required=True)
    starting.add_argument("--onto", required=True)
    starting.add_argument("--default", action="store_true", help="a check along the way: no fuzzy")
    starting.add_argument("brief", type=Path)
    starting.add_argument("workdir", type=Path)
    starting.add_argument("report", type=Path)
    commands.add_parser("_exec").add_argument("id")
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            for name in ("brief", "workdir", "report"):
                if not getattr(args, name).is_absolute():
                    raise ValueError(f"{name} must be absolute")
            if not args.brief.is_file() or not args.workdir.is_dir():
                raise ValueError("brief must be a file and workdir a directory")
            if args.report.exists() or args.report.is_symlink():
                raise ValueError(f"report already exists: {args.report}")
            while True:
                identifier = codex.new_id()
                directory = log.home() / "check" / identifier
                try:
                    directory.mkdir(parents=True, mode=0o700)
                    break
                except FileExistsError:
                    continue
            meta = {"tip": args.tip, "onto": args.onto, "brief": str(args.brief), "default": args.default,
                    "dir": str(args.workdir), "report": str(args.report), "started": log.now()}
            atomic.write(directory / "meta.json", json.dumps(meta) + "\n")
            launcher = Path(__file__).resolve().parent.parent / "bin/fab"
            run(["systemd-run", "--user", "--collect", "--quiet", "--unit", f"fab-check-{identifier}",
                 "--property=UMask=0077",
                 f"--property=ExecStopPost=-{sys.executable} -I -B {launcher} wake codex {identifier}",
                 "--", sys.executable, "-I", "-B", str(launcher), "check", "_exec", identifier], check=True)
            print(f"{identifier} {directory}")
            return 0
        directory = log.home() / "check" / args.id
        meta = json.loads((directory / "meta.json").read_text())
        try:
            receipt = precheck.precheck(Path(meta["dir"]), meta["tip"], onto=meta["onto"], full=True,
                                        without=MID_WITHOUT if meta.get("default") else ())
            green = receipt["outcome"] == "green"
            red = next((step.rsplit(":", 2)[0] for step in receipt["steps"]
                        if step.rsplit(":", 2)[1] != "0"), receipt["outcome"])
            first = f"Done: green {meta['tip']}" if green else f"Failed: {red} red"
            report = "\n".join([first, *receipt["steps"], receipt["log"]]) + "\n"
        except Exception as error:
            green = False
            report = f"Failed: precheck red\n{error}\n"
        atomic.write(Path(meta["report"]), report)
        atomic.write(directory / "result.json", json.dumps({"exit": 0 if green else 1, "ended": log.now()}) + "\n")
        atomic.write(directory / "ended", "")
        return 0 if green else 1
    except (OSError, ValueError, Failed) as error:
        print(f"fab check: {error}", file=sys.stderr)
        return 1
