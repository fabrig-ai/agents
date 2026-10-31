"""Acceptance apart from the implementers: test-writer and accept runs (docs/design/fab.md, 13.1).

Whoever designs a thing never accepts it. Once a feature part's skeleton and specs have
landed, a test-writer run (Codex, high) writes the part's acceptance tests from its design
and its skeleton's test vocabulary, marked pending so main stays green. Once every task of
the part has landed, an accept run (Codex, medium) removes the markers and runs the suite.
Green, its branch lands and the part is done. Red, it writes a repair task spec of the part
instead, and the next round's accept run waits for that task. A slice's story test is
written once every part of the slice is designed, and accepted once they are all done.

No spec holds these tasks. `tasks` derives them from the plan, its specs and the log, and
the tick adds them to the specs' tasks, so the fold, runs, gates and landing treat them as
any task. Their ids have three parts, `<draft>/<unit>/<name>`, where a spec's have two.
Their runs push branches under BRANCH, apart from the specs' `<draft>/<task>`: a spec task
named after its part would otherwise hold the ref `<draft>/<part>` that git needs free for
`<draft>/<part>/tests-1`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from fab.plan import Plan, Task

KINDS = ("tests", "accept")  # the run kinds, and the Task.kind of the tasks they run
REPOS = ("agents",)  # repositories whose plans owe acceptance: the tests are Python under fab/tests/
MODES = ("feature",)  # part modes accepted this way; a migration keeps its tests' meaning
SLICE = "slice-{}"  # a slice's unit key, from its number
TESTS_PREFIX = "fab/tests/test_accept_"  # every acceptance test module's path starts so
SUPPORT = "fab/tests/support.py"  # the shared test vocabulary, pending among it
TASKS_DIR = "docs/plan/{}/tasks"  # a draft's task specs, where a red accept run writes its fix
BRANCH = "accept/{}"  # a run's branch, from its run id; no spec's branch is under it
GREEN = "Done: accepted"  # the first line of a green accept run's report (fab/roles/accepter.md)
TESTS_MINUTES = 40  # the test-writer's expected minutes
ACCEPT_MINUTES = 15  # the accept run's
FIX_MINUTES = 30  # the repair task a red accept run writes
ROLES = {  # the role text of each kind's runs; fab.run.role_text reads it
    "tests": Path(__file__).resolve().parent / "roles" / "test-writer.md",
    "accept": Path(__file__).resolve().parent / "roles" / "accepter.md",
}


@dataclass(frozen=True)
class Unit:
    """What one test module accepts: a part, or a slice's story."""

    draft: str
    key: str  # the part's id, or SLICE.format(n)
    parts: tuple[str, ...]  # the part's id alone, or the slice's parts in its order
    slice: int | None  # the slice's number; None for a part
    subject: str  # `<draft>/<key>`: the pending marker's subject and the tasks' id prefix
    path: str  # tests_path(draft, key)


def tests_path(draft: str, key: str) -> str:
    """The unit's test module: TESTS_PREFIX, then draft and key each lowercased with every run
    of characters other than a-z and 0-9 made one `_` and leading and trailing `_` stripped,
    joined by `_`, then `.py`. ("agents-rebuild", "slice-6") gives
    `fab/tests/test_accept_agents_rebuild_slice_6.py`. ValueError when either becomes empty."""
    raise NotImplementedError


def owned(task_id: str) -> bool:
    """Whether task_id is one of this module's tasks: three non-empty parts split at `/`, the
    last `tests` or `accept-<k>`, k a decimal without a leading zero. Spec ids
    (`<draft>/<task>`) and foreman runs' task fields (`<draft>/<task>/foreman`) are not."""
    raise NotImplementedError


def units(plan: Plan, specs: Mapping[str, Task], events: Iterable[dict]) -> list[Unit]:
    """The plan's units that owe acceptance: its parts in the plan's order, then its slices
    in the plan's order. None when plan.repo is not in REPOS. Tasks of specs that owned names
    are ignored throughout; a part's spec tasks are those of specs whose part is its id.

    A part owes acceptance when its mode is in MODES, it is not marked done, it has spec
    tasks (its skeleton has landed with them), and either one of them is not landed
    (fab.state.fold(specs, events)) or a run.started names the part's tests task
    (`<draft>/<part>/tests`). So a part whose tasks all landed before acceptance began stays
    done without it, and a part whose acceptance began keeps it.

    A slice owes acceptance when one of its parts does and every one of its parts is marked
    done or has spec tasks: its last part has been designed.

    key, parts and slice as Unit says; subject `<draft>/<key>`; path tests_path(draft, key).
    Pure."""
    raise NotImplementedError


def read_report(run_id: str) -> str:
    """The text of a run's report as fab.run.collect copied it here,
    FAB_HOME/runs/<run>/report.md; "" when it cannot be read."""
    raise NotImplementedError


def needs(plan: Plan, unit: Unit, specs: Mapping[str, Task], events: Iterable[dict], *,
          report: Callable[[str], str] = read_report) -> tuple[str, ...]:
    """What the unit's accept task waits for, in this order: its tests task
    (`<subject>/tests`); then for a part, its spec tasks' ids in specs' order; for a slice,
    per part of the slice in its order: when the part owes acceptance (units), its current
    accept task's id, `<draft>/<part>/accept-<k>` with k from accept_round over the part
    unit's own needs (report passed on); else its spec tasks' ids in specs' order (none for a part marked
    done). Pure."""
    raise NotImplementedError


def accept_round(subject: str, waits: Sequence[str], events: Iterable[dict], *,
                 report: Callable[[str], str] = read_report) -> tuple[int, bool]:
    """The unit's current accept round and whether it is accepted, waits being its needs.

    Round k's task is `<subject>/accept-<k>`. Walk k from 1. No branch.landed names round
    k's task: (k, False). Otherwise its reference is the index in events of the task's last
    run.started, or of the branch.landed when no run.started names it. The round is green,
    (k, True), when both hold:
    - the first non-blank line of report(<that run>), stripped, starts with GREEN (a round
      landed with no run.started skips this);
    - every id in waits has a branch.landed at an earlier index than the reference.
    Otherwise it is red, and the walk goes on with k + 1. The report says red at once, in
    the tick that lands it, before the fix spec it wrote reaches the plan's checkout; the
    waits say red when something the unit waits for landed after the accept run started (a
    consolidation task, a part accepted again), so a unit is accepted on its latest code.
    Pure but for report; events in log order."""
    raise NotImplementedError


def fix_files(unit: Unit, specs: Mapping[str, Task]) -> tuple[str, ...]:
    """The files a red round's repair task may change: every entry of the files of the spec
    tasks whose part is one of unit.parts, in specs' order, each once, except entries that
    start with TESTS_PREFIX (acceptance tests are never the implementer's). Pure."""
    raise NotImplementedError


def tests_body(plan: Plan, unit: Unit, specs: Mapping[str, Task]) -> str:
    """The tests task's body, which fab.run.brief puts after the run's facts. Markdown,
    sections joined by one blank line, ending with one newline:

    1. For a part: `# Acceptance tests for <subject>`, then the line `Part \\`<key>\\`:
       <title>. Design: <design>.` For a slice: `# The story test of <subject>`, then
       `Story: <story>`, then `Parts:` and one line per part of the slice, `- \\`<id>\\`:
       <title>. Design: <design>.`
    2. `## What to write`, then these lines:
       `- One module, \\`<path>\\`; change nothing else.`
       `- Mark every TestCase class \\`@support.pending("<subject>")\\`
       (\\`from fab.tests import support\\`), so the tests are skipped on main until the
       accept run.`
       `- Run them with \\`FAB_PENDING=<subject> bin/fab test -k <the module's stem>\\`.
       On the skeleton they fail for the behaviour they test, never for an import; then
       \\`bin/fab test\\` passes with them pending.`
    3. `## The skeleton`, then `- Modules: ` and the files of fix_files(unit, specs) that do
       not start with `fab/tests/`, each in backticks, joined by `, ` (`(none)` when there
       are none); then `- Test vocabulary: ` and SUPPORT then the remaining files of
       fix_files, the same way.
    The specs' bodies are left out: the tests come from the design, not the implementers'
    plan. Pure."""
    raise NotImplementedError


def accept_body(plan: Plan, unit: Unit, specs: Mapping[str, Task], number: int) -> str:
    """The accept task's body for round number, the fix it may write being `<key>-fix-<number>`.
    Markdown, sections joined by one blank line, ending with one newline:

    1. `# Accept <subject>, round <number>`, then the line `Remove every line
       \\`@support.pending("<subject>")\\` from \\`<path>\\`, change nothing else in it, and run
       \\`bin/fab test\\`.`
    2. `## Green`, then `Commit (\\`Accept <subject>\\`), push, and report \\`Done: accepted\\`.`
    3. `## Red`, then `Keep the markers. Write the spec below to \\`<spec path>\\` with your
       findings in its body: per failing test, its name, what it asserts, what it got and
       the public item it reaches. Commit only the spec (\\`Red: <subject>, round
       <number>\\`), push, and report \\`Done: red, <draft>/<key>-fix-<number>\\`.` The spec
       path is TASKS_DIR.format(draft) + `/<key>-fix-<number>.md`. For a slice, one more
       line: `Set part to the one of <its parts, each in backticks, joined by ", "> whose
       public item the first failing test reaches.`
    4. A ```toml fence holding the spec: `+++`, then `id = "<key>-fix-<number>"`, `part =
       "<key>"` (a slice: `part = "<the part>"`), `kind = "repair"`, `needs = []`,
       `files = [...]` (fix_files(unit, specs), each a TOML basic string, joined by `, `),
       `effort = "high"`, `minutes = <FIX_MINUTES>`, `+++`, `# Make <subject>'s acceptance
       tests pass`, a blank line, `<your findings>`, a blank line, `## Acceptance`, a blank
       line, and `- \\`FAB_PENDING=<subject> bin/fab test\\` passes; \\`<path>\\` is
       unchanged.`
    Pure."""
    raise NotImplementedError


def tasks(plan: Plan, specs: Mapping[str, Task], events: Iterable[dict], *,
          report: Callable[[str], str] = read_report) -> dict[str, Task]:
    """The tasks of every unit of units(plan, specs, events), keyed by id, unit by unit: its
    tests task, then its accept task. A unit's part field is its key for a part and "" for a
    slice (no part's status waits on a slice). Both tasks have repo plan.repo and path ""
    (no spec file: fab.run.brief names none).

    - tests: id `<subject>/tests`, kind "tests", needs (), files (path,), effort "high",
      minutes TESTS_MINUTES, body tests_body(plan, unit, specs).
    - accept: (k, accepted) = accept_round(subject, waits, events, report=report), waits
      being needs(plan, unit, specs, events, report=report); id `<subject>/accept-<k>`, kind "accept", needs
      waits, files (path, TASKS_DIR.format(draft) + `/<key>-fix-<k>.md`), effort "medium",
      minutes ACCEPT_MINUTES, body accept_body(plan, unit, specs, k).

    Red rounds' tasks are left out, so the fold sees only the current round; an accepted
    unit's accept task is landed in the fold, and fab.state.part_statuses counts the part
    done only then. Pure but for report."""
    raise NotImplementedError


def slices_done(plan: Plan, specs: Mapping[str, Task], events: Iterable[dict], *,
                report: Callable[[str], str] = read_report) -> list[int]:
    """The numbers of the plan's slices whose story is accepted (a slice unit whose
    accept_round is accepted) and that no slice.done record with this draft and slice
    names, in the plan's order. The tick logs slice.done (draft, slice, task: the accepted
    accept task's id) for each. Pure but for report, passed on to accept_round."""
    raise NotImplementedError
