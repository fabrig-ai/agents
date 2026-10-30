"""The foreman: questions the task's own options settle never reach the answerer (docs/design/fab.md, 13.1).

A run that ends with a question parks its task. Before the question queues for the
answerer, a read-only Codex run, the foreman, reads it beside the task spec. When the spec's
pre-approved options answer it, the foreman says which; the tick writes that answer into the
spec's Answers section, lands it, and the task runs again. Otherwise the question joins the
answerer's queue. `questions` folds where each open question stands from the log; the tick
turns each state into its next step.

Foreman runs are ordinary runs whose task field is `task_field(<task>)`, which no task has:
the fold leaves them out of the task's own runs, and the tick collects them as any run.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from fab.hosts import Host
from fab.plan import Task
from fab.sh import Runner, run

KIND = "foreman"  # the foreman run's kind in run.started
EFFORT = "medium"  # its Codex effort
ROLE = Path(__file__).resolve().parent / "roles" / "foreman.md"  # its role text
ASKING = ("implement", "repair", "rebase")  # run kinds whose questions go to the foreman first
ANSWER_LINES = 20  # lines of a foreman's report after its first that the answer keeps
STATES = ("foreman", "deciding", "settled", "queued")


@dataclass(frozen=True)
class Question:
    """An open question of a task and where it stands, as questions folds it."""

    task: str  # the parked task's id, `<draft>/<task>`
    run: str  # the run that asked
    text: str  # the question.asked text: the first lines of that run's report
    asked: str  # the question.asked ts
    state: str  # one of STATES
    since: str  # the ts the state began; the answerer's queue ages by it
    foreman: str | None = None  # the last foreman run for this question
    report: str = ""  # that run's collected report path (its run.ended's report), once ended


def task_field(task_id: str) -> str:
    """The task field of a foreman run's records for task_id: `<task_id>/foreman`. No task
    has such an id, so fab.state.fold, decide's history and MAX_RUNS leave foreman runs out;
    fab.run.next_run over it numbers the runs `<task_id>/foreman-<n>`."""
    raise NotImplementedError


def questions(tasks: Mapping[str, Task], events: Iterable[dict]) -> list[Question]:
    """Every open question of the given tasks, in the order of their question.asked, with
    where it stands.

    Open: a question.asked whose task is in tasks, with no later question.answered for that
    task (as fab.calls.open_questions). It is the foreman's when its `run` has, before the
    question.asked, a run.started with kind in ASKING and a run.ended with outcome question
    (fab.run.collect logs the question.asked right after that run.ended). Its foreman runs
    are the run.started records after the question.asked with kind KIND, task
    task_field(<task>) and `asked` equal to its run; the last one counts, with the first
    run.ended of the same run.

    state and since, the first that holds:
    - queued, since the question.asked ts: it is not the foreman's (the dispatcher's park
      at MAX_RUNS, a run of another kind, a question logged by hand);
    - foreman, since the question.asked ts: no foreman run yet;
    - deciding, since the foreman run's run.started ts: it has no run.ended;
    - settled, since its run.ended ts: it ended done;
    - queued, since its run.ended ts: it ended with any other outcome (question, failed,
      infra): the options do not settle it, or the foreman could not say. A foreman runs
      once per question; an infra foreman is not retried.
    foreman is the counted run's id and report its run.ended's report ("" before it ended).

    Walk the events once in log order, keeping each record's index, so equal timestamps keep
    their order. Pure: no file is read. Records missing a field the rule reads are skipped."""
    raise NotImplementedError


def brief(question: Question, task: Task, *, run_id: str, report: str, spec: str,
          asking: str) -> str:
    """The foreman run's brief, its sections in this order, joined by blank lines and ending
    with a newline:

    1. The role text, ROLE's.
    2. `# Your question`: one line each, `- Run: <run_id>`, `- Task: <task.id> (spec
       \\`<task.path>\\`)`, `- Asked by: <question.run>`, `- Report: write it to
       \\`<report>\\``, then the line `Your checkout is the task's repository at main,
       read-only.`
    3. `# The run's report`: asking, the asking run's whole report, in a ```text fence.
    4. `# The task spec`: spec, the spec file's whole text (its `+++` header too), verbatim.

    Pure: the caller reads the files."""
    raise NotImplementedError


def start(question: Question, task: Task, host: Host, events: Iterable[dict], *,
          sh: Runner = run, log_path: Path | None = None) -> str:
    """Start the foreman run of question on host (a builder) and return its run id.

    1. The run id fab.run.next_run(task_field(task.id), events): `<task>/foreman-<n>`.
    2. On this machine: spec, the text of the file at task.path; asking, the text of
       FAB_HOME/runs/<question.run>/report.md (fab.run.collect's copy), or question.text
       when that cannot be read. A spec that cannot be read raises OSError and starts
       nothing.
    3. fab.run.launch_detached(host, run_id, task.repo, "origin/main", sh=sh,
       log_path=log_path, task=task_field(task.id), kind=KIND, branch=task.id,
       base="origin/main", brief=brief(...), effort=EFFORT, asked=question.run), the
       brief's report being `<fab.run.remote_home(host)>/runs/<run>/report.md`, where
       fab.run.launch puts it.
    fab.run.collect ends the run as any other: its run.ended carries the outcome questions
    reads, and frees the worktree."""
    raise NotImplementedError


def answer(report: str) -> str:
    """The answer a foreman's report gives: its first non-blank line must start `Done:`
    (else ValueError); the answer is that line's text after `Done:`, stripped, then the
    report's next lines, at most ANSWER_LINES, each right-stripped, the trailing blank ones
    dropped, joined by newlines. An empty first-line text is a ValueError: the role asks
    for the answer in one line there."""
    raise NotImplementedError


def with_answer(spec: str, *, day: str, question: Question, answer: str, run: str) -> str:
    """spec with the foreman's answer recorded in its Answers section, ending with a newline.

    The entry is `### <day>: <the question in one line> (<question.run>, foreman <run>)`, a
    blank line, then answer. The question's line is the first non-blank line of
    question.text with a leading `Question:` removed, stripped.
    - A spec whose text already holds the line `### ` ... ` foreman <run>)` for this run is
      returned unchanged: the answer was recorded before.
    - With a line `## Answers`, the entry goes at the end of that section: before the next
      line starting `## ` after it, or at the end; one blank line on each side.
    - Without one, `## Answers`, a blank line and the entry are appended after one blank
      line, the spec's trailing newlines first stripped.
    Pure."""
    raise NotImplementedError


def commit(question: Question, task: Task, text: str, checkout: Path, *, run_id: str,
           day: str, sh: Runner = run) -> str | None:
    """Record text, the foreman run run_id's answer, in the task's spec on a branch of
    checkout's repository and return the branch to land, or None when origin/main already
    records it.

    checkout is the plan's repository on this machine (a clone with origin; the tick's plan
    checkout). The branch is `answers/<run_id>`; the worktree FAB_HOME/runs/<run_id>/wt.
    The spec's path is Path(task.path).resolve() relative to checkout.resolve(); a spec
    outside the checkout is a ValueError before any command. Each git command with
    check=True:
    1. `git fetch origin` in checkout;
    2. `git worktree add -B <branch> <worktree> origin/main` in checkout (-B: an earlier
       attempt's branch is reset);
    3. the spec at that path, read in the worktree; new = with_answer(spec, day=day,
       question=question, answer=text, run=run_id); equal to the spec means None, with
       nothing committed or pushed;
    4. otherwise new written there through fab.atomic.write, then in the worktree
       `git -c user.name=fab -c user.email=fab@localhost commit -q -m "Answer <task.id>'s
       question from its options" -- <spec path>` and `git push -q --force origin
       HEAD:refs/heads/<branch>`.
    In every outcome, last: `git worktree remove --force <worktree>` and `git branch -D
    <branch>` in checkout, errors ignored. The pushed branch stays for fab.land.main."""
    raise NotImplementedError
