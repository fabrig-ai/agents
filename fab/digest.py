"""A branch's structure digest: what a reviewer needs without reading the code
(docs/design/fab.md, 12).

The core reads two trees already on disk, the branch's base and its tip, each holding the
package (PACKAGE/), and the changed paths with their line counts. It says which public items
the branch adds, removes or changes (from fab.calls.inventory on both trees), which paths lie
outside its task's files, which new or changed functions are longer than SIZE_CAP and which
blocks of CLONE_LINES lines repeat. `render` turns that into deterministic Markdown of
bounded size; the gates (fab/gates.py) check the Digest itself. The shell is two git
commands: the numstat and an archive of each tree.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from fab.calls import Signature, inventory
from fab.plan import Task
from fab.sh import Runner, run

PACKAGE = "fab"  # the package the trees hold and inventory reads
SIZE_CAP = 60  # lines: a new or changed function longer than this is flagged
CLONE_LINES = 8  # kept lines: a block this long repeated elsewhere is flagged
LIST_CAP = 30  # entries per rendered list; the rest are counted, not shown
LINE_CAP = 160  # characters per rendered entry, cut with "..."
DIGEST_LIMIT = 8_000  # characters of the whole rendered digest
KINDS = ("production", "tests", "docs")


@dataclass(frozen=True)
class Change:
    path: str  # repository-relative, posix
    kind: str  # one of KINDS, from classify
    added: int  # lines; 0 for a binary file
    removed: int


@dataclass(frozen=True)
class Function:
    module: str  # repository-relative path, e.g. "fab/run.py"
    name: str  # qualified: "start", "Queue.cycle", "tick.take"
    start: int  # the `def` line, 1-based (decorators excluded)
    lines: int  # end_lineno - start + 1


@dataclass(frozen=True)
class Clone:
    path: str  # the changed file holding the repeated block
    start: int  # its first line, 1-based
    end: int  # its last line
    other: str  # where the same block also stands
    other_start: int  # its first line there


@dataclass(frozen=True)
class Digest:
    run: str
    task: str
    kind: str  # the task's kind (fab.plan.KINDS); the shape gate reads it
    branch: str
    base: str  # full sha
    tip: str  # full sha
    changes: tuple[Change, ...]  # sorted by path
    added: tuple[Signature, ...]  # public items at tip and not at base, tip order
    removed: tuple[Signature, ...]  # public items at base and not at tip, base order
    changed: tuple[tuple[Signature, Signature], ...]  # (base, tip) whose text differs, tip order
    modules: tuple[str, ...]  # new package modules (paths), sorted
    outside: tuple[str, ...]  # changed paths outside the task's files, sorted
    long: tuple[Function, ...]  # new or changed functions over SIZE_CAP, by (module, start)
    clones: tuple[Clone, ...]  # by (path, start, other, other_start)


def classify(path: str) -> str:
    """"tests" for a path under `<PACKAGE>/tests/` or whose file name starts with `test_`;
    "docs" for a path ending in `.md` or under `docs/`; "production" otherwise (bin/fab,
    fab/hosts.toml and every other module among them). Tests win over docs."""
    raise NotImplementedError


def outside(paths: Sequence[str], files: Sequence[str]) -> list[str]:
    """The paths no glob of files matches, sorted. A glob matches as
    `PurePosixPath(path).full_match(glob)` (Python 3.13: `*` stays within one component,
    `**` spans any). No files at all: every path is outside."""
    raise NotImplementedError


def items(base: Path, tip: Path) -> tuple[list[Signature], list[Signature],
                                          list[tuple[Signature, Signature]]]:
    """(added, removed, changed) between inventory(base, PACKAGE) and inventory(tip, PACKAGE),
    entries keyed by (module, name), the first entry of a key kept when a module defines a name
    twice. added: keys only at tip, in tip order; removed: keys only at base, in base order;
    changed: keys in both whose text differs, as (base entry, tip entry) in tip order. A
    docstring that changes alone is not a change. A tree without PACKAGE/ has no items."""
    raise NotImplementedError


def added_lines(before: str, after: str) -> set[int]:
    """The 1-based line numbers of after that are not carried over from before:
    difflib.SequenceMatcher(None, before lines, after lines, autojunk=False), the after side of
    every replace and insert opcode. before "" (a new file): every line of after."""
    raise NotImplementedError


def functions(module: str, text: str) -> list[Function]:
    """Every function and method in text, at any depth (nested ones too), from ast, in source
    order: name qualified by its enclosing classes and functions joined with ".", start the
    node's lineno (the `def` line), lines end_lineno - lineno + 1. A SyntaxError propagates."""
    raise NotImplementedError


def long_functions(module: str, before: str, after: str, cap: int = SIZE_CAP) -> list[Function]:
    """functions(module, after) longer than cap lines whose span [start, start + lines) holds
    at least one of added_lines(before, after): new or changed. A long function the branch did
    not touch, or only shortened, is not listed."""
    raise NotImplementedError


def clones(texts: Mapping[str, str], changed: Mapping[str, set[int]],
           size: int = CLONE_LINES) -> list[Clone]:
    """The blocks of the changed lines that repeat, sorted by (path, start, other, other_start).

    texts: every package module at tip (path to text); changed: for some of those paths, their
    added lines. A file's kept lines are its lines stripped, leaving out blank ones, comments
    (starting with "#") and imports (starting with "import " or "from "); each keeps its 1-based
    line number. A window is `size` consecutive kept lines of one file; its key is their
    stripped texts. A window of a changed path holding at least one added line is a clone when
    the same key stands at another window: in another file, or in the same file at least `size`
    kept lines away. Its match is the lowest (path, first line) among those. Windows of one
    path at consecutive kept indexes whose matches are in the same other file at consecutive
    kept indexes merge into one Clone: start the first window's first line, end the last
    window's last line, other_start the first match's first line."""
    raise NotImplementedError


def build(task: Task, run_id: str, branch: str, base_sha: str, tip_sha: str,
          changes: Sequence[Change], base: Path, tip: Path) -> Digest:
    """The digest of a branch from its changes (as `changes` returns them) and its two trees.

    In order: changes sorted by path; outside(their paths, task.files); items(base, tip);
    modules: the changes at `<PACKAGE>/<name>.py` (production) with no such file under base;
    long: long_functions for each production change at `<PACKAGE>/<name>.py` that exists under
    tip, with its text under base ("" when absent) and under tip; clones: clones over the texts
    of every module inventory reads at tip (`<PACKAGE>/*.py`, not tests), with the added lines
    of those same production changes. Files are read as UTF-8. A SyntaxError propagates."""
    raise NotImplementedError


def render(digest: Digest) -> str:
    """The digest as Markdown, ending with a newline, nothing in it varying between calls:

        # Digest: <run>

        - Task: <task> (<kind>)
        - Branch: `<branch>`
        - Base: `<base[:12]>`; tip: `<tip[:12]>`
        - Lines: production +A -R, tests +A -R, docs +A -R

        ## Changed paths
        ## Public items
        ## Outside the task's files
        ## Functions over <SIZE_CAP> lines
        ## Repeated blocks

    Each section is a list, `- none` when empty. Changed paths: `- `<path>` <kind> +A -R`.
    Public items: `- module added `<path>`` per new module, then `- added `<text>` (<module>)`
    with ` — <doc>` or ` — no docstring`, `- removed `<text>` (<module>)` and
    `- changed `<base text>` -> `<tip text>` (<module>)`. Outside: `- `<path>``. Functions:
    `- `<module>:<start>` <name>: <lines> lines`. Repeated: `- `<path>:<start>-<end>` repeats
    `<other>:<other_start>``. A list shows its first LIST_CAP entries then `- ... and <k> more`;
    an entry longer than LINE_CAP characters is cut to LINE_CAP - 3 and "...". When the whole
    is longer than DIGEST_LIMIT, it keeps the most whole lines from the start that leave room
    for a last line `(cut at <DIGEST_LIMIT> characters)`, so the result, final newline
    included, is at most DIGEST_LIMIT characters."""
    raise NotImplementedError


def changes(repo: Path, base: str, tip: str, *, sh: Runner = run) -> list[Change]:
    """`git diff --numstat -z --no-renames <base> <tip> --` in repo (check=True): each record
    `added<TAB>removed<TAB>path` ends with NUL; a binary file's `-` counts are 0. Each path
    gets its kind from classify. In git's order."""
    raise NotImplementedError


def archive(repo: Path, rev: str, dest: Path, *, sh: Runner = run) -> Path:
    """Extract rev's PACKAGE/ into dest (created; it must not exist) and return dest:
    `git archive --format=tar -o <dest>.tar <rev> -- <PACKAGE>` in repo (check=True), then
    tarfile extractall into dest with filter="data", then the tar removed. A rev without
    PACKAGE/ fails as git does (fab.sh.Failed)."""
    raise NotImplementedError
