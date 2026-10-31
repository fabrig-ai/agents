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


@dataclass(frozen=True)
class Step:
    """The next integration action, its trunk tip and the detail printed by the tick."""

    kind: str
    tip: str
    detail: str


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


def repair_tasks(plan: Plan, events: Sequence[dict], reports: Mapping[str, str]) -> dict[str, Task]:
    """One integration repair per failed check, in log order, quoting at most 120 report lines.

    Repairs have no spec file and may change any file. Their acceptance requires the
    failed step green on the trunk with the change, running the narrowest checks first.
    """
    if plan.landing != "integration":
        return {}
    tasks = {}
    for check in _checks(plan, events):
        if check["outcome"] != "failed":
            continue
        identifier = f"{plan.draft}/repair-{len(tasks) + 1}"
        report = "\n".join(reports.get(check["run"], "").splitlines()[:120])
        body = (f"# Repair the integration check\n\n"
                f"- Tip: `{check['base']}`\n- Run: `{check['run']}`\n\n"
                f"{report}\n\n## Acceptance\n\n"
                "The failing step must be green on the trunk with this change. "
                "Run the narrowest checks first, then the failing step itself.\n")
        tasks[identifier] = Task(identifier, "integration", "repair", plan.repo, (),
                                 ("**",), "high", 20, body, "")
    return tasks


def next_step(plan: Plan, tasks: Mapping[str, Task], events: Sequence[dict]) -> Step | None:
    """Check an entirely merged trunk, ready its green tip once when requested, or stop
    after three failed checks. Wait for unfinished tasks, absent merges and checks in flight.
    The third red stops before its generated repair can start. Pure."""
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
    if sum(check["outcome"] == "failed" for check in checks) >= 3:
        return Step("stop", tip, "red 3 times; needs judgement")
    if any(view.status != "landed" for view in state.fold(tasks, events).values()):
        return None
    checked = next((check for check in reversed(checks) if check.get("base") == tip), None)
    if checked is None:
        return Step("check", tip, tip)
    if (checked["outcome"] == "done" and plan.ready
            and not any(event.get("ev") == "branch.ready"
                        and event.get("task") == f"{plan.draft}/integration" for event in events)):
        return Step("ready", tip, tip)
    return None


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
            meta = {"tip": args.tip, "onto": args.onto, "brief": str(args.brief),
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
            receipt = precheck.precheck(Path(meta["dir"]), meta["tip"], onto=meta["onto"], full=True)
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
