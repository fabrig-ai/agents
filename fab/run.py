"""`fab run`: start a Codex run on a builder, read its outcome, collect it (docs/design/fab.md, 5)."""

from __future__ import annotations

import argparse
import shlex
import tempfile
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from fab import hosts, log, plan
from fab.hosts import Host
from fab.plan import Task
from fab.sh import Failed, Runner, run, ssh

KINDS = ("implement", "repair", "rebase", "review")
OUTCOMES = {"Done:": "done", "Question:": "question", "Infra:": "infra", "Failed:": "failed"}
REMOTES = {"agents": "git@github.com:fabrig-ai/agents.git", "fabrig": "git@github.com:fabrig-ai/fabrig.git"}
ROLE = Path(__file__).resolve().parent / "roles" / "implementer.md"
NOTIFY = "fab@hel8"  # codex-run posts its end here; nothing waits on it
SLOTTED = ("fabrig",)  # repositories whose runs build in a builder's warm slot
LAUNCHER = "codex-run"  # "codex-run" (fabrig's) or "fab" (fab codex start); see fab/codex.py


def remote_home(host: Host) -> str:
    """The builder's FAB_HOME as an absolute path: /home/<user>/src/fabrig/fab, user from host.ssh."""
    user, separator, machine = host.ssh.partition("@")
    if not separator or not user or not machine or "/" in user:
        raise ValueError(f"{host.name}: ssh must name user@host")
    return f"/home/{user}/src/fabrig/fab"


def next_run(task_id: str, events: Iterable[dict]) -> str:
    """`<task>-<n>`: n is one more than the run.started events for the task."""
    count = sum(event.get("ev") == "run.started" and event.get("task") == task_id
                for event in events)
    return f"{task_id}-{count + 1}"


def branch_for(task: Task, kind: str, events: Iterable[dict]) -> str:
    """implement and review: the task id; repair: the branch of the task's last run.started
    (the task id if none); rebase: `<task>-r<n>`, n counting the task's earlier rebase runs from 1."""
    if kind not in KINDS:
        raise ValueError(f"unknown run kind {kind!r}")
    started = [event for event in events
               if event.get("ev") == "run.started" and event.get("task") == task.id]
    if kind == "repair" and started:
        return started[-1]["branch"]
    if kind == "rebase":
        count = sum(event.get("kind") == "rebase" for event in started)
        return f"{task.id}-r{count + 1}"
    return task.id


def outcome(report: str) -> str:
    """The outcome named by the report's first non-blank line (OUTCOMES); anything else is failed."""
    first = next((line.strip() for line in report.splitlines() if line.strip()), "")
    return next((value for prefix, value in OUTCOMES.items() if first.startswith(prefix)), "failed")


def brief(task: Task, role: str, *, run_id: str, branch: str, base: str, report: str) -> str:
    """The brief Codex gets: the role text, then a `# Your task` section listing run, branch,
    base, report path, the files it may change and the expected minutes, then the spec's body."""
    files = ", ".join(task.files) or "(none)"
    return (f"{role.rstrip()}\n\n# Your task\n\n"
            f"- Task: {task.id} (spec `{task.path}`)\n"
            f"- Repository: {task.repo}\n"
            f"- Run: {run_id}\n"
            f"- Branch: `{branch}`\n"
            f"- Base: `{base}`\n"
            f"- Report: write it to `{report}`\n"
            f"- Files you may change: {files}\n"
            f"- Expected: about {task.minutes} implementer-minutes\n\n"
            f"{task.body}")


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

    A task of a repository in SLOTTED builds in a slot instead of a worktree: claim the first
    idle slot (`fab slot list`, then `fab slot claim N RUN TASK`; none idle is a ValueError
    naming the host), then in `~/src/fabrig/slots/<n>` fetch origin and switch to the branch
    (`git switch -C <branch> origin/main`; repair: `origin/<branch>`). dir is the slot, and
    run.started also carries slot (the number). The launcher is `fab codex start` (same
    arguments and output as codex-run task) once LAUNCHER says so.
    """
    events = list(events)
    branch = branch_for(task, kind, events)
    if task.repo not in REMOTES:
        raise ValueError(f"unknown repository {task.repo!r}")
    run_id = next_run(task.id, events)
    root = Path(remote_home(host))
    repo = root / "repos" / task.repo
    worktree = root / "wt" / run_id
    directory = root / "runs" / run_id
    brief_path, report_path = directory / "brief.md", directory / "report.md"
    base = "origin/main"
    text = brief(task, ROLE.read_text(), run_id=run_id, branch=branch, base=base,
                 report=str(report_path))

    def remote(argv, *, input=None):
        return sh(ssh(host.ssh, argv), input=input, check=True)

    remote(["mkdir", "-p", str(repo.parent), str(worktree.parent), str(directory)])
    clone = shlex.join(["git", "clone", "--", REMOTES[task.repo], str(repo)])
    remote(["bash", "-c", f"if ! test -d {shlex.quote(str(repo / '.git'))}; then {clone}; fi"])
    remote(["git", "-C", str(repo), "fetch", "origin"])
    if kind == "repair":
        source = f"origin/{branch}"
        remote(["git", "-C", str(repo), "worktree", "add", "--detach", str(worktree), source])
        remote(["git", "-C", str(worktree), "checkout", "--ignore-other-worktrees", "-B", branch, source])
    else:
        remote(["git", "-C", str(repo), "worktree", "add", "-b", branch, str(worktree), base])
    temporary = brief_path.with_name("brief.md.tmp")
    remote(["bash", "-c", f"cat > {shlex.quote(str(temporary))} && "
            + shlex.join(["mv", "--", str(temporary), str(brief_path)])], input=text)
    _write(log.home() / "runs" / run_id / "brief.md", text)
    command = ["codex-run", "task", "--effort", task.effort, "--to", NOTIFY]
    if kind == "review":
        command.append("--read-only")
    result = remote([*command, str(brief_path), str(worktree), str(report_path)])
    fields = result.out.strip().split(maxsplit=1)
    if len(fields) != 2 or not fields[1].startswith("/") or "\n" in fields[1]:
        raise ValueError("codex-run did not return an id and absolute state directory")
    codex, state = fields
    log.append("run.started", path=log_path, run=run_id, task=task.id, kind=kind,
               host=host.name, dir=str(worktree), branch=branch, base=base,
               codex=codex, state=state, report=str(report_path))
    return run_id


def status(started: dict, host: Host, *, sh: Runner = run) -> dict:
    """Whether a run has ended, from its run.started record: one ssh reading codex-run's
    `<state>/ended` marker and, once ended, the report. Returns {"run", "ended", "outcome",
    "report"}; outcome and report are None until ended."""
    marker = shlex.quote(str(Path(started["state"]) / "ended"))
    report_path = shlex.quote(started["report"])
    script = (f"if test -f {marker}; then printf 'ended\\n'; "
              f"if test -f {report_path}; then cat -- {report_path}; fi; "
              "else printf 'running\\n'; fi")
    result = sh(ssh(host.ssh, ["bash", "-c", script]), check=True)
    state, _, report = result.out.partition("\n")
    if state not in ("running", "ended"):
        raise ValueError(f"{started['run']}: invalid status response")
    ended = state == "ended"
    return {"run": started["run"], "ended": ended,
            "outcome": outcome(report) if ended else None, "report": report if ended else None}


def collect(run_id: str, events: Iterable[dict], hosts: dict[str, Host], *, sh: Runner = run,
            log_path: Path | None = None) -> str | None:
    """Collect an ended run once: copy its report to FAB_HOME/runs/<run>/report.md here, log
    run.ended (run, task, outcome, report, minutes since run.started) and, for a question,
    question.asked with the report's first 15 lines as text. Returns the outcome; None while the
    run is still going or when it was already collected.

    Then free what the run held on the builder: a slot run's `fab slot release N RUN` (its
    output, the bytes freed, goes into run.ended as freed); a worktree run's
    `git worktree remove --force` of its dir (the branch stays on origin). A failure to free
    is noted in run.ended as free_error, never a refusal."""
    events = list(events)
    if any(event.get("ev") == "run.ended" and event.get("run") == run_id
           for event in [*events, *log.read(log_path)]):
        return None
    started = next((event for event in reversed(events)
                    if event.get("ev") == "run.started" and event.get("run") == run_id), None)
    if started is None:
        raise ValueError(f"unknown run {run_id!r}")
    host = hosts[started["host"]]
    current = status(started, host, sh=sh)
    if not current["ended"]:
        return None
    report_path = log.home() / "runs" / run_id / "report.md"
    _write(report_path, current["report"])
    stamp = log.now()
    minutes = max(0.0, (datetime.fromisoformat(stamp)
                       - datetime.fromisoformat(started["ts"])).total_seconds() / 60)
    log.append("run.ended", path=log_path, ts=stamp, run=run_id, task=started["task"],
               outcome=current["outcome"], report=str(report_path), minutes=minutes)
    if current["outcome"] == "question":
        log.append("question.asked", path=log_path, task=started["task"], run=run_id,
                   text="\n".join(current["report"].splitlines()[:15]))
    return current["outcome"]


def main(argv: list[str]) -> int:
    """`fab run start SPEC --host H [--kind K]` (SPEC: docs/plan/<draft>/tasks/<task>.md, its plan
    two directories up), `fab run status RUN`, `fab run collect RUN`. Prints one line; exit 0,
    or 1 on a refusal with its reason."""
    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise ValueError(message)

    parser = Parser(prog="fab run", description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    launch = commands.add_parser("start")
    launch.add_argument("spec", type=Path)
    launch.add_argument("--host", required=True)
    launch.add_argument("--kind", choices=KINDS, default="implement")
    for action in ("status", "collect"):
        commands.add_parser(action).add_argument("run_id")
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return 0 if error.code == 0 else 1
    except ValueError as error:
        print(f"fab run: {error}")
        return 1
    try:
        events = log.read()
        found = hosts.load()
        if args.action == "start":
            if args.host not in found:
                raise ValueError(f"unknown host {args.host!r}")
            run_id = start(_load_spec(args.spec), found[args.host], kind=args.kind,
                           events=events, sh=run)
            print(run_id)
        else:
            started = next((event for event in reversed(events)
                            if event.get("ev") == "run.started" and event.get("run") == args.run_id), None)
            if started is None:
                raise ValueError(f"unknown run {args.run_id!r}")
            if started["host"] not in found:
                raise ValueError(f"unknown host {started['host']!r}")
            if args.action == "status":
                current = status(started, found[started["host"]], sh=run)
                state = current["outcome"] if current["ended"] else "running"
            else:
                state = collect(args.run_id, events, found, sh=run) or "pending or already collected"
            print(f"{args.run_id} {state}")
    except (OSError, ValueError, Failed) as error:
        print("fab run: " + " ".join(str(error).splitlines()))
        return 1
    return 0


def _load_spec(path: Path) -> Task:
    plan_path = path.parent.parent / "plan.toml"
    loaded = plan.load_plan(plan_path)
    return plan.parse_task(path.read_text(), str(path), loaded.draft, loaded.repo)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=path.name + ".", delete=False) as sibling:
        temporary = Path(sibling.name)
        try:
            sibling.write(text)
            sibling.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
