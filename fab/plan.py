"""Plans and task specs, read from a draft's `docs/plan/<draft>/` (docs/design/fab.md, 4)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

MODES = ("feature", "migration", "fix", "probe")
KINDS = ("feature", "interface", "migration", "repair", "rebase", "docs")
EFFORTS = ("medium", "high")


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

    @property
    def draft(self) -> str:
        return self.id.split("/", 1)[0]

    @property
    def name(self) -> str:
        return self.id.split("/", 1)[1]


def load_plan(path: Path) -> Plan:
    """Read plan.toml: required keys draft, repo, parts; defaults sources=(), buffer low=1.0 high=2.0.

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
    parts = {}
    for item in value(data, "part", (list,), required=True):
        if not isinstance(item, dict):
            raise PlanError(f"{path}: part must be a table")
        part = Part(value(item, "id", (str,), required=True),
                    value(item, "title", (str,), required=True),
                    value(item, "mode", (str,), required=True),
                    strings(item, "needs", required=True),
                    value(item, "design", (str,), required=True),
                    value(item, "done", (bool,), False))
        if part.mode not in MODES:
            raise PlanError(f"{path}: part {part.id} has unknown mode {part.mode!r}")
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
    return Plan(draft, repo, sources, float(low), float(high), parts, tuple(slices))


def parse_task(text: str, path: str, draft: str, default_repo: str) -> Task:
    """Parse a spec: a `+++` line, TOML, a `+++` line, then the Markdown body (kept verbatim).

    Required: id, part, kind; defaults: repo=default_repo, needs=(), files=(), effort="high",
    minutes=25. Short ids in `id` and `needs` become full ids. Raises PlanError naming path
    for a missing header, a bad value (unknown kind or effort, minutes not a positive int).
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
                effort, minutes, "".join(lines[end + 1:]), path)


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
    a cycle among part needs or among task needs; a part in no slice.
    """
    issues = []
    included = {part for item in plan.slices for part in item.parts}
    for part in plan.parts.values():
        for need in part.needs:
            if need not in plan.parts:
                issues.append(f"part {part.id} needs unknown part {need}")
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

    def cycles(graph, kind):
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

    cycles({key: part.needs for key, part in plan.parts.items()}, "part")
    cycles({key: task.needs for key, task in tasks.items()}, "task")
    return sorted(issues)
