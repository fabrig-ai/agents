"""Routed findings' foremen, settlements and repair tasks (docs/design/qa.md, 2)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from fab import findings, fix, foreman, log
from fab.findings import Finding
from fab.plan import Plan, Task
from fab.run import Host, Runner, run

KIND = "finding"  # repair task kind
PART = "qa"  # log-derived tasks have no plan part
ROLE = Path(__file__).resolve().parent / "roles" / "foreman-finding.md"  # read-only cause survey
SETTLED = "finding.settled"  # the foreman's verdict
WALK_REPORT_BYTES = 15 * 1024  # the walk kit's report cap


def repair_id(finding: Finding) -> str:
    """Return <draft>/<finding id> (docs/design/qa.md, 2)."""
    return f"{finding.draft}/{finding.id}"


@dataclass(frozen=True)
class Foreman:
    """A finding's first foreman; outcome/report stay empty until collected
    (docs/design/qa.md, 2).
    """

    finding: str
    run: str
    tip: str
    outcome: str = ""
    report: str = ""


def foremen(events: Sequence[dict]) -> dict[str, Foreman]:
    """Return each finding's first foreman and first matching end, in log order;
    pure. Only kind foreman at <draft>/<finding>/foreman counts (docs/design/qa.md, 2).
    """
    found, by_run, ended = {}, {}, set()
    for event in events:
        if event.get("ev") == "run.started":
            identifier, task = event.get("finding"), event.get("task")
            if (event.get("kind") != foreman.KIND
                    or not all(isinstance(event.get(key), str) and event[key]
                               for key in ("finding", "task", "run", "tip"))):
                continue
            suffix = f"/{identifier}/foreman"
            if not task.endswith(suffix) or not task.removesuffix(suffix) or identifier in found:
                continue
            found[identifier] = Foreman(identifier, event["run"], event["tip"])
            by_run[event["run"]] = identifier
        elif event.get("ev") == "run.ended":
            run_id = event.get("run")
            if not isinstance(run_id, str) or run_id not in by_run or run_id in ended:
                continue
            if not isinstance(event.get("outcome"), str):
                continue
            identifier = by_run[run_id]
            report = event.get("report", "")
            found[identifier] = replace(found[identifier], outcome=event["outcome"],
                                        report=report if isinstance(report, str) else "")
            ended.add(run_id)
    return found


def _record(finding: Finding, merged: Sequence[Finding]) -> str:
    """Render the finding and each merged reproduction without reading files."""
    text = (f"### {finding.title}\n\nReproduction:\n{finding.reproduction}\n\n"
            f"Expected:\n{finding.expected}\n\nSeen:\n{finding.seen}\n")
    for sighting in merged:
        text += (f"\n### {sighting.id} (walk {sighting.walk})\n\n"
                 f"Reproduction:\n{sighting.reproduction}\n")
    return text


def brief(finding: Finding, plan: Plan, *, run_id: str, report: str, tip: str,
          briefs: Sequence[str | Path], merged: Sequence[Finding], walk_report: str, role: str) -> str:
    """Return role, finding facts, record and whole walk report; pure.

    briefs are repository paths for the rung's brief files. merged supplies sightings;
    walk_report may contain an unreadable or truncated marker (docs/design/qa.md, 2).
    """
    facts = (f"- Run: {run_id}\n- Finding: {finding.id}\n- Draft: {plan.draft}\n"
             f"- Rung: {finding.rung}\n- Backend: {finding.backend}\n- Walk: {finding.walk}\n"
             f"- Commit walked: `{finding.commit}`\n- Area: {finding.area}\n"
             f"- Owner: {finding.owner}\n- Triager's reason: {finding.reason}\n"
             + "".join(f"- Brief: `{path}`\n" for path in briefs)
             + f"- Report: write it to `{report}`\nYour checkout is fabrig at {tip}, read-only.")
    return (role.rstrip("\n") + "\n\n# The finding\n\n" + facts
            + "\n\n# The record\n\n" + _record(finding, merged)
            + "\n# The walk's report\n\n" + walk_report)


def _walk_report(walk: str) -> str:
    """Read at most the walk kit's byte cap, marking unreadable or cut reports."""
    try:
        with (log.home() / "walks" / walk / "report.md").open("rb") as stream:
            content = stream.read(WALK_REPORT_BYTES + 1)
        if len(content) > WALK_REPORT_BYTES:
            return (content[:WALK_REPORT_BYTES].decode("utf-8", errors="ignore")
                    + f"\n(walk report truncated at {WALK_REPORT_BYTES} bytes)\n")
        return content.decode("utf-8")
    except (OSError, UnicodeError) as error:
        return f"(walk report unreadable: {error})"


def start(finding: Finding, plan: Plan, plan_path: Path, host: Host, tip: str,
          events: Sequence[dict], *, sh: Runner = run, log_path: Path | None = None) -> str:
    """Launch the finding's read-only fabrig foreman at tip; return its run id.

    Read ROLE and FAB_HOME/walks/<walk>/report.md, fold sightings from events and name
    plan_path/<brief> for every rung brief; role read errors propagate (docs/design/qa.md, 2).
    """
    role, report_text = ROLE.read_text(), _walk_report(finding.walk)
    found = findings.findings(events)
    merged = [found[identifier] for identifier in finding.sightings if identifier in found]
    paths = [plan_path / path for path in plan.rungs[finding.rung].brief]
    return fix.launch(
        repair_id(finding), host, tip,
        lambda run_id, report: brief(finding, plan, run_id=run_id, report=report, tip=tip,
                                     briefs=paths, merged=merged, walk_report=report_text, role=role),
        events, sh=sh, log_path=log_path, finding=finding.id)


def settle(finding: Finding, foreman: Foreman, report: str, *,
           log_path: Path | None = None) -> dict:
    """Parse the foreman report, log finding.settled and return its record.

    A fix keeps a dated Repair section; left and none keep no section (docs/design/qa.md, 2).
    """
    verdict, reason, lines, _ = fix.parse(report)
    return fix.settle(SETTLED, lambda day: dict(
        finding=finding.id, run=foreman.run, verdict=verdict, reason=reason,
        section=fix.section(f"## Repair ({day}, finding {finding.id.removeprefix('finding-')}, "
                            f"foreman {foreman.run})", reason, lines) if verdict == "fix" else ""),
        log_path=log_path)


def _repairs(events: Sequence[dict], surveys: dict[str, Foreman]) -> dict[str, str]:
    """Keep the first settlement or non-done end that creates each repair."""
    by_run = {survey.run: identifier for identifier, survey in surveys.items()}
    started, ended, settled, sections = set(), set(), set(), {}
    for event in events:
        run_id = event.get("run")
        identifier = by_run.get(run_id) if isinstance(run_id, str) else None
        if identifier is None:
            continue
        survey = surveys[identifier]
        if event.get("ev") == "run.started":
            started.add(run_id)
        elif event.get("ev") == "run.ended" and run_id in started and run_id not in ended:
            if event.get("outcome") != survey.outcome:
                continue
            ended.add(run_id)
            if survey.outcome != "done":
                sections[identifier] = ""
        elif (event.get("ev") == SETTLED and run_id in ended and survey.outcome == "done"
              and event.get("finding") == identifier and identifier not in settled
              and event.get("verdict") in ("fix", "none", "left")
              and all(isinstance(event.get(key), str) for key in ("ts", "reason", "section"))):
            settled.add(identifier)
            if event["verdict"] != "left":
                sections[identifier] = event["section"] if event["verdict"] == "fix" else ""
    return sections


def _body(finding: Finding, merged: Sequence[Finding], reason: str, section: str) -> str:
    """Render a repair's facts, evidence, foreman section and Fix-mode acceptance."""
    return (f"# Repair a QA finding ({finding.id})\n\n"
            f"- Rung: {finding.rung}\n- Backend: {finding.backend}\n- Walk: {finding.walk}\n"
            f"- Commit: `{finding.commit}`\n- Edition: {finding.edition}\n- Area: {finding.area}\n"
            f"- Owner: {finding.owner}\n- Triager's reason: {reason}\n\n## The finding\n\n"
            + _record(finding, merged) + ("\n" + section.rstrip("\n") + "\n" if section else "")
            + "\n## Acceptance\n\n"
            "Reproduce first, in the lowest world that shows it: a test red on main before "
            "the change and green after, naming the world and why it is the lowest. Then fix. "
            "Design text the change makes untrue changes in the same branch: the tree's "
            "docs/design/ and status file; temper/docs/help/ with its help tests. Then run "
            "the task's own checks as any fabrig task (precheck --onto origin/main).\n")


def tasks(plan: Plan, events: Sequence[dict]) -> dict[str, Task]:
    """Return this draft's specless finding repairs in raise order; pure.

    A fix/none settlement or non-done foreman end creates a lasting task. Fold current
    sightings into its body, retain triage's reason, and append refusal sections and
    user answers through fab.fix (docs/design/qa.md, 2).
    """
    found = findings.findings(events)
    surveys = foremen(events)
    repairs = _repairs(events, surveys)
    answers, sections = fix.answers(events), fix.sections(events)
    reasons = {event.get("finding"): event["reason"] for event in events
               if event.get("ev") == "finding.triaged" and event.get("decision") == "path"
               and isinstance(event.get("finding"), str) and isinstance(event.get("reason"), str)}
    result = {}
    for identifier, finding in found.items():
        if finding.draft != plan.draft or identifier not in repairs:
            continue
        task_id = repair_id(finding)
        merged = [found[sighting] for sighting in finding.sightings if sighting in found]
        body = _body(finding, merged, reasons.get(identifier, finding.reason), repairs[identifier])
        for section in sections.get(task_id, ()):
            body += "\n" + section.rstrip("\n") + "\n"
        result[task_id] = fix.task(task_id, KIND, PART, body, answers.get(task_id, ()))
    return result
