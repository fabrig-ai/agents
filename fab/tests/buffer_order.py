"""The vocabulary of the buffer's order tests (docs/design/tick.md, 7): plans with slices
and contract parts, specs that may be consolidations, and an assertion on the order.

test_buffer.py and the dispatcher's order tests speak in these; add a builder here rather
than beside a test.
"""

from __future__ import annotations

import unittest
from collections.abc import Collection, Iterable, Mapping, Sequence

from fab import buffer, plan

DRAFT = "draft"


def sliced(*slices: Sequence[str], contracts: Collection[str] = ()) -> plan.Plan:
    """A plan of DRAFT whose slices, numbered from 1, hold the given part names. Parts come in
    the order they first appear, each a feature part needing nothing, contract when named in
    contracts."""
    parts = {}
    for names in slices:
        for name in names:
            parts.setdefault(name, plan.Part(name, name, "feature", (), "design.md",
                                             contract=name in contracts))
    return plan.Plan(DRAFT, "agents", (), 1.0, 2.0, parts,
                     tuple(plan.Slice(n, f"slice {n}", tuple(names), False)
                           for n, names in enumerate(slices, 1)),
                     landing="queue", reviews=True, direct=False)


def spec(name: str, part: str, *, consolidation: bool = False, kind: str = "feature") -> plan.Task:
    """A spec of DRAFT named name, of part, needing nothing."""
    return plan.Task(f"{DRAFT}/{name}", part, kind, "agents", (), (), "high", 25, "",
                     f"tasks/{name}.md", consolidation=consolidation)


def specs(*tasks: plan.Task) -> dict[str, plan.Task]:
    """tasks keyed by id, in the given order (the order load_tasks would give them)."""
    return {task.id: task for task in tasks}


def ids(*names: str) -> list[str]:
    """The full ids of DRAFT's tasks named names, in order."""
    return [f"{DRAFT}/{name}" for name in names]


class BufferTestCase(unittest.TestCase):
    def assertOrder(self, the_plan: plan.Plan, tasks: Mapping[str, plan.Task],
                    expected: Sequence[str], *, refused: Iterable[str] = (),
                    candidates: Iterable[str] | None = None) -> None:
        """buffer.order puts candidates (default: every task, in tasks' order) in expected's
        order; expected and refused are short names."""
        chosen = list(tasks) if candidates is None else list(candidates)
        self.assertEqual(buffer.order(the_plan, tasks, chosen, frozenset(ids(*refused))),
                         ids(*expected))
