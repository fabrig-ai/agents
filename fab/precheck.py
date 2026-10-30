"""Precheck: the queue's checks on a branch merged with main, in its implementer's slot (docs/design/fab.md, 6)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fab.sh import Runner, run


def precheck(slot: Path, tip: str, *, home: Path | None = None, sh: Runner = run,
             load: Callable[[Path], dict] | None = None) -> dict:
    """Check tip as the queue would and return the receipt.

    In slot: remember where HEAD is; fetch origin; detach at origin/main and merge tip (--no-ff;
    a conflict aborts it: outcome "conflict"); select with fab.gate.select (load: the metadata
    loader); run the ratchet steps without --write and the build-lane checks, logging to
    FAB_HOME/precheck/<tip>.log. Always restore the slot to where HEAD was, clean.
    The receipt {tip, main (origin/main's sha), selection ("full", "docs" or sorted names), steps
    (as "name:code:seconds"), outcome ("green", "red" or "conflict"), log, at (fab.log.now())} is
    written to FAB_HOME/precheck/<tip>.json and returned.
    """
    raise NotImplementedError


def main(argv: list[str]) -> int:
    """`fab precheck SLOT TIP`: prints the receipt's path and outcome; exit 0 green, 1 otherwise."""
    raise NotImplementedError
