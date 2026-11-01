"""The integration trunk's end check and repairs (docs/design/fab.md, 13.12)."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from fab import atomic, codex, gate, log, precheck, state
from fab.plan import Plan, Task
from fab.sh import Failed, Runner, run


CATCH_UP = "catch-up"  # the step of a rejection when main does not merge into the trunk
QUEUE_LIMIT = 3  # queue rejections of a trunk before its plan stops for judgement


@dataclass(frozen=True)
class Step:
    """The next integration action, its trunk tip and the detail printed by the tick."""

    kind: str
    tip: str
    detail: str


MID_EVERY = 10  # task merges since the last check that call for a check along the way (13.12)
MID_AFTER = 45  # minutes since the last check (or the first merge) that call for one, with a merge since
MID_WITHOUT = ("fuzzy",)  # a check along the way runs the end check's steps but these


def trunk_tip(plan: Plan, events: Sequence[dict]) -> str | None:
    """The main of the last branch.landed into this plan's trunk, or None."""
    return next((event.get("main") for event in reversed(events)
                 if event.get("ev") == "branch.landed" and event.get("into") == plan.trunk), None)


def _first_merge(plan: Plan, events: Sequence[dict]) -> int | None:
    """The position of the first merge of one of the plan's tasks into its trunk; the
    cut's, answers' and repair sections' branches are not tasks."""
    return next((position for position, event in enumerate(events)
                 if event.get("ev") == "branch.landed" and event.get("into") == plan.trunk
                 and str(event.get("task", "")).startswith(f"{plan.draft}/")), None)


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


def repair_tasks(plan: Plan, events: Sequence[dict], reports: Mapping[str, str],
                 plan_tasks: Mapping[str, Task] | None = None) -> dict[str, Task]:
    """One integration repair per failed check, in log order, quoting at most 120 report lines.

    Repairs have no spec file and may change any file. Their acceptance requires the
    failed step green on the trunk with the change, running the narrowest checks first.
    A repair of a check along the way (mid) lists, given plan_tasks, the tasks not merged when it
    started and their files, to leave what they own. An answer to a repair's question (a question.answered with `answer`) has no spec to go
    into, so it is folded into the body's Answers section, in log order.
    """
    if plan.landing != "integration":
        return {}
    repairs = {}
    for check in _checks(plan, events):
        if check["outcome"] != "failed":
            continue
        identifier = f"{plan.draft}/repair-{len(repairs) + 1}"
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
                       if name not in landed and task.kind != "repair"]
            if pending:
                body += ("\n## Not merged yet\n\nThis was a check along the way: these tasks had not "
                         "merged. Leave a red that lies in what one of them owns, or that one of them "
                         "will fix by its spec; repair the rest.\n\n"
                         + "\n".join(f"- {task.id}: {', '.join(task.files) or '(no files named)'}"
                                      for task in pending) + "\n")
        answers = [event["answer"] for event in events if event.get("ev") == "question.answered"
                   and event.get("task") == identifier and event.get("answer")]
        if answers:
            body += "\n## Answers\n\n" + "\n".join(f"- {answer}" for answer in answers) + "\n"
        repairs[identifier] = Task(identifier, "integration", "repair", plan.repo, (),
                                 ("**",), "high", 20, body, "")
    return repairs


def with_repairs(plan: Plan, tasks: Mapping[str, Task], events: Sequence[dict]) -> dict[str, Task]:
    """tasks plus the log-derived repairs, reading the collected check reports locally; an
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


def next_step(plan: Plan, tasks: Mapping[str, Task], events: Sequence[dict]) -> Step | None:
    """Check an entirely merged trunk, ready its green tip when requested (queue_step), or stop
    after three failed checks. Wait for unfinished tasks, absent merges and checks in flight.
    The third red stops before its generated repair can start. A trunk whose catch-up with
    main conflicted at its tip (branch.rejected, step catch-up) stops for judgement. Pure."""
    if plan.landing != "integration":
        return None
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
    if sum(check["outcome"] == "failed" and not check.get("mid") for check in checks) >= 3:
        return Step("stop", tip, "red 3 times; needs judgement")
    views = state.fold(tasks, events)
    if any(view.status != "landed" for view in views.values()):
        return _mid_step(plan, tasks, views, events, tip, checks)
    if any(event.get("ev") == "branch.rejected" and event.get("step") == CATCH_UP
           and event.get("task") == f"{plan.draft}/integration" and event.get("tip") == tip
           for event in events):
        return Step("stop", tip, "main conflicts with the trunk; needs judgement")
    checked = next((check for check in reversed(checks) if check.get("base") == tip and not check.get("mid")), None)
    if checked is None:
        return Step("check", tip, tip)
    if checked["outcome"] == "done" and plan.ready:
        return queue_step(plan, events, tip)
    return None


def _mid_step(plan: Plan, tasks: Mapping[str, Task], views: Mapping[str, state.TaskView],
              events: Sequence[dict], tip: str, checks: Sequence[dict]) -> Step | None:
    """A check along the way (13.12) while tasks remain: once MID_EVERY task merges came since
    the last check, or MID_AFTER minutes passed since it (or since the first merge) with one
    merge since; never while a repair is open or for a tip already checked. Its reds never count
    toward the three that stop a plan. Now is the last event's time. Pure."""
    if any(task.kind == "repair" and views[identifier].status != "landed"
           for identifier, task in tasks.items() if identifier in views):
        return None
    if any(check.get("base") == tip for check in checks):
        return None
    last = checks[-1] if checks else None
    since = last.get("ts", "") if last else next(
        (event.get("ts", "") for event in events if event.get("ev") == "branch.landed"
         and event.get("into") == plan.trunk and str(event.get("task", "")).startswith(f"{plan.draft}/")), "")
    merges = sum(1 for event in events if event.get("ev") == "branch.landed" and event.get("into") == plan.trunk
                 and event.get("task") in tasks and (last is None or event.get("ts", "") > since))
    now = max((event.get("ts", "") for event in events), default=since)
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
    QUEUE_LIMIT times: stop for judgement. Not readied at tip yet: ready it. Readied at tip
    and rejected since: check again (the tick catches the trunk up with main first), and once
    that check has started, ready again. Otherwise the queue has it: wait."""
    subject = f"{plan.draft}/integration"
    mine = [(position, event) for position, event in enumerate(events) if event.get("task") == subject]
    if any(event.get("ev") == "branch.landed" and "queue_ts" in event for _, event in mine):
        return None
    rejections = [(position, event) for position, event in mine
                  if event.get("ev") == "branch.rejected" and "queue_ts" in event]
    if len(rejections) >= QUEUE_LIMIT:
        return Step("stop", tip, f"rejected by the queue {QUEUE_LIMIT} times; needs judgement")
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
