"""`fab run`: start a Codex run on a builder, read its outcome, collect it (docs/design/fab.md, 5)."""

from __future__ import annotations

import argparse
import json
import shlex
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from fab import atomic, hosts, log, plan
from fab.hosts import Host
from fab.plan import Task
from fab.sh import Failed, Runner, run, ssh

KINDS = ("implement", "repair", "rebase", "review")
OUTCOMES = {"Done:": "done", "Question:": "question", "Infra:": "infra", "Failed:": "failed"}
REMOTES = {"agents": "git@github.com:fabrig-ai/agents.git", "fabrig": "git@github.com:fabrig-ai/fabrig.git"}
ROLE = Path(__file__).resolve().parent / "roles" / "implementer.md"
TASTE = Path(__file__).resolve().parent / "taste.md"  # banned names and pairs; every brief carries it
NOTIFY = "fab@hel8"  # codex-run posts its end here; nothing waits on it
MODEL = "gpt-6.1-sol"  # every Codex run's model, explicit (the user, 10-30): Sol 6.1
# The Codex efforts the user's model sets by role (execution-modes.md): implementers high,
# reviewers medium; a task spec's effort applies only to kinds not named here.
EFFORTS = {"implement": "high", "repair": "high", "rebase": "high", "review": "medium"}
SLOTTED = ("fabrig",)  # repositories whose runs build in a builder's warm slot
LAUNCHER = "fab"  # "fab" (fab codex start) or "codex-run" (fabrig's, retired); see fab/codex.py


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


def role_text(repo: str) -> str:
    """The implementer's role text, then the taste file (TASTE), then the repository's notes
    (fab/roles/<repo>.md) when it has any, each separated by one blank line."""
    notes = ROLE.with_name(f"{repo}.md")
    texts = [ROLE.read_text(), TASTE.read_text()]
    if notes.exists():
        texts.append(notes.read_text())
    return "\n\n".join(text.rstrip("\n") for text in texts) + "\n"


def brief(task: Task, role: str, *, run_id: str, branch: str, base: str, report: str,
          rejection: dict | None = None) -> str:
    """The brief Codex gets: the role text, then a `# Your task` section listing run, branch,
    base, report path, the files it may change and the expected minutes, then the spec's body.
    A rejection adds the failed step and queue log between the facts and body; start supplies
    its log text in `text`. Only the last matching step, at most 120 lines, is included."""
    files = ", ".join(task.files) or "(none)"
    refusal = ""
    if rejection is not None:
        step = rejection.get("step", "unknown")
        lines = rejection.get("text", "(log unreadable: no log text)").splitlines()
        if "findings" not in rejection:
            starts = [i for i, line in enumerate(lines) if line.startswith(f"[{step}]")]
            if starts:
                lines = lines[starts[-1]:]
                end = next((i for i, line in enumerate(lines[1:], 1)
                            if line.startswith("[") and " (cwd " in line), len(lines))
                lines = lines[:end]
            elif not lines or not lines[0].startswith("(log unreadable:"):
                lines = [f"(log unreadable: step [{step}] not found)"]
        excerpt = "\n".join(lines[:120])
        refusal = ("## The landing refused this branch\n\n"
                   "The landing's checks failed; reproduce this first, in the lowest tier "
                   "that shows it. If it does not reproduce, say so in your report's first line.\n\n"
                   f"- Step: `{step}`\n"
                   f"- Queue log: `{rejection.get('log', '(missing)')}`\n\n"
                   f"```text\n{excerpt}\n```\n\n")
    return (f"{role.rstrip()}\n\n# Your task\n\n"
            f"- Task: {task.id} (spec `{task.path}`)\n"
            f"- Repository: {task.repo}\n"
            f"- Run: {run_id}\n"
            f"- Branch: `{branch}`\n"
            f"- Base: `{base}`\n"
            f"- Report: write it to `{report}`\n"
            f"- Files you may change: {files}\n"
            f"- Expected: about {task.minutes} implementer-minutes\n\n"
            f"{refusal}{task.body}")


def rejection_text(record: dict, gate_host: Host, *, sh: Runner = run) -> str:
    """Read a rejection's queue log in one ssh on the gate; unreadable logs give a diagnostic.

    brief selects the last occurrence of the failed step and caps it at 120 lines. The text
    travels in a copy of the rejection record as `text`, leaving the logged record unchanged.
    """
    if not record.get("log"):
        return "(log unreadable: rejection has no log path)"
    try:
        result = sh(ssh(gate_host.ssh, ["tail", "-n", "+1", "--", record["log"]]), check=True)
    except (OSError, Failed) as error:
        return "(log unreadable: " + " ".join(str(error).splitlines()) + ")"
    return result.out


def start(task: Task, host: Host, *, kind: str = "implement", events: Iterable[dict] = (),
          sh: Runner = run, log_path: Path | None = None, rejection: dict | None = None) -> str:
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

    A rejection's text is its `findings` when it has them (a gate's, fab.gates.screen), read
    from no machine; otherwise rejection_text from the first gate host.
    """
    events = list(events)
    branch = branch_for(task, kind, events)
    if task.repo not in REMOTES:
        raise ValueError(f"unknown repository {task.repo!r}")
    run_id = next_run(task.id, events)
    root = Path(remote_home(host))
    worktree = root / "wt" / run_id
    directory = root / "runs" / run_id
    brief_path, report_path = directory / "brief.md", directory / "report.md"
    base = "origin/main"
    rejection = _rejection(rejection, sh=sh)
    text = brief(task, role_text(task.repo), run_id=run_id, branch=branch, base=base,
                 report=str(report_path), rejection=rejection)

    def remote(argv, *, input=None):
        return sh(ssh(host.ssh, argv), input=input, check=True)

    repo = fetch_clone(host, task.repo, sh=sh)
    try:
        return _prepare_and_launch(task, host, kind, sh, run_id=run_id, branch=branch,
                                   base=base, root=root, repo=repo, worktree=worktree,
                                   brief_path=brief_path, report_path=report_path, text=text,
                                   log_path=log_path)
    except BaseException:
        # A start that fails part way gives back what it took, so the next start finds it free.
        _undo_start(task, remote, run_id=run_id, branch=branch, repo=repo, worktree=worktree)
        raise


def _undo_start(task: Task, remote, *, run_id: str, branch: str, repo: Path, worktree: Path) -> None:
    try:
        if task.repo in SLOTTED:
            listed = remote(["fab", "slot", "list"])
            for line in listed.out.splitlines():
                entry = json.loads(line) if line.strip() else {}
                if (entry.get("claim") or {}).get("run") == run_id:
                    remote(["fab", "slot", "release", str(entry["slot"]), run_id])
        else:
            remote(["bash", "-c", shlex.join(["git", "-C", str(repo), "worktree", "remove", "--force",
                                              str(worktree)]) + " 2>/dev/null; "
                    + shlex.join(["git", "-C", str(repo), "branch", "-D", branch]) + " 2>/dev/null; true"])
    except Exception:
        pass


def _prepare_and_launch(task: Task, host: Host, kind: str, remote, *, run_id: str, branch: str,
                        base: str, root: Path, repo: Path, worktree: Path, brief_path: Path,
                        report_path: Path, text: str, log_path: Path | None) -> str:
    sh = remote

    def remote(argv, *, input=None):
        return sh(ssh(host.ssh, argv), input=input, check=True)

    slot = None
    if task.repo in SLOTTED:
        listed = remote(["fab", "slot", "list"])
        idle = [entry for line in listed.out.splitlines() if line.strip()
                if (entry := json.loads(line))["claim"] is None]
        if not idle:
            raise ValueError(f"{host.name}: no idle slot")
        slot = min(idle, key=lambda entry: entry["idle"])["slot"]
        remote(["fab", "slot", "claim", str(slot), run_id, task.id])
        worktree = root.parent / "slots" / str(slot)
        remote(["git", "-C", str(worktree), "fetch", "origin"])
        source = f"origin/{branch}" if kind == "repair" else base
        remote(["git", "-C", str(worktree), "switch", "-C", branch, source])
    elif kind == "repair":
        source = f"origin/{branch}"
        remote(["git", "-C", str(repo), "worktree", "add", "--detach", str(worktree), source])
        remote(["git", "-C", str(worktree), "checkout", "--ignore-other-worktrees", "-B", branch, source])
    else:
        remote(["git", "-C", str(repo), "worktree", "add", "-b", branch, str(worktree), base])
    held = {} if slot is None else {"slot": slot}
    return launch(host, run_id, task=task.id, kind=kind, workdir=str(worktree), branch=branch,
                  base=base, brief=text, effort=EFFORTS.get(kind, task.effort), read_only=kind == "review",
                  sh=sh, log_path=log_path, **held)


def fetch_clone(host: Host, repo: str, *, sh: Runner = run) -> Path:
    """Make sure the builder has a fresh clone of repo and return its path there:
    `<remote_home(host)>/repos/<repo>`. Over ssh, each with check=True: `mkdir -p` of
    `<remote_home>/repos`, `/wt` and `/runs`; clone REMOTES[repo] into it when it has no .git (one bash
    -c test, as start does); `git -C <clone> fetch origin`. ValueError for a repo not in
    REMOTES, before any command. start uses it for every run; fab.call_review for review runs."""
    if repo not in REMOTES:
        raise ValueError(f"unknown repository {repo!r}")
    root = Path(remote_home(host))
    clone = root / "repos" / repo
    sh(ssh(host.ssh, ["mkdir", "-p", str(clone.parent), str(root / "wt"), str(root / "runs")]),
       check=True)
    command = shlex.join(["git", "clone", "--", REMOTES[repo], str(clone)])
    sh(ssh(host.ssh, ["bash", "-c",
                    f"if ! test -d {shlex.quote(str(clone / '.git'))}; then {command}; fi"]),
       check=True)
    sh(ssh(host.ssh, ["git", "-C", str(clone), "fetch", "origin"]), check=True)
    return clone


def launch(host: Host, run_id: str, *, task: str, kind: str, workdir: str, branch: str,
           base: str, brief: str, effort: str, read_only: bool = False, sh: Runner = run,
           log_path: Path | None = None, **fields) -> str:
    """Start Codex on host in workdir, a checkout the caller prepared, log run.started and
    return run_id. start uses it for every run; fab.call_review for review runs.

    Over ssh, check=True: write brief to `<remote_home(host)>/runs/<run>/brief.md` (mkdir -p
    its directory, `cat` to brief.md.tmp, then `mv`, in one bash -c with the brief on stdin);
    keep a copy at this machine's FAB_HOME/runs/<run>/brief.md (fab.atomic.write); then LAUNCHER's
    command, `fab codex start --effort <effort> --model MODEL` or `codex-run task --effort <effort>
    --model MODEL --to
    NOTIFY`, with `--read-only` when read_only, then BRIEF, workdir and REPORT, REPORT being
    `<remote_home(host)>/runs/<run>/report.md`. Its output must be `<id> <absolute state
    directory>` on one line, else ValueError. run.started carries run, task, kind, host
    (host.name), dir (workdir), branch, base, codex (the id), state, report (REPORT) and
    fields, flat as fab.log.record takes them."""
    directory = Path(remote_home(host)) / "runs" / run_id
    brief_path, report_path = directory / "brief.md", directory / "report.md"
    temporary = brief_path.with_name("brief.md.tmp")
    write = (shlex.join(["mkdir", "-p", str(directory)])
             + f" && cat > {shlex.quote(str(temporary))} && "
             + shlex.join(["mv", "--", str(temporary), str(brief_path)]))
    sh(ssh(host.ssh, ["bash", "-c", write]), input=brief, check=True)
    atomic.write(log.home() / "runs" / run_id / "brief.md", brief)
    if LAUNCHER == "fab":
        command = ["fab", "codex", "start", "--effort", effort, "--model", MODEL]
    else:
        command = ["codex-run", "task", "--effort", effort, "--model", MODEL, "--to", NOTIFY]
    if read_only:
        command.append("--read-only")
    result = sh(ssh(host.ssh, [*command, str(brief_path), workdir, str(report_path)]), check=True)
    response = result.out.strip()
    answer = response.split(maxsplit=1)
    if len(answer) != 2 or not answer[1].startswith("/") or "\n" in response or "\r" in response:
        raise ValueError("codex-run did not return an id and absolute state directory")
    codex, state = answer
    log.append("run.started", path=log_path, run=run_id, task=task, kind=kind,
               host=host.name, dir=workdir, branch=branch, base=base,
               codex=codex, state=state, report=str(report_path), **fields)
    return run_id


def status(started: dict, host: Host, *, sh: Runner = run) -> dict:
    """Whether a run has ended, from its run.started record: one ssh reading the launcher's
    `<state>/ended` marker and, once ended, `<state>/result.json` and the report. The script
    prints `running`, or `ended`, then result.json's first line (an empty line when it is
    missing), then the report (nothing when it is missing), each part after a newline.
    Returns {"run", "ended", "outcome", "report", "tokens"}; outcome and report are None
    until ended; tokens is fab.codex.tokens_field of the result line, None until ended and
    when the line gives none."""
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


def launch_detached(host: Host, run_id: str, repo: str, rev: str, *, sh: Runner = run,
                    log_path: Path | None = None, **launched) -> str:
    """Start a read-only run on host in a fresh worktree of repo detached at rev; return
    run_id. Review runs (fab.call_review) and foreman runs (fab.foreman) start this way.

    clone = fetch_clone(host, repo, sh=sh); the worktree `<remote_home(host)>/wt/<run_id>`,
    added with `git -C <clone> worktree add --detach <worktree> <rev>` over ssh (check=True);
    then launch(host, run_id, workdir=<worktree>, read_only=True, sh=sh, log_path=log_path,
    **launched), launched holding launch's other keywords (task, kind, branch, base, brief,
    effort and run.started's extra fields). A failure after the worktree is added removes it
    (`git -C <clone> worktree remove --force <worktree>` over ssh, errors ignored) and
    re-raises. collect frees the worktree when the run ends, as for any worktree run."""
    raise NotImplementedError


def collect(run_id: str, events: Iterable[dict], hosts: dict[str, Host], *, sh: Runner = run,
            log_path: Path | None = None) -> str | None:
    """Collect an ended run once: copy its report to FAB_HOME/runs/<run>/report.md here, log
    run.ended (run, task, outcome, report, minutes since run.started, and tokens when status
    gives them, 13.5) and, for a question,
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
    atomic.write(report_path, current["report"])
    stamp = log.now()
    minutes = max(0.0, (datetime.fromisoformat(stamp)
                       - datetime.fromisoformat(started["ts"])).total_seconds() / 60)
    freed = {}
    try:
        if "slot" in started:
            result = sh(ssh(host.ssh, ["fab", "slot", "release", str(started["slot"]), run_id]),
                        check=True)
            freed["freed"] = int(result.out.strip())
        else:
            sh(ssh(host.ssh, ["git", "-C", started["dir"], "worktree", "remove", "--force",
                              started["dir"]]), check=True)
    except (OSError, ValueError, Failed) as error:
        freed["free_error"] = str(error)
    log.append("run.ended", path=log_path, ts=stamp, run=run_id, task=started["task"],
               outcome=current["outcome"], report=str(report_path), minutes=minutes, **freed)
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


def _rejection(rejection: dict | None, *, sh: Runner) -> dict | None:
    """Supply findings or a gate-log excerpt without changing the rejection record."""
    if rejection is not None:
        if "findings" in rejection:
            red = rejection["findings"]
        else:
            try:
                gates = sorted((host for host in hosts.load().values() if "gate" in host.roles),
                               key=lambda host: host.name)
                if not gates:
                    raise ValueError("no gate host configured")
                red = rejection_text(rejection, gates[0], sh=sh)
            except (OSError, ValueError) as error:
                red = "(log unreadable: " + " ".join(str(error).splitlines()) + ")"
        rejection = {**rejection, "text": red}
    return rejection
