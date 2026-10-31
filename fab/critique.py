"""The self-critique: a read-only review of every task's branch before it lands or is readied
(docs/design/fab.md, 13.1).

When a task's run ends done and the gates pass, a critic run (Codex, high, read-only) reviews
the branch's tip against its skeleton, the taste file and the gates' output. A critique with
no findings lets the branch through at once. Findings go to the task's next run on the same
branch, a fix run, once: after the fix ends done the branch lands or is readied. Every other
run of the task that ends done (a repair, a rebase) makes a new tip, critiqued again. A
branch whose critic cannot run is held, never let through uncritiqued. `stages` folds where
each task's critique stands from the log; the tick turns each stage into its next step.

Critic runs are ordinary runs whose task field is `task_field(<task>)`, which no task has, as
foreman runs are (fab.foreman): the fold leaves them out of the task's own runs, and the tick
collects them as any run.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from fab import run as runs
from fab.hosts import Host
from fab.plan import Task
from fab.sh import Runner, run

KIND = "critique"  # the critic run's kind in run.started
FIX = "fix"  # the kind of the task's run that fixes the findings (fab.run.KINDS)
EFFORT = "high"  # the critic's Codex effort (the user's model: Codex, high, read-only)
ROLE = Path(__file__).resolve().parent / "roles" / "critic.md"  # the critic's role text
STEP = "critique"  # the step of the rejection a fix run's brief carries (fab.run.brief)
INFRA_LIMIT = 3  # critic runs of one tip ending infra after which the task is held
FINDINGS_LINES = 40  # lines of a critic's report that a fix run's brief quotes
STAGES = ("critique", "critiquing", "fix", "hold", "clear")


@dataclass(frozen=True)
class Stage:
    """Where a task's self-critique stands, as stages folds it."""

    task: str  # the task's id, `<draft>/<task>`
    stage: str  # one of STAGES
    critique: str | None = None  # the reviewed run's last critic run; None before the first
    report: str = ""  # that run's collected report path (its run.ended's report), once ended
    reason: str = ""  # for hold: why, one line


def task_field(task_id: str) -> str:
    """The task field of a critic run's records for task_id: `<task_id>/critique`. No task
    has such an id, so fab.state.fold, decide's history and MAX_RUNS leave critic runs out;
    fab.run.next_run over it numbers the runs `<task_id>/critique-<n>`."""
    raise NotImplementedError


def stages(tasks: Mapping[str, Task], events: Iterable[dict]) -> dict[str, Stage]:
    """Where each task's self-critique stands after the events, keyed by task id in the
    tasks' order. A task with no run.started of its own is left out.

    The task's runs are the run.started records whose task is its id. The reviewed run is
    reviewed(<id>, events): the tip a critique covers. Its critic runs are the run.started
    records with task task_field(<id>), kind KIND and `of` the reviewed run, each with the
    first run.ended of the same run. The last of them counts; critique is its id and report
    its run.ended's report ("" before it ended or without one).

    stage and reason, the first that holds:
    - critique: no reviewed run (no run of the task's ended done yet), or no critic run of it;
    - critiquing: the last critic run has no run.ended;
    - critique: it ended infra and fewer than INFRA_LIMIT of the reviewed run's critic runs
      that started after the task's last question.answered (any, when none) did;
    - hold, reason `<INFRA_LIMIT> critiques ended infra`: it ended infra. The branch is not
      let through uncritiqued: the tick parks the task for judgement, and the answer
      (question.answered naming the task) restarts the count, so the stage is critique again;
    - clear: it ended done, the critic found nothing;
    - clear: it ended with any other outcome (failed, question: the critic found something)
      and a run of the task's own of kind FIX that started after that run.ended has a
      run.ended with outcome done: the fix is in;
    - fix: it found something and no such run has ended done.
    Every tip is critiqued: a later run of the task that ends done and is not a fix run (a
    repair after a rejection, a rebase, a run after the task was parked) is the new reviewed
    run, and its stage starts again at critique. The fix run's own tip is not critiqued
    again: it answers the critique.

    Read the events as one list in log order, keeping each record's index, so equal
    timestamps keep their order. Pure: no file is read. Records missing a field the rule reads are skipped."""
    raise NotImplementedError


def reviewed(task_id: str, events: Iterable[dict]) -> dict | None:
    """The run.started of the run whose tip task_id's next or current critique covers: the
    task's last run (task field task_id) of a kind other than FIX whose first run.ended has
    outcome done; None when no such run has ended done. Pure; records missing `run`, `kind`
    or `outcome` are skipped."""
    raise NotImplementedError


def brief(task: Task, *, run_id: str, branch: str, report: str, digest: str | None) -> str:
    """The critic run's brief, its sections in this order, joined by blank lines and ending
    with one newline, each text stripped of trailing newlines:

    1. The role text, ROLE's.
    2. The taste file, fab.run.TASTE's text.
    3. `# Your branch`: one line each, `- Run: <run_id>`, `- Task: <task.id> (spec
       \\`<task.path>\\`, kind <task.kind>)`, `- Branch: \\`<branch>\\``, `- Files the task may
       change: <task.files joined by ", ", or (none)>`, `- Report: write it to \\`<report>\\``,
       then the line `Your checkout is the branch's tip, detached and read-only; the change is
       \\`git diff origin/main...HEAD\\`.`
    4. `# The gates' output`: with a digest, the line `The gates passed; this is the digest
       they read.`, a blank line, then digest verbatim; with None, the one line `No gates run
       on <task.repo> branches yet; read the change itself.`
    5. `# The task spec`: task.body verbatim.

    Reads ROLE and fab.run.TASTE; nothing else."""
    raise NotImplementedError


def start(task: Task, host: Host, events: Iterable[dict], *, digest: str | None,
          sh: Runner = run, log_path: Path | None = None) -> str:
    """Start the critic run of task's branch on host (a builder) and return its run id.

    1. The branch and the reviewed run: the branch and run of reviewed(task.id, events)
       (None: ValueError naming the task, before any command).
    2. The run id fab.run.next_run(task_field(task.id), events): `<task>/critique-<n>`.
    3. fab.run.launch_detached(host, run_id, task.repo, "origin/<branch>", sh=sh,
       log_path=log_path, task=task_field(task.id), kind=KIND, branch=<branch>,
       base="origin/main", brief=brief(task, ...), effort=EFFORT, of=<the reviewed run>),
       the brief's report being `<fab.run.remote_home(host)>/runs/<run>/report.md`, where
       fab.run.launch puts it, and digest passed through.
    The worktree is detached at the branch's tip as the builder's clone fetches it.
    fab.run.collect ends the run as any other: its run.ended carries the outcome stages
    reads, and frees the worktree."""
    raise NotImplementedError


def findings(report: str) -> str:
    """The findings a fix run's brief quotes from a critic's report: the report from its first
    non-blank line on, at most FINDINGS_LINES lines, each right-stripped, the trailing blank
    ones dropped, ending with one newline. A report with no non-blank line gives `(the
    critique's report is empty)` and a newline. Pure."""
    raise NotImplementedError


def rejection(stage: Stage) -> dict:
    """What a fix run's start passes fab.run.start as its rejection, so its brief quotes the
    findings under `## The self-critique found` (fab.run.brief):
    `{"step": STEP, "log": stage.report, "findings": findings(<the report's text>)}`.

    The text is read from stage.report (fab.run.collect's copy on this machine); one that
    cannot be read (OSError, UnicodeError) gives the findings `(the critique's report could
    not be read: <stage.report>)` and a newline. A stage other than fix is a ValueError
    naming the task, before any read."""
    raise NotImplementedError
