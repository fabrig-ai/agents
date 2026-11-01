"""Pure triage timing, report decisions and backlog views (docs/design/qa.md, 2)."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections.abc import Mapping
from dataclasses import fields
from datetime import datetime, timedelta
from pathlib import Path

from fab import calls, channel, findings as qa, log, walks
from fab.plan import Plan, load_plan
from fab.sh import Failed

ROLE = "triage"  # the report-only director call
AT = 4  # new findings that start triage at once, as dispatch.ANSWER_AT
AFTER = 30  # minutes before triage or a failed call's retry, as dispatch.ANSWER_AFTER


def subject(draft: str) -> str:
    """The draft's batch triage subject (docs/design/qa.md, 2)."""
    return f"{draft}/triage"


def due(plan: Plan, events: list[dict], now: str) -> bool:
    """Whether new findings need a call, absent flight, an open ask or retry delay.

    Urgent findings run at once; others batch at AT or AFTER minutes since their
    walk ended or they became new again (docs/design/qa.md, 2, When).
    """
    new = {key: finding for key, finding in qa.findings(events).items()
           if finding.draft == plan.draft and finding.state == "new"}
    if not new:
        return False
    flight: set[str] = set()
    question = False
    last_end = None
    for position, event in enumerate(events):
        kind = event.get("ev")
        if (kind == "call.answered" and event.get("subject") == subject(plan.draft)
                and _strings(event, "ts subject call by question answer")):
            question = False
        if (event.get("role") != ROLE or event.get("subject") != subject(plan.draft)
                or not _strings(event, "ts call role subject")):
            continue
        if kind == "call.started":
            flight.add(event["call"])
        elif kind == "call.ended" and isinstance(event.get("outcome"), str):
            flight.discard(event["call"])
            last_end = position, event
            if event["outcome"] == "question":
                question = True
    if flight or question:
        return False
    since = _new_since(new, events)
    if last_end is not None:
        position, ended = last_end
        if (ended["outcome"] == "failed" and not _old_enough(ended["ts"], now)
                and not any(index > position for index, stamp in since.values())):
            return False
    return (any(finding.blocking or finding.verdict in ("fail", "void") for finding in new.values())
            or len(new) >= AT or any(_old_enough(stamp, now) for index, stamp in since.values()))


def _new_since(new: Mapping[str, qa.Finding], events: list[dict]) -> dict[str, tuple[int, str]]:
    """The log position and timestamp at which each currently new finding became new."""
    ends = {}
    for position, event in enumerate(events):
        if (event.get("ev") == "walk.ended" and _strings(event, "ts walk verdict reason report")
                and event["verdict"] in qa.VERDICTS and isinstance(event.get("findings"), list)
                and all(isinstance(identifier, str) for identifier in event["findings"])):
            ends.setdefault(event["walk"], (position, event["ts"]))
    since = {key: ends[finding.walk] for key, finding in new.items()}
    dispositions = {}
    subjects = {f"{finding.draft}/triage/{key}": key for key, finding in new.items()}
    for position, event in enumerate(events):
        kind = event.get("ev")
        if (kind == "finding.triaged" and _strings(event, "ts finding call decision owner reason question into")
                and event["decision"] in qa.DECISIONS):
            identifier = event["finding"]
            if identifier not in since or position <= ends[new[identifier].walk][0]:
                continue
            dispositions[identifier] = event["decision"]
            if event["decision"] == "again":
                since[identifier] = position, event["ts"]
        elif kind == "call.answered" and _strings(event, "ts subject call by question answer"):
            identifier = subjects.get(event["subject"])
            if identifier is not None and dispositions.get(identifier) == "user":
                since[identifier] = position, event["ts"]
                dispositions[identifier] = "new"
    return since


def _old_enough(stamp: str, now: str) -> bool:
    """Whether a parseable timestamp is at least AFTER minutes old."""
    try:
        return datetime.fromisoformat(now) - datetime.fromisoformat(stamp) >= timedelta(minutes=AFTER)
    except (TypeError, ValueError):
        return False


def decisions(plan: Plan, events: list[dict], reports: Mapping[str, str]) -> list[tuple[str, dict]]:
    """Records for unrecorded done triage calls whose reports are available.

    Apply valid lines in report order, once per finding per call; invalid lines
    leave it for another call. Prose alone gets a note (docs/design/qa.md, 2).
    """
    recorded = set()
    for event in events:
        key = "by" if event.get("ev") == "finding.merged" else "call"
        if (event.get("ev") in ("finding.triaged", "finding.merged", "note")
                and isinstance(event.get(key), str)):
            recorded.add(event[key])
    result = []
    history = list(events)
    found = qa.findings(history)
    for event in events:
        if (event.get("ev") != "call.ended" or event.get("role") != ROLE
                or event.get("subject") != subject(plan.draft) or event.get("outcome") != "done"
                or not _strings(event, "ts call role subject outcome")):
            continue
        call = event["call"]
        if call in recorded or call not in reports:
            continue
        accepted = set()
        for line in reports[call].splitlines():
            parsed = _line(line)
            if parsed is None:
                continue
            identifier, fields = parsed
            finding = found.get(identifier)
            if (identifier in accepted or finding is None or finding.draft != plan.draft
                    or finding.state not in ("new", "backlog")):
                continue
            kind = "finding.triaged"
            if fields["decision"] == "merge":
                destination = found.get(qa.target(found, fields["into"]))
                if (destination is None or destination.draft != plan.draft or destination.id == identifier
                        or (finding.again and qa.target(found, finding.again) == destination.id)):
                    continue
                if qa.mergeable(destination):
                    kind = "finding.merged"
                    fields = dict(into=fields["into"], by=call, reason=fields["reason"])
                else:
                    fields.update(decision="again", into=destination.id)
            if kind == "finding.triaged":
                fields["call"] = call
            fields["finding"] = identifier
            result.append((kind, fields))
            accepted.add(identifier)
            history.append(dict(ev=kind, ts=event["ts"], **fields))
            found = qa.findings(history)
        if not accepted:
            result.append(("note", dict(call=call, text=f"triage {call}: no decisions")))
        recorded.add(call)
    return result


def _line(line: str) -> tuple[str, dict] | None:
    """Parse a column-zero decision, optionally prefixed by '- ' or '* '."""
    match = re.fullmatch(r"(?:[-*] )?(finding-[0-9]+):[ \t]*(.*)", line.rstrip())
    if match is None:
        return None
    identifier, body = match.groups()
    choice = re.fullmatch(r"(path|brief|merge)[ \t]+([^\s:]+):[ \t]*(\S.*)", body)
    if choice is not None:
        decision, owner, text = choice.groups()
        if decision == "merge" and re.fullmatch(r"finding-[0-9]+", owner) is None:
            return None
    else:
        choice = re.fullmatch(r"(backlog|user|drop):[ \t]*(\S.*)", body)
        if choice is None:
            return None
        decision, text = choice.groups()
        owner = ""
    fields = dict(decision=decision, owner="", reason="", question="", into="")
    if decision in ("user", "brief"):
        fields.update(owner=owner, question=text)
    elif decision == "merge":
        fields.update(into=owner, reason=text)
    else:
        if decision == "path":
            reason, marker, action = text.rpartition("; user:")
            if marker:
                if not reason.strip() or not action.strip():
                    return None
                text = reason.rstrip()
                fields["question"] = action.strip()
            fields["owner"] = owner
        fields["reason"] = text
    return identifier, fields


def backlog_text(plan: Plan, events: list[dict]) -> str:
    """Render backlog findings in raise order, omitting promoted or merged entries.

    The file identifies its ladder and log source, carries each finding's context
    and triage reason, and ends in a newline (docs/design/qa.md, 2).
    """
    sections = [f"# {plan.draft} backlog",
                "fab writes this ladder's backlog from its log. Do not edit by hand."]
    for finding in qa.findings(events).values():
        if finding.draft != plan.draft or finding.state != "backlog":
            continue
        sections.append(f"## {finding.id}: {finding.title}")
        sections.append("\n".join((f"- Rung: {finding.rung}", f"- Walk: {finding.walk}",
                                  f"- Backend: {finding.backend}", f"- Commit: {finding.commit}",
                                  f"- Area: {finding.area}", f"- Severity: {finding.severity}",
                                  f"- Sightings: {', '.join(finding.sightings) or '(none)'}")))
        for title, text in (("Reproduction", finding.reproduction), ("Expected", finding.expected),
                            ("Seen", finding.seen), ("Triage reason", finding.reason)):
            sections.append(f"### {title}\n\n{text}")
    return "\n\n".join(sections).rstrip("\n") + "\n"


def render_key(text: str) -> str:
    """The UTF-8 render's sha256 hex for branch.ready (docs/design/qa.md, 2)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def backlog_held(plan: Plan, events: list[dict], render: str) -> dict | None:
    """Latest rejection after two of this render since the last clear or backlog landing.

    Ready records associate ladder/<draft>/backlog-<n> branches with renders;
    other drafts and renders cannot hold this one (docs/design/qa.md, 2).
    """
    branch_form = re.compile(rf"ladder/{re.escape(plan.draft)}/backlog-[1-9][0-9]*")
    ready = {}
    rejected = []
    for event in events:
        kind = event.get("ev")
        if (kind == "signal.cleared" and event.get("signal") == f"backlog:{plan.draft}"
                and _strings(event, "ts signal by text")):
            rejected.clear()
        branch = event.get("branch")
        if not isinstance(branch, str) or branch_form.fullmatch(branch) is None:
            continue
        if kind == "branch.ready" and _strings(event, "ts task branch tip render"):
            ready[branch] = event["render"]
        elif kind == "branch.landed" and _strings(event, "ts task branch tip main into"):
            rejected.clear()
        elif (kind == "branch.rejected" and _strings(event, "ts task branch tip step log")
              and ready.get(branch) == render):
            rejected.append(event)
    return rejected[-1] if len(rejected) >= 2 else None


def _strings(event: dict, fields: str) -> bool:
    """Whether the fields used from a log record are all strings."""
    return all(isinstance(event.get(field), str) for field in fields.split())


def brief(plan: Plan, events: list[dict], root: Path, plan_dir: Path,
          editions: Mapping[str, str], *, call_id: str, branch: str, report: str,
          now: str) -> str:
    """Compile role, facts, happy path, rungs, new findings and open merge targets.

    Include whole brief files only for rungs with new findings, and each finding's
    user answers. Refuse a plan without rungs or a ladder; raise on BRIEF_LIMIT
    overflow rather than trim context (docs/design/qa.md, 2, Its brief).
    """
    if not plan.rungs or plan.ladder is None:
        raise ValueError("triage requires a plan with rungs and a ladder")
    found = [finding for finding in qa.findings(events).values() if finding.draft == plan.draft]
    new = [finding for finding in found if finding.state == "new"]
    rung_text = [qa.line(state) for state in qa.rungs(plan, events, editions, now)]
    affected = {finding.rung for finding in new}
    for rung in plan.rungs.values():
        if rung.id in affected:
            for path in rung.brief:
                rung_text.append(f"## {rung.id}: {path}\n\n"
                                 + (plan_dir / path).read_text(encoding="utf-8"))
    new_text = []
    for finding in new:
        lines = [f"## {finding.id}: {finding.title}", "", "- Kind: qa"]
        for field in fields(finding):
            if field.name == "answers" or (field.name == "again" and not finding.again):
                continue
            value = getattr(finding, field.name)
            if isinstance(value, tuple):
                value = ", ".join(value) or "(none)"
            lines.append(f"- {field.name.capitalize()}: {value}")
        answers = channel.answers_text(f"{subject(plan.draft)}/{finding.id}", events)
        if answers:
            lines.extend(("", "### The user's answers", "", answers))
        new_text.append("\n".join(lines))
    open_text = []
    for finding in found:
        if finding.state in ("asked", "foreman", "deciding", "decided", "repairing", "landed", "backlog"):
            line = (f"- {finding.id}: {finding.state}; rung {finding.rung}; area {finding.area}; "
                    f"{finding.title}; sightings: {', '.join(finding.sightings) or '(none)'}")
            open_text.append(" ".join(line.splitlines()))
    return calls._brief([
        ("Role", calls.ROLES[ROLE].read_text(encoding="utf-8")),
        ("Call facts", calls._facts(call_id, branch, report)),
        ("The happy path", calls._cited_design(root, plan.ladder.happy_path)),
        ("The rungs", "\n\n".join(rung_text)),
        ("New findings", "\n\n".join(new_text)),
        ("Open findings", "\n".join(open_text)),
    ])


def main(argv: list[str]) -> int:
    """Compile or run fab call triage --plan PLAN_DIR [--brief-only].

    Use the plan's repository and trunk for a report-only call, print its outcome,
    and return 0 only for done or a printed brief; refusals and failed calls return
    1 (docs/design/qa.md, 2, Triage is a Claude call in the director's role).
    """
    parser = argparse.ArgumentParser(prog="fab call triage", description=main.__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--brief-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        directory = args.plan.resolve()
        plan = load_plan(directory / "plan.toml")
        if not plan.rungs or plan.ladder is None:
            raise ValueError("triage requires a plan with rungs and a ladder")
        checkout = calls.run(["git", "rev-parse", "--show-toplevel"], cwd=str(directory), check=True)
        root = Path(checkout.out.strip()).resolve()
        text = brief(plan, log.read(), root, directory, walks.editions(plan, directory, sh=calls.run),
                     call_id="(assigned at start)", branch="(assigned at start)",
                     report="(assigned at start)", now=log.now())
        if args.brief_only:
            print(text)
            return 0
        repo = log.home() / "repos/fabrig" if plan.repo == "fabrig" else root
        result = calls.start(ROLE, subject(plan.draft), repo, text, sh=calls.run,
                             base=plan.trunk, report_only=True)
        print(result["outcome"])
        return 0 if result["outcome"] == "done" else 1
    except (OSError, ValueError, Failed) as error:
        print(f"fab call triage: {error}", file=sys.stderr)
        return 1
