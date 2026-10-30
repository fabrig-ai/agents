"""The gates: code's checks of a branch's structure before it lands (docs/design/fab.md, 12).

Not fabrig's check steps (fab/gate.py). These read the branch's digest (fab/digest.py) and
its task, and are pure; `screen` is the shell around them that the tick calls before it lands
a task's branch. A finding rejects the branch with step `gate:<name>`, and the repair loop
takes it as it takes a red landing.
"""

from __future__ import annotations

import fcntl
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from fab import atomic, digest, log, run as runs
from fab.digest import SIZE_CAP, Digest
from fab.plan import Task
from fab.sh import Runner, run

REPOS = ("agents",)  # repositories whose branches are gated: the first gates read Python
GATES = ("files", "shape", "size", "names", "docs", "clones")
PARSE = "parse"  # the finding's gate when the tip's Python does not parse
EXEMPT = ("interface", "migration")  # task kinds that may change or remove a signature


@dataclass(frozen=True)
class Finding:
    gate: str  # one of GATES, or PARSE
    text: str  # one line, Markdown


def banned_names(taste: str) -> frozenset[str]:
    """The banned names of a taste file's text (fab/taste.md), lowercased: the first
    backquoted word of each line starting with "- `" between the `## Banned names` heading
    and the next `## ` heading. No such heading: none."""
    active = False
    names = set()
    for line in taste.splitlines():
        if active and line.startswith("## "):
            break
        if line == "## Banned names":
            active = True
        elif active and line.startswith("- `"):
            word, closing, _ = line[3:].partition("`")
            if closing:
                names.add(word.lower())
    return frozenset(names)


def words(name: str) -> list[str]:
    """The lowercased words of an identifier: split at underscores, then before each capital
    that starts a word and between letters and digits. `fetch_all` -> fetch, all;
    `TaskView` -> task, view; `HTTPError` -> http, error; `sha256` -> sha, 256;
    `_private_x` -> private, x."""
    result = []
    for part in name.split("_"):
        start = 0
        for i in range(1, len(part)):
            previous, current = part[i - 1], part[i]
            digit_edge = (previous.isalpha() and current.isdigit()
                          or previous.isdigit() and current.isalpha())
            capital_edge = current.isupper() and (
                previous.islower() or previous.isupper()
                and i + 1 < len(part) and part[i + 1].islower())
            if digit_edge or capital_edge:
                result.append(part[start:i].lower())
                start = i
        if part:
            result.append(part[start:].lower())
    return result


def check(digest: Digest, banned: Iterable[str]) -> list[Finding]:
    """Every gate's findings, the gates in GATES order and each gate's in the digest's order.
    Names are written in backquotes as shown.

    - files: per path of digest.outside: "`<path>` is outside the task's files".
    - shape, unless digest.kind is in EXEMPT: per removed item "`<module>`: `<text>` removed",
      then per changed pair "`<module>`: `<base text>` changed to `<tip text>`".
    - size: per digest.long: "`<module>:<start>` <name> is <lines> lines (cap <SIZE_CAP>)".
    - names: per new module (its file stem) then per added item (the last dotted component
      of its name), the first of its words() that banned holds (compared lowercased):
      "`<path>` uses the banned word `<word>`" for a module,
      "`<module>`: `<name>` uses the banned word `<word>`" for an item.
    - docs: per added item whose doc is empty: "`<module>`: `<text>` has no docstring".
    - clones: per clone: "`<path>:<start>-<end>` repeats `<other>:<other_start>`"."""
    findings = [Finding("files", f"`{path}` is outside the task's files")
                for path in digest.outside]
    if digest.kind not in EXEMPT:
        findings.extend(Finding("shape", f"`{item.module}`: `{item.text}` removed")
                        for item in digest.removed)
        findings.extend(Finding("shape", f"`{base.module}`: `{base.text}` changed to `{tip.text}`")
                        for base, tip in digest.changed)
    findings.extend(Finding("size", f"`{item.module}:{item.start}` {item.name} is "
                            f"{item.lines} lines (cap {SIZE_CAP})")
                    for item in digest.long)
    banned = frozenset(word.lower() for word in banned)
    for path in digest.modules:
        word = next((word for word in words(Path(path).stem) if word in banned), None)
        if word is not None:
            findings.append(Finding("names", f"`{path}` uses the banned word `{word}`"))
    for item in digest.added:
        word = next((word for word in words(item.name.rsplit(".", 1)[-1])
                     if word in banned), None)
        if word is not None:
            findings.append(Finding("names", f"`{item.module}`: `{item.name}` "
                                    f"uses the banned word `{word}`"))
    findings.extend(Finding("docs", f"`{item.module}`: `{item.text}` has no docstring")
                    for item in digest.added if not item.doc)
    findings.extend(Finding("clones", f"`{item.path}:{item.start}-{item.end}` repeats "
                            f"`{item.other}:{item.other_start}`")
                    for item in digest.clones)
    return findings


def findings_text(findings: Sequence[Finding]) -> str:
    """The findings for a rejection and the repair brief: per gate in order of its first
    finding, a line `[gate:<gate>]`, then one `- <text>` line per finding; ends with a newline.
    fab.run.brief quotes it from the first header on (it finds `[<step>]`)."""
    grouped = {}
    for finding in findings:
        grouped.setdefault(finding.gate, []).append(finding.text)
    return "".join(f"[gate:{gate}]\n" + "".join(f"- {text}\n" for text in texts)
                   for gate, texts in grouped.items())


def screen(task: Task, events: Iterable[dict], *, sh: Runner = run,
           log_path: Path | None = None) -> list[Finding]:
    """Gate a task's branch before it lands; return the findings (empty: it may land).

    The run is the task's last run.started in events (none: ValueError naming the task) and
    the branch that record's. Under an exclusive flock on FAB_HOME/land-agents.lock (fab
    land's, so no landing moves the clone meanwhile), in the clone FAB_HOME/repos/<task.repo>
    (cloned from fab.run.REMOTES[task.repo] when it has no .git): `git fetch origin --prune`;
    the tip `git rev-parse --verify refs/remotes/origin/<branch>^{commit}`; the base
    `git merge-base refs/remotes/origin/main <tip>`; fab.digest.changes(base, tip); both trees
    by fab.digest.archive into `base` and `tip` of a temporary directory under FAB_HOME,
    removed afterwards; fab.digest.build; its render written to FAB_HOME/digests/<run>.md with
    fab.atomic.write. Every git command runs with check=True, so a git failure raises
    fab.sh.Failed, writes no digest and logs nothing. The lock is released before logging.

    Then the findings are check(digest, banned_names(fab.run.TASTE's text)). A SyntaxError
    from build is instead one finding of gate PARSE, "`<filename>:<lineno>` <msg>", with no
    digest written. Any findings: log branch.rejected (task, branch, tip, step
    `gate:<the first finding's gate>`, log the digest's path or "" without one, findings
    findings_text(findings)). The task's status becomes rejected and decide starts a repair."""
    started = next((event for event in reversed(list(events))
                    if event.get("ev") == "run.started" and event.get("task") == task.id), None)
    if started is None:
        raise ValueError(f"{task.id}: no run.started")
    branch, run_id = started["branch"], started["run"]
    home = log.home()
    home.mkdir(parents=True, exist_ok=True)
    repo = home / "repos" / task.repo
    written = ""
    with open(home / "land-agents.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not (repo / ".git").exists():
            repo.parent.mkdir(parents=True, exist_ok=True)
            sh(["git", "clone", runs.REMOTES[task.repo], str(repo)], check=True)
        sh(["git", "fetch", "origin", "--prune"], cwd=str(repo), check=True)
        tip = sh(["git", "rev-parse", "--verify", f"refs/remotes/origin/{branch}^{{commit}}"],
                 cwd=str(repo), check=True).out.strip()
        base = sh(["git", "merge-base", "refs/remotes/origin/main", tip],
                  cwd=str(repo), check=True).out.strip()
        changed = digest.changes(repo, base, tip, sh=sh)
        with tempfile.TemporaryDirectory(dir=home) as directory:
            before = digest.archive(repo, base, Path(directory) / "base", sh=sh)
            after = digest.archive(repo, tip, Path(directory) / "tip", sh=sh)
            try:
                summary = digest.build(task, run_id, branch, base, tip, changed, before, after)
            except SyntaxError as error:
                findings = [Finding(PARSE, f"`{error.filename}:{error.lineno}` {error.msg}")]
            else:
                written = str(home / "digests" / f"{run_id}.md")
                atomic.write(Path(written), digest.render(summary))
                findings = check(summary, banned_names(runs.TASTE.read_text(encoding="utf-8")))
    if findings:
        log.append("branch.rejected", path=log_path, task=task.id, branch=branch, tip=tip,
                   step=f"gate:{findings[0].gate}", log=written, findings=findings_text(findings))
    return findings
