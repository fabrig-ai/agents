"""Ladder plans on disk for findings-loop tests (docs/design/fab.md, 13.15)."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from fab import atomic


def write_ladder(directory: Path, draft: str = "ladder",
                 rungs: Mapping[str, tuple[str, Sequence[str]]] | None = None, *,
                 briefs: Mapping[str, str] | None = None) -> Path:
    """Write a sound queue ladder and its kit and rung briefs; return directory.
    Rungs map ids to (backend, after), default b0 then b1 on claude-forgejo.
    Briefs overrides text by plan-relative file path, also writing any extra files.
    """
    rungs = {"b0": ("claude-forgejo", ()), "b1": ("claude-forgejo", ("b0",))} if rungs is None else rungs
    lines = [f"draft = {json.dumps(draft)}", 'repo = "agents"', 'landing = "queue"',
             "[ladder]", 'happy_path = "docs/design/draft/path.md, 2 and 4"',
             'backlog = "docs/design/debt/ladder.md"']
    texts = {"briefs/kit.md": "The walk kit.\n"}
    for identifier, (backend, after) in rungs.items():
        path = f"briefs/{identifier}.md"
        lines += ["[[rung]]", f"id = {json.dumps(identifier)}", f"backend = {json.dumps(backend)}",
                  f"brief = {json.dumps(['briefs/kit.md', path])}", f"after = {json.dumps(list(after))}"]
        texts[path] = f"Walk {identifier}.\n"
    texts.update(briefs or {})
    atomic.write(directory / "plan.toml", "\n".join(lines) + "\n")
    for path, text in texts.items():
        atomic.write(directory / path, text)
    return directory
