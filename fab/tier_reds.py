"""After-landing reds, their foremen and repairs (docs/design/fab-after-landing.md, 2; fab-calls.md, 2).

The dispatcher closes before opening, then acts on each plan's folded reds. Decisions
here use log order, including when timestamps tie. Only open_reds, close_reds, tasks,
start and settle act; their pure counterparts let callers decide without machine state.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from fab import atomic, foreman, land, log, run as runs
from fab.hosts import Host
from fab.plan import Plan, Task
from fab.sh import Failed, Runner, run, ssh

RED_RUNS = 2
KIND = "red"
OPENED = "red.opened"
SETTLED = "red.settled"
CLOSED = "red.closed"
TIERS_RUN = "tiers.run"
TIERS_RED = "tiers.red"
RECOVERED = "tiers.recovered"
ROLE = Path(__file__).resolve().parent / "roles" / "foreman-red.md"
STATES = ("foreman", "deciding", "decided", "repairing", "landed", "signal", "closed")
VERDICTS = ("fix", "left", "none")
SECTION_LINES = 30


@dataclass(frozen=True)
class Red:
    """One red.opened and its lifecycle. task is its repair id; repair says the task
    exists, started whether it ran before closing. A closed, never-started task drops.
    reason is the settlement's reason, signal_reason the page's, close_reason the close's.
    tasks contains suspect owners: task ids, or draft names for integration trunks.
    covered is the first fault-free tiers.run tip naming the landed repair (including
    rebased branches); empty until covered. hand_pushed lists suspects without fab owners.
    signal_ts is when it became a signal, empty until then and retained after closing.
    """

    id: str
    tip: str
    keys: tuple[str, ...]
    suspects: tuple[str, ...]
    tasks: tuple[str, ...]
    draft: str
    route: str
    at: str
    state: str
    since: str
    foreman: str | None = None
    report: str = ""
    verdict: str = ""
    reason: str = ""
    owner: str = ""
    section: str = ""
    signal_reason: str = ""
    close_reason: str = ""
    close_tip: str = ""
    repair: bool = False
    started: bool = False
    covered: str = ""
    signal_ts: str = ""
    _signal_at: int = field(default=-1, repr=False, compare=False)  # log position, for clears with tied ts

    @property
    def task(self) -> str:
        """The repair id, <draft>/red-<n>, or empty for an ownerless red."""
        return f"{self.draft}/{self.id}" if self.draft else ""

    @property
    def hand_pushed(self) -> tuple[str, ...]:
        """Suspect branches without a fab task or loaded integration trunk owner."""
        return _hand_pushed(self.suspects, self.tasks)


@dataclass(frozen=True)
class Group:
    """Unheld tiers.red records at one tip with one ordered suspect list, ready to open.
    records keeps the evidence in log order; keys and tasks keep first occurrences.
    commits and branches come from the last tiers.run at this tip, not tiers.red.
    """

    tip: str
    keys: tuple[str, ...]
    suspects: tuple[str, ...]
    tasks: tuple[str, ...]
    draft: str
    route: str
    reason: str
    records: tuple[dict, ...]
    commits: int | None = None
    branches: tuple[str, ...] = ()

    @property
    def hand_pushed(self) -> tuple[str, ...]:
        """Suspect branches without a fab task or loaded integration trunk owner."""
        return _hand_pushed(self.suspects, self.tasks)


def _hand_pushed(suspects: Sequence[str], tasks: Sequence[str]) -> tuple[str, ...]:
    """Branches not owned by the recorded suspect tasks or integration plans."""
    owned = set(tasks)
    return tuple(branch for branch in suspects if land.task_of(branch) not in owned
                 and not (branch.endswith("/integration")
                          and branch.removesuffix("/integration") in owned))


def reds(events: Iterable[dict]) -> list[Red]:
    """Every valid red.opened, in log order, including closed reds; pure.

    Initially foreman or signal (route). The first later run.started with kind foreman,
    red=id, tip=tip and task=<draft>/<red>/foreman makes deciding; its first run.ended
    makes decided if done, otherwise repairing (fallback, no settlement required).
    The first matching red.settled after a done end makes repairing for fix/none or
    signal for left, with reason `not the suspects': <reason>`. Settlement fields are
    retained. Task run.started marks started; branch.landed makes landed. The first
    fault-free tiers.run naming that task (via fab.land.task_of) records covered, its
    tip; covering-before-import also moves a repairing red to landed, since that run
    proves the repair is on main even before branch.landed is imported. That run or any
    later fault-free run listing a key makes signal,
    `unfixed: <task> landed, still red at <tip>`. A covering run that starves a key does
    not unfix it unless that key is listed red; coverage persists for later runs.
    red.closed is terminal and supplies close_reason/close_tip. since is the record's
    ts for each state transition; report is the foreman's run.ended report path, even
    when collected after closing.
    Missing required opening fields, non-string red/tip/draft/route, and
    keys/suspects/tasks other than lists of strings are skipped. Non-string red ids on
    settlements and tiers.run records with reds other than a list of strings are skipped
    too. A clear is decided by closures, not folded as closed until close_reds writes
    red.closed. No files are read.
    """
    found: dict[str, Red] = {}
    by_run, by_task, landed = {}, {}, set()
    for position, event in enumerate(events):
        kind, stamp = event.get("ev"), event.get("ts")
        if not isinstance(stamp, str) or not isinstance(kind, str):
            continue
        if (kind == TIERS_RUN and "reds" in event
                and (not isinstance(event["reds"], list)
                     or not all(isinstance(key, str) for key in event["reds"]))):
            continue
        if kind == OPENED and all(k in event for k in
                                  ("red", "tip", "keys", "suspects", "tasks", "draft", "route")):
            if (not all(isinstance(event[key], str) for key in ("red", "tip", "draft", "route"))
                    or not all(isinstance(event[key], list)
                               and all(isinstance(value, str) for value in event[key])
                               for key in ("keys", "suspects", "tasks"))):
                continue
            identifier = event["red"]
            if identifier not in found:
                state = "foreman" if event["route"] == "foreman" else "signal"
                red = Red(identifier, event["tip"], tuple(event["keys"]),
                          tuple(event["suspects"]), tuple(event["tasks"]),
                          event["draft"], event["route"], stamp, state, stamp,
                          signal_reason=event.get("reason", "") if state == "signal" else "",
                          signal_ts=stamp if state == "signal" else "",
                          _signal_at=position if state == "signal" else -1)
                found[identifier] = red
                if red.task:
                    by_task[red.task] = identifier
            continue
        if kind in (CLOSED, SETTLED):
            identifier = event.get("red")
        elif kind == "run.ended":
            identifier = by_run.get(event.get("run"))
        elif kind == "run.started":
            identifier = event.get("red") or by_task.get(event.get("task"))
        elif kind == "branch.landed":
            identifier = by_task.get(event.get("task"))
        elif kind == TIERS_RUN:
            identifier = None
        else:
            continue
        if kind == TIERS_RUN:
            named = {by_task[land.task_of(branch)] for branch in event.get("branches", ())
                     if land.task_of(branch) in by_task}
            affected = landed | named
        else:
            affected = (identifier,)
        for identifier in affected:
            red = found.get(identifier) if isinstance(identifier, str) else None
            if red is None or (red.state == "closed" and kind != "run.ended"):
                continue
            advanced = _advance(red, event)
            if advanced is red:
                continue
            if advanced.state == "signal" and red.state != "signal":
                advanced = replace(advanced, signal_ts=stamp, _signal_at=position)
            found[identifier] = advanced
            if advanced.foreman is not None:
                by_run[advanced.foreman] = identifier
            if advanced.state == "landed":
                landed.add(identifier)
            else:
                landed.discard(identifier)
    return list(found.values())


def _advance(red: Red, event: dict) -> Red:
    """Advance a red by one later record, without reading files."""
    kind, stamp = event["ev"], event["ts"]
    if red.state == "closed":
        if (kind == "run.ended" and red.foreman is not None
                and event.get("run") == red.foreman and not red.report):
            return replace(red, report=event.get("report", ""))
        return red
    if kind == CLOSED and event.get("red") == red.id and "reason" in event:
        return replace(red, state="closed", since=stamp, close_reason=event["reason"],
                       close_tip=event.get("tip", ""))
    if (kind == "run.started" and event.get("red") == red.id
            and event.get("tip") == red.tip and event.get("kind") == foreman.KIND
            and event.get("task") == foreman.task_field(red.task)
            and "run" in event and red.state == "foreman" and red.foreman is None):
        return replace(red, state="deciding", since=stamp, foreman=event["run"])
    if (kind == "run.ended" and red.foreman is not None and event.get("run") == red.foreman
            and "outcome" in event and red.state == "deciding"):
        done = event["outcome"] == "done"
        return replace(red, state="decided" if done else "repairing", since=stamp,
                       report=event.get("report", ""), repair=not done)
    if (kind == SETTLED and event.get("red") == red.id and event.get("run") == red.foreman
            and event.get("verdict") in VERDICTS and red.state == "decided"):
        left = event["verdict"] == "left"
        return replace(red, state="signal" if left else "repairing", since=stamp,
                       verdict=event["verdict"], reason=event.get("reason", ""),
                       owner=event.get("owner", ""), section=event.get("section", ""),
                       signal_reason="not the suspects': " + event.get("reason", "") if left else "",
                       repair=not left)
    if red.repair and kind == "run.started" and event.get("task") == red.task:
        return replace(red, started=True)
    if red.repair and kind == "branch.landed" and event.get("task") == red.task and red.state == "repairing":
        return replace(red, state="landed", since=stamp)
    if red.repair and red.state in ("repairing", "landed") and kind == TIERS_RUN and not event.get("faults"):
        if not red.covered and any(land.task_of(branch) == red.task
                                   for branch in event.get("branches", ())):
            red = replace(red, covered=event.get("tip", ""))
            if red.state == "repairing":
                red = replace(red, state="landed", since=stamp)
        if red.covered and set(red.keys).intersection(event.get("reds", ())):
            return replace(red, state="signal", since=stamp,
                           signal_reason=f"unfixed: {red.task} landed, still red at {event.get('tip', '')}")
    return red


def closures(events: Sequence[dict], *, folded: Sequence[Red] | None = None) -> list[tuple[str, str, str]]:
    """Pending (red id, reason, tip) closes, in opening order; pure.

    Only records later than that red.opened count. A key closes once on tiers.recovered
    or a tiers.run with a reds list, no faults, no wall_starved, explicit starved=0 and
    unobserved=0, and the key absent. All keys must close. The last key supplies
    reason/tip, except all recovered is recovered. A signal.cleared naming this red
    while it is a signal closes all keys with cleared and empty tip. Already red.closed
    reds are omitted. Log positions, not ts, order it. folded may be reds(events), reused
    for this same events snapshot, to avoid folding again. Malformed red.opened red ids,
    tiers.recovered keys, and tiers.run reds lists are skipped.
    """
    folded = reds(events) if folded is None else folded
    opened = {red.id: red for red in folded if red.state != "closed"}
    remaining, by_key, result = {}, {}, {}
    for position, event in enumerate(events):
        kind = event.get("ev")
        if not isinstance(event.get("ts"), str):
            continue
        identifier = event.get("red")
        if (kind == OPENED and isinstance(identifier, str)
                and identifier in opened and identifier not in remaining
                and all(k in event for k in ("tip", "keys", "suspects", "tasks", "draft", "route"))):
            remaining[identifier] = set(opened[identifier].keys)
            for key in remaining[identifier]:
                by_key.setdefault(key, set()).add(identifier)
        elif kind == RECOVERED:
            key = event.get("key")
            if not isinstance(key, str):
                continue
            for identifier in by_key.pop(key, ()):
                remaining[identifier].discard(key)
                if not remaining[identifier] and identifier not in result:
                    result[identifier] = (identifier, "recovered", event.get("tip", ""))
        elif (kind == TIERS_RUN and isinstance(event.get("reds"), list)
              and all(isinstance(key, str) for key in event["reds"]) and not event.get("faults")
              and not event.get("wall_starved") and event.get("starved") == 0
              and event.get("unobserved") == 0):
            absent = by_key.keys() - set(event["reds"])
            for key in absent:
                for identifier in by_key.pop(key):
                    remaining[identifier].discard(key)
                    if not remaining[identifier] and identifier not in result:
                        result[identifier] = (identifier, "absent", event.get("tip", ""))
        elif kind == "signal.cleared":
            identifier = event.get("signal")
            red = opened.get(identifier)
            if (red is not None and identifier in remaining and identifier not in result
                    and 0 <= red._signal_at < position):
                result[identifier] = (identifier, "cleared", "")
                for key in remaining[identifier]:
                    by_key[key].discard(identifier)
                remaining[identifier].clear()
    return [result[red.id] for red in folded if red.id in result]


def close_reds(events: Sequence[dict], *, folded: Sequence[Red] | None = None,
               log_path: Path | None = None) -> list[dict]:
    """Log red.closed for each closures(events) result and return those appended records.
    Caller supplies the current log and optional reds(events) snapshot as folded, then
    includes these records before opening reds.
    """
    return [log.append(CLOSED, path=log_path, red=identifier, reason=reason, tip=tip)
            for identifier, reason, tip in closures(events, folded=folded)]


def owners(plans: Iterable[tuple[Plan, Mapping[str, Task]]], events: Sequence[dict], *,
           folded: Sequence[Red] | None = None) -> dict[str, str]:
    """Map suspect branches to loaded fab owners, without reading files.

    plans holds (Plan, tasks) pairs; retired plans are ignored. Include each plan's
    log-derived red tasks even if the caller has not joined them yet. fab.land.task_of
    resolves branch suffixes (-r<n>); a loaded integration trunk owns its draft name.
    Return branch -> owner (a task id, or the draft for a trunk), covering canonical
    task branches, trunks and branches named by tiers.red. Unknown branches are absent,
    hence hand-pushed. Call openings with this mapping. folded may be reds(events),
    reused for this same events snapshot, to avoid folding again.
    """
    folded = reds(events) if folded is None else folded
    known, trunks = set(), {}
    for plan, plan_tasks in plans:
        if plan.retired:
            continue
        known.update(plan_tasks)
        known.update(red.task for red in folded if red.draft == plan.draft and red.repair
                     and (red.state != "closed" or red.started))
        if plan.landing == "integration":
            trunks[plan.trunk] = plan.draft
    branches = set(known) | set(trunks)
    for event in events:
        if event.get("ev") == TIERS_RED:
            branches.update(event.get("branches", ()))
    return {branch: trunks[branch] if branch in trunks else land.task_of(branch)
            for branch in sorted(branches)
            if branch in trunks or land.task_of(branch) in known}


def openings(events: Sequence[dict], owners: Mapping[str, str], *,
             folded: Sequence[Red] | None = None) -> list[Group]:
    """Groups to open from tiers.red, in first-record order; pure.

    The newest tiers.run must contain reds; keep only keys it still lists. Never reuse
    an opened (tip, key), even after closing, nor a key in any open red. Group by tip
    and ordered branches, preserving record order and unique keys. tasks is the fab
    owners in suspect order; draft is the last fab owner's draft (or the trunk's draft).
    Only the last tiers.red for each key is eligible: an earlier red passed before the
    next red of that key. Each Group carries commits and branches from the last tiers.run
    with its tip, for the evidence's unbranched commit count. No fab owner routes to
    signal, with `no suspects` or `no fab task among the suspects`. folded may be
    reds(events), reused for this same events snapshot, to avoid folding again.
    """
    newest = next((event for event in reversed(events) if event.get("ev") == TIERS_RUN), {})
    standing = set(newest.get("reds", ()))
    folded = reds(events) if folded is None else folded
    held = {(red.tip, key) for red in folded for key in red.keys}
    busy = {key for red in folded if red.state != "closed" for key in red.keys}
    grouped, last_red, last_run = {}, {}, {}
    for position, event in enumerate(events):
        if event.get("ev") == TIERS_RED and all(k in event for k in ("tip", "key")):
            last_red[event["key"]] = position
        elif event.get("ev") == TIERS_RUN and "tip" in event:
            last_run[event["tip"]] = event
    for position, event in enumerate(events):
        if event.get("ev") != TIERS_RED or last_red.get(event.get("key")) != position:
            continue
        tip, key = event["tip"], event["key"]
        if key not in standing or (tip, key) in held or key in busy:
            continue
        suspects = tuple(event.get("branches", ()))
        grouped.setdefault((tip, suspects), []).append(event)
        held.add((tip, key))
        busy.add(key)
    result = []
    for (tip, suspects), records in grouped.items():
        assigned = tuple(dict.fromkeys(owners[branch] for branch in suspects if branch in owners))
        last = next((owners[branch] for branch in reversed(suspects) if branch in owners), "")
        draft = last.split("/", 1)[0]
        reason = "" if assigned else "no fab task among the suspects" if suspects else "no suspects"
        checked = last_run.get(tip, {})
        result.append(Group(tip, tuple(record["key"] for record in records), suspects, assigned,
                            draft, "foreman" if assigned else "signal", reason, tuple(records),
                            checked.get("commits") if type(checked.get("commits")) is int else None,
                            tuple(checked.get("branches", ()))))
    return result


def evidence_path(red_id: str) -> Path:
    """The dispatcher-local evidence file, FAB_HOME/reds/<red_id>.md."""
    return log.home() / "reds" / f"{red_id}.md"


def evidence(group: Group, *, red_id: str, machine: str, owners: Mapping[str, str],
             reruns: Mapping[str, str]) -> str:
    """Render evidence without I/O: tip, suspects and owners, unbranched commit count,
    first 20 reds with machine:log and machine:rerun, then the first three rerun tails
    in text fences (last 40 lines). reruns maps remote paths to text or unreadable markers.
    Count unbranched commits as max(0, group.commits - len(group.branches)), from the
    last tiers.run at the group's tip; unknown only when that run has no commits field.
    Mark hand-pushed suspects and name trunk owners as `the trunk of plan <draft>`.
    Missing tails carry a marker.
    """
    lines = [f"# After-landing red {red_id}", "", f"- Tip: `{group.tip}` (main)", "", "## Suspects", ""]
    for branch in group.suspects:
        owner = owners.get(branch, "")
        label = ("hand-pushed" if branch in group.hand_pushed else
                 f"the trunk of plan {owner}" if branch == f"{owner}/integration" else owner)
        lines.append(f"- {branch}: {label}")
    count = (str(max(0, group.commits - len(group.branches))) if group.commits is not None
             else "unknown (commit count not recorded)")
    lines += [f"- Commits with no branch: {count}", "", "## Reds", ""]
    for record in group.records[:20]:
        lines += [f"- {record.get('profile', '')} {record.get('binary', '')} {record.get('test', '')} "
                  f"({record.get('state', '')}): {record.get('error', '')}",
                  f"  {machine}:{record.get('log', '')}", f"  {machine}:{record.get('rerun', '')}"]
    if len(group.records) > 20:
        lines += [f"- {len(group.records) - 20} more reds"]
    for record in group.records[:3]:
        path = record.get("rerun", "")
        text = reruns.get(path, "(log unreadable: no rerun path)")
        lines += ["", f"### {machine}:{path}", "", "```text", *text.splitlines()[-40:], "```"]
    return "\n".join(lines) + "\n"


def open_reds(events: Sequence[dict], owners: Mapping[str, str], host: Host, *,
              sh: Runner = run, log_path: Path | None = None,
              folded: Sequence[Red] | None = None) -> list[dict]:
    """Write evidence, then log red.opened for openings(events, owners); return successes.

    host is the after-landing machine. Read only the first three reds' rerun paths over
    ssh (`tail -n 40 -- <path>`), once per path per group; command failures become
    `(log unreadable: <why>)`. Use fab.atomic for FAB_HOME/reds/red-<n>.md, n one more
    than red.opened records in events, incrementing only on success. An OSError or
    UnicodeError writing evidence logs a note and opens nothing for that group; a later
    tick retries. The dispatcher must be the sole writer and pass its current events;
    folded, when supplied, must be reds(events) for that same snapshot.
    """
    number = sum(event.get("ev") == OPENED for event in events)
    opened = []
    for group in openings(events, owners, folded=folded):
        identifier = f"red-{number + 1}"
        tails = {}
        for record in group.records[:3]:
            path = record.get("rerun", "")
            if not path or path in tails:
                continue
            try:
                result = sh(ssh(host.ssh, ["tail", "-n", "40", "--", path]))
                why = (result.err or result.out).strip() or f"exit {result.code}"
                tails[path] = result.out if result.ok else f"(log unreadable: {why})"
            except (OSError, UnicodeError, Failed) as error:
                tails[path] = f"(log unreadable: {error})"
        try:
            atomic.write(evidence_path(identifier), evidence(group, red_id=identifier,
                         machine=host.name, owners=owners, reruns=tails))
        except (OSError, UnicodeError) as error:
            log.append("note", path=log_path, text=f"{identifier}: evidence write failed: {error}")
            continue
        opened.append(log.append(OPENED, path=log_path, red=identifier, tip=group.tip,
                                 keys=group.keys, suspects=group.suspects, tasks=group.tasks,
                                 draft=group.draft, route=group.route, reason=group.reason))
        number += 1
    return opened


def repair_tasks(plan: Plan, events: Sequence[dict], evidence_texts: Mapping[str, str], *,
                 folded: Sequence[Red] | None = None) -> dict[str, Task]:
    """Pure red tasks for plan, in opening order; evidence_texts maps red ids to evidence.

    A fix/none settlement or non-done foreman end creates a task. Closing before the
    first task run drops it; a started task stays even after closure or an unfixed signal.
    kind red, part after-landing, repo fabrig, no needs, files **, high, 20 minutes,
    no path. Quote evidence, owner and section, then fab-after-landing.md 2's acceptance. Append
    question.answered answers under ## Answers, in log order, scanning events once for
    all answers. Missing evidence is marked. folded may be reds(events), reused for
    this same events snapshot, to avoid folding again.
    """
    folded = reds(events) if folded is None else folded
    answers, sections = {}, {}
    for event in events:
        if event.get("ev") == "question.answered" and "task" in event and event.get("answer"):
            answers.setdefault(event["task"], []).append(event["answer"])
        elif event.get("ev") == "refusal.settled" and event.get("verdict") == "fix" and event.get("section"):
            sections.setdefault(event.get("task"), []).append(event["section"])
    result = {}
    for red in folded:
        if red.draft != plan.draft or not red.repair or (red.state == "closed" and not red.started):
            continue
        body = (f"# Repair a red after landing ({red.id})\n\n- Tip: `{red.tip}` (main)\n"
                + "".join(f"- Suspect: {branch}\n" for branch in red.suspects)
                + (f"- Owner: {red.owner}\n" if red.owner else "")
                + "\n## Evidence\n\n" + evidence_texts.get(red.id, "(evidence unreadable: not supplied)").rstrip("\n")
                + ("\n\n" + red.section.rstrip("\n") if red.section else "")
                + "\n\n## Acceptance\n\n"
                "Reproduce first, in the lowest tier that shows it: a unit test in the default "
                "profile when possible, failing on main before the change; otherwise run the red "
                "tests alone in their profile, through heavy. Then fix. The reproduction and "
                "every red test must pass with the change, then run the task's own checks as any "
                "fabrig task (precheck --onto origin/main). A red of a live pair cannot be "
                "reproduced without logins: use the foreman's section as the guide and the next "
                "after-landing run as the check.\n")
        for section in sections.get(red.task, ()):
            body += "\n" + section.rstrip("\n") + "\n"
        if answers.get(red.task):
            body += "\n## Answers\n\n" + "\n".join(f"- {answer}" for answer in answers[red.task]) + "\n"
        result[red.task] = Task(red.task, "after-landing", KIND, "fabrig", (), ("**",), "high", 20, body, "")
    return result


def _read_evidence(identifier: str) -> str:
    """Read a local evidence file or retain its failure as evidence."""
    try:
        return evidence_path(identifier).read_text()
    except (OSError, UnicodeError) as error:
        return f"(evidence unreadable: {error})"


def tasks(plan: Plan, events: Sequence[dict], *, folded: Sequence[Red] | None = None) -> dict[str, Task]:
    """Reading variant of repair_tasks: read FAB_HOME/reds/<red>.md for this plan's reds,
    quoting `(evidence unreadable: <why>)` on OSError/UnicodeError. Return only red tasks;
    caller joins these to loaded tasks and integration.with_repairs' result. folded may
    be reds(events), reused for this same events snapshot, to avoid folding again.
    """
    folded = reds(events) if folded is None else folded
    texts = {red.id: _read_evidence(red.id) for red in folded
             if red.draft == plan.draft and red.repair}
    return repair_tasks(plan, events, texts, folded=folded)


def brief(red: Red, *, run_id: str, report: str, evidence: str,
          plan_tasks: Mapping[str, Task], specs: Mapping[str, str], role: str) -> str:
    """Pure foreman brief: role, # The red, # The evidence, # The suspects' specs.

    The red section names run, red and tip on main, each suspect as task + spec path,
    trunk of plan, or hand-pushed, the report path and the read-only checkout. specs
    maps task ids to whole specs supplied by the caller. Quote direct suspects newest
    first, at most five whole (rest by id); a trunk lists its plan's tasks and files.
    Evidence is quoted verbatim, including an unreadable marker supplied by the caller.
    plan_tasks must include tasks of all loaded suspect plans, including red repairs.
    red.hand_pushed supplies the hand-pushed branches; specless tasks say `(no spec)`.
    """
    facts = [f"- Run: {run_id}", f"- Red: {red.id} at `{red.tip}` on main"]
    quoted, seen, whole = [], set(), 0
    for branch in red.suspects:
        task_id = land.task_of(branch)
        if branch in red.hand_pushed:
            facts.append(f"- {branch}: hand-pushed, no fab task")
        elif branch.endswith("/integration") and branch.removesuffix("/integration") in red.tasks:
            facts.append(f"- {branch}: the trunk of plan {branch.removesuffix('/integration')}")
        elif task_id in red.tasks and task_id in plan_tasks:
            path = plan_tasks[task_id].path
            spec = f"spec `{path}`" if path else "(no spec)"
            facts.append(f"- {branch}: task {task_id}, {spec}")
        else:
            facts.append(f"- {branch}: hand-pushed, no fab task")
    for branch in reversed(red.suspects):
        task_id = land.task_of(branch)
        draft = branch.removesuffix("/integration") if branch.endswith("/integration") else ""
        if draft and draft in red.tasks:
            quoted.append(f"## Trunk {draft}\n\n" + "\n".join(
                f"- {task.id}: {', '.join(task.files) or '(no files named)'}"
                for task in plan_tasks.values() if task.draft == draft))
        elif task_id in red.tasks and task_id in plan_tasks and task_id not in seen:
            seen.add(task_id)
            text = "\n\n" + specs.get(task_id, plan_tasks[task_id].body) if whole < 5 else ""
            quoted.append(f"## {task_id}" + text)
            whole += 1
    facts += [f"- Report: write it to `{report}`", f"Your checkout is fabrig at {red.tip}, read-only."]
    return "\n\n".join([role.rstrip("\n"), "# The red\n\n" + "\n".join(facts),
                          "# The evidence\n\n" + evidence.rstrip("\n"),
                          "# The suspects' specs\n\n" + "\n\n".join(quoted)]).rstrip("\n") + "\n"


def start(red: Red, host: Host, events: Sequence[dict], *, plan_tasks: Mapping[str, Task],
          specs: Mapping[str, str] | None = None, sh: Runner = run,
          log_path: Path | None = None) -> str:
    """Launch this red's once-only foreman on the caller-selected builder; return run id.

    Caller selects state foreman and the builder with most free places, even at none.
    next_run(foreman.task_field(red.task), events) numbers the run. Read role and local
    evidence (unreadable marker on failure); unless specs was supplied, read direct
    suspect specs from plan_tasks, using body for specless tasks. A spec/role read error
    propagates before launch. launch_detached(host, id, 'fabrig', red.tip) uses task
    <red.task>/foreman, kind foreman.KIND, effort foreman.EFFORT, branch red.task,
    base red.tip and extra run.started fields red=red.id, tip=red.tip. The brief's report
    path is runs.remote_home(host)/runs/<id>/report.md. collect handles its end as usual.
    """
    run_id = runs.next_run(foreman.task_field(red.task), events)
    if specs is None:
        specs = {task_id: Path(task.path).read_text() if task.path else task.body
                 for task_id, task in plan_tasks.items() if task_id in red.tasks}
    report = str(Path(runs.remote_home(host)) / "runs" / run_id / "report.md")
    text = brief(red, run_id=run_id, report=report, evidence=_read_evidence(red.id),
                 plan_tasks=plan_tasks, specs=specs, role=ROLE.read_text())
    return runs.launch_detached(host, run_id, "fabrig", red.tip, sh=sh, log_path=log_path,
                                task=foreman.task_field(red.task), kind=foreman.KIND,
                                branch=red.task, base=red.tip, brief=text, effort=foreman.EFFORT,
                                red=red.id, tip=red.tip)


def remedy(red: Red, report: str, *, plan_tasks: Mapping[str, Task] | None = None,
           day: str | None = None) -> tuple[str, str, str, str]:
    """Pure (verdict, reason, owner, section) from a foreman report; never raises for form.

    First nonblank line must match Done: fix: <line> or Done: retry: <line> (spaces
    around colons allowed, nonempty reason). retry becomes left; other forms give none,
    `no verdict: <first line, at most 120 chars>`. fix keeps the next 30 right-stripped
    lines, excluding an optional Owner: line immediately after the first. Accept owner
    only if it names a fab suspect task or a plan_tasks task of a suspect trunk. All
    other owners become empty and their Owner line is omitted. Section is ## Repair
    (<day>, after landing <red.id>, foreman <red.foreman>), blank line, reason and lines,
    trailing blanks removed, newline. day defaults to red.since's date (no clock read).
    left/none have empty owner and section. Supply all loaded tasks to validate trunks.
    """
    lines = report.splitlines()
    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    head = lines[first].strip() if first is not None else ""
    match = re.fullmatch(r"Done\s*:\s*(fix|retry)\s*:\s*(.+)", head)
    if match is None or not match[2].strip():
        return "none", "no verdict: " + head[:120], "", ""
    reason = match[2].strip()
    if match[1] == "retry":
        return "left", reason, "", ""
    rest, owner = lines[first + 1:], ""
    if rest and rest[0].strip().startswith("Owner:"):
        candidate = rest.pop(0).strip().removeprefix("Owner:").strip()
        trunk_task = (plan_tasks or {}).get(candidate)
        if (candidate in red.tasks and "/" in candidate) or (trunk_task is not None
                and trunk_task.draft in red.tasks and f"{trunk_task.draft}/integration" in red.suspects):
            owner = candidate
    kept = [reason, *(line.rstrip() for line in rest[:SECTION_LINES])]
    while not kept[-1]:
        kept.pop()
    section = (f"## Repair ({day or red.since[:10]}, after landing {red.id}, foreman {red.foreman})"
               + "\n\n" + "\n".join(kept) + "\n")
    return "fix", reason, owner, section


def settle(red: Red, report: str, *, plan_tasks: Mapping[str, Task] | None = None,
           log_path: Path | None = None) -> dict:
    """Log remedy's four fields as red.settled, with red id and foreman run; return it.
    Caller supplies a currently decided red and report, the text of the file at
    red.report. Day and timestamp use log.now together. No spec is edited; the section
    belongs to the red task body.
    """
    stamp = log.now()
    verdict, reason, owner, section = remedy(red, report, plan_tasks=plan_tasks, day=stamp[:10])
    return log.append(SETTLED, path=log_path, ts=stamp, red=red.id, run=red.foreman,
                      verdict=verdict, reason=reason, owner=owner, section=section)
