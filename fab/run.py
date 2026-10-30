"""`fab run`: start a Codex run on a builder, read its outcome, collect it (docs/design/fab.md, 5)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from fab.hosts import Host
from fab.plan import Task
from fab.sh import Runner, run

KINDS = ("implement", "repair", "rebase", "review")
OUTCOMES = {"Done:": "done", "Question:": "question", "Infra:": "infra", "Failed:": "failed"}
REMOTES = {"agents": "git@github.com:fabrig-ai/agents.git", "fabrig": "git@github.com:fabrig-ai/fabrig.git"}
ROLE = Path(__file__).resolve().parent / "roles" / "implementer.md"
NOTIFY = "fab@hel8"  # codex-run posts its end here; nothing waits on it


def remote_home(host: Host) -> str:
    """The builder's FAB_HOME as an absolute path: /home/<user>/src/fabrig/fab, user from host.ssh."""
    raise NotImplementedError


def next_run(task_id: str, events: Iterable[dict]) -> str:
    """`<task>-<n>`: n is one more than the run.started events for the task."""
    raise NotImplementedError


def branch_for(task: Task, kind: str, events: Iterable[dict]) -> str:
    """implement and review: the task id; repair: the branch of the task's last run.started
    (the task id if none); rebase: `<task>-r<n>`, n counting the task's earlier rebase runs from 1."""
    raise NotImplementedError


def outcome(report: str) -> str:
    """The outcome named by the report's first non-blank line (OUTCOMES); anything else is failed."""
    raise NotImplementedError


def brief(task: Task, role: str, *, run_id: str, branch: str, base: str, report: str) -> str:
    """The brief Codex gets: the role text, then a `# Your task` section listing run, branch,
    base, report path, the files it may change and the expected minutes, then the spec's body."""
    raise NotImplementedError


def start(task: Task, host: Host, *, kind: str = "implement", events: Iterable[dict] = (),
          sh: Runner = run, log_path: Path | None = None) -> str:
    """Start a run of task on host and log run.started; return the run id.

    On the builder, over ssh: make sure FAB_HOME/repos/<task.repo> is a clone of
    REMOTES[task.repo] and fetch it; add the worktree FAB_HOME/wt/<run> on the branch
    (implement, review, rebase: a new branch from origin/main; repair: the existing
    origin/<branch>); write the brief to FAB_HOME/runs/<run>/brief.md; then
    `codex-run task --effort <task.effort> --to NOTIFY BRIEF WORKTREE REPORT`, REPORT being
    FAB_HOME/runs/<run>/report.md, review adding --read-only. codex-run prints `<id> <state>`.
    The brief is also kept on this machine at FAB_HOME/runs/<run>/brief.md. run.started carries
    run, task, kind, host, dir (the worktree), branch, base ("origin/main"), codex (the id),
    state (codex-run's state directory) and report (the builder's report path).
    """
    raise NotImplementedError


def status(started: dict, host: Host, *, sh: Runner = run) -> dict:
    """Whether a run has ended, from its run.started record: one ssh reading codex-run's
    `<state>/ended` marker and, once ended, the report. Returns {"run", "ended", "outcome",
    "report"}; outcome and report are None until ended."""
    raise NotImplementedError


def collect(run_id: str, events: Iterable[dict], hosts: dict[str, Host], *, sh: Runner = run,
            log_path: Path | None = None) -> str | None:
    """Collect an ended run once: copy its report to FAB_HOME/runs/<run>/report.md here, log
    run.ended (run, task, outcome, report, minutes since run.started) and, for a question,
    question.asked with the report's first 15 lines as text. Returns the outcome; None while the
    run is still going or when it was already collected."""
    raise NotImplementedError


def main(argv: list[str]) -> int:
    """`fab run start SPEC --host H [--kind K]` (SPEC: docs/plan/<draft>/tasks/<task>.md, its plan
    two directories up), `fab run status RUN`, `fab run collect RUN`. Prints one line; exit 0,
    or 1 on a refusal with its reason."""
    raise NotImplementedError
