"""Replace text files through siblings (AGENTS.md; docs/design/fab.md, 2 and 8)."""

import tempfile
from pathlib import Path


def write(path: Path, text: str) -> None:
    """Create parents and replace path with UTF-8 text through a new hidden sibling.

    Remove the sibling on failure, leaving the destination whole.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=f".{path.name}.", delete=False) as sibling:
        pending = Path(sibling.name)
        try:
            sibling.write(text)
            sibling.close()
            pending.replace(path)
        finally:
            pending.unlink(missing_ok=True)


def extend(path: Path, text: str) -> None:
    """Replace path with its UTF-8 text followed by text; a missing file starts empty."""
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        content = ""
    write(path, content + text)
