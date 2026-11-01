"""`fab run`: start a Codex run on a builder, read its outcome, collect it (docs/design/fab-tick.md, 3)."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from fab import atomic, codex, hosts, log, plan
from fab.hosts import Host
from fab.plan import Task
from fab.sh import Failed, Runner, run, ssh

KINDS = ("implement", "repair", "rebase", "review")
OUTCOMES = {"Done:": "done", "Question:": "question", "Infra:": "infra", "Failed:": "failed"}
REMOTES = {"agents": "git@github.com:fabrig-ai/agents.git", "fabrig": "git@github.com:fabrig-ai/fabrig.git"}
ROLE = Path(__file__).resolve().parent / "roles" / "implementer.md"
TASTE = Path(__file__).resolve().parent / "taste.md"  # banned names and pairs for the standard role
NOTIFY = "fab@hel8"  # codex-run posts its end here; nothing waits on it
MODEL = "gpt-6.1-sol"  # every Codex run's model, explicit (the user, 10-30): Sol 6.1
# The Codex efforts the user's model sets by role (execution-modes.md): implementers high,
# reviewers medium; a task spec's effort applies only to kinds not named here.
EFFORTS = {"implement": "high", "repair": "high", "rebase": "high", "review": "medium"}
SLOTTED = ("fabrig",)  # repositories whose runs build in a builder's warm slot
LANDED = ("agents",)  # repositories fab land lands: a refusal's log is its detail, not a path
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


def role_text(repo: str, trunk: str = "main") -> str:
    """The implementer's role text, then the taste file (TASTE), then the repository's notes
    (fab/roles/<repo>.md) when it has any, each separated by one blank line. A non-main
    trunk uses fab/roles/<repo>-integration.md instead when it exists. For fabrig on
    a non-main trunk, fab/roles/fabrig-run.md is the entire role text."""
    if repo == "fabrig" and trunk != "main":
        return ROLE.with_name("fabrig-run.md").read_text()
    notes = ROLE.with_name(f"{repo}.md")
    integration = ROLE.with_name(f"{repo}-integration.md")
    if trunk != "main" and integration.exists():
        notes = integration
    texts = [ROLE.read_text(), TASTE.read_text()]
    if notes.exists():
        texts.append(notes.read_text())
    return "\n\n".join(text.rstrip("\n") for text in texts) + "\n"


def brief(task: Task, role: str, *, run_id: str, branch: str, base: str, report: str,
          rejection: dict | None = None, trunk: str = "main") -> str:
    """The brief Codex gets: the role text, then a `# Your task` section listing run, branch,
    base, report path, the files it may change and the expected minutes, then the spec's body.
    A non-main trunk adds a Trunk fact after Base, naming origin/<trunk>.
    A rejection adds the failed step and queue log between the facts and body; start supplies
    its log text in `text`. A non-empty rejection section is quoted verbatim after the
    facts, followed by a blank line before the refusal. Only the last matching step, at
    most 120 lines, is included."""
    files = ", ".join(task.files) or "(none)"
    trunk_fact = f"- Trunk: `origin/{trunk}`\n" if trunk != "main" else ""
    refusal, section = "", ""
    if rejection is not None:
        section = rejection.get("section", "")
        if section:
            section += "\n" if section.endswith("\n") else "\n\n"
        step = rejection.get("step", "unknown")
        text = rejection.get("text", "(log unreadable: no log text)")
        quoted = ("\n".join(text.splitlines()[:120]) if "findings" in rejection
                  else excerpt(step, text))
        refusal = ("## The landing refused this branch\n\n"
                   "The landing's checks failed; reproduce this first, in the lowest tier "
                   "that shows it. If it does not reproduce, say so in your report's first line.\n\n"
                   f"- Step: `{step}`\n"
                   f"- Queue log: `{rejection.get('log', '(missing)')}`\n\n"
                   f"```text\n{quoted}\n```\n\n")
    return (f"{role.rstrip()}\n\n# Your task\n\n"
            f"- Task: {task.id} (spec `{task.path}`)\n"
            f"- Repository: {task.repo}\n"
            f"- Run: {run_id}\n"
            f"- Branch: `{branch}`\n"
            f"- Base: `{base}`\n"
            f"{trunk_fact}"
            f"- Report: write it to `{report}`\n"
            f"- Files you may change: {files}\n"
            f"- Expected: about {task.minutes} implementer-minutes\n\n"
            f"{section}{refusal}{task.body}")


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


def excerpt(step: str, text: str) -> str:
    """The lines of a queue log that a brief quotes for a refusal at step, joined by newlines:
    from the last line starting `[<step>]` up to the next line starting `[` that holds
    ` (cwd ` (not included), at most 120 lines. A text starting `(log unreadable:` is kept
    as it is (cut at 120 lines); a text without the step's line gives the one line
    `(log unreadable: step [<step>] not found)`. brief's cut, moved here unchanged: brief
    calls it for a rejection without findings. Pure."""
    lines = text.splitlines()
    if not text.startswith("(log unreadable:"):
        starts = [i for i, line in enumerate(lines) if line.startswith(f"[{step}]")]
        if starts:
            lines = lines[starts[-1]:]
            end = next((i for i, line in enumerate(lines[1:], 1)
                        if line.startswith("[") and " (cwd " in line), len(lines))
            lines = lines[:end]
        else:
            lines = [f"(log unreadable: step [{step}] not found)"]
    return "\n".join(lines[:120])


def refusal_text(record: dict, repo: str, *, sh: Runner = run) -> str:
    """The lines a foreman's brief quotes for a refusal (a branch.rejected record) of a
    branch of repo, at most 120 of them:
    - its `findings` when it has them (the gates', fab.gates.screen), read from no machine;
    - for repo in LANDED, its `log`, which is fab land's detail text, not a path ("(log
      unreadable: rejection has no log)" when it has none);
    - otherwise excerpt(step, rejection_text(record, <the first gate host by name in
      fab.hosts.load()>, sh=sh)); no gate host, or hosts that cannot be loaded, gives `(log
      unreadable: <why>)`.
    Never raises for an unreadable log."""
    if "findings" in record:
        text = record["findings"]
    elif repo in LANDED:
        text = record.get("log") or "(log unreadable: rejection has no log)"
    else:
        return excerpt(record.get("step", "unknown"), _gate_log(record, sh=sh))
    return "\n".join(text.splitlines()[:120])


def start(task: Task, host: Host, *, kind: str = "implement", events: Iterable[dict] = (),
          sh: Runner = run, log_path: Path | None = None, rejection: dict | None = None,
          trunk: str = "main", checkout: Path | None = None,
          early: Sequence[tuple[str, str]] = ()) -> str:
    """Start a run of task on host and log run.started; return the run id.

    early names (need, branch) for each need not merged yet whose pushed work the run starts
    from (docs/design/fab-integration.md, 3): each origin/<branch> is merged into the
    run's checkout after it is set up, in order, and the brief says so; a merge that conflicts
    aborts the start with a ValueError beginning `early:`. run.started carries early (the needs).

    With checkout, an absolute task.path inside it is repository-relative in the brief;
    paths outside it, paths already relative and checkout=None keep their given spelling.
    First move an unpinned builder install forward to this package's HEAD; failures only note
    stderr. Dispatcher hosts are skipped (docs/design/fab-tick.md, 3).
    On the builder, over ssh: make sure FAB_HOME/repos/<task.repo> is a clone of
    REMOTES[task.repo] and fetch it; add the worktree FAB_HOME/wt/<run> on the branch
    (implement, review, rebase: the branch made afresh from origin/<trunk>, an earlier run's local branch reset; repair: the existing
    origin/<branch>); write the brief to FAB_HOME/runs/<run>/brief.md; then
    `codex-run task --effort <task.effort> --to NOTIFY BRIEF WORKTREE REPORT`, REPORT being
    FAB_HOME/runs/<run>/report.md, review adding --read-only. codex-run prints `<id> <state>`.
    The brief is also kept on this machine at FAB_HOME/runs/<run>/brief.md. run.started carries
    run, task, kind, host, dir (the worktree), branch, base ("origin/<trunk>", or the checked
    skeleton tip), codex (the id), state (codex-run's state directory) and report (the builder's
    report path).
    A task of a repository in SLOTTED builds in a slot instead of a worktree: claim the first
    idle slot (`fab slot list`, then `fab slot claim N RUN TASK`; none idle is a ValueError
    naming the host), then in `~/src/fabrig/slots/<n>` fetch origin and switch to the branch
    (`git clean -fdq`, then `git switch --discard-changes -C <branch> origin/<trunk>`, so an
    earlier run's edits never carry over and its untracked files never block the switch; repair: `origin/<branch>`). dir is the slot, and
    run.started also carries slot (the number). The launcher is `fab codex start` (same
    arguments and output as codex-run task) once LAUNCHER says so.

    A rejection's text is its `findings` when it has them (a gate's, fab.gates.screen), read
    from no machine; otherwise rejection_text from the first gate host.
    """
    if checkout is not None and Path(task.path).is_absolute():
        try:
            spec = Path(task.path).resolve().relative_to(checkout.resolve()).as_posix()
        except ValueError:
            pass
        else:
            task = replace(task, path=spec)
    events = list(events)
    branch = branch_for(task, kind, events)
    if task.repo not in REMOTES:
        raise ValueError(f"unknown repository {task.repo!r}")
    run_id = next_run(task.id, events)
    root = Path(remote_home(host))
    worktree = root / "wt" / run_id
    directory = root / "runs" / run_id
    brief_path, report_path = directory / "brief.md", directory / "report.md"
    base = f"origin/{trunk}"
    from fab import call_review
    source = call_review.task_source(task, events)
    if source is not None and kind != "rebase":
        base = source[0]["tip"]
    _sync_install(host, sh=sh)
    rejection = _rejection(rejection, sh=sh)
    text = brief(task, role_text(task.repo, trunk), run_id=run_id, branch=branch, base=base,
                 report=str(report_path), rejection=rejection, trunk=trunk)
    if early:
        text += early_section(early)
    def remote(argv, *, input=None):
        return sh(ssh(host.ssh, argv), input=input, check=True)

    repo = fetch_clone(host, task.repo, sh=sh)
    if rejection is not None and "skeleton" in rejection:
        text = _rebase_brief(task, host, repo, events, rejection, run_id=run_id,
                             branch=branch, report=str(report_path), sh=sh, trunk=trunk)
    try:
        return _prepare_and_launch(task, host, kind, sh, run_id=run_id, branch=branch,
                                   base=base, root=root, repo=repo, worktree=worktree,
                                   brief_path=brief_path, report_path=report_path, text=text,
                                   log_path=log_path, early=early)
    except BaseException:
        # A start that fails part way gives back what it took, so the next start finds it free.
        _undo_start(task, remote, run_id=run_id, branch=branch, repo=repo, worktree=worktree)
        raise


def _sync_install(host: Host, *, sh: Runner) -> None:
    """Advance an unpinned ancestor install; any failure leaves the start free to proceed."""
    if "dispatcher" in host.roles:
        return
    try:
        package = Path(__file__).resolve().parent.parent
        tip = sh(["git", "-C", str(package), "rev-parse", "HEAD"], check=True).out.strip()
        if len(tip) not in (40, 64) or any(char not in "0123456789abcdef" for char in tip):
            raise ValueError("package HEAD is not a commit hash")
        root = Path(remote_home(host))
        git = shlex.join(["git", "-C", str(root / "install")])
        script = (f'if test -e {shlex.quote(str(root / "install.pinned"))}; then '
                  "printf '%s\\n' 'install pinned'; exit 0; fi; "
                  f'{git} fetch origin && head=$({git} rev-parse HEAD) && '
                  f'if test "$head" = {tip}; then :; else '
                  f'{git} merge-base --is-ancestor "$head" {tip}; ancestry=$?; '
                  f'if test "$ancestry" = 0; then {git} checkout -q --detach {tip}; '
                  'elif test "$ancestry" != 1; then exit "$ancestry"; fi; fi')
        result = sh(ssh(host.ssh, ["flock", "-w", "60", str(root / "install.lock"),
                                 "bash", "-c", script]), check=True, timeout=120)
        if result.out.strip() == "install pinned":
            print(f"fab run: {host.name}: install pinned", file=sys.stderr)
    except (OSError, Failed, ValueError) as error:
        detail = (error.result.err or error.result.out or f"exit {error.result.code}"
                  if isinstance(error, Failed) else str(error))
        print(f"fab run: {host.name}: install sync failed: {' '.join(detail.splitlines())}",
              file=sys.stderr)


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
                        report_path: Path, text: str, log_path: Path | None,
                        early: Sequence[tuple[str, str]] = ()) -> str:
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
        # A rerun continues from the work its earlier run pushed (the implementer pushes before
        # it asks: fabrig-run.md), rather than redoing it from the trunk.
        if kind == "implement" and sh(ssh(host.ssh, ["git", "-C", str(worktree), "rev-parse", "-q", "--verify",
                                                     f"refs/remotes/origin/{branch}"])).ok:
            source = f"origin/{branch}"
        # A slot keeps only its build cache between runs: an earlier run's uncommitted edits
        # and untracked files go (ignored files, target/ among them, stay warm). Clean first:
        # an untracked file the new base tracks stops the switch (the playground replay, 10-31).
        remote(["git", "-C", str(worktree), "clean", "-fdq"])
        remote(["git", "-C", str(worktree), "switch", "--discard-changes", "-C", branch, source])
        if kind == "implement" and source != base:
            # The continued branch catches up with the trunk, which may now hold the needs it
            # started early on (the playground replay, 11-01: fe-world-remove reran three times
            # asking for its merged needs). A conflict is left for the run: it is aborted here.
            caught = sh(ssh(host.ssh, ["git", "-C", str(worktree), "-c", "user.name=fab", "-c",
                                       "user.email=fab@localhost", "merge", "--no-edit", base]))
            if not caught.ok:
                sh(ssh(host.ssh, ["git", "-C", str(worktree), "merge", "--abort"]))
    elif kind == "repair":
        source = f"origin/{branch}"
        remote(["git", "-C", str(repo), "worktree", "add", "--detach", str(worktree), source])
        remote(["git", "-C", str(worktree), "checkout", "--ignore-other-worktrees", "-B", branch, source])
    else:
        # -B, not -b: an earlier run's local branch stays in the clone after its worktree goes,
        # and -b refused every rerun's start once (findings-loop, 11-01).
        remote(["git", "-C", str(repo), "worktree", "add", "-B", branch, str(worktree), base])
    for need, need_branch in early:
        merged = sh(ssh(host.ssh, ["git", "-C", str(worktree), "-c", "user.name=fab", "-c",
                                   "user.email=fab@localhost", "merge", "--no-edit", f"origin/{need_branch}"]))
        if not merged.ok:
            sh(ssh(host.ssh, ["git", "-C", str(worktree), "merge", "--abort"]))
            raise ValueError(f"early: {need}'s pushed work conflicts with the base")
    held = {} if slot is None else {"slot": slot}
    if early:
        held["early"] = [need for need, _ in early]
    return launch(host, run_id, task=task.id, kind=kind, workdir=str(worktree), branch=branch,
                  base=base, brief=text, effort=EFFORTS.get(kind, task.effort), read_only=kind == "review",
                  sh=sh, log_path=log_path, **held)


def early_section(early: Sequence[tuple[str, str]]) -> str:
    """The brief's section for an early start: the needs whose pushed work is in its base."""
    lines = "\n".join(f"- {need}: `origin/{branch}`" for need, branch in early)
    return ("\n\n# Started early\n\nThese needs have not merged yet; the work each has pushed so far "
            f"is merged into your base:\n\n{lines}\n\nWhat you build on may still change. When you "
            "need more of it, and before you push, `git fetch origin` and merge each branch again "
            "(`git merge --no-edit origin/<branch>`); a conflict there is yours to resolve. fab merges "
            "your branch into the trunk only after these needs have merged.\n")


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
           log_path: Path | None = None, command: Sequence[str] | None = None, **fields) -> str:
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
    fields, flat as fab.log.record takes them. With command, append BRIEF, workdir and
    REPORT to that command instead of the Codex launcher."""
    directory = Path(remote_home(host)) / "runs" / run_id
    brief_path, report_path = directory / "brief.md", directory / "report.md"
    temporary = brief_path.with_name("brief.md.tmp")
    write = (shlex.join(["mkdir", "-p", str(directory)])
             + f" && cat > {shlex.quote(str(temporary))} && "
             + shlex.join(["mv", "--", str(temporary), str(brief_path)]))
    sh(ssh(host.ssh, ["bash", "-c", write]), input=brief, check=True)
    atomic.write(log.home() / "runs" / run_id / "brief.md", brief)
    if command is None:
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
    result_path = shlex.quote(str(Path(started["state"]) / "result.json"))
    script = (f"if test -f {marker}; then printf 'ended\\n'; "
              f"line=; if test -f {result_path}; then IFS= read -r line < {result_path} || :; fi; "
              "printf '%s\\n' \"$line\"; "
              f"if test -f {report_path}; then cat -- {report_path}; fi; "
              "else printf 'running\\n'; fi")
    result = sh(ssh(host.ssh, ["bash", "-c", script]), check=True)
    state, _, rest = result.out.partition("\n")
    result_line, _, report = rest.partition("\n")
    if state not in ("running", "ended"):
        raise ValueError(f"{started['run']}: invalid status response")
    ended = state == "ended"
    return {"run": started["run"], "ended": ended,
            "outcome": outcome(report) if ended else None, "report": report if ended else None,
            "tokens": codex.tokens_field(result_line) if ended else None}


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
    clone = fetch_clone(host, repo, sh=sh)
    worktree = str(Path(remote_home(host)) / "wt" / run_id)
    sh(ssh(host.ssh, ["git", "-C", str(clone), "worktree", "add", "--detach", worktree, rev]),
       check=True)
    try:
        return launch(host, run_id, workdir=worktree, read_only=True, sh=sh,
                      log_path=log_path, **launched)
    except BaseException:
        try:
            sh(ssh(host.ssh, ["git", "-C", str(clone), "worktree", "remove", "--force", worktree]))
        except Exception:
            pass
        raise


def collect(run_id: str, events: Iterable[dict], hosts: dict[str, Host], *, sh: Runner = run,
            log_path: Path | None = None) -> str | None:
    """Collect an ended run once: copy its report to FAB_HOME/runs/<run>/report.md here, log
    run.ended (run, task, outcome, report, minutes since run.started, and tokens when status
    gives them, fab-reports.md 3) and, for a question,
    question.asked with the report's first 15 lines as text; for a failed implement, repair or
    rebase run that did not start early, the same with park = true (fab-calls.md 2). Returns the outcome; None while the
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
    fields = {"tokens": current["tokens"]} if current["tokens"] is not None else {}
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
               outcome=current["outcome"], report=str(report_path), minutes=minutes, **fields, **freed)
    if current["outcome"] == "question":
        log.append("question.asked", path=log_path, task=started["task"], run=run_id,
                   text="\n".join(current["report"].splitlines()[:15]))
    elif (current["outcome"] == "failed" and started.get("kind") in ("implement", "repair", "rebase")
          and not started.get("early")):
        # A failed task run parks for judgement as a park does, so the answerer takes it at once
        # (findings-loop, 11-01: ladder-plan's failed repair sat parked and unheard).
        log.append("question.asked", path=log_path, task=started["task"], run=run_id,
                   text="\n".join(current["report"].splitlines()[:15]), park=True)
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
        red = rejection["findings"] if "findings" in rejection else _gate_log(rejection, sh=sh)
        rejection = {**rejection, "text": red}
    return rejection


def _gate_log(record: dict, *, sh: Runner) -> str:
    """Read the queue log on the first gate by name, or return an unreadable diagnostic."""
    try:
        gates = sorted((host for host in hosts.load().values() if "gate" in host.roles),
                       key=lambda host: host.name)
        if not gates:
            raise ValueError("no gate host configured")
        return rejection_text(record, gates[0], sh=sh)
    except (OSError, ValueError) as error:
        return "(log unreadable: " + " ".join(str(error).splitlines()) + ")"


def _rebase_brief(task: Task, host: Host, repo: Path, events: Iterable[dict], rejection: dict, *,
                  run_id: str, branch: str, report: str, sh: Runner, trunk: str = "main") -> str:
    """Keep the task's commits while moving its checked skeleton base onto the amended trunk."""
    previous = next(event["branch"] for event in reversed(list(events))
                    if event.get("ev") == "run.started" and event.get("task") == task.id)
    diff = sh(ssh(host.ssh, ["git", "-C", str(repo), "diff", rejection["old_tip"], rejection["tip"]]),
              check=True).out
    instructions = ("## Rebase after the skeleton amendment\n\n"
                    f"On your branch `{branch}`, run `git reset --hard origin/{previous}`, "
                    f"then `git rebase --onto origin/{trunk} {rejection['old_tip']}`. "
                    "Resolve conflicts, check the result, and push your branch.\n\n"
                    "The skeleton's amendment:\n\n```diff\n" + diff + "\n```\n\n")
    return brief(task, role_text(task.repo, trunk), run_id=run_id, branch=branch, base=f"origin/{trunk}",
                 report=report, rejection={**rejection, "section": instructions}, trunk=trunk)
