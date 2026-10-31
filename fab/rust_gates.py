"""Minimal Rust old-form gates (docs/design/fab.md, 13.11).

Size remains a digest flag. A command or count failure raises so the branch waits.
"""

from __future__ import annotations

import fcntl
import tempfile
from collections.abc import Iterable
from pathlib import Path

from fab import atomic, log, run as runs, rust_digest
from fab.gates import Finding, findings_text
from fab.plan import Task
from fab.sh import Runner, run

REPOS = ("fabrig",)
GATES = ("ratchet",)


def check(digest: rust_digest.Digest) -> list[Finding]:
    """Ratchet findings in digest order; size and outside paths do not reject.

    Each per-tree form whose actual tip count exceeds its base count fails ratchet,
    naming the tree, form and both counts.
    """
    return [Finding("ratchet", f"`{entry.tree}`: `{entry.form}` rose from "
                    f"{entry.base} to {entry.tip}")
            for entry in digest.ratchets if entry.tip > entry.base and not entry.new]


def screen(task: Task, events: Iterable[dict], *, sh: Runner = run,
           log_path: Path | None = None, trunk: str = "main") -> list[Finding]:
    """Gate the task's last run.started branch, as fab.gates.screen does.

    Under FAB_HOME/land-<repo>.lock, clone if needed, fetch, resolve the remote tip and
    merge base with origin/<trunk>, numstat and archive both full trees. Run old_forms.py in
    each touched tree on both sides, build the digest and atomically write
    FAB_HOME/digests/<run>.md. Release the lock before logging branch.rejected with task,
    branch, tip, step gate:<first gate>, log the digest path and findings_text.

    No run.started raises ValueError. Git/script/parse failures raise, write no digest
    and log no rejection; callers must leave the branch waiting. Return all findings.
    """
    started = next((event for event in reversed(list(events))
                    if event.get("ev") == "run.started" and event.get("task") == task.id), None)
    if started is None:
        raise ValueError(f"{task.id}: no run.started")
    branch, run_id = started["branch"], started["run"]
    home = log.home()
    home.mkdir(parents=True, exist_ok=True)
    repo = home / "repos" / task.repo
    with open(home / f"land-{task.repo}.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not (repo / ".git").exists():
            repo.parent.mkdir(parents=True, exist_ok=True)
            sh(["git", "clone", runs.REMOTES[task.repo], str(repo)], check=True)
        sh(["git", "fetch", "origin", "--prune"], cwd=str(repo), check=True)
        tip = sh(["git", "rev-parse", "--verify", f"refs/remotes/origin/{branch}^{{commit}}"],
                 cwd=str(repo), check=True).out.strip()
        base = sh(["git", "merge-base", f"refs/remotes/origin/{trunk}", tip],
                  cwd=str(repo), check=True).out.strip()
        changes = rust_digest.changes(repo, base, tip, sh=sh)
        with tempfile.TemporaryDirectory(dir=home) as directory:
            before = rust_digest.archive(repo, base, Path(directory) / "base", sh=sh)
            after = rust_digest.archive(repo, tip, Path(directory) / "tip", sh=sh)
            counts = rust_digest.ratchets(before, after, [entry.path for entry in changes], sh=sh)
            summary = rust_digest.build(task, run_id, branch, base, tip, changes, before, after, counts)
            written = home / "digests" / f"{run_id}.md"
            findings = check(summary)
            atomic.write(written, rust_digest.render(summary))
    if findings:
        log.append("branch.rejected", path=log_path, task=task.id, branch=branch, tip=tip,
                   step=f"gate:{findings[0].gate}", log=str(written), findings=findings_text(findings))
    return findings
