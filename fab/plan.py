"""Plans and task specs, read from a draft's `docs/plan/<draft>/` (docs/design/fab.md, 4)."""

from __future__ import annotations

import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from fab import log

MODES = ("feature", "migration", "fix", "probe", "direct")
KINDS = ("feature", "interface", "migration", "repair", "rebase", "docs")
EFFORTS = ("medium", "high")
RESERVED = ("cut", "retire", "review")  # call subjects `<draft>/<name>` (fab.designer); not part ids


class PlanError(ValueError):
    """A plan or task spec that does not parse or does not hold together; the message names the file."""


@dataclass(frozen=True)
class Part:
    id: str
    title: str
    mode: str
    needs: tuple[str, ...]
    design: str
    done: bool = False  # built without task specs (by hand); counts as landed for its readers
    contract: bool = False  # a shared contract: the designer's contract call designs it (13.3)
    needs_landed: tuple[str, ...] = ()


@dataclass(frozen=True)
class Question:
    """A question of the user's from the cut (budgets, machines, what is hard to reverse)."""

    id: str  # unique in the plan
    text: str
    parts: tuple[str, ...]  # parts not designed until it is answered
    answer: str = ""  # the user's answer, written into plan.toml; empty while open


@dataclass(frozen=True)
class Slice:
    id: int
    story: str
    parts: tuple[str, ...]
    walk: bool


@dataclass(frozen=True)
class Plan:
    draft: str
    repo: str
    sources: tuple[str, ...]
    low: float
    high: float
    parts: dict[str, Part]
    slices: tuple[Slice, ...]
    retired: bool = False  # set by the retire call; the tick skips a retired plan
    questions: tuple[Question, ...] = ()


@dataclass(frozen=True)
class Task:
    """A task spec. `id` and every entry of `needs` are full ids, `<draft>/<task>`."""

    id: str
    part: str
    kind: str
    repo: str
    needs: tuple[str, ...]
    files: tuple[str, ...]
    effort: str
    minutes: int
    body: str
    path: str
    consolidation: bool = False  # written by a structure review; heads the buffer (13.10)

    @property
    def draft(self) -> str:
        return self.id.split("/", 1)[0]

    @property
    def name(self) -> str:
        return self.id.split("/", 1)[1]


def load(plan_dir: Path) -> tuple[Plan, dict[str, Task]]:
    """Read plan.toml and tasks/; raise PlanError naming plan_dir and every problem if unsound."""
    plan = load_plan(plan_dir / "plan.toml")
    tasks = load_tasks(plan_dir / "tasks", plan.draft, plan.repo)
    tasks = checked_tasks(plan, tasks, log.read())
    issues = problems(plan, tasks)
    if issues:
        raise PlanError(f"{plan_dir}: " + "\n".join(issues))
    return plan, tasks


def load_plan(path: Path) -> Plan:
    """Read plan.toml: required keys draft, repo, parts; defaults sources=(), buffer low=1.0 high=2.0,
    retired=false. A part's contract defaults to false and needs_landed to ().
    Each `[[question]]` table requires id, text and parts (strings) and defaults answer="".

    Raises PlanError for a missing key, a wrong type, an unknown mode, or a part id used twice.
    """
    def value(table, key, expected, default=None, *, required=False):
        if key not in table:
            if required:
                raise PlanError(f"{path}: missing {key}")
            return default
        result = table[key]
        if type(result) not in expected:
            raise PlanError(f"{path}: {key} has the wrong type")
        return result

    def strings(table, key, default=(), *, required=False):
        items = value(table, key, (list,), default, required=required)
        if any(not isinstance(item, str) for item in items):
            raise PlanError(f"{path}: {key} must contain strings")
        return tuple(items)

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise PlanError(f"{path}: {error}") from error
    draft = value(data, "draft", (str,), required=True)
    repo = value(data, "repo", (str,), required=True)
    sources = strings(data, "sources")
    buffer = value(data, "buffer", (dict,), {})
    low = value(buffer, "low", (int, float), 1.0)
    high = value(buffer, "high", (int, float), 2.0)
    parts, slices, questions = _plan_tables(data, path, value, strings)
    return Plan(draft, repo, sources, float(low), float(high), parts, slices,
                value(data, "retired", (bool,), False), questions)


def _plan_tables(data, path, value, strings):
    """Read the plan's ordered tables with load_plan's field checks."""
    parts = {}
    for item in value(data, "part", (list,), required=True):
        if not isinstance(item, dict):
            raise PlanError(f"{path}: part must be a table")
        part = Part(value(item, "id", (str,), required=True),
                    value(item, "title", (str,), required=True),
                    value(item, "mode", (str,), required=True),
                    strings(item, "needs", required=True),
                    value(item, "design", (str,), required=True),
                    value(item, "done", (bool,), False),
                    contract=value(item, "contract", (bool,), False),
                    needs_landed=strings(item, "needs_landed"))
        if part.mode not in MODES:
            raise PlanError(f"{path}: part {part.id} has unknown mode {part.mode!r}")
        if part.mode == "direct" and part.contract:
            raise PlanError(f"{path}: part {part.id} is direct and cannot be a contract")
        if part.id in parts:
            raise PlanError(f"{path}: duplicate part {part.id}")
        parts[part.id] = part
    slices = []
    for item in value(data, "slice", (list,), []):
        if not isinstance(item, dict):
            raise PlanError(f"{path}: slice must be a table")
        slices.append(Slice(value(item, "id", (int,), required=True),
                            value(item, "story", (str,), required=True),
                            strings(item, "parts", required=True),
                            value(item, "walk", (bool,), required=True)))
    questions = []
    for item in value(data, "question", (list,), []):
        if not isinstance(item, dict):
            raise PlanError(f"{path}: question must be a table")
        questions.append(Question(value(item, "id", (str,), required=True),
                                  value(item, "text", (str,), required=True),
                                  strings(item, "parts", required=True),
                                  value(item, "answer", (str,), "")))
    return parts, tuple(slices), tuple(questions)


def parse_task(text: str, path: str, draft: str, default_repo: str) -> Task:
    """Parse a spec: a `+++` line, TOML, a `+++` line, then the Markdown body (kept verbatim).

    Required: id, part, kind; defaults: repo=default_repo, needs=(), files=(), effort="high",
    minutes=25, consolidation=false. Short ids in `id` and `needs` become full ids.
    Raises PlanError naming path for a missing header, a bad value (unknown kind or effort,
    minutes not a positive int).
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "+++":
        raise PlanError(f"{path}: missing +++ header")
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip("\r\n") == "+++"), None)
    if end is None:
        raise PlanError(f"{path}: missing closing +++ header line")
    try:
        data = tomllib.loads("".join(lines[1:end]))
    except tomllib.TOMLDecodeError as error:
        raise PlanError(f"{path}: {error}") from error

    def value(key, expected, default=None, *, required=False):
        if key not in data:
            if required:
                raise PlanError(f"{path}: missing {key}")
            return default
        result = data[key]
        if type(result) is not expected:
            raise PlanError(f"{path}: {key} has the wrong type")
        return result

    def strings(key):
        items = value(key, list, ())
        if any(not isinstance(item, str) for item in items):
            raise PlanError(f"{path}: {key} must contain strings")
        return tuple(items)

    def full(identifier):
        return identifier if "/" in identifier else f"{draft}/{identifier}"

    identifier = value("id", str, required=True)
    part = value("part", str, required=True)
    kind = value("kind", str, required=True)
    repo = value("repo", str, default_repo)
    needs = strings("needs")
    files = strings("files")
    effort = value("effort", str, "high")
    minutes = value("minutes", int, 25)
    if kind not in KINDS:
        raise PlanError(f"{path}: unknown kind {kind!r}")
    if effort not in EFFORTS:
        raise PlanError(f"{path}: unknown effort {effort!r}")
    if minutes <= 0:
        raise PlanError(f"{path}: minutes must be a positive int")
    return Task(full(identifier), part, kind, repo, tuple(map(full, needs)), files,
                effort, minutes, "".join(lines[end + 1:]), path,
                consolidation=value("consolidation", bool, False))


def load_tasks(directory: Path, draft: str, default_repo: str) -> dict[str, Task]:
    """Every `*.md` in directory (sorted by name), keyed by full id; a duplicate id is a PlanError."""
    tasks = {}
    for path in sorted(directory.glob("*.md")):
        try:
            with path.open(encoding="utf-8", newline="") as source:
                task = parse_task(source.read(), str(path), draft, default_repo)
        except (OSError, UnicodeError) as error:
            raise PlanError(f"{path}: {error}") from error
        if task.id in tasks:
            raise PlanError(f"{path}: duplicate task {task.id} (also in {tasks[task.id].path})")
        tasks[task.id] = task
    return tasks


def problems(plan: Plan, tasks: dict[str, Task]) -> list[str]:
    """What does not hold together, one line each, in a stable order (empty when sound):

    a part's need or a slice's part naming no part; a task naming no part or needing no task;
    a cycle among part needs or among task needs; a part in no slice; a part whose id is in
    RESERVED; a question id used twice; a question naming no part; a part's needs_landed
    naming a part outside its needs.
    """
    issues = []
    included = {part for item in plan.slices for part in item.parts}
    for part in plan.parts.values():
        if part.id in RESERVED:
            issues.append(f"part {part.id} takes a reserved id")
        for need in part.needs:
            if need not in plan.parts:
                issues.append(f"part {part.id} needs unknown part {need}")
        for need in part.needs_landed:
            if need not in part.needs:
                issues.append(f"part {part.id} needs_landed names {need} outside needs")
        if part.id not in included:
            issues.append(f"part {part.id} is in no slice")
    for item in plan.slices:
        for part in item.parts:
            if part not in plan.parts:
                issues.append(f"slice {item.id} names unknown part {part}")
    for task in tasks.values():
        if task.part not in plan.parts:
            issues.append(f"task {task.id} names unknown part {task.part}")
        for need in task.needs:
            if need not in tasks:
                issues.append(f"task {task.id} needs unknown task {need}")

    seen = set()
    for question in plan.questions:
        if question.id in seen:
            issues.append(f"question {question.id} is used twice")
        seen.add(question.id)
        for part in question.parts:
            if part not in plan.parts:
                issues.append(f"question {question.id} names unknown part {part}")
    issues.extend(_cycles({key: part.needs for key, part in plan.parts.items()}, "part"))
    issues.extend(_cycles({key: task.needs for key, task in tasks.items()}, "task"))
    return sorted(issues)


def _cycles(graph: dict[str, tuple[str, ...]], kind: str) -> list[str]:
    """One diagnostic per cyclic component, with sorted members and unknown needs skipped."""
    issues = []
    # Tarjan's components group overlapping cycles into one diagnostic.
    indices, lowest = {}, {}
    stack, active = [], set()

    def visit(node):
        indices[node] = lowest[node] = len(indices)
        stack.append(node)
        active.add(node)
        for need in sorted(set(graph[node])):
            if need not in graph:
                continue
            if need not in indices:
                visit(need)
                lowest[node] = min(lowest[node], lowest[need])
            elif need in active:
                lowest[node] = min(lowest[node], indices[need])
        if lowest[node] == indices[node]:
            members = []
            while True:
                member = stack.pop()
                active.remove(member)
                members.append(member)
                if member == node:
                    break
            if len(members) > 1 or node in graph[node]:
                issues.append(f"{kind} cycle: {', '.join(sorted(members))}")

    for node in sorted(graph):
        if node not in indices:
            visit(node)
    return issues


def checked_tasks(plan: Plan, tasks: Mapping[str, Task], events: Iterable[dict]) -> dict[str, Task]:
    """Add this plan's green checked specs, preserving specs already present on main.

    Check records keep the exact git-show text and checkout path so status, needs and
    buffer decisions see the same specs without reading a moving branch again.
    """
    result = {}
    for event in events:
        if (event.get("ev") != "call.checked" or event.get("outcome") != "green"
                or event.get("subject", "").rsplit("/", 1)[0] != plan.draft):
            continue
        for path, text in zip(event.get("paths", ()), event.get("specs", ())):
            task = parse_task(text, path, plan.draft, plan.repo)
            if task.part in plan.parts:
                result[task.id] = task
    result.update(tasks)
    return result
