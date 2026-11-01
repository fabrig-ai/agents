"""A rung's edition from its brief files at origin/main (docs/design/fab.md, 13.15)."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

from fab.plan import Plan
from fab.sh import Runner, run


def edition(files: Sequence[tuple[str, str]]) -> str:
    """First 12 hex of SHA-256 over ordered UTF-8 paths and texts, each NUL-terminated.
    Paths are spelled as in plan.toml. Pure; docs/design/fab.md, 13.15.
    """
    digest = hashlib.sha256()
    for path, text in files:
        digest.update(path.encode("utf-8") + b"\0")
        digest.update(text.encode("utf-8") + b"\0")
    return digest.hexdigest()[:12]


def editions(plan: Plan, plan_dir: Path, *, sh: Runner = run) -> dict[str, str]:
    """Each rung's edition in plan order, reading briefs at the checkout's origin/main.
    Find the checkout with git rev-parse, then git show each checkout-relative brief.
    Raise ValueError naming the rung and file when git show fails (docs/design/fab.md, 13.15).
    """
    if not plan.rungs:
        return {}
    directory = plan_dir.resolve()
    root = Path(sh(["git", "rev-parse", "--show-toplevel"],
                   cwd=str(directory), check=True).out.strip()).resolve()
    relative = directory.relative_to(root)
    result = {}
    for rung in plan.rungs.values():
        files = []
        for path in rung.brief:
            shown = sh(["git", "show", f"origin/main:{(relative / path).as_posix()}"],
                       cwd=str(root), check=False)
            if not shown.ok:
                raise ValueError(f"rung {rung.id}: cannot read brief {path} at origin/main")
            files.append((path, shown.out))
        result[rung.id] = edition(files)
    return result
