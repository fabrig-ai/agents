"""The gates: code's checks of a branch's structure before it lands (docs/design/fab.md, 12).

Not fabrig's check steps (fab/gate.py). These read the branch's digest (fab/digest.py) and
its task, and are pure; `screen` is the shell around them that the tick calls before it lands
a task's branch. A finding rejects the branch with step `gate:<name>`, and the repair loop
takes it as it takes a red landing.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

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
    raise NotImplementedError


def words(name: str) -> list[str]:
    """The lowercased words of an identifier: split at underscores, then before each capital
    that starts a word and between letters and digits. `fetch_all` -> fetch, all;
    `TaskView` -> task, view; `HTTPError` -> http, error; `sha256` -> sha, 256;
    `_private_x` -> private, x."""
    raise NotImplementedError


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
    raise NotImplementedError


def findings_text(findings: Sequence[Finding]) -> str:
    """The findings for a rejection and the repair brief: per gate in order of its first
    finding, a line `[gate:<gate>]`, then one `- <text>` line per finding; ends with a newline.
    fab.run.brief quotes it from the first header on (it finds `[<step>]`)."""
    raise NotImplementedError


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
    fab.run._write. Every git command runs with check=True, so a git failure raises
    fab.sh.Failed, writes no digest and logs nothing. The lock is released before logging.

    Then the findings are check(digest, banned_names(fab.run.TASTE's text)). A SyntaxError
    from build is instead one finding of gate PARSE, "`<filename>:<lineno>` <msg>", with no
    digest written. Any findings: log branch.rejected (task, branch, tip, step
    `gate:<the first finding's gate>`, log the digest's path or "" without one, findings
    findings_text(findings)). The task's status becomes rejected and decide starts a repair."""
    raise NotImplementedError
