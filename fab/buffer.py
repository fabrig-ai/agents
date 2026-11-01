"""The ready-task buffer's order: which runnable task starts first (docs/design/fab-tick.md, 7).

The user's timeline puts a structure review's consolidations at the head of the buffer, then
repairs and rebases, then the tasks of contract parts, then the rest by their part's slice.
`group` and `order` are pure functions of the plan and its specs. The dispatcher computes
which tasks are refused (their next run carries a refusal) and starts runs in `order`'s order.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping

from fab import fix
from fab.plan import Plan, Task

GROUPS = ("consolidation", "repair", "contract", "slice")  # the buffer's groups, first first


def group(plan: Plan, task: Task, refused: bool) -> str:
    """The GROUPS entry task starts in, the first that holds:

    - "consolidation": task.consolidation is true (a structure review wrote it, fab-gates.md 2),
      whatever else holds of it;
    - "repair": kind in fix.FIX_KINDS (red or finding; docs/design/fab-qa.md, 2), or
      refused is true (its next run is a repair or rebase run on a refusal);
    - "contract": its part is in plan.parts with contract true;
    - "slice": anything else, a task whose part is not in plan.parts among them.
    """
    if task.consolidation:
        return "consolidation"
    if task.kind in fix.FIX_KINDS or refused:
        return "repair"
    part = plan.parts.get(task.part)
    if part is not None and part.contract:
        return "contract"
    return "slice"


def order(plan: Plan, tasks: Mapping[str, Task], candidates: Iterable[str],
          refused: Collection[str] = ()) -> list[str]:
    """candidates (task ids, each a key of tasks) in the order runs start for them.

    A sort of candidates by four keys:
    1. the index in GROUPS of group(plan, tasks[id], id in refused);
    2. the position in plan.slices of the first slice whose parts hold the task's part;
       len(plan.slices) when none does (a part in no slice, or not in the plan);
    3. the position of the task's part in plan.parts; len(plan.parts) when it is not there;
    4. the position of id in tasks (the specs' order), so candidates' own order never
       decides: the dispatcher lists rejected tasks before runnable ones, and a later
       rejected spec must not go before an earlier refused runnable one.
    Every group sorts by keys 2 to 4 alike: a repair of a slice 1 part goes before a repair
    of a slice 2 part. Returns a new list; candidates and tasks are not changed. A
    candidate missing from tasks is a KeyError.
    """
    slices = {}
    for position, item in enumerate(plan.slices):
        for part in item.parts:
            if part in plan.parts:
                slices.setdefault(part, position)
    parts = {part: position for position, part in enumerate(plan.parts)}
    specs = {identifier: position for position, identifier in enumerate(tasks)}

    def rank(identifier):
        task = tasks[identifier]
        return (GROUPS.index(group(plan, task, identifier in refused)),
                slices.get(task.part, len(plan.slices)),
                parts.get(task.part, len(plan.parts)), specs[identifier])

    return sorted(candidates, key=rank)
