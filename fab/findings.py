"""QA findings and their repair states, folded in log order (docs/design/fab.md, 13.15)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

BACKENDS: dict[str, tuple[str, ...]] = {  # login kinds borrowed by each walk backend
    "chatgpt-forgejo": ("chatgpt",),
    "claude-forgejo": ("claude-box",),
    "chatgpt-github": ("chatgpt", "github"),
}
VERDICTS = ("pass", "fail", "void")  # a walk's outcomes
SEVERITIES = ("low", "medium", "high")  # the walker's assessment
DECISIONS = ("path", "backlog", "user", "brief", "drop", "again")  # triage decisions
STATES = ("new", "asked", "foreman", "deciding", "decided", "repairing", "landed",
          "fixed", "unfixed", "left", "backlog", "dropped", "merged")  # finding lifecycle
WALK_HOURS = 4  # the walk's wall cap plus an hour to report


@dataclass(frozen=True)
class Finding:
    """A raised QA finding and its current disposition (docs/design/fab.md, 13.15).

    into is the direct merge target; sightings are ids merged into this finding.
    question and action are open user requests; answers retain all replies in log order.
    landed is the main commit containing the repair, retained after fixed or unfixed.
    """

    id: str
    draft: str
    walk: str
    index: int
    rung: str
    backend: str
    commit: str
    edition: str
    title: str
    severity: str
    area: str
    blocking: bool
    reproduction: str
    expected: str
    seen: str
    evidence: tuple[str, ...]
    again: str
    raised: str
    verdict: str
    state: str = "new"
    into: str = ""
    owner: str = ""
    reason: str = ""
    question: str = ""
    action: str = ""
    answers: tuple[str, ...] = ()
    sightings: tuple[str, ...] = ()
    landed: str = ""

    @property
    def holds(self) -> bool:
        """Whether this finding holds its rung (docs/design/fab.md, 13.15).

        Blocking findings and failed or void walks hold while active or awaiting a
        user action. Left findings hold nothing, even if an action was requested.
        """
        return (self.blocking or self.verdict in ("fail", "void")) and self.state != "left" and (
            self.state in ("new", "asked", "foreman", "deciding", "decided", "repairing")
            or bool(self.action))


# Required string fields; the remaining typed fields are checked by _valid.
_FIELDS = {
    "finding.raised": "finding draft walk rung backend commit edition kind title severity area "
                      "reproduction expected seen again",
    "walk.ended": "walk verdict reason report",
    "finding.merged": "finding into by reason",
    "finding.triaged": "finding call decision owner reason question into",
    "finding.settled": "finding run verdict reason section",
    "call.answered": "subject call by question answer",
    "run.started": "run task kind",
    "run.ended": "run task outcome",
    "branch.landed": "task branch tip main into",
    "rung.passed": "draft rung walk edition commit",
    "signal.cleared": "signal by text",
}


def _strings(value: object) -> bool:
    """Whether value is a list of strings, including the empty list."""
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _valid(event: dict) -> bool:
    """Ignore malformed records; evidence alone may fall back to an empty tuple."""
    kind = event.get("ev")
    if not isinstance(kind, str) or kind not in _FIELDS or not isinstance(event.get("ts"), str):
        return False
    if not all(isinstance(event.get(key), str) for key in _FIELDS[kind].split()):
        return False
    if kind == "finding.raised":
        return (type(event.get("index")) is int and type(event.get("blocking")) is bool
                and "evidence" in event and event["kind"] == "qa"
                and event["backend"] in BACKENDS and event["severity"] in SEVERITIES)
    if kind == "walk.ended":
        return event["verdict"] in VERDICTS and _strings(event.get("findings"))
    if kind == "finding.triaged":
        return event["decision"] in DECISIONS
    if kind == "finding.settled":
        return event["verdict"] in ("fix", "none", "left")
    return True


def findings(events: Iterable[dict]) -> dict[str, Finding]:
    """Findings of ended walks, keyed by id in raise order; pure (docs/design/fab.md, 13.15).

    Only raises of ended walks participate, so interrupted intake has no visible
    findings or sightings. Intake merges retain their log positions; other changes
    start at walk.ended. Unknown events and malformed records are skipped. Every
    draft is included; readers filter by draft. Invalid evidence becomes ().
    """
    events = [event for event in events if _valid(event)]
    ended: dict[str, str] = {}
    for event in events:
        if event["ev"] == "walk.ended":
            ended.setdefault(event["walk"], event["verdict"])
    found: dict[str, Finding] = {}
    finished: set[str] = set()
    asks: dict[str, str] = {}
    foremen: dict[str, str] = {}
    for event in events:
        kind = event["ev"]
        if kind == "finding.raised":
            identifier, walk = event["finding"], event["walk"]
            if identifier not in found and walk in ended and walk not in finished:
                finding = _raised(event, ended[walk])
                found[identifier] = finding
                _again(found, finding.again)
            continue
        if kind == "finding.merged":
            _merge(found, event)
            continue
        if kind == "walk.ended":
            finished.add(event["walk"])
            continue
        if kind == "rung.passed":
            for identifier, finding in found.items():
                if (finding.walk in finished and finding.state == "landed"
                        and finding.draft == event["draft"] and finding.rung == event["rung"]):
                    found[identifier] = replace(finding, state="fixed")
            continue
        if kind == "call.answered":
            for identifier, finding in found.items():
                if (finding.walk not in finished
                        or event["subject"] != f"{finding.draft}/triage/{identifier}"):
                    continue
                found[identifier] = _answered(finding, event, asks.get(identifier, ""))
            continue
        if kind == "signal.cleared":
            identifier = event["signal"]
        elif kind in ("run.started", "run.ended", "branch.landed"):
            task = event["task"]
            identifier = task.removesuffix("/foreman").rsplit("/", 1)[-1]
        else:
            identifier = event["finding"]
        finding = found.get(identifier)
        if finding is None or finding.walk not in finished:
            continue
        _transition(finding, event, found, asks, foremen)
    return {identifier: finding for identifier, finding in found.items() if finding.walk in finished}


def _answered(finding: Finding, event: dict, decision: str) -> Finding:
    """Keep an answer, release its action and resolve an asked finding (docs/design/fab.md, 13.15)."""
    changes = {"answers": (*finding.answers, event["answer"]), "action": ""}
    if finding.state == "asked":
        brief = decision == "brief"
        changes.update(state="dropped" if brief else "new", question="")
        if brief:
            changes["reason"] = event["answer"]
    return replace(finding, **changes)


def _transition(finding: Finding, event: dict, found: dict[str, Finding],
                asks: dict[str, str], foremen: dict[str, str]) -> None:
    """Apply one validated event to a visible finding (docs/design/fab.md, 13.15).

    Update found in place, including recurrence targets; retain triage decisions
    in asks for answers and foreman run ids in foremen for matching completions.
    """
    identifier, kind = finding.id, event["ev"]
    if kind == "finding.triaged":
        decision = event["decision"]
        state = {"path": "foreman", "user": "asked", "brief": "asked",
                 "backlog": "backlog", "drop": "dropped", "again": "new"}[decision]
        found[identifier] = replace(
            finding, state=state, owner=event["owner"], reason=event["reason"],
            question=event["question"] if state == "asked" else "",
            action=event["question"] if decision == "path" else "",
            again=event["into"] if decision == "again" else finding.again)
        asks[identifier] = decision
        if decision == "again":
            _again(found, event["into"])
    elif kind == "finding.settled":
        if finding.state == "decided" and foremen.get(identifier) == event["run"]:
            left = event["verdict"] == "left"
            found[identifier] = replace(finding, state="left" if left else "repairing",
                                        reason=event["reason"], action="" if left else finding.action)
    elif kind == "signal.cleared":
        found[identifier] = replace(finding, state="dropped", reason=event["text"],
                                    question="", action="")
    else:
        task = f"{finding.draft}/{identifier}"
        if event["task"] == task + "/foreman":
            if kind == "run.started" and event["kind"] == "foreman" and finding.state == "foreman":
                foremen[identifier] = event["run"]
                found[identifier] = replace(finding, state="deciding")
            elif (kind == "run.ended" and finding.state == "deciding"
                  and foremen.get(identifier) == event["run"]):
                found[identifier] = replace(finding, state="decided" if event["outcome"] == "done"
                                            else "repairing")
        elif event["task"] == task and finding.state == "repairing":
            if kind == "branch.landed":
                found[identifier] = replace(finding, state="landed", landed=event["main"])
            elif kind == "run.started":
                found[identifier] = replace(finding, state="repairing")


def _raised(event: dict, verdict: str) -> Finding:
    """Publish a validated raise with its walk's verdict."""
    fields = {name: event[name] for name in (
        "draft", "walk", "index", "rung", "backend", "commit", "edition", "title", "severity",
        "area", "blocking", "reproduction", "expected", "seen", "again")}
    return Finding(id=event["finding"], **fields, raised=event["ts"], verdict=verdict,
                   evidence=tuple(event["evidence"]) if _strings(event["evidence"]) else ())


def _again(found: dict[str, Finding], identifier: str) -> None:
    """A recurrence after landing disproves the repair, including after a pass."""
    identifier = target(found, identifier)
    finding = found.get(identifier)
    if finding is not None and finding.state in ("landed", "fixed"):
        found[identifier] = replace(finding, state="unfixed")


def _merge(found: dict[str, Finding], event: dict) -> None:
    """Merge once into an open target, carrying earlier sightings with the source."""
    source = found.get(event["finding"])
    identifier = target(found, event["into"])
    destination = found.get(identifier)
    if (source is None or destination is None or source.id == identifier
            or source.state == "merged" or not mergeable(destination)
            or (source.again and target(found, source.again) == identifier)):
        return
    found[source.id] = replace(source, state="merged", into=event["into"],
                               reason=event["reason"], question="", action="")
    sightings = tuple(dict.fromkeys((*destination.sightings, *source.sightings, source.id)))
    found[identifier] = replace(destination, sightings=sightings)


def target(found: Mapping[str, Finding], identifier: str) -> str:
    """Follow direct merge targets; stop at a live, unknown or repeated id (docs/design/fab.md, 13.15).

    A cycle returns the last id reached before following an already visited id.
    """
    visited = {identifier}
    while (finding := found.get(identifier)) is not None and finding.state == "merged":
        if finding.into in visited:
            break
        identifier = finding.into
        visited.add(identifier)
    return identifier


def mergeable(finding: Finding) -> bool:
    """Whether a duplicate merges here rather than being filed again (docs/design/fab.md, 13.15)."""
    return finding.state in ("new", "asked", "backlog", "foreman", "deciding", "decided", "repairing")
