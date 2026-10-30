"""Whole-file writes through a hidden sibling (docs/design/fab.md, 2)."""

import tempfile
from pathlib import Path


def write(path: Path, text: str) -> None:
    """Create parents, write UTF-8 to a new hidden sibling, and replace path.

    Remove the sibling if writing or replacing fails; keep the old file whole.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=f".{path.name}.", delete=False) as sibling:
        temporary = Path(sibling.name)
        try:
            sibling.write(text)
            sibling.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def extend(path: Path, text: str) -> None:
    """Replace path with its UTF-8 text followed by text; use empty text when missing."""
    try:
        previous = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        previous = ""
    write(path, previous + text)
