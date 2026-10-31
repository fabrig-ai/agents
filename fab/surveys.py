"""Survey runs: Codex reads the code before a design call (docs/design/fab.md, 13.10).

A survey is a read-only Codex run (kind survey, effort medium) in a worktree detached at
main. It reports what one design call needs to know of the code: the readers of what a
draft changes, the primitives in reach with their signatures, each area's test world. At
intake three surveys come before the cut; before each skeleton or contract call one
refreshes the primitives in reach for its part. Their reports go into the call's brief
beside the code-built inventory, so parts designed in parallel reuse what has landed.

A survey is one run per topic and call: one that ends in any outcome lets its call start,
without its report when that is not done. Every function here but start is pure, or
reads only FAB_HOME.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from fab import calls, log, report
from fab import run as runs
from fab.hosts import Host
from fab.plan import Plan
from fab.sh import Runner, run

KIND = "survey"  # run.started's kind
EFFORT = "medium"  # the surveyor's effort (execution-modes.md, the roles table)
ROLE = Path(__file__).resolve().parent / "roles" / "surveyor.md"
FRESH = 60  # minutes after its end that a survey's report still serves its call
REPORT_LIMIT = 20_000  # characters of one survey's report a call's brief quotes
SECTION = "Surveys"  # the brief section that quotes them, right after Inventory
TOPICS = {
    "readers": (
        "The readers of what the draft changes. For each module, type, function, stored "
        "format, command or role text the draft's words would change, replace or delete: who "
        "reads, calls or writes it today (path and line, one line each on how), and the tests "
        "that pin it. Group them by what changes, and say which readers live in other "
        "repositories or on machines, as far as the checkout shows."
    ),
    "primitives": (
        "The primitives in reach. The functions, types, constants, test helpers, role texts "
        "and commands already on main that the subject would use, extend or must not "
        "duplicate, each with its signature as written and one or two lines on its contract "
        "(what it takes, returns, raises and writes). The inventory below lists public "
        "signatures and first doc lines only: name the entries that apply and what their "
        "docstrings and bodies promise beyond that line, and add what it cannot show: "
        "private functions a shared primitive should come out of, the test package's "
        "builders, shell tools and code in other languages. Name near-duplicates: two primitives that do "
        "the same thing."
    ),
    "tests": (
        "Each area's test world. For each area the draft touches: how its tests are built "
        "(the fixtures, builders, fakes and assertion helpers, with their signatures), the "
        "test modules that show them best, how long those modules take, and what a new test "
        "there must not do (live machine state, the network, real services)."
    ),
}
BEFORE = {  # the topics surveyed before a call of each role, in this order
    "cut": ("readers", "primitives", "tests"),
    "skeleton": ("primitives",),
    "contract": ("primitives",),
}


@dataclass(frozen=True)
class Survey:
    """One survey run of a subject, as surveys folds it from the log."""

    run: str  # `<subject>/survey-<n>`
    subject: str  # the call's subject: `<draft>/cut` or `<draft>/<part>`
    topic: str  # a key of TOPICS, from run.started's topic
    position: int  # the index of its run.started in the events
    outcome: str | None  # its run.ended's outcome; None while in flight
    ended: str | None  # its run.ended's ts; None while in flight


def task_field(subject: str) -> str:
    """The task field of a survey run's records for subject: `<subject>/survey`. No task has
    it, so a survey is never one of a task's runs; fab.run.next_run over it numbers the
    subject's surveys, `<subject>/survey-<n>`. ValueError for an empty subject."""
    raise NotImplementedError


def surveys(subject: str, events: Iterable[dict]) -> list[Survey]:
    """Every survey run of subject, in the order of their run.started.

    A survey is a run.started whose task is task_field(subject) and whose kind is KIND; its
    topic is the record's `topic` (a record without a string topic is skipped), its position
    the record's index in events. Its outcome and ended are those of the first run.ended
    with the same run that comes after it, else None. Records of other subjects or kinds,
    and a run.ended without its run.started, are ignored. Never raises on a record missing
    a field."""
    raise NotImplementedError


def due(subject: str, role: str, events: Sequence[dict], now: str) -> tuple[str, ...]:
    """The topics of BEFORE[role], in that order, whose survey must start now for the
    subject's next call of that role.

    A topic's current survey is its latest of surveys(subject, events), when that one's
    position is after the subject's last call.started whose role is a key of BEFORE (an
    amend, answer or review call does not count); a survey from before that call served it.
    A topic is due when it has no current survey, or its current survey ended more than
    FRESH minutes before now (fab.report.minutes(ended, now) > FRESH). A current survey in
    flight is never due, however old. ValueError for a role not in BEFORE. Pure."""
    raise NotImplementedError


def ready(subject: str, role: str, events: Sequence[dict], now: str) -> bool:
    """Whether the subject's next call of role may start: every topic of BEFORE[role] has a
    current survey (as due defines it) that has ended, in any outcome, within FRESH minutes
    of now. Not ready while one is in flight or due. ValueError for a role not in BEFORE.
    Pure."""
    raise NotImplementedError


def brief(plan: Plan, subject: str, topic: str, root: Path, *, run_id: str, report: str,
          part: str | None = None) -> str:
    """The survey run's brief, its sections through fab.calls._brief, in this order:

    1. `Role`: ROLE's text.
    2. `Your survey`: `- Run: <run_id>`, `- Topic: <topic>`, `- Repository: <plan.repo>, at
       main, read-only` and `- Report: write it to \\`<report>\\``.
    3. `What to survey`: TOPICS[topic].
    4. `The subject`: for a part, `- Plan: <draft>`, `- Part: <id> — <title>`, `- Mode:
       <mode>`, `- Needs: <needs, comma-separated, or (none)>` and `- Design: <citation>
       (read it in your checkout)`; for the cut (part None), `- Draft: <draft>` and
       `- Sources: \\`<source>\\`, ...` (read them in your checkout).
    5. `Inventory`: fab.calls.render_inventory(fab.calls.inventory(root)), or `(none)` when
       it is empty: what the call gets already, which the survey names and does not repeat.

    root is the plan's checkout on this machine. ValueError for a topic not in TOPICS or a
    part not in plan.parts, and past fab.calls.BRIEF_LIMIT as every brief."""
    raise NotImplementedError


def start(plan: Plan, subject: str, topic: str, root: Path, host: Host, events: Iterable[dict],
          *, part: str | None = None, sh: Runner = run, log_path: Path | None = None) -> str:
    """Start one survey run of subject on topic on host (a builder) and return its run id.

    1. ValueError for a topic not in TOPICS, before any command.
    2. The run id fab.run.next_run(task_field(subject), events): `<subject>/survey-<n>`.
    3. fab.run.launch_detached(host, run_id, plan.repo, "origin/main", sh=sh,
       log_path=log_path, task=task_field(subject), kind=KIND, branch="main",
       base="origin/main", brief=brief(plan, subject, topic, root, run_id=run_id,
       report=<report>, part=part), effort=EFFORT, topic=topic), the report being
       `<fab.run.remote_home(host)>/runs/<run>/report.md`, where fab.run.launch puts it.
    fab.run.collect ends the run as any other: it copies the report to
    FAB_HOME/runs/<run>/report.md, logs run.ended and frees the worktree."""
    raise NotImplementedError


def section(subject: str, role: str, events: Iterable[dict]) -> str:
    """The text of a call's SECTION: per topic of BEFORE[role], in that order, the latest
    survey of surveys(subject, events) with that topic that has ended:

    - outcome done: `## <topic> (<run>, done)`, a blank line, then the text of
      FAB_HOME/runs/<run>/report.md (fab.run.collect's copy), right-stripped. A text longer
      than REPORT_LIMIT keeps its first REPORT_LIMIT characters, then a line `(cut at
      <REPORT_LIMIT> characters; the whole report: \\`<path>\\`)`. A file that cannot be
      read gives `(report unreadable: \\`<path>\\`)` instead of the text.
    - any other outcome: `## <topic> (<run>, <outcome>)`, a blank line, then `(no report:
      the survey ended <outcome>; \\`<path>\\`)`.
    - no ended survey: `## <topic>`, a blank line, then `(no survey)`.
    Entries are joined by one blank line. ValueError for a role not in BEFORE."""
    raise NotImplementedError
