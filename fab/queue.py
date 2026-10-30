"""fabrig's merge queue (docs/design/fab.md, 6). Runs on the gate machine.

Ready refs `ready/<draft>/<task>` are taken oldest first, merged on main as one batch, checked
in the gate lane, and pushed to main; a red batch is bisected. State is re-derived from git
on every cycle, except the tips already tried, kept in FAB_HOME/queue-state.json. Every
outcome is recorded in FAB_HOME/queue.jsonl, which the dispatcher reads.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from fab.sh import Runner, run


@dataclass(frozen=True)
class Branch:
    name: str  # "<draft>/<task>": the ready ref without its "ready/" prefix
    tip: str
    timestamp: int  # committer time of the tip


def candidates(repo: Path, tried: dict[str, str], *, sh: Runner = run) -> list[Branch]:
    """refs/remotes/origin/ready/<draft>/<task> after a fetch, oldest committer time first (then
    name); a branch whose tip equals tried[name] is left out."""
    raise NotImplementedError


def build_batch(repo: Path, branches: Sequence[Branch], base: str = "origin/main", *,
                sh: Runner = run) -> tuple[list[Branch], list[tuple[Branch, str]]]:
    """Detach at base and merge each tip (--no-ff, message `Merge <name>`); return (merged,
    conflicts with their output). A conflict confined to `<tree>/scripts/old-forms.txt` files is
    resolved as fabrig's mq merge_ratchets does (keep ours, recount with old_forms.py --write; a
    raised count is a conflict). A tip already contained in the batch is neither."""
    raise NotImplementedError


def bisect(branches: Sequence[Branch], check: Callable[[list[Branch]], bool]) -> tuple[list[Branch], list[Branch]]:
    """(green, red): check the whole; if red and more than one, each half in order, recursively.
    check lands what it passes, so later halves are checked on top of earlier green ones."""
    raise NotImplementedError


class Queue:
    def __init__(self, repo: Path, *, batch: int = 8, full_every: int = 5, home: Path | None = None,
                 sh: Runner = run, load: Callable[[Path], dict] | None = None):
        """repo: the queue's own clone; home: FAB_HOME; load: the metadata loader (fab.gate.metadata)."""
        raise NotImplementedError

    def attempt(self, branches: Sequence[Branch]) -> bool:
        """Check branches as one batch on origin/main and land it when green; return green.

        Conflicts are rejected (step "merge"). If nothing merged, the branches are marked tried
        and the attempt is green. Otherwise: selection (full on every full_every-th batch), the
        ratchet steps with --write and a commit of lowered baselines, the gate-lane checks, the
        detail log FAB_HOME/queue/<batch>.log. Green: push the candidate to main with
        --force-with-lease=refs/heads/main:<parent> (refused: an error, nothing marked), delete
        each branch's ready/<name> and <name> refs with leases on their tips, record `landed` per
        branch. Red: a single branch is rejected with its failing step and marked tried.
        Records: `batch` (branches, parent, selection, steps as "name:code:seconds", outcome
        green, red, conflict or error, log), `landed` (branch, tip, main), `rejected` (branch,
        tip, step, log). The checkout is left clean and detached."""
        raise NotImplementedError

    def cycle(self) -> bool:
        """fetch --prune, then take up to `batch` candidates and attempt them, bisecting when red;
        return whether there was anything to do."""
        raise NotImplementedError

    def run(self, *, stop: Path, idle: float = 30.0, sleep: Callable[[float], None] | None = None) -> None:
        """Cycle until the file `stop` exists, sleeping `idle` seconds after a cycle with nothing to do.
        An error in a cycle is recorded (`batch` with outcome error) and the loop sleeps and goes on."""
        raise NotImplementedError


def main(argv: list[str]) -> int:
    """`fab queue run|once [--repo PATH] [--batch N]` (repo default FAB_HOME/repos/fabrig; run stops
    at FAB_HOME/queue.stop), `fab queue plan` (the next batch's names, no checks),
    `fab queue log [--since TS]` (queue.jsonl records at or after TS, one per line)."""
    raise NotImplementedError
