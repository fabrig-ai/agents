"""Plans and task specs, read from a draft's `docs/plan/<draft>/` (docs/design/fab.md, 4)."""

from __future__ import annotations

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
    raise NotImplementedError


def parse_task(text: str, path: str, draft: str, default_repo: str) -> Task:
    """Parse a spec: a `+++` line, TOML, a `+++` line, then the Markdown body (kept verbatim).

    Required: id, part, kind; defaults: repo=default_repo, needs=(), files=(), effort="high",
    minutes=25. Short ids in `id` and `needs` become full ids. Raises PlanError naming path
    for a missing header, a bad value (unknown kind or effort, minutes not a positive int).
    """
    raise NotImplementedError


def load_tasks(directory: Path, draft: str, default_repo: str) -> dict[str, Task]:
    """Every `*.md` in directory (sorted by name), keyed by full id; a duplicate id is a PlanError."""
    raise NotImplementedError


def problems(plan: Plan, tasks: dict[str, Task]) -> list[str]:
    """What does not hold together, one line each, in a stable order (empty when sound):

    a part's need or a slice's part naming no part; a task naming no part or needing no task;
    a cycle among part needs or among task needs; a part in no slice.
    """
    raise NotImplementedError
