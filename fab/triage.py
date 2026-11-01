"""Pure triage timing, report decisions and backlog views (docs/design/fab.md, 13.15)."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from datetime import datetime, timedelta

from fab import findings as qa
from fab.plan import Plan

ROLE = "triage"  # the report-only director call
AT = 4  # new findings that start triage at once, as dispatch.ANSWER_AT
AFTER = 30  # minutes before triage or a failed call's retry, as dispatch.ANSWER_AFTER


def subject(draft: str) -> str:
    """The draft's batch triage subject (docs/design/fab.md, 13.15)."""
    return f"{draft}/triage"


def due(plan: Plan, events: list[dict], now: str) -> bool:
    """Whether new findings need a call, absent flight, an open ask or retry delay.

    Urgent findings run at once; others batch at AT or AFTER minutes since their
    walk ended or they became new again (docs/design/fab.md, 13.15, When).
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
    leave it for another call. Prose alone gets a note (docs/design/fab.md, 13.15).
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
    and triage reason, and ends in a newline (docs/design/fab.md, 13.15).
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
    """The UTF-8 render's sha256 hex for branch.ready (docs/design/fab.md, 13.15)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def backlog_held(plan: Plan, events: list[dict], render: str) -> dict | None:
    """Latest rejection after two of this render since the last clear or backlog landing.

    Ready records associate ladder/<draft>/backlog-<n> branches with renders;
    other drafts and renders cannot hold this one (docs/design/fab.md, 13.15).
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
