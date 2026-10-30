"""Slots on a builder: claims, the sweep that bounds a slot, reclaim (docs/design/fab.md, 7).

Runs on the builder itself; the dispatcher calls it over ssh (`bin/fab slot ...`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# A test executable is a regular, user-executable file in a profile's deps/ without these suffixes.
NOT_EXECUTABLES = (".so", ".rlib", ".rmeta", ".d")


def slots_dir() -> Path:
    """FAB_SLOTS, or ~/src/fabrig/slots: slot n is the checkout `<dir>/<n>`, its claim `<dir>/<n>.claim`,
    its last release time the mtime of `<dir>/<n>.released`."""
    return Path(os.environ.get("FAB_SLOTS") or Path.home() / "src/fabrig/slots")


@dataclass(frozen=True)
class Claim:
    slot: int
    run: str
    task: str
    since: str  # fab.log.now() when claimed


def slots() -> list[int]:
    """The numbered slot checkouts that exist, ascending."""
    raise NotImplementedError


def claim(slot: int, run: str, task: str) -> Claim | None:
    """Claim a slot for a run: create its claim file exclusively (O_EXCL) and return the Claim;
    None when it is already claimed. A slot that does not exist is a ValueError."""
    raise NotImplementedError


def read_claim(slot: int) -> Claim | None:
    raise NotImplementedError


def release(slot: int, run: str) -> int:
    """End a run's hold on its slot: sweep what the run did not write (sweep_plan with since = the
    claim's time), remove the claim, touch the release marker; return the bytes freed.
    A claim held by another run is left alone and is a ValueError; no claim releases nothing (0)."""
    raise NotImplementedError


def idle() -> list[int]:
    """Unclaimed slots, least recently released first (a slot never released counts as oldest)."""
    raise NotImplementedError


def sweep_plan(target: Path, since_ns: int | None) -> list[Path]:
    """What to delete from a cargo target directory to bound it, sorted: every `incremental*`
    directory directly under a profile directory (`<target>/<profile>/incremental*`), and every
    test executable in `<target>/<profile>/deps` whose mtime is older than since_ns (every one
    when since_ns is None). Symlinks are never followed or listed."""
    raise NotImplementedError


def remove(paths: list[Path]) -> int:
    """Delete files and directory trees; return the bytes they occupied (st_blocks * 512).
    A path that vanished meanwhile is skipped."""
    raise NotImplementedError


def free_bytes(path: Path | None = None) -> int:
    """Bytes available to this user on the filesystem holding path (slots_dir() by default)."""
    raise NotImplementedError


def reclaim(need: int, *, free=free_bytes) -> int:
    """Free disk until free() >= need, taking from idle slots only; return the bytes freed.

    First pass, least recently released first: each idle slot's sweep_plan(target, None).
    Second pass, same order: each idle slot's whole target directory. Stop as soon as
    free() >= need. Each slot is claimed (run "reclaim") while it is worked on and its claim
    removed after, without touching its release marker; a slot that cannot be claimed is skipped.
    """
    raise NotImplementedError


def main(argv: list[str]) -> int:
    """`fab slot list` (one JSON line per slot: slot, claim fields or null, idle rank),
    `fab slot claim N RUN TASK` (exit 1 if held), `fab slot release N RUN` (prints bytes freed),
    `fab slot reclaim --need-gb G` (prints bytes freed and free bytes; exit 1 if still short)."""
    raise NotImplementedError
